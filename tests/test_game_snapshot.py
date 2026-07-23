"""فاز ۴ — snapshot/recovery بازی فعال."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bot import db
from bot.game import GameManager
from bot.game_snapshot import (
    delete_game_snapshot,
    game_from_snapshot_dict,
    game_to_snapshot_dict,
    persist_game_snapshot,
    restore_games_into_manager,
)
from bot.models import Phase, Player, Role


class GameSnapshotRoundTripTests(unittest.TestCase):
    def test_encode_decode_bazpors_no_host(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=100,
            host_full_name="Host",
            host_username="h",
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game, Player(user_id=100, full_name="Host", username="h")
        )
        gm.fill_bazpors_no_host_synthetic_lobby(game)
        gm.assign_roles(game)
        game.seats_finalized = True
        game.roles_dealt = True
        game.bazpors_narrator_step = "night_start"
        game.bazpors_narrator_night_count = 1
        game.no_host_doctor_flow_active = True
        game.no_host_mafia_night1_refs[200] = (100, 42, "panel")
        game.mafia_ids = {200, 201}
        game.player_end_approvals = {100, 200}

        payload = game_to_snapshot_dict(game)
        raw = json.dumps(payload, ensure_ascii=False)
        loaded = game_from_snapshot_dict(json.loads(raw))

        self.assertEqual(loaded.room_code, game.room_code)
        self.assertEqual(loaded.phase, game.phase)
        self.assertEqual(loaded.bazpors_host_mode, "no_host")
        self.assertEqual(loaded.bazpors_narrator_step, "night_start")
        self.assertEqual(len(loaded.players), len(game.players))
        self.assertEqual(loaded.mafia_ids, game.mafia_ids)
        self.assertEqual(loaded.player_end_approvals, game.player_end_approvals)
        self.assertEqual(
            loaded.no_host_mafia_night1_refs[200],
            game.no_host_mafia_night1_refs[200],
        )
        p100 = loaded.players[100]
        self.assertIsNotNone(p100.role)


class GameSnapshotDbTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmp.name) / "test.sqlite3"
        self._patch = mock.patch(
            "bot.config.get_database_path", return_value=self._db_path
        )
        self._patch.start()
        db.init_db()
        db.delete_all_active_game_snapshots()
        self.gm = GameManager()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def test_persist_and_restore_after_simulated_restart(self) -> None:
        game = self.gm.create_game(
            host_id=501,
            host_full_name="G",
            host_username=None,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=501, full_name="G", username=None)
        )
        self.gm.fill_bazpors_semi_auto_synthetic_lobby(game)
        self.gm.assign_roles(game)
        code = game.room_code
        self.gm.persist_snapshot(game, reason="test")

        fresh = GameManager()
        restored = fresh.restore_active_games_from_db()
        self.assertIn(code, restored)
        g2 = fresh.get_game(code)
        assert g2 is not None
        self.assertEqual(len(g2.players), 10)
        self.assertEqual(fresh.get_room_for_host(501), code)
        self.assertEqual(fresh.get_room_for_user(501), code)

    def test_end_game_deletes_snapshot(self) -> None:
        game = self.gm.create_game(
            host_id=601,
            host_full_name="H",
            host_username=None,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        persist_game_snapshot(game, reason="create")
        code = game.room_code
        self.gm.end_game(code)
        codes = [r["room_code"] for r in db.list_active_game_snapshots()]
        self.assertNotIn(code, codes)

    def test_restore_skips_corrupt_snapshot(self) -> None:
        db.upsert_active_game_snapshot(
            "99",
            "{not-json",
            reason="bad",
            phase="LOBBY",
            roles_dealt=0,
        )
        fresh = GameManager()
        self.assertEqual(fresh.restore_active_games_from_db(), [])
        self.assertEqual(db.list_active_game_snapshots(), [])


class GameSnapshotSimulationTests(unittest.TestCase):
    """شبیه‌سازی ری‌استارت وسط چند بازی."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._db_path = Path(self._tmp.name) / "test.sqlite3"
        self._patch = mock.patch(
            "bot.config.get_database_path", return_value=self._db_path
        )
        self._patch.start()
        db.init_db()
        db.delete_all_active_game_snapshots()

    def tearDown(self) -> None:
        self._patch.stop()
        self._tmp.cleanup()

    def test_multi_game_restore_semi_auto_and_no_host(self) -> None:
        gm = GameManager()
        codes: list[str] = []
        for i, mode in enumerate(("semi_auto", "no_host", "semi_auto")):
            host = 7000 + i
            game = gm.create_game(
                host_id=host,
                host_full_name=f"H{i}",
                host_username=None,
                scenario_name="bazpors",
                max_players=10,
                bazpors_host_mode=mode,
            )
            assert game is not None
            gm.add_player(
                game,
                Player(user_id=host, full_name=f"H{i}", username=None),
            )
            if mode == "no_host":
                gm.fill_bazpors_no_host_synthetic_lobby(game)
            else:
                gm.fill_bazpors_semi_auto_synthetic_lobby(game)
            gm.assign_roles(game)
            game.seats_finalized = True
            gm.finalize_deal_roles_phase(game)
            codes.append(game.room_code)

        gm2 = GameManager()
        restored = gm2.restore_active_games_from_db()
        self.assertEqual(len(restored), 3)
        for code in codes:
            g = gm2.get_game(code)
            assert g is not None
            self.assertTrue(g.roles_dealt)
            self.assertEqual(g.phase, Phase.MANUAL)


if __name__ == "__main__":
    unittest.main()
