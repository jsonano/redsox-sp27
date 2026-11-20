"""Turn raw API data into row dicts whose keys match the column names in schema.sql. All cleaning lives here."""
import csv
import io


def to_int(value):
    """Convert a number sent as text into an int, keeping missing values as None.

    A few MLB fields are numbers sent as strings (firstYearOfPlay "1901", season "2025",
    battingOrder "501"). Missing values become None, which SQLite stores as NULL.

    Args:
        value (str | int | None): e.g. "1901", 1901, "" or None.

    Returns:
        int | None: 1901, or None if the value is missing.
    """
    return int(value) if value not in (None, "") else None


def team_row(t):
    """Convert one team from the /teams endpoint into a TEAM row.

    Picks the wanted fields, renames them to snake_case and simplifies nested ones
    (t["league"]["id"] -> league_id).

    Args:
        t (dict): one team, e.g. {"id": 111, "name": "Boston Red Sox", "league": {"id": 103, ...}, ...}.

    Returns:
        dict: one TEAM row keyed by column name, e.g. {"team_id": 111, "league_id": 103, ...}.
    """
    return {
        "team_id": t["id"],
        "name": t["name"],
        "abbreviation": t.get("abbreviation"),
        "team_name": t.get("teamName"),
        "location_name": t.get("locationName"),
        "league_id": t.get("league", {}).get("id"),
        "league_name": t.get("league", {}).get("name"),
        "division_id": t.get("division", {}).get("id"),
        "division_name": t.get("division", {}).get("name"),
        "venue_id": t.get("venue", {}).get("id"),
        "venue_name": t.get("venue", {}).get("name"),
        "first_year_of_play": to_int(t.get("firstYearOfPlay")),
        "season": t.get("season"),
        "active": t.get("active"),
    }


def schedule_rows(games):
    """Remove duplicate games from the schedule, then convert each one into a SCHEDULE row.

    A postponed game is listed twice (Postponed, then Final), and some games are listed twice
    outright. Keeps one entry per gamePk; a Final entry is never replaced by a later one.

    Args:
        games (list[dict]): every game from fetch_schedule, duplicates included.

    Returns:
        list[dict]: one SCHEDULE row per unique gamePk.
    """
    by_pk = {}
    for g in games:
        kept = by_pk.get(g["gamePk"])
        if kept is None or kept["status"]["codedGameState"] != "F":
            by_pk[g["gamePk"]] = g
    return [schedule_row(g) for g in by_pk.values()]


def schedule_row(g):
    """Convert one game from the /schedule endpoint into a SCHEDULE row.

    Home and away get the same columns. Score and winner are None until the game is played,
    and wins/losses are the team's record after this game.

    Args:
        g (dict): one game, e.g. {"gamePk": 777283, "officialDate": "2025-07-01", "teams": {...}, ...}.

    Returns:
        dict: one SCHEDULE row keyed by column name.
    """
    home, away = g["teams"]["home"], g["teams"]["away"]
    return {
        "game_pk": g["gamePk"],
        "official_date": g["officialDate"],
        "game_datetime_utc": g.get("gameDate"),
        "season": to_int(g.get("season")),
        "game_type": g.get("gameType"),
        "status_code": g["status"].get("codedGameState"),
        "status_detail": g["status"].get("detailedState"),
        "home_team_id": home["team"]["id"],
        "home_team_name": home["team"].get("name"),
        "home_score": home.get("score"),        # missing until the game is played -> NULL
        "home_is_winner": home.get("isWinner"),
        "home_wins": home.get("leagueRecord", {}).get("wins"),
        "home_losses": home.get("leagueRecord", {}).get("losses"),
        "away_team_id": away["team"]["id"],
        "away_team_name": away["team"].get("name"),
        "away_score": away.get("score"),
        "away_is_winner": away.get("isWinner"),
        "away_wins": away.get("leagueRecord", {}).get("wins"),
        "away_losses": away.get("leagueRecord", {}).get("losses"),
        "venue_id": g.get("venue", {}).get("id"),
        "venue_name": g.get("venue", {}).get("name"),
        "double_header": g.get("doubleHeader"),
        "game_number": g.get("gameNumber"),
        "day_night": g.get("dayNight"),
    }


def transaction_row(t):
    """Convert one transaction from the /transactions endpoint into a TRANSACTIONS row.

    person is missing on cash-only trade rows and fromTeam on signings and call-ups; their
    columns become None. Team names are kept next to team IDs because many IDs are
    minor-league teams that aren't in TEAM.

    Args:
        t (dict): one transaction, e.g. {"id": 851826, "person": {...}, "toTeam": {...}, "date": "2025-07-01", ...}.

    Returns:
        dict: one TRANSACTIONS row keyed by column name.
    """
    person = t.get("person", {})       # missing on cash-only rows
    from_team = t.get("fromTeam", {})  # missing on signings, call-ups, etc.
    to_team = t.get("toTeam", {})
    return {
        "transaction_id": t["id"],
        "person_id": person.get("id"),
        "person_name": person.get("fullName"),
        "type_code": t.get("typeCode"),
        "type_desc": t.get("typeDesc"),
        "description": t.get("description"),
        "date": t["date"],
        "effective_date": t.get("effectiveDate"),
        "resolution_date": t.get("resolutionDate"),
        "from_team_id": from_team.get("id"),
        "from_team_name": from_team.get("name"),
        "to_team_id": to_team.get("id"),
        "to_team_name": to_team.get("name"),
    }


