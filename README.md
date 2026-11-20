# Red Sox Data Engineering Take-Home

## Setup

Requires Python 3.12 (SQLite 3.33 or newer, which it includes).

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```bash
python -m pipeline YYYY-MM-DD YYYY-MM-DD
```

Keep dates in the provided format. There is data from 1901 onward.  
Finished games are cached in `data/raw/`, so any reruns take much less time.

- To start a fresh database (e.g. for a different date range), delete `redsox.db`.
- To download every game again, delete `data/raw/`.
- To run tests: `python -m unittest`
- Example queries are in`sql/example_queries.sql`. You need to run `python -m pipeline 2026-07-10 2026-07-12` first though.

## My Table Design

Tables use MLB's own IDs as keys

| Table | One row per | Primary key |
|---|---|---|
| TEAM | MLB team | `team_id` |
| PLAYER | player that appears in any other table | `player_id` |
| SCHEDULE | game | `game_pk` |
| BOX_SCORE | player per game | (`game_pk`, `player_id`) |
| PITCH | pitch (from Baseball Savant) | (`game_pk`, `at_bat_number`, `pitch_number`) |
| TRANSACTIONS | player per transaction | `row_id` (generated) |

- **TEAM** and **PLAYER** are the most basic tables with fundamental info about each.
- **SCHEDULE** contains info such as date, time, venue, and each team's info after the game is over
- **BOX_SCORE** each player has their own row for every game they played, containing batting and pitching stats and info from Statcast. Columns that don't apply are saved as NULL to avoid needing more tables.
Statcast info (velocity, spin, whiffs, called strikes) are calculated in SQL from PITCH instead of downloaded so there are no disagreements between the 2 tables.
- **PITCH** filters out roughly 2/3 of the data from Savant. Includes data about the game in context, batting stats, and the pitch itself.
- **TRANSACTIONS** gets a generated ID PK. It contains all the most important info about a transaction. Team IDs don't reference any data from TEAM in the case they are minor league teams.

## Assumptions

- Missing values are stored as NULL, never as 0.
- A postponed game is listed twice in the schedule, and some games are just listed twice. Duplicate games are removed, only keeping the Final entry.
- Only Final games get box scores and pitches. Unplayed games keep NULL scores.
- TEAM keeps one row per team, using the latest season in the date range. Only the MLB league is stored, not the spring training league.
- Bench players who didn't play are left out of BOX_SCORE. A batting order of `"701"` (spot 7, first substitute) is stored as 7.
- Savant counts automatic balls and strikes (intentional walks, pitch-clock violations) as pitches, even though they were never thrown. PITCH keeps them, so a pitcher may have more PITCH rows than `pit_pitches`. `pit_pitches` is the actual count.
- Whiffs are swinging strikes. Foul tips don't count.
- Many transaction team IDs are minor-league teams that aren't in TEAM. The team name is stored next to each ID so the rows stay readable.
- If a transaction doesn't involve a person (ie. cash, future considerations) the person's ID and name are saved as NULL.
- If, for some reason, a game fails to download, it is skipped and listed at the end. Running again should pick it up.
