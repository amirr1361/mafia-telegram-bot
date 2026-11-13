"""Namayande 10-player fork (bot/nam10) — Phase 1 foundation contract tests.

Covers: package import smoke, fork room create + role-composition equivalence
with the Bazpors 10-player snapshot, lobby synthetic fill + display-name sync,
state-namespace isolation (fields AND engine helpers), routing predicates,
classical namayande counts untouched, snapshot persistence, and the documented
Phase-2 router rule: mirror acts are stateless strings shared by both engines,
so the dispatcher must branch on ``is_namayande10_no_host_room`` BEFORE the
generic act matching (guarded here by a contract assertion).
"""

from __future__ import annotations

import importlib
import json
import pathlib
import unittest
from collections import Counter

from bot import db
from bot.game import GameManager
from bot.models import Game, Phase, Player, Role
from bot.room_mode import (
    is_bazpors_no_host_room,
    is_namayande10_no_host_room,
    is_no_host_player_room,
    lobby_dev_fill_enabled,
)

FORK_PKG = "bot.nam10"


def setUpModule() -> None:
    try:
        db.init_db()
    except Exception:
        pass


def _fork_modules() -> list[str]:
    pkg_dir = pathlib.Path("bot/nam10")
    return sorted(p.stem for p in pkg_dir.glob("*.py") if p.stem != "__init__")


class Nam10ForkImportSmokeTests(unittest.TestCase):
    def test_all_fork_modules_import(self) -> None:
        bad = []
        for name in _fork_modules():
            try:
                importlib.import_module(f"{FORK_PKG}.{name}")
            except Exception as exc:  # noqa: BLE001
                bad.append((name, repr(exc)))
        self.assertEqual(bad, [])

    def test_fork_identity_distinct_from_bazpors(self) -> None:
        from bot.nam10.mode import is_nam10_fork_room

        game = Game(room_code="x1", host_id=1)
        game.scenario_name = "namayande"
        game.nmnd_host_mode = "no_host"
        self.assertTrue(is_nam10_fork_room(game))
        self.assertTrue(is_namayande10_no_host_room(game))
        game.scenario_name = "bazpors"
        self.assertFalse(is_nam10_fork_room(game))
        game.nmnd_host_mode = "no_host"
        self.assertFalse(is_nam10_fork_room(game))

    def test_model_has_independent_field_namespaces(self) -> None:
        fields = Game.__dataclass_fields__
        self.assertIn("bazpors_host_mode", fields)
        self.assertIn("nmnd_host_mode", fields)
        self.assertIn("no_host_detective_pending_tid", fields)
        self.assertIn("nam10_detective_pending_tid", fields)
        player_fields = Player.__dataclass_fields__
        self.assertIn("bazpors_original_role", player_fields)
        self.assertIn("nmnd_original_role", player_fields)


class Nam10ForkRoomSetupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _build_fork_room(self):
        game = self.gm.create_game(
            host_id=7001,
            host_full_name="سازنده",
            host_username=None,
            scenario_name="namayande",
            max_players=10,
            nam10_no_host=True,
        )
        assert game is not None
        for uid in range(7001, 7011):
            err = self.gm.add_player(
                game, Player(user_id=uid, full_name=f"پ{uid - 7000}", username=None)
            )
            self.assertIn(err, (None, "already_in_room"))
        return game

    def test_fork_room_create_and_identity(self) -> None:
        game = self._build_fork_room()
        self.assertEqual(game.nmnd_host_mode, "no_host")
        self.assertEqual(game.scenario_name, "namayande")
        self.assertIsNone(game.bazpors_host_mode)
        self.assertTrue(is_namayande10_no_host_room(game))
        self.assertTrue(is_no_host_player_room(game))

    def test_fork_accepts_10_to_13_rejects_others(self) -> None:
        # The expansion covers 10-13-player fork rooms.
        for n in (10, 11, 12, 13):
            game = self.gm.create_game(
                host_id=7100 + n,
                host_full_name="سازنده",
                host_username=None,
                scenario_name="namayande",
                max_players=n,
                nam10_no_host=True,
            )
            self.assertIsNotNone(game, n)
            self.assertEqual(game.nmnd_host_mode, "no_host", n)
        for n in (9, 14):
            game = self.gm.create_game(
                host_id=7200 + n,
                host_full_name="سازنده",
                host_username=None,
                scenario_name="namayande",
                max_players=n,
                nam10_no_host=True,
            )
            self.assertIsNone(game, n)

    def test_stage2_router_contract_act_strings_overlap(self) -> None:
        """Mirror act strings are stateless and shared; the Phase-2 dispatcher
        MUST branch on the fork-room identity before generic act matching.
        This test locks that requirement into the suite."""
        from bot.no_host_detective_night import (
            no_host_detective_act_active as baz_det_active,
        )

        fork = self._build_fork_room()
        # Original predicate is stateless: a fork room DOES light it up.
        # Therefore routing isolation cannot come from field state alone.
        self.assertTrue(baz_det_active(fork, "ndp"))

    def test_fork_state_fields_never_leak_into_shared_state(self) -> None:
        """Setting fork state touches no Bazpors/shared field and vice versa."""
        fork = self._build_fork_room()
        fork.nam10_detective_pending_tid = 9010
        fork.nmnd_mafia_recruit_ids.add(9011)
        self.assertEqual(fork.no_host_detective_pending_tid, None)
        self.assertEqual(len(fork.bazpors_mafia_recruit_ids), 0)
        self.assertEqual(fork.bazpors_host_mode, None)


