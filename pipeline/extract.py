"""Fetch raw data from the MLB Stats API and Baseball Savant. No cleaning happens here."""
import json
from pathlib import Path

import requests

STATS_API = "https://statsapi.mlb.com/api/v1"
SAVANT_CSV = "https://baseballsavant.mlb.com/statcast_search/csv"
# Project root / data / raw  (this file is <root>/pipeline/extract.py)
RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw"


def get(url, params=None):
    """Send a GET request and stop with an error if the server returns an error status.

    Args:
        url (str)
        params (dict | None): query parameters, e.g. {"sportId": 1, "season": 2025}.

    Returns:
        requests.Response: the response; callers use .json(), .text or .content.
    """
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    return resp


def fetch_teams(season):
    """Fetch all 30 MLB teams as they were in one season (/teams?sportId=1&season=...).

    Args:
        season (int)

    Returns:
        list[dict]: one raw team dict per team, for transform.team_row.
    """
    return get(f"{STATS_API}/teams", {"sportId": 1, "season": season}).json()["teams"]


def fetch_schedule(start, end):
    """Fetch every game scheduled in a date range (/schedule).

    The API groups games by date; this flattens them into one list. The list may hold
    duplicate gamePks (postponed games); transform.schedule_rows removes them.

    Args:
        start (date | str)
        end (date | str)

    Returns:
        list[dict]: one raw game dict per schedule entry; [] if no games
    """
    data = get(f"{STATS_API}/schedule", {"sportId": 1, "startDate": start, "endDate": end}).json()
    games = []
    for day in data.get("dates", []):   # each day in the range
        for game in day["games"]:       # each game on that day
            games.append(game)
    return games


def fetch_transactions(start, end):
    """Fetch every MLB transaction in a date range (/transactions).

    Args:
        start (date | str): first date, e.g. date(2025, 7, 1) or "2025-07-01".
        end (date | str): last date, included.

    Returns:
        list[dict]: one raw transaction dict per row; [] if there were none.
    """
    return get(
        f"{STATS_API}/transactions", {"sportId": 1, "startDate": start, "endDate": end}
    ).json().get("transactions", [])


def fetch_people(person_ids):
    """Fetch player details for a set of player IDs (/people?personIds=...).

    The IDs go in the URL, and about 1,000 IDs exceeds the server's URL length limit
    (414 error), so they are sent 500 per request.

    Args:
        person_ids (set[int]): player IDs, e.g. {660271, 592332}.

    Returns:
        list[dict]: one raw person dict per ID the API knows, for transform.player_row.
    """
    ids = sorted(person_ids)
    people = []
    # separate into 500 IDs per batch to not exceed URL char limits
    for i in range(0, len(ids), 500):
        chunk = ",".join(str(pid) for pid in ids[i:i + 500])
        people += get(f"{STATS_API}/people", {"personIds": chunk}).json()["people"]
    return people


# Box scores and pitches are only fetched for games that have already ended
# Since they never change, they're cached in a separate dir

def fetch_boxscore(game_pk):
    """Fetch one game's box score (/game/{gamePk}/boxscore), using the disk cache if present.

    The first download is saved to data/raw/boxscore/{gamePk}.json; later calls read that
    file instead of the network. To re-download, delete data/raw/.

    Args:
        game_pk (int): the game's ID, e.g. 777283.

    Returns:
        dict: the raw box score, for transform.boxscore_rows.
    """
    path = RAW_DIR / "boxscore" / f"{game_pk}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    text = get(f"{STATS_API}/game/{game_pk}/boxscore").text
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return json.loads(text)


def fetch_pitches(game_pk):
    """Fetch one game's pitch-by-pitch CSV from Baseball Savant, using the disk cache if present.

    Decodes with utf-8-sig to strip the invisible BOM before the header. Saves to
    data/raw/pitches/{gamePk}.csv, except when Savant returns only a header (no data yet),
    so a later run asks again. To re-download, delete data/raw/.

    Args:
        game_pk (int): the game's ID, e.g. 777283.

    Returns:
        str: the whole CSV file as text, for transform.pitch_rows. Only a header line if
            Savant has no data for the game.
    """
    path = RAW_DIR / "pitches" / f"{game_pk}.csv"
    if path.exists():
        return path.read_text(encoding="utf-8")
    text = get(SAVANT_CSV, {"all": "true", "type": "details", "game_pk": game_pk}).content.decode("utf-8-sig")
    if len(text.strip().splitlines()) > 1:  # don't cache an empty result
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return text
