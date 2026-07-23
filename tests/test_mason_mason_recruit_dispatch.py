"""تست ارسال پنل جذب ماسون — سناریوی ماسون (Room 79 style)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager, is_synthetic_player_uid
from bot.mason_night_role import (
    MSM_NONE,
    MSM_TAILOR,
    dispatch_mason_mason_recruit_panel,
    dispatch_mason_night_role,
)
from bot.models import Player, Role
from bot.roles import mason_fraternity as ms_mf


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
    return game


def _setup_mason(game, gm) -> Player:
    mason = _p(10, "Amir", Role.MASON)
    gm.add_player(game, mason)
    ms_mf.initialize_mason_team_for_new_game(game)
    return mason


class MasonRecruitDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_alive_mason_dispatches_recruit_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason = _setup_mason(game, gm)
        gm.add_player(game, _p(20, "Hasan", Role.TOWN_SIMPLE))
        bot = MagicMock()
        captured: list[tuple[int, str, bool, bool]] = []

        async def _capture(bot_, game_, uid, ui_key, text, kb, **kw):
            captured.append(
                (uid, text, kw.get("send_player", True), kw.get("send_observer", False))
            )

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_mason_recruit_panel(bot, game, gm)

        self.assertEqual(len(captured), 1)
        uid, text, send_player, send_observer = captured[0]
        self.assertEqual(uid, mason.user_id)
        self.assertIn("ماسون", text)
        self.assertIn("اعضای کنونی تیم ماسون:", text)
        self.assertIn("Amir", text)
        self.assertTrue(send_player)
        self.assertTrue(send_observer)
        self.assertFalse(game.mason_night_mason_confirmed)

    async def test_panel_lists_alive_team_members(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason = _setup_mason(game, gm)
        hasan = _p(20, "Hasan", Role.TOWN_SIMPLE)
        qasem = _p(21, "Qasem", Role.TOWN_SIMPLE)
        gm.add_player(game, hasan)
        gm.add_player(game, qasem)
        game.mason_team_member_ids.add(hasan.user_id)
        game.mason_team_member_ids.add(qasem.user_id)
        qasem.is_alive = False
        bot = MagicMock()
        captured: list[str] = []

        async def _capture(bot_, game_, uid, ui_key, text, kb, **kw):
            captured.append(text)

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_mason_recruit_panel(bot, game, gm)

        text = captured[0]
        self.assertIn("اعضای کنونی تیم ماسون:", text)
        self.assertIn("Amir", text)
        self.assertIn("Hasan", text)
        self.assertNotIn("Qasem", text)

    async def test_panel_empty_team_fallback(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason = _setup_mason(game, gm)
        game.mason_team_member_ids.clear()
        bot = MagicMock()
        captured: list[str] = []

        async def _capture(bot_, game_, uid, ui_key, text, kb, **kw):
            captured.append(text)

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_mason_recruit_panel(bot, game, gm)

        self.assertIn("هیچ عضوی ثبت نشده است.", captured[0])

    async def test_synthetic_mason_still_mirrors_to_observer(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        syn = -920079
        self.assertTrue(is_synthetic_player_uid(syn))
        mason = _p(syn, "SynMason", Role.MASON)
        gm.add_player(game, mason)
        ms_mf.initialize_mason_team_for_new_game(game)
        gm.add_player(game, _p(20, "Hasan", Role.TOWN_SIMPLE))
        bot = MagicMock()

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            new=AsyncMock(),
        ) as reg:
            await dispatch_mason_mason_recruit_panel(bot, game, gm)

        reg.assert_awaited_once()
        kw = reg.await_args.kwargs
        self.assertTrue(kw.get("send_observer"))
        self.assertTrue(kw.get("send_player"))
        self.assertFalse(game.mason_night_mason_confirmed)

    async def test_panel_includes_tailor_button_when_available(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason(game, gm)
        gm.add_player(game, _p(40, "Tyler", Role.TAILOR))
        gm.add_player(game, _p(20, "Hasan", Role.TOWN_SIMPLE))
        bot = MagicMock()
        button_texts: list[str] = []

        async def _capture(bot_, game_, uid, ui_key, text, kb, **kw):
            for row in kb.inline_keyboard:
                for btn in row:
                    button_texts.append(btn.text)

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_capture,
        ):
            await dispatch_mason_mason_recruit_panel(bot, game, gm)

        self.assertIn(ms_mf.MASON_TAILOR_RECRUIT_LABEL, button_texts)
        self.assertIn(ms_mf.MASON_NO_RECRUIT_LABEL, button_texts)

    async def test_none_pick_confirms_mason_readiness(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason = _setup_mason(game, gm)
        gm.add_player(game, _p(20, "Hasan", Role.TOWN_SIMPLE))
        game.no_host_night_parallel_collect_active = True
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        with patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=mason.user_id,
                actor_uid=mason.user_id,
                act=MSM_NONE,
                tid=0,
            )

        self.assertTrue(game.mason_night_mason_confirmed)
        self.assertTrue(game.mason_mason_night_no_recruit)

    async def test_tailor_pick_confirms_mason_readiness(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        mason = _setup_mason(game, gm)
        tailor = _p(40, "Tyler", Role.TAILOR)
        gm.add_player(game, tailor)
        game.no_host_night_parallel_collect_active = True
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        with patch(
            "bot.mason_recruit_delivery.deliver_mason_recruit_membership_message",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=mason.user_id,
                actor_uid=mason.user_id,
                act=MSM_TAILOR,
                tid=tailor.user_id,
            )

        self.assertTrue(game.mason_night_mason_confirmed)
        self.assertEqual(game.mason_pending_recruit_uid, tailor.user_id)

    async def test_dead_mason_auto_confirms_without_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        mason = _p(10, "Amir", Role.MASON, alive=False)
        gm.add_player(game, mason)
        ms_mf.initialize_mason_team_for_new_game(game)
        bot = MagicMock()

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            new=AsyncMock(),
        ) as reg:
            await dispatch_mason_mason_recruit_panel(bot, game, gm)

        reg.assert_not_awaited()
        self.assertTrue(game.mason_night_mason_confirmed)

    async def test_observer_acts_for_synthetic_mason(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        syn = -920079
        mason = _p(syn, "SynMason", Role.MASON)
        gm.add_player(game, mason)
        ms_mf.initialize_mason_team_for_new_game(game)
        game.no_host_night_parallel_collect_active = True
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        with patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=syn,
                actor_uid=999,
                act=MSM_NONE,
                tid=0,
            )

        self.assertTrue(game.mason_night_mason_confirmed)


class MasonRecruitPanelHtmlTests(unittest.TestCase):
    def test_build_panel_lists_members(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="masoon",
            max_players=16,
        )
        assert game is not None
        mason = _p(10, "Amir", Role.MASON)
        hasan = _p(20, "Hasan", Role.TOWN_SIMPLE)
        gm.add_player(game, mason)
        gm.add_player(game, hasan)
        ms_mf.initialize_mason_team_for_new_game(game)
        text = ms_mf.build_mason_recruit_panel_html(game)
        self.assertIn("اعضای کنونی تیم ماسون:", text)
        self.assertIn("Amir", text)
        self.assertNotIn("Hasan", text)
