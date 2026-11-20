# Red Sox Data Engineering Take-Home: Plan

## Context
This is the Boston Red Sox Data Engineering take-home (`BRS_Data_Engineering_Take_Home_Assessment.pdf`). The job: build a small CLI pipeline that takes a start and end date, pulls data from the MLB Stats API and Baseball Savant, cleans it, and loads 6 tables into SQLite: TEAM, PLAYER, SCHEDULE, BOX_SCORE, PITCH, TRANSACTIONS. The deliverables are the code, a built `.db`, a README (setup, run steps, table design, assumptions), and example SQL. The time limit is 4 hours. Graders look at organization, how messy data is handled, and whether it is easy to run. Scope: core only. The optional extensions are listed as stretch work at the end.

The project folder is empty apart from the PDF, so everything is new.

## Stack
- **Python 3.12** (installed) and the **stdlib `sqlite3`**.
- **`requests`**, the only third-party dependency (2.31 is already installed). Every request goes through one 3-line helper, `get(url, params=None)`. It calls `requests.get(..., timeout=60)`, then `raise_for_status()`. There is no Session, no retry loop, and no custom User-Agent; Savant was tested and returns 200 without one. A game that fails is printed and skipped. Running the same command again re-fetches only the failed games, because the others are cached.
- Stdlib for the rest: `sys`, `csv`, `json`, `datetime`, `pathlib`, `io`, and `unittest` for the tests.
- **CLI is just `sys.argv`:** `python -m pipeline 2025-07-01 2025-07-07`. Bad input exits with a plain-English `sys.exit("...")` message. There are no flags: the DB is always `<root>/redsox.db`, and to re-download cached games you delete `data/raw/`.
- **Progress and failure messages use `print()`,** not the `logging` module.
- **No pandas.** `csv.DictReader` and SQL aggregation cover every need. Leaving it out keeps the install small and the type handling explicit. It is also not installed.

## Directory layout
```
redsox_sp27/
├── README.md               # setup, run, table design, assumptions, "with more time"
├── requirements.txt        # requests
├── pipeline/
│   ├── __main__.py         # CLI: python -m pipeline 2025-07-01 2025-07-07
│   ├── extract.py          # get() helper, raw-file cache, fetch_teams/schedule/transactions/people/boxscore/pitches
│   ├── transform.py        # pure functions: raw JSON/CSV -> row dicts (all cleaning lives here)
│   ├── load.py             # connect, apply schema.sql, upserts, Statcast -> BOX_SCORE aggregation
│   └── schema.sql          # CREATE TABLE IF NOT EXISTS for all 6 tables + indexes
├── sql/
│   └── example_queries.sql # validation and demo queries
├── tests/
│   ├── fixtures/           # small saved samples: 1 schedule, 1 boxscore, 1 statcast CSV, 1 transactions
│   └── test_transform.py   # offline unittest of the cleaning rules
├── data/raw/               # cached API responses (leave out of the zip)
└── redsox.db               # the database built by the pipeline (deliverable)
```
The split is extract, transform, load. Transforms are pure functions, so they can be tested offline against fixtures.

## Pipeline flow (`__main__.py`)
1. Read the two dates from `sys.argv`. `date.fromisoformat` validates them, and the run stops with a plain message if start > end.
2. `connect(db)` and run `executescript(schema.sql)`.
3. **TEAM**: call `/teams?sportId=1&season=Y` for each season year in the range and upsert the results.
4. **SCHEDULE**: call `/schedule?...` once for the whole range, dedupe (see the data issues section), and upsert.
5. For each game where `status.codedGameState == 'F'`:
   - **BOX_SCORE**: call `/game/{pk}/boxscore` and keep one row per player who appeared.
   - **PITCH**: call Savant `statcast_search/csv?...&game_pk={pk}` and keep one row per pitch.
   - Each game commits on its own. A game that fails is printed and skipped, and the run continues. Failed gamePks are listed in a summary at the end.
