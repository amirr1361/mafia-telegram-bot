"""امتیاز پس از پایان بازی — مستقل از اتاق فعال."""

from __future__ import annotations

import os
import tempfile
import unittest

from bot import db


class PostGameRatingDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._old = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = str(
            os.path.join(self._tmpdir.name, "test.sqlite3")
        )
        db.init_db()

    def tearDown(self) -> None:
        if self._old is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self._old
        self._tmpdir.cleanup()

    def _session(
        self,
        *,
        host_id: int = 1,
        players: list[dict[str, object]] | None = None,
    ) -> int:
        payload = players or [
            {"id": host_id, "fn": "Host", "un": None},
            {"id": 20, "fn": "P20", "un": None},
        ]
        return db.insert_game_session(
            "77",
            host_id,
            "bazpors",
            "citizen",
            payload,
        )

    def test_rating_via_invite_without_player_id_key(self) -> None:
        sid = db.insert_game_session(
            "88",
            1,
            "bazpors",
            "mafia",
            [{"user_id": 1, "fn": "Host"}, {"user_id": 30, "fn": "P30"}],
        )
        db.record_rating_invite(sid, 30)
        self.assertIsNone(db.rating_submission_error(sid, 30))
        self.assertTrue(db.save_narrator_rating(sid, 30, 4))

    def test_host_cannot_rate(self) -> None:
        sid = self._session()
        db.record_rating_invite(sid, 1)
        self.assertEqual(
            db.rating_submission_error(sid, 1),
            "گرداننده به خودش امتیاز نمی‌دهد.",
        )

    def test_duplicate_rating_rejected(self) -> None:
        sid = self._session()
        db.record_rating_invite(sid, 20)
        self.assertTrue(db.save_narrator_rating(sid, 20, 5))
        self.assertEqual(
            db.rating_submission_error(sid, 20),
            "قبلاً برای این دست امتیاز داده‌اید.",
        )

    def test_latest_unrated_session(self) -> None:
        sid1 = self._session(players=[{"id": 1, "fn": "H"}, {"id": 20, "fn": "A"}])
        sid2 = self._session(players=[{"id": 1, "fn": "H"}, {"id": 20, "fn": "A"}])
        db.record_rating_invite(sid1, 20)
        db.record_rating_invite(sid2, 20)
        db.save_narrator_rating(sid2, 20, 3)
        self.assertEqual(db.latest_unrated_session_for_user(20), sid1)
