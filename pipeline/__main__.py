"""Run the pipeline: python -m pipeline START_DATE END_DATE   (e.g. 2025-07-01 2025-07-07)"""
import sys
from datetime import date
from pathlib import Path

from pipeline import extract, load, transform

DB_PATH = Path(__file__).resolve().parent.parent / "redsox.db"
USAGE = "Usage: python -m pipeline START_DATE END_DATE   (dates as YYYY-MM-DD, e.g. 2025-07-01 2025-07-07)"


def parse_dates(args):
    '''Handling CLI args'''
    if len(args) != 2:  # needs 2 dates
        sys.exit(USAGE)
        
    try:
        start, end = date.fromisoformat(args[0]), date.fromisoformat(args[1])
    except ValueError:
        # occurs if they are not valid dates
        sys.exit(f"Dates must look like 2025-07-01.\n{USAGE}")

    if start > end:
        sys.exit("The start date must be on or before the end date.")

    return start, end


def main():
    """Run the whole pipeline for the dates on the command line.

    Order matters: TEAM, SCHEDULE and TRANSACTIONS first; then BOX_SCORE and PITCH for
    each Final game; then PLAYER (built from the IDs those tables refer to); and last the
    Statcast totals in BOX_SCORE (computed from PITCH).
    """
    start, end = parse_dates(sys.argv[1:])
    conn = load.connect(DB_PATH)
    print(f"Loading {start} to {end} into {DB_PATH.name}")  # print to show program is working

    for season in range(start.year, end.year + 1):
        # only keeps latest season's details in the table
        teams = [transform.team_row(t) for t in extract.fetch_teams(season)]
        load.insert_rows(conn, "TEAM", teams)
    print(f"TEAM COUNT: {len(teams)} teams")

    games = transform.schedule_rows(extract.fetch_schedule(start, end))
    load.insert_rows(conn, "SCHEDULE", games)
    print(f"GAME COUNT: {len(games)} games")

    transactions = [transform.transaction_row(t) for t in extract.fetch_transactions(start, end)]
    load.replace_transactions(conn, start, end, transactions)
    print(f"TRANSACTIONS: {len(transactions)} rows")

    final_games = [g for g in games if g["status_code"] == "F"]  # postponed/cancelled games have no box score or pitches
    skipped = []
    for i, g in enumerate(final_games, start=1):
        # compile box score & pitches bc they share the same games
        game_pk = g["game_pk"]
        try:
            # if either statsapi or savant fails, its skipped entirely
            box = transform.boxscore_rows(extract.fetch_boxscore(game_pk), game_pk)
            pitches = transform.pitch_rows(extract.fetch_pitches(game_pk))
        except Exception as e:  # a bad download or unexpected data skips instead of terminating
            print(f"  Skipped game {game_pk}: {e}")
            skipped.append(game_pk)
            continue

        load.insert_rows(conn, "BOX_SCORE", box)
        load.insert_rows(conn, "PITCH", pitches)
        conn.commit()  # save after each game so a crash later keeps the finished ones
        print(f"  Game {i}/{len(final_games)} ({game_pk}): {len(box)} players, {len(pitches)} pitches")
    
    print(f"BOX_SCORE and PITCH: {len(final_games) - len(skipped)} games loaded, {len(skipped)} skipped {skipped}")

    # after the game loop, because player IDs are read out of BOX_SCORE, PITCH and TRANSACTIONS
    people = [transform.player_row(p) for p in extract.fetch_people(load.player_ids(conn))]
    load.insert_rows(conn, "PLAYER", people)
    print(f"PLAYER COUNT: {len(people)} players")

    load.update_statcast_totals(conn)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    main()