6. **TRANSACTIONS**: call `/transactions?startDate&endDate&sportId=1` once for the whole range.
7. **PLAYER**: collect every person ID seen in BOX_SCORE, PITCH (pitcher and batter), and TRANSACTIONS. Fetch all of them on every run, so player details stay fresh, through the batch endpoint `/people?personIds=a,b,c`, 500 IDs per call. Tested: 1,000 IDs per call gets a 414 URI Too Long.
8. **Statcast aggregation**: one SQL `UPDATE BOX_SCORE ... FROM (SELECT ... FROM PITCH GROUP BY game_pk, pitcher)` fills the pitch-metric columns.
9. Log the row count for each table.

**Raw cache:** `extract.py` writes each response for a Final game (boxscore and statcast) to `data/raw/{kind}/{gamePk}.json|csv` and reads it back on reruns. Final games don't change, so the cache is safe, and it avoids re-requesting ~200 slow URLs while developing. Schedule, teams, and transactions are always fetched fresh. To re-download, delete `data/raw/`.

## How the data is organized
- **Dimension tables:** TEAM and PLAYER hold one row per entity, keyed by MLB's own IDs (`team_id`, `player_id`). These are the IDs every other source uses, Statcast included, so joins line up with no crosswalk.
- **Event tables:** SCHEDULE (one row per game), BOX_SCORE (one row per player per game), PITCH (one row per pitch), and TRANSACTIONS (one row per player per transaction). Each one points to the dimensions by ID.
- **Grain goes from coarse to fine:** game → player-game → pitch. BOX_SCORE's Statcast columns are a roll-up of PITCH. They are computed in SQL, never fetched separately, so the two tables can't disagree.
- **Team details are stored once.** League, division, and venue live only in TEAM. SCHEDULE keeps home/away team IDs plus the team name as of that game, and anything more comes from a join to TEAM. That stops division names from being copied onto every game row.
- **Facts that belong to a single game stay on the game row,** such as the score, the winner, and the record at game time. They differ from game to game and don't belong in TEAM.

## Table design (`schema.sql`)
Table names are uppercase, as in the PDF. Columns are snake_case. Primary keys are the natural source IDs. `REFERENCES` clauses are written for documentation only, and `PRAGMA foreign_keys` stays off because source data breaks them on purpose (see below). An orphan-check query in the example SQL reports those cases.

| Table | PK | Key columns |
|---|---|---|
| TEAM | `team_id` | name, abbreviation, team_name, location_name, league_id/league_name (MLB league only: American or National; `springLeague` and `springVenue` are deliberately not loaded), division_id/name, venue_id/name, first_year_of_play, season, active |
| PLAYER | `player_id` | full_name, first/last_name, birth_date, birth_country, height_inches (int, parsed from `6' 4"`), weight, primary_position, bat_side, pitch_hand, mlb_debut_date, active |
| SCHEDULE | `game_pk` | official_date, game_datetime_utc, season, game_type, status_code, status_detail, venue_id/name, double_header, game_number, day_night. **Home and away get the same columns**: `home_team_id`, `home_team_name`, `home_score`, `home_is_winner`, `home_wins`, `home_losses` (record at game time), and the matching `away_*` columns. Scores and the winner flag are NULL until the game is played. |
| BOX_SCORE | (`game_pk`, `player_id`) | team_id, is_home, position, batting_order; batting: ab, r, h, 2b, 3b, hr, rbi, bb, so, sb; pitching (NULL for non-pitchers): ip (text "5.1"), outs, h, r, er, bb, so, hr, pitches_box, strikes; **Statcast**: sc_avg_velo, sc_max_velo, sc_avg_spin, sc_whiffs, sc_called_strikes |
| PITCH | (`game_pk`, `at_bat_number`, `pitch_number`) | game_date, inning, inning_topbot, pitcher_id, batter_id, stand, p_throws, balls, strikes, outs_when_up, pitch_type, pitch_name, release_speed, effective_speed, release_spin_rate, spin_axis, release_extension, release_pos_x/z, pfx_x/z, plate_x/z, zone, sz_top/bot, type, description, events, des, bb_type, launch_speed, launch_angle, hit_distance_sc, estimated_ba/woba_using_speedangle, delta_run_exp, bat_speed, swing_length, home_score, away_score |
| TRANSACTIONS | `row_id` INTEGER surrogate | transaction_id, person_id (nullable), person_name, type_code, type_desc, description, date, effective_date, resolution_date, from_team_id/name, to_team_id/name |