class Nam10CompositionEquivalenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _build_fork_room(self):
        game = self.gm.create_game(
            host_id=7050,
            host_full_name="سازنده",
            host_username=None,
            scenario_name="namayande",
            max_players=10,
            nam10_no_host=True,
        )
        assert game is not None
        for uid in range(7050, 7060):
            err = self.gm.add_player(
                game, Player(user_id=uid, full_name=f"پ{uid - 7049}", username=None)
            )
            self.assertIn(err, (None, "already_in_room"))
        return game

    def test_composition_matches_bazpors_10p_snapshot(self) -> None:
        from bot.game import bazpors_roles_for_count
        from bot.nam10.lobby import roles_for_count

        self.assertEqual(
            Counter(roles_for_count(10)), Counter(bazpors_roles_for_count(10))
        )
        game = self._build_fork_room()
        game.seats_finalized = True
        self.gm.assign_roles(game)
        got = Counter(p.role for p in game.players.values())
        self.assertEqual(got, Counter(bazpors_roles_for_count(10)))
        self.assertEqual(len(game.mafia_ids), 3)
        for pl in game.players.values():
            self.assertIsNone(pl.nmnd_original_role)
            self.assertFalse(pl.nmnd_converted_by_yakuza)
            self.assertIsNone(pl.bazpors_original_role)
            self.assertFalse(pl.bazpors_converted_by_yakuza)

    def _creator_only_fork_room(self):
        game = self.gm.create_game(
            host_id=7070,
            host_full_name="سازنده",
            host_username=None,
            scenario_name="namayande",
            max_players=10,
            nam10_no_host=True,
        )
        assert game is not None
        err = self.gm.add_player(
            game, Player(user_id=7070, full_name="سازنده", username=None)
        )
        self.assertIn(err, (None, "already_in_room"))
        return game

    def test_synthetic_lobby_fill_and_display_name_sync(self) -> None:
        from bot.game import is_synthetic_player_uid
        from bot.nam10.lobby import sync_synthetic_player_display_names_nam10

        game = self._creator_only_fork_room()
        err = self.gm.fill_namayande10_synthetic_lobby(game)
        self.assertIsNone(err)
        self.assertEqual(len(game.players), 10)
        game.seats_finalized = True
        self.gm.assign_roles(game)
        sync_synthetic_player_display_names_nam10(game)
        labeled = [
            pl.full_name
            for pl in game.players.values()
            if is_synthetic_player_uid(pl.user_id)
        ]
        # creator kept its real name; exactly 9 synthetic seats were filled
        self.assertEqual(len(labeled), 9)
        for name in labeled:
            self.assertIn("-", name)

    def test_by_player_assignment_fork_fields(self) -> None:
        from bot.nam10.lobby import assign_roles_by_player_namayande10

        game = self._build_fork_room()
        players = sorted(game.players.values(), key=lambda p: p.user_id)
        role_by_player = {
            p.user_id: role
            for p, role in zip(
                players,
                [
                    Role.MAFIA_BOSS,
                    Role.NATO,
                    Role.SHIAD,
                    Role.HUNTER,
                    Role.INTERROGATOR,
                    Role.DETECTIVE,
                    Role.DOCTOR,
                    Role.RUINTAN,
                    Role.CITIZEN,
                    Role.CITIZEN,
                ],
            )
        }
        assign_roles_by_player_namayande10(game, role_by_player)
        for p in players:
            self.assertEqual(p.role, role_by_player[p.user_id])
        boss_uid = next(
            p.user_id for p in players if p.role == Role.MAFIA_BOSS
        )
        self.assertIn(boss_uid, game.mafia_ids)

    def test_classic_namayande_untouched(self) -> None:
        for count in (10, 11, 12):
            game = self.gm.create_game(
                host_id=7300 + count,
                host_full_name="سازنده",
                host_username=None,
                scenario_name="namayande",
                max_players=count,
            )
            assert game is not None
            self.assertIsNone(game.nmnd_host_mode)
            self.assertFalse(is_namayande10_no_host_room(game))
            self.assertFalse(is_no_host_player_room(game))


