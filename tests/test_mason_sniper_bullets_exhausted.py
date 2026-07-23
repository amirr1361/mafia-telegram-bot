"""تست گلوله‌های تمام‌شدهٔ اسنایپر — سناریوی ماسون (Room 22)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager, is_synthetic_player_uid
from bot.mason_night_entry import (
    MASON_NIGHT_WAIT_TEXT,
    night_action_holder_uids,
    reset_mason_current_night_selections,
)
from bot.mason_night_ready import all_mason_parallel_night_ready
from bot.mason_night_role import (
    MASON_NO_NIGHT_PICK_WAIT_TEXT,
    dispatch_mason_commander_panel,
    dispatch_mason_sniper_panel,
)
from bot.models import Player, Role
from bot.roles import mason_commander as ms_cmd
from bot.roles import mason_sniper as ms_sn


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mason_game(gm: GameManager, *, n: int = 16):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bot_assistant_user_id = 900
    game.observer_prompt_status = "registered"
    game.observer_user_id = 999
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = NIGHT_START
    game.no_host_night_parallel_collect_active = True
    return game


def _arm_other_roles(game) -> None:
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_chosen_action = "shot"
    game.no_host_mafia_shot_done = True
    game.mason_night_saboteur_confirmed = True
    game.mason_night_doctor_confirmed = True
    game.mason_night_gunner_confirmed = True
    game.mason_night_guardian_confirmed = True
    game.mason_night_mason_confirmed = True
    game.mason_night_detective_confirmed = True
    game.mason_night_natasha_confirmed = True
    game.mason_night_priest_confirmed = True
    game.mason_night_commander_confirmed = True


class MasonSniperBulletAccountingTests(unittest.TestCase):
    def test_room22_total_bullets_is_three(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        self.assertEqual(ms_sn.mason_sniper_total_bullets(game), 3)

    def test_bullets_spent_survives_night_reset(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        game.mason_sniper_bullets_spent = 3
        game.mason_sniper_night_selected_uids = [20, 30]
        reset_mason_current_night_selections(game)
        self.assertEqual(game.mason_sniper_bullets_spent, 3)
        self.assertEqual(ms_sn.mason_sniper_night_selected_uids(game), [])

    def test_no_commander_auto_approves_sniper_selections(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "B", Role.TOWN_SIMPLE))
        ms_sn.commit_mason_sniper_night_selection(game, [20, 30])
        ms_cmd.auto_approve_sniper_shots_when_no_commander(game)
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 2)
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [20, 30])

    def test_commander_reject_does_not_consume_bullets(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(40, "Cmd", Role.COMMANDER))
        ms_sn.commit_mason_sniper_night_selection(game, [20])
        ms_cmd.mason_commander_rejects_all_shots(game)
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 0)

    def test_room22_two_night_simulation_exhausts_three_bullets(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "B", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(40, "C", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(50, "Cmd", Role.COMMANDER))

        # Night 1 — two approved shots
        ms_sn.commit_mason_sniper_night_selection(game, [20, 30])
        ms_cmd.commit_mason_commander_approval(game, [20, 30])
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 2)
        reset_mason_current_night_selections(game)

        # Night 2 — one more approved shot
        ms_sn.commit_mason_sniper_night_selection(game, [40])
        ms_cmd.commit_mason_commander_approval(game, [40])
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 3)
        reset_mason_current_night_selections(game)

        # Night 3 — no bullets left
        self.assertEqual(ms_sn.mason_sniper_bullets_remaining(game), 0)
        self.assertFalse(ms_sn.mason_sniper_needs_night_pick(game))


class MasonSniperExhaustedDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_shot_panel_when_bullets_exhausted(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        bot = MagicMock()
        captured: list[tuple[int, str, object | None]] = []

        async def _capture(_bot, _game, uid, _ui, text, kb, **kw):
            captured.append((uid, text, kb))

        with patch(
            "bot.mason_night_role._show_mason_sniper_panel",
            new=AsyncMock(),
        ) as show_sn, patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_sniper_panel(bot, game, gm)

        show_sn.assert_not_awaited()
        self.assertFalse(game.mason_night_sniper_confirmed)
        sniper_msgs = [row for row in captured if row[0] == 50]
        self.assertEqual(len(sniper_msgs), 1)
        _, text, kb = sniper_msgs[0]
        self.assertIn(MASON_NO_NIGHT_PICK_WAIT_TEXT, text)
        self.assertIsNotNone(kb)

    async def test_commander_inherits_no_shot_panel_when_bullets_zero(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        game.mason_night_sniper_confirmed = True
        bot = MagicMock()
        captured: list[tuple[int, str, object | None]] = []

        async def _capture(_bot, _game, uid, _ui, text, kb, **kw):
            captured.append((uid, text, kb))

        with patch(
            "bot.mason_night_role._show_mason_commander_panel",
            new=AsyncMock(),
        ) as show_cmd, patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_commander_panel(bot, game, gm)

        show_cmd.assert_not_awaited()
        self.assertFalse(game.mason_night_commander_confirmed)
        cmd_msgs = [row for row in captured if row[0] == 51]
        self.assertEqual(len(cmd_msgs), 1)
        _, text, kb = cmd_msgs[0]
        self.assertIn(MASON_NO_NIGHT_PICK_WAIT_TEXT, text)
        self.assertIsNotNone(kb)

    async def test_synthetic_sniper_still_dispatches_no_pick_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        syn = -920050
        gm.add_player(game, _p(syn, "SynSn", Role.SNIPER))
        game.mason_sniper_bullets_spent = 3
        bot = MagicMock()
        captured: list[tuple[int, str, dict]] = []

        async def _capture(_bot, _game, uid, _ui, text, kb, **kw):
            captured.append((uid, text, kw))

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_sniper_panel(bot, game, gm)

        self.assertEqual(len(captured), 1)
        uid, text, kw = captured[0]
        self.assertEqual(uid, syn)
        self.assertIn(MASON_NO_NIGHT_PICK_WAIT_TEXT, text)
        self.assertTrue(kw.get("send_observer"))
        self.assertTrue(is_synthetic_player_uid(syn))

    async def test_exhausted_sniper_skips_generic_wait_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        game.mason_sniper_bullets_spent = 3
        game.mason_night_commander_confirmed = True
        captured: list[tuple[int, str]] = []

        async def _capture(_bot, _game, uid, _ui, text, _kb, **kw):
            captured.append((uid, text))

        with patch(
            "bot.mason_night_entry.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            from bot.mason_night_entry import _dispatch_mason_wait_panels

            await _dispatch_mason_wait_panels(AsyncMock(), game)

        sniper_msgs = [t for uid, t in captured if uid == 50]
        self.assertEqual(len(sniper_msgs), 0)

    def test_exhausted_sniper_excluded_from_action_holders(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        game.mason_sniper_bullets_spent = 3
        self.assertNotIn(50, night_action_holder_uids(game))

    def test_readiness_not_blocked_when_sniper_exhausted(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_confirmed = True
        _arm_other_roles(game)
        game.mason_night_wait_ok_uids = [50, 51]
        self.assertTrue(all_mason_parallel_night_ready(game))

    async def test_night_resolution_runs_when_bullets_exhausted(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(51, "Cmd", Role.COMMANDER))
        game.mason_sniper_bullets_spent = 3
        _arm_other_roles(game)
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_confirmed = True
        game.mason_night_wait_ok_uids = [50, 51]
        bot = MagicMock()
        finish = AsyncMock()

        with patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            finish,
        ):
            from bot.mason_night_ready import maybe_finish_mason_parallel_night

            await maybe_finish_mason_parallel_night(bot, game, gm)

        finish.assert_awaited_once()

    async def test_synthetic_sniper_observer_ok(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        syn = -920050
        gm.add_player(game, _p(syn, "SynSn", Role.SNIPER))
        game.mason_sniper_bullets_spent = 3
        _arm_other_roles(game)
        self.assertTrue(is_synthetic_player_uid(syn))
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        with patch(
            "bot.observer_delivery.update_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            from bot.mason_night_entry import dispatch_mason_night_wait_ok

            await dispatch_mason_night_wait_ok(
                cb, bot, game, gm, as_uid=syn, actor_uid=999
            )

        self.assertIn(syn, game.mason_night_wait_ok_uids)


if __name__ == "__main__":
    unittest.main()
