"""مدال پایان دست — هر بازیکن حداکثر یک مدال."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bot import db


class SessionMedalsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmp.name) / "test.sqlite3"
        self._patch = mock.patch(
            "bot.config.get_database_path", return_value=self._db_path
        )
        self._patch.start()
        from bot.db import init_db

        init_db()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def _session_with_players(self) -> int:
        return db.insert_game_session(
            "01",
            host_id=1,
            scenario_name="bazpors",
            winner="citizen",
            players=[
                {"id": 10, "fn": "رضا", "un": None},
                {"id": 20, "fn": "امیر", "un": None},
                {"id": 30, "fn": "حسن", "un": None},
            ],
        )

    def test_available_excludes_previous_recipients(self) -> None:
        sid = self._session_with_players()
        all_ids = {10, 20, 30}
        self.assertEqual(
            {int(p["id"]) for p in db.session_players_available_for_medal(sid)},
            all_ids,
        )
        db.save_session_medal(sid, "gold", 10)
        available = db.session_players_available_for_medal(sid)
        self.assertEqual({int(p["id"]) for p in available}, {20, 30})
        db.save_session_medal(sid, "silver", 20)
        available = db.session_players_available_for_medal(sid)
        self.assertEqual({int(p["id"]) for p in available}, {30})


if __name__ == "__main__":
    unittest.main()