Design decisions:
- **BOX_SCORE is a single wide table**, with batting and pitching columns in one row per player per game. Two-way players fit without extra handling. Pitching columns are NULL for batters.
- **The Statcast aggregation is done in SQL from PITCH**, not in Python. That keeps one source of truth, and the columns can be rebuilt with no new fetches.
- **PITCH keeps about 45 of Savant's 118 columns.** Deprecated and derived columns (`*_deprecated`, win-expectancy fields, fielder IDs) are dropped. The kept list is one Python constant, so changing it is a one-line edit.
- Indexes: `PITCH(pitcher_id)`, `PITCH(batter_id)`, `SCHEDULE(official_date)`, `TRANSACTIONS(person_id)`, `TRANSACTIONS(date)`.

**Idempotency / reruns:** keyed tables use `INSERT OR REPLACE`, so a rerun or an overlapping date range updates rows and never creates duplicates. TRANSACTIONS has no unique natural key: in one month of data, 77 `id`s repeat, because a trade gets one row per player and cash-only rows have no person. The load runs `DELETE FROM TRANSACTIONS WHERE date BETWEEN ? AND ?` and then inserts the window again, in one transaction. The BOX_SCORE Statcast columns are recomputed after every run.

## Imperfect source data (checked against the live APIs)
The general policy is **keep, flag, explain**:
- Bad or missing values become NULL. They are never turned into fake zeros or dropped quietly.
- Duplicates are resolved by a rule written down here.
- If one game fails to fetch, only that game is skipped, and it is listed in the summary at the end of the run.
- Gaps between sources are kept and shown by example queries, not hidden.
- All cleaning happens in `transform.py`, so the rules are in one place and covered by tests.

These cases go in the README's assumptions section and the code handles each one:
1. **Duplicate games in the schedule.** A postponed game appears twice: once on its original date as `Postponed`, and again as `Final` (e.g. gamePk 777284/777289/777290 on 2025-07-02). Some Final games are listed twice outright (777294). The fix is to dedupe by `gamePk`, preferring the entry with `codedGameState == 'F'`.
2. **Games that were never played** (Postponed, Cancelled, Scheduled) have no box score or Statcast data. They stay in SCHEDULE with NULL scores and are not fetched.
3. **TRANSACTIONS reference teams that aren't in TEAM.** One window had 58 distinct team IDs, and most of them were minor-league affiliates. The pipeline stores `*_team_name` next to each ID and does not enforce an FK. Some rows also have no `person` (cash trades) or no `fromTeam`, so those columns are nullable.
4. **Statcast CSV quirks:** a UTF-8 BOM on the header (read with `utf-8-sig`), empty strings that must become NULL, and every number arriving as text. A cast map in `transform.py` handles them, and empty-string handling runs before casting. A game without Statcast tracking returns only the header. That is printed, and the BOX_SCORE `sc_*` columns stay NULL.
5. **Savant requests** are made one per game, which stays clear of Savant's ~25k-row cap on search exports. A failed request is printed and the game is skipped, and a rerun picks it up.
6. **Pitch-count mismatch:** box-score `numberOfPitches` can be lower than the Statcast row count, because Savant adds rows for automatic balls and strikes (intentional walks, pitch-clock violations) that were never thrown. `pit_pitches` is the official count; an example query compares it against PITCH.
7. **Box-score players who didn't play** have empty `stats.batting` and `stats.pitching` and are dropped. Rule: keep a player only if a batting or pitching stat dict is non-empty.
8. **Team metadata depends on the season**, for example the Athletics' 2026 location. Teams are fetched for each season year in the range. TEAM keeps one row per team with the latest season's details, e.g. 2024 Oakland Athletics/OAK becomes 2025 Athletics/ATH, Sacramento. The per-game team names stay in SCHEDULE.
9. **Height arrives as text** (`6' 4"`) and is parsed to inches. `inningsPitched` ("5.1") stays as text, and `outs` is kept as the integer column for math.

