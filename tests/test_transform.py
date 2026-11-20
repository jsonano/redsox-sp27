"""Offline tests for the cleaning rules in transform.py and the Statcast roll-up in load.py.

Run from the project root:  python -m unittest
"""
import json
import unittest
from pathlib import Path

from pipeline import load, transform

FIXTURES = Path(__file__).resolve().parent / "fixtures"
GAME_PK = 822876       # Astros @ Rangers, 2026-07-12, copied from data/raw/
# pitcher in that game with an intentional walk; text, because Savant CSV values are text
PEYTON_GRAY = "682608"


def box_rows():
    box = json.loads((FIXTURES / "boxscore_822876.json").read_text(encoding="utf-8"))
    return transform.boxscore_rows(box, GAME_PK)


def pitch_rows():
    return transform.pitch_rows((FIXTURES / "pitches_822876.csv").read_text(encoding="utf-8"))


def game(pk, state):
    """A minimal /schedule game with only the fields schedule_row requires."""
    return {"gamePk": pk, "officialDate": "2026-07-10",
            "status": {"codedGameState": state},
            "teams": {"home": {"team": {"id": 111}}, "away": {"team": {"id": 121}}}}


class ScheduleTests(unittest.TestCase):
    def test_postponed_then_final_keeps_final(self):
        """Testing schedule dedupe for postponed games.

        A gamePk listed as Postponed and then Final keeps only the Final entry.
        """
        rows = transform.schedule_rows([game(1, "D"), game(1, "F"), game(2, "F")])
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["status_code"], "F")

    def test_final_is_never_replaced(self):
        """Testing schedule dedupe for duplicate entries.

        A Final entry stays even when a later duplicate is not Final.
        """
        rows = transform.schedule_rows([game(1, "F"), game(1, "D")])
        self.assertEqual(rows[0]["status_code"], "F")

    def test_unplayed_game_has_null_score(self):
        """Testing scores for unplayed games.

        A game that was never played gets a NULL score instead of 0.
        """
        self.assertIsNone(transform.schedule_rows([game(1, "D")])[0]["home_score"])


class TransactionTests(unittest.TestCase):
    def test_missing_person_and_from_team_become_none(self):
        """Testing missing fields for transactions.

        No person or fromTeam (e.g. cash or a signing) gives None in those columns.
        """
        row = transform.transaction_row(
            {"id": 1, "date": "2026-07-10", "toTeam": {"id": 111, "name": "Boston Red Sox"}})
        self.assertIsNone(row["person_id"])
        self.assertIsNone(row["from_team_id"])
        self.assertEqual(row["to_team_id"], 111)


class HeightTests(unittest.TestCase):
    def test_height_inches(self):
        """Testing height parsing for player heights.

        6' 4\" becomes 76 inches, and missing or odd values become None.
        """
        self.assertEqual(transform.height_inches("6' 4\""), 76)
        self.assertIsNone(transform.height_inches(None))       # missing
        self.assertIsNone(transform.height_inches("unknown"))  # odd format


class BoxScoreTests(unittest.TestCase):
    def test_bench_players_dropped(self):
        """Testing player filtering for box scores.

        Bench players with no batting or pitching stats are skipped.
        """
        rows = box_rows()
        self.assertEqual(len(rows), 38)  # 25 batters + 13 pitchers; bench players skipped
        self.assertEqual(sum(r["pit_pitches"] is not None for r in rows), 13)

    def test_batting_order_is_lineup_spot(self):
        """Testing batting order codes for box scores.

        Codes like "701" (spot 7, first substitute) are stored as lineup spot 1-9.
        """
        orders = {r["batting_order"] for r in box_rows()} - {None}
        self.assertEqual(orders, set(range(1, 10)))  # "701" -> 7, never 701


class PitchTests(unittest.TestCase):
    def test_one_row_per_pitch_with_renamed_ids(self):
        """Testing row count and column names for pitch data.

        Each CSV line becomes one row, with pitcher/batter renamed to pitcher_id/batter_id.
        """
        rows = pitch_rows()
        self.assertEqual(len(rows), 311)
        self.assertIn("pitcher_id", rows[0])
        self.assertNotIn("pitcher", rows[0])

    def test_blanks_become_none(self):
        """Testing blank values for pitch data.

        Savant's blanks become None, so SQLite stores NULL instead of empty text.
        """
        values = [v for row in pitch_rows() for v in row.values()]
        self.assertNotIn("", values)
        self.assertIn(None, values)

    def test_header_only_csv_gives_no_rows(self):
        """Testing empty downloads for pitch data.

        A CSV with only a header (no Savant data for the game) gives no rows.
        """
        header = (FIXTURES / "pitches_822876.csv").read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(transform.pitch_rows(header + "\n"), [])


class StatcastRollupTests(unittest.TestCase):
    def test_pitcher_stats_come_from_their_pitches(self):
        """Testing the Statcast roll-up for pitchers.

        sc_avg_velo averages only thrown pitches (automatic balls have no speed), and
        batters get no sc_* values.
        """
        conn = load.connect(":memory:")  # throwaway database, never touches redsox.db
        pitches = pitch_rows()
        load.insert_rows(conn, "BOX_SCORE", box_rows())
        load.insert_rows(conn, "PITCH", pitches)
        load.update_statcast_totals(conn)

        # Peyton Gray threw 16 pitches plus 4 automatic balls (intentional walk) that have no speed
        speeds = [float(p["release_speed"]) for p in pitches
                  if p["pitcher_id"] == PEYTON_GRAY and p["release_speed"] is not None]
        self.assertEqual(len(speeds), 16)
        avg_velo, = conn.execute(
            "SELECT sc_avg_velo FROM BOX_SCORE WHERE player_id = ?", (int(PEYTON_GRAY),)).fetchone()
        self.assertAlmostEqual(avg_velo, sum(speeds) / len(speeds), places=1)

        batters_with_sc, = conn.execute(
            "SELECT COUNT(*) FROM BOX_SCORE WHERE pit_pitches IS NULL AND sc_avg_velo IS NOT NULL"
        ).fetchone()
        self.assertEqual(batters_with_sc, 0)


if __name__ == "__main__":
    unittest.main()
