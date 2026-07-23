"""اسنپ‌شات جمع‌بندی پایان دست — پایداری در DB پس از ری‌استارت."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bot import db


class SessionRecapPersistTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmp.name) / "test.sqlite3"
        self._patch = mock.patch(
            "bot.config.get_database_path", return_value=self._db_path
        )
        self._patch.start()
        db.init_db()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def _sample_snapshot(self) -> dict[str, object]:
        return {
            "winner": "mafia",
            "scenario_name": "bazpors",
            "room_code": "70",
            "audit_log_path": None,
            "host_id": 108214166,
            "host_full_name": "Amir",
            "host_username": "amirlati",
            "observer_user_id": None,
            "max_players": 10,
            "bazpors_host_mode": "no_host",
            "rows": [
                {
                    "user_id": 108214166,
                    "seat": 4,
                    "tag": "Amir",
                    "role": "MAFIA_BOSS",
                    "yakuza_converted": False,
                    "original_role": None,
                },
            ],
        }

    def test_insert_stores_recap_snapshot(self) -> None:
        snap = self._sample_snapshot()
        sid = db.insert_game_session(
            "70",
            host_id=108214166,
            scenario_name="bazpors",
            winner="mafia",
            players=[{"id": 108214166, "fn": "Amir", "un": "amirlati"}],
            recap_snapshot=snap,
        )
        loaded = db.get_session_recap_snapshot(sid)
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["room_code"], "70")
        self.assertEqual(loaded["host_id"], 108214166)

    def test_broadcast_mark_clears_pending_snapshot(self) -> None:
        snap = self._sample_snapshot()
        sid = db.insert_game_session(
            "70",
            host_id=108214166,
            scenario_name="bazpors",
            winner="mafia",
            players=[{"id": 108214166, "fn": "Amir", "un": None}],
            recap_snapshot=snap,
        )
        self.assertFalse(db.session_recap_already_broadcasted(sid))
        db.mark_session_recap_broadcasted(sid)
        self.assertTrue(db.session_recap_already_broadcasted(sid))
        self.assertIsNone(db.get_session_recap_snapshot(sid))

    def test_finalize_loads_from_db_when_ram_empty(self) -> None:
        import asyncio

        from bot.main import PENDING_SESSION_RECAP, finalize_pending_session_recap

        snap = self._sample_snapshot()
        sid = db.insert_game_session(
            "70",
            host_id=108214166,
            scenario_name="bazpors",
            winner="mafia",
            players=[{"id": 108214166, "fn": "Amir", "un": None}],
            recap_snapshot=snap,
        )
        PENDING_SESSION_RECAP.pop(sid, None)

        class FakeBot:
            pass

        sent: list[int] = []

        async def fake_send(bot, chat_id, text, **kwargs):
            sent.append(chat_id)
            return True

        with mock.patch("bot.main.safe_send_message", side_effect=fake_send):
            ok = asyncio.run(finalize_pending_session_recap(FakeBot(), sid))

        self.assertTrue(ok)
        self.assertIn(108214166, sent)
        self.assertTrue(db.session_recap_already_broadcasted(sid))

    def test_finalize_fails_without_snapshot(self) -> None:
        import asyncio

        from bot.main import PENDING_SESSION_RECAP, finalize_pending_session_recap

        sid = db.insert_game_session(
            "70",
            host_id=1,
            scenario_name="bazpors",
            winner="mafia",
            players=[{"id": 2, "fn": "P", "un": None}],
        )
        PENDING_SESSION_RECAP.pop(sid, None)

        ok = asyncio.run(finalize_pending_session_recap(object(), sid))
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