def boxscore_rows(box, game_pk):
    """Convert one game's box score into BOX_SCORE rows, one per player who batted or pitched.

    Bench players who didn't play have empty batting and pitching stats and are skipped.
    A pitcher who didn't bat gets None batting columns, and vice versa. battingOrder "501"
    is stored as lineup spot 5. The sc_* Statcast columns are filled later from PITCH.

    Args:
        box (dict): the whole box score from fetch_boxscore, with teams.home/away.players.
        game_pk (int): the game's ID, passed in because the box score doesn't include it.

    Returns:
        list[dict]: BOX_SCORE rows keyed by column name, about 30-40 per game.
    """
    rows = []
    for side in ("home", "away"):
        team = box["teams"][side]
        for player in team["players"].values():
            batting = player["stats"]["batting"]
            pitching = player["stats"]["pitching"]
            if not batting and not pitching:
                continue
            order = to_int(player.get("battingOrder"))  # "501" = lineup spot 5, 1st substitute
            rows.append({
                "game_pk": game_pk,
                "player_id": player["person"]["id"],
                "team_id": team["team"]["id"],
                "is_home": side == "home",
                "position": player.get("position", {}).get("abbreviation"),
                "batting_order": order // 100 if order else None,
                "bat_ab": batting.get("atBats"),
                "bat_r": batting.get("runs"),
                "bat_h": batting.get("hits"),
                "bat_doubles": batting.get("doubles"),
                "bat_triples": batting.get("triples"),
                "bat_hr": batting.get("homeRuns"),
                "bat_rbi": batting.get("rbi"),
                "bat_bb": batting.get("baseOnBalls"),
                "bat_so": batting.get("strikeOuts"),
                "bat_sb": batting.get("stolenBases"),
                "pit_ip": pitching.get("inningsPitched"),
                "pit_outs": pitching.get("outs"),
                "pit_batters_faced": pitching.get("battersFaced"),
                "pit_h": pitching.get("hits"),
                "pit_r": pitching.get("runs"),
                "pit_er": pitching.get("earnedRuns"),
                "pit_bb": pitching.get("baseOnBalls"),
                "pit_so": pitching.get("strikeOuts"),
                "pit_hr": pitching.get("homeRuns"),
                "pit_pitches": pitching.get("numberOfPitches"),
                "pit_strikes": pitching.get("strikes"),
            })
    return rows


# All the Savant columns kept in PITCH. Names match schema.sql except pitcher/batter, which are renamed to IDs. 
# SQLite turns number-looking text into numbers itself.
PITCH_COLUMNS = [
    "game_pk", "game_date", "at_bat_number", "pitch_number", "inning", "inning_topbot",
    "home_score", "away_score", "pitcher", "p_throws", "batter", "stand",
    "balls", "strikes", "outs_when_up",
    "pitch_type", "pitch_name", "release_speed", "effective_speed", "release_spin_rate",
    "spin_axis", "release_extension", "release_pos_x", "release_pos_z", "pfx_x", "pfx_z",
    "plate_x", "plate_z", "zone", "sz_top", "sz_bot",
    "type", "description", "events", "des", "delta_run_exp",
    "bat_speed", "swing_length",
    "bb_type", "launch_speed", "launch_angle", "hit_distance_sc",
    "estimated_ba_using_speedangle", "estimated_woba_using_speedangle",
]
RENAMES = {"pitcher": "pitcher_id", "batter": "batter_id"}


def pitch_rows(csv_text):
    """Convert one game's Savant CSV into PITCH rows, one per pitch.

    Keeps the PITCH_COLUMNS fields and renames pitcher/batter via RENAMES. Savant marks
    missing values with "", which becomes None so averages skip them instead of counting 0.
    Other values stay text; SQLite turns number-looking text into numbers on insert.

    Args:
        csv_text (str): the whole CSV file from fetch_pitches, header line included.

    Returns:
        list[dict]: PITCH rows keyed by column name, or [] if Savant had no data for the game.
    """
    rows = []
    for raw in csv.DictReader(io.StringIO(csv_text)):
        row = {}
        for name in PITCH_COLUMNS:
            value = raw[name]
            row[RENAMES.get(name, name)] = value if value != "" else None
        rows.append(row)
    return rows


def height_inches(text):
    """Convert a height like 6' 4" into total inches.

    Args:
        text (str | None): the API's height text, e.g. "6' 4\"".

    Returns:
        int | None: 76, or None if the height is missing or in an unexpected format.
    """
    try:
        feet, inches = text.replace('"', "").split("'")  # "6' 4\"" -> "6' 4" -> ["6", " 4"]
        return int(feet) * 12 + int(inches)
    except (AttributeError, ValueError):  # AttributeError: height missing (None); ValueError: odd format
        return None


def player_row(p):
    """Convert one person from the /people endpoint into a PLAYER row.

    Height is converted to inches; position, bat side and throwing hand are stored as their
    short codes (e.g. "SS", "L", "R").

    Args:
        p (dict): one person, e.g. {"id": 660271, "fullName": "Shohei Ohtani", "height": "6' 4\"", ...}.

    Returns:
        dict: one PLAYER row keyed by column name.
    """
    return {
        "player_id": p["id"],
        "full_name": p["fullName"],
        "first_name": p.get("firstName"),
        "last_name": p.get("lastName"),
        "birth_date": p.get("birthDate"),
        "birth_country": p.get("birthCountry"),
        "height_inches": height_inches(p.get("height")),
        "weight": p.get("weight"),
        "primary_position": p.get("primaryPosition", {}).get("abbreviation"),
        "bat_side": p.get("batSide", {}).get("code"),      # L / R / S
        "pitch_hand": p.get("pitchHand", {}).get("code"),  # L / R
        "mlb_debut_date": p.get("mlbDebutDate"),
        "active": p.get("active"),
    }