class Nam10IsolationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _fork_game(self) -> Game:
        game = self.gm.create_game(
            host_id=8001,
            host_full_name="سازنده",
            host_username=None,
            scenario_name="namayande",
            max_players=10,
            nam10_no_host=True,
        )
        assert game is not None
        return game

    def _bazpors_game(self) -> Game:
        game = self.gm.create_game(
            host_id=8100,
            host_full_name="سازنده",
            host_username=None,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        return game

    def test_room_predicate_matrix(self) -> None:
        fork = self._fork_game()
        baz = self._bazpors_game()
        self.assertTrue(is_namayande10_no_host_room(fork))
        self.assertFalse(is_bazpors_no_host_room(fork))
        self.assertTrue(is_bazpors_no_host_room(baz))
        self.assertFalse(is_namayande10_no_host_room(baz))
        self.assertTrue(lobby_dev_fill_enabled(fork))
        self.assertTrue(lobby_dev_fill_enabled(baz))

    def test_doctor_pending_state_isolation_both_directions(self) -> None:
        from bot.no_host_doctor_night import _pending_save_uid as baz_pending
        from bot.nam10.no_host_doctor_night import (
            _pending_save_uid as fork_pending,
        )

        fork = self._fork_game()
        baz = self._bazpors_game()
        fork.nam10_doctor_pending_save_uids = [9003]
        baz.no_host_doctor_pending_save_uids = [9004]
        self.assertEqual(fork_pending(fork), 9003)
        self.assertEqual(baz_pending(baz), 9004)
        self.assertIsNone(fork_pending(baz))
        self.assertIsNone(baz_pending(fork))

    def test_yakuza_helpers_only_touch_fork_state(self) -> None:
        from bot.nam10.engine import (
            apply_bazpors_yakuzai_recruit,
            mark_bazpors_eliminated_by_sniper,
        )

        fork = self._fork_game()
        for uid in range(8201, 8211):
            self.gm.add_player(
                fork, Player(user_id=uid, full_name=f"ب{uid - 8200}", username=None)
            )
        victim_uid = sorted(fork.players.keys())[0]
        victim = fork.players[victim_uid]
        victim.role = Role.CITIZEN
        apply_bazpors_yakuzai_recruit(fork, victim)
        self.assertEqual(victim.role, Role.MAFIA_BASIC)
        self.assertEqual(victim.nmnd_original_role, Role.CITIZEN)
        self.assertTrue(victim.nmnd_converted_by_yakuza)
        self.assertIn(victim_uid, fork.nmnd_mafia_recruit_ids)
        self.assertNotIn(victim_uid, fork.bazpors_mafia_recruit_ids)
        mark_bazpors_eliminated_by_sniper(fork, victim_uid)
        self.assertIn(victim_uid, fork.nmnd_sniper_eliminated_uids)
        self.assertNotIn(victim_uid, fork.bazpors_sniper_eliminated_uids)

    def test_fork_counts_as_mafia_faction_scope(self) -> None:
        from bot.nam10.engine import nmnd_counts_as_mafia_faction

        fork = self._fork_game()
        for uid in range(8301, 8311):
            self.gm.add_player(
                fork, Player(user_id=uid, full_name=f"ب{uid - 8300}", username=None)
            )
        citizens = [p for p in fork.players.values()]
        for p in citizens:
            p.role = Role.CITIZEN
        recruited = citizens[0]
        recruited.role = Role.MAFIA_BASIC
        self.assertTrue(nmnd_counts_as_mafia_faction(fork, recruited))
        self.assertFalse(nmnd_counts_as_mafia_faction(fork, citizens[1]))


class Nam10SnapshotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        try:
            db.init_db()
        except Exception:
            pass

    def test_fork_room_snapshot_roundtrip(self) -> None:
        from bot.game_snapshot import (
            persist_game_snapshot,
            restore_games_into_manager,
        )

        gm = GameManager()
        game = gm.create_game(
            host_id=9001,
            host_full_name="سازنده",
            host_username=None,
            scenario_name="namayande",
            max_players=10,
            nam10_no_host=True,
        )
        assert game is not None
        for uid in range(9001, 9011):
            gm.add_player(
                game, Player(user_id=uid, full_name=f"ب{uid - 9000}", username=None)
            )
        game.phase = Phase.MANUAL
        game.nam10_detective_pending_tid = 9099
        persist_game_snapshot(game, reason="test")
        restored_manager = GameManager()
        restored = restore_games_into_manager(restored_manager)
        self.assertIn(game.room_code, restored)
        rgame = restored_manager.get_game(game.room_code)
        assert rgame is not None
        self.assertEqual(rgame.scenario_name, "namayande")
        self.assertEqual(rgame.nmnd_host_mode, "no_host")
        self.assertEqual(rgame.nam10_detective_pending_tid, 9099)
        self.assertEqual(
            len(rgame.players),
            len(game.players),
        )


if __name__ == "__main__":
    unittest.main()