## Example queries (`sql/example_queries.sql`)
1. Row counts for each table.
2. Red Sox games in the range, with opponent names joined from TEAM and the score.
3. Box score for one game, with pitchers' box stats next to their Statcast velo and spin.
4. Data-quality check: pitchers whose `pit_pitches` differs from their PITCH row count, explained by automatic balls and strikes.
5. Pitch-type breakdown for one pitcher: count, average velo, whiff %.
6. Red Sox transactions in the range, with player details joined from PLAYER.
7. Orphan check: SCHEDULE/BOX_SCORE/PITCH IDs with no TEAM or PLAYER match. This should return 0 rows except for documented cases.

## Tests (`tests/test_transform.py`, run with `python -m unittest`)
These run offline against the saved fixtures:
- schedule dedupe keeps the Final entry for a postponed gamePk;
- Statcast row cleaning (BOM, empty string → None, numeric casts);
- box-score flattening drops players who didn't play and has the right pitcher count;
- the transaction transform handles a missing person or fromTeam;
- height parsing.

There is also one small integration check: load the fixtures into an in-memory SQLite DB, run the aggregation, and assert that one pitcher's `sc_avg_velo` and `sc_whiffs` match values computed by hand from the fixture.

## Build order (fits in about 4 hours)
1. (30m) Skeleton, `schema.sql` (done), `extract.py` (code agreed in chat; Savant's fetch is `fetch_pitches`, cached at `data/raw/pitches/`), the CLI. Show and explain each file to the user before writing it.
2. (45m) TEAM, SCHEDULE, TRANSACTIONS: the simple endpoints, end to end.
3. (60m) BOX_SCORE and PITCH transforms, the per-game loop, error isolation.
4. (20m) PLAYER batch fetch, Statcast aggregation SQL.
5. (30m) Fixtures and tests. Build the shipped DB for **2025-07-01 → 2025-07-07**: about 95 Final games, roughly 28k pitches, and a few minutes of runtime on a cold cache.
6. (35m) Example queries, the README (design, assumptions, "with more time").

## Stretch (only if time is left)
- MLB Trade Rumors RSS: parse with stdlib `xml.etree`. Add an `MLBTR_POST` table, a `MLBTR_CATEGORY` table, and an `MLBTR_MATCH` table that matches on player-name category, team category, and ±3 days, with a `match_confidence` column. Uncertain matches are kept, not dropped.
- Retrosheet `gameinfo.zip`: use stdlib `zipfile`. Add a retro→MLB team crosswalk, and match games on (date, home team, game_number), keeping the unmatched ones in a table.

## "With more time" (README)
Parallel game fetches with a small thread pool, incremental loads (skip gamePks already loaded), loading minor-league teams for the transaction FKs, a real migration story for the schema, and wider Statcast coverage.

## Verification
1. `python -m venv .venv && pip install -r requirements.txt`
2. `python -m unittest` passes.
3. `python -m pipeline 2025-07-01 2025-07-07`. The printed counts should be about 95 games, about 28k pitches, and 0 failed games.
4. Run it a second time: the counts stay identical, which shows reruns are idempotent and create no duplicates.
5. `sqlite3 redsox.db < sql/example_queries.sql`. Check the Red Sox games against MLB.com, and confirm the orphan check shows only the documented minor-league team IDs.
6. Run an edge case: `python -m pipeline 2025-12-01 2025-12-03`, which is the offseason. It should finish cleanly with 0 games and only transactions loaded.
