"""Write cleaned rows into SQLite."""
import sqlite3
from pathlib import Path

SCHEMA = Path(__file__).resolve().parent / "schema.sql"


def connect(db_path):
    """Open the database, creating the file and any missing tables.

    Runs schema.sql every time; its CREATE TABLE IF NOT EXISTS statements leave an
    existing database unchanged.

    Args:
        db_path (Path | str): the SQLite file, e.g. <project root>/redsox.db.

    Returns:
        sqlite3.Connection: the open connection. Changes are saved only on conn.commit().
    """
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    return conn


def insert_rows(conn, table, rows):
    """Insert row dicts into a table, replacing any row with the same primary key.

    Builds "INSERT OR REPLACE INTO table (a, b) VALUES (:a, :b)" from the first row's keys,
    so reruns and overlapping date ranges update rows instead of duplicating them.

    Args:
        conn (sqlite3.Connection): the open database.
        table (str): table name, e.g. "TEAM". Always a constant from our code, never user input.
        rows (list[dict]): rows from transform.py; every dict has the same keys (column names).

    Returns:
        None. Does nothing if rows is empty.
    """
    if not rows:
        return
    columns = list(rows[0])
    names = ", ".join(columns)                          # team_id, name, ...
    placeholders = ", ".join(":" + c for c in columns)  # :team_id, :name, ...
    conn.executemany(f"INSERT OR REPLACE INTO {table} ({names}) VALUES ({placeholders})", rows)


def replace_transactions(conn, start, end, rows):
    """Replace all TRANSACTIONS rows in a date range with a fresh copy.

    TRANSACTIONS has no unique key (a trade has one row per player under the same ID, and
    cash rows have no player), so INSERT OR REPLACE can't spot duplicates. Instead the
    whole date window is deleted, then inserted again.

    Args:
        conn (sqlite3.Connection): the open database.
        start (date): first date of the window.
        end (date): last date of the window, included.
        rows (list[dict]): TRANSACTIONS rows from transform.transaction_row.

    Returns:
        None.
    """
    conn.execute("DELETE FROM TRANSACTIONS WHERE date BETWEEN ? AND ?", (str(start), str(end)))
    insert_rows(conn, "TRANSACTIONS", rows)


def player_ids(conn):
    """Collect every player ID that BOX_SCORE, PITCH or TRANSACTIONS refers to.

    PLAYER is built from these IDs, so every player in the other tables gets a PLAYER row.
    UNION removes duplicates; cash-only transaction rows (no player) are skipped.

    Args:
        conn (sqlite3.Connection): the open database, with those three tables loaded.

    Returns:
        set[int]: unique player IDs, e.g. {660271, 592332, ...}.
    """
    rows = conn.execute("""
        SELECT player_id FROM BOX_SCORE
        UNION SELECT pitcher_id FROM PITCH
        UNION SELECT batter_id  FROM PITCH
        UNION SELECT person_id  FROM TRANSACTIONS WHERE person_id IS NOT NULL
    """).fetchall()
    return {row[0] for row in rows}


def update_statcast_totals(conn):
    """Fill BOX_SCORE's sc_* columns for each pitcher by summarizing their pitches in PITCH.

    Batters never match a pitcher, so their sc_* columns stay NULL. AVG and MAX skip NULL
    readings. Whiffs = swinging strikes (foul tips not counted). Recomputed for every
    game on every run, because reloading a BOX_SCORE row resets its sc_* columns.

    Args:
        conn (sqlite3.Connection): the open database, with BOX_SCORE and PITCH loaded.

    Returns:
        None.
    """
    conn.execute("""
        UPDATE BOX_SCORE
        SET sc_avg_velo       = s.avg_velo,
            sc_max_velo       = s.max_velo,
            sc_avg_spin       = s.avg_spin,
            sc_whiffs         = s.whiffs,
            sc_called_strikes = s.called_strikes
        FROM (
            SELECT game_pk, pitcher_id,
                   ROUND(AVG(release_speed), 1)     AS avg_velo,
                   MAX(release_speed)               AS max_velo,
                   ROUND(AVG(release_spin_rate))    AS avg_spin,
                   SUM(description IN ('swinging_strike', 'swinging_strike_blocked')) AS whiffs,
                   SUM(description = 'called_strike')                                 AS called_strikes
            FROM PITCH
            GROUP BY game_pk, pitcher_id
        ) AS s
        WHERE BOX_SCORE.game_pk = s.game_pk AND BOX_SCORE.player_id = s.pitcher_id
    """)
