"""پنل دفاعیهٔ روز بازپرس — رنگ دکمه‌ها + تأیید دومرحله‌ای «دفاعیه نداریم»."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import begin_no_host_day1_defense_pick, day_vote_pick_uids
from bot.game import GameManager
from bot.main import (
    NO_HOST_DAY1_NONE_CONFIRM_HTML,
    NoHostDay1DefenseCb,
    PlayerMirrorCb,
    _day1_defense_panel_style_kwargs,
    _dispatch_no_host_day1_defense_act,
    _no_host_day1_defense_no_votes,
    _no_host_day1_none_confirm_keyboard,
    _no_host_day1_defense_pick_keyboard,
    build_no_host_day1_defense_pick_html,
    day1_defense_pick_keyboard_for,
)
from bot.models import Player, Role


def _p(uid: int, name: str, role: Role = Role.CITIZEN) -> Player:
    return Player(user_id=uid, full_name=name, username=None, role=role)


def _btn_texts(kb):
    return [btn.text for row in kb.inline_keyboard for btn in row]


def _player_buttons(kb):
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            if "nhd" in (btn.callback_data or "") and (
                ":tog:" in btn.callback_data or btn.text.startswith(("✅", "☐"))
            ):
                out.append(btn)
            elif "pmr" in (btn.callback_data or "") and ":d1dt:" in btn.callback_data:
                out.append(btn)
    return out


class BazporsDay1DefenseColourSpecTests(unittest.TestCase):
    """رنگ دکمه‌ها — فقط بازپرس: آبی/قرمز بازیکنان، سبز دو دکمهٔ پایانی."""

    def setUp(self):
        self.gm = GameManager()

    def _game(self, scenario="bazpors", mode="no_host"):
        game = self.gm.create_game(
            host_id=1,
            scenario_name=scenario,
            max_players=12,
            bazpors_host_mode=mode,
        )
        assert game is not None
        for uid, name in ((10, "A"), (20, "B"), (30, "C")):
            self.gm.add_player(game, _p(uid, name))
        game.roles_dealt = True
        game.bot_assistant_user_id = 10
        begin_no_host_day1_defense_pick(game)
        return game

    def test_player_buttons_initially_blue(self):
        game = self._game()
        kb = day1_defense_pick_keyboard_for(game, 10)
        player_btns = _player_buttons(kb)
        self.assertEqual(len(player_btns), 3)
        for btn in player_btns:
            self.assertEqual(getattr(btn, "style", None), "primary")

    def test_selected_player_red_unselected_blue(self):
        game = self._game()
        from bot.bazpors_narrator import set_day_vote_pick_uids

        set_day_vote_pick_uids(game, {20})
        kb = day1_defense_pick_keyboard_for(game, 10)
        checked = {
            btn.text: getattr(btn, "style", None)
            for btn in _player_buttons(kb)
            if btn.text.startswith("✅")
        }
        self.assertEqual(len(checked), 1)
        for _label, style in checked.items():
            self.assertEqual(style, "danger")
        unchecked = [
            getattr(btn, "style", None)
            for btn in _player_buttons(kb)
            if btn.text.startswith("☐")
        ]
        self.assertEqual(unchecked, ["primary", "primary"])

    def test_next_stage_button_green(self):
        game = self._game()
        kb = day1_defense_pick_keyboard_for(game, 10)
        labels = _btn_texts(kb)
        self.assertIn("⏭️ برو به مرحله بعد", labels)
        self.assertIn("🌙 دفاعیه نداریم", labels)
        idx = labels.index("⏭️ برو به مرحله بعد")
        btn = kb.inline_keyboard[-2][0]
        self.assertEqual(btn.text, "⏭️ برو به مرحله بعد")
        self.assertEqual(getattr(btn, "style", None), "success")
        none_btn = kb.inline_keyboard[-1][0]
        self.assertEqual(none_btn.text, "🌙 دفاعیه نداریم")
        self.assertEqual(getattr(none_btn, "style", None), "success")

    def test_confirm_keyboard_yes_green_back_neutral(self):
        game = self._game()
        kb = _no_host_day1_none_confirm_keyboard(game, 10, mirror=False)
        yes, back = kb.inline_keyboard[0][0], kb.inline_keyboard[1][0]
        self.assertEqual(yes.text, "✅ تأیید نهایی")
        self.assertEqual(getattr(yes, "style", None), "success")
        self.assertEqual(back.text, "↩️ بازگشت")
        self.assertNotEqual(getattr(back, "style", None), "success")
        # mirror variant carries the pmr acts
        kb2 = _no_host_day1_none_confirm_keyboard(game, 10, mirror=True)
        self.assertIn("pmr", kb2.inline_keyboard[0][0].callback_data)
        self.assertIn("d1nf", kb2.inline_keyboard[0][0].callback_data)
        self.assertIn("d1nb", kb2.inline_keyboard[1][0].callback_data)

    def test_confirm_text_matches_spec(self):
        self.assertIn("⚠️ تأیید عدم برگزاری دفاعیه", NO_HOST_DAY1_NONE_CONFIRM_HTML)
        self.assertIn(
            "آیا مطمئن هستید که هیچ بازیکنی برای دفاعیه انتخاب نشده است؟",
            NO_HOST_DAY1_NONE_CONFIRM_HTML,
        )

    def test_other_scenarios_have_no_styles(self):
        # masoon — same shared panel, no colours
        game = self._game(scenario="masoon")
        kb = _no_host_day1_defense_pick_keyboard(game, 10, mirror=False)
        for btn in _player_buttons(kb):
            self.assertIsNone(getattr(btn, "style", None))
        self.assertIsNone(getattr(kb.inline_keyboard[-1][0], "style", None))
        # style helper is bazpors-only
        self.assertEqual(_day1_defense_panel_style_kwargs(game, success=True), {})
        self.assertEqual(
            _day1_defense_panel_style_kwargs(game, selected=True), {}
        )


class BazporsDay1NoneConfirmFlowTests(unittest.IsolatedAsyncioTestCase):
    """تأیید دومرحله‌ای «دفاعیه نداریم» — بازپرس فقط."""

    def setUp(self):
        self.gm = GameManager()

    def _game(self, *, scenario="bazpors", mode="no_host"):
        game = self.gm.create_game(
            host_id=1,
            scenario_name=scenario,
            max_players=12,
            bazpors_host_mode=mode,
        )
        assert game is not None
        for uid, name in ((10, "A"), (20, "B"), (30, "C")):
            self.gm.add_player(game, _p(uid, name))
        game.roles_dealt = True
        game.bot_assistant_user_id = 10
        begin_no_host_day1_defense_pick(game)
        return game

    def _cb(self):
        cb = MagicMock()
        cb.answer = AsyncMock()
        cb.message = MagicMock()
        return cb

    async def _dispatch(self, game, act, tid=0):
        cb = self._cb()
        bot = MagicMock()
        await _dispatch_no_host_day1_defense_act(
            cb, bot, game, 10, 10, act, tid=tid
        )
        return cb, bot

    async def test_none_press_opens_confirmation_without_advancing(self):
        game = self._game()
        cb, _ = await self._dispatch(game, "none")
        self.assertTrue(game.no_host_day1_defense_none_confirm_active)
        self.assertEqual(game.no_host_day1_defense_phase, "pick")
        self.assertNotIn(
            "✅ پیام پایان روز", cb.message.edit_text.call_args.args[0]
            if cb.message.edit_text.call_args
            else "",
        )
        answer = cb.answer.await_args.args[0]
        self.assertEqual(answer, "برای پایان دفاعیه تأیید لازم است.")

    async def test_none_immediately_does_not_enter_night(self):
        game = self._game()
        with patch(
            "bot.main.on_no_host_entered_night1", new=AsyncMock()
        ) as night1, patch(
            "bot.no_host_night_entry.dispatch_all_no_host_night_entry_panels",
            new=AsyncMock(),
        ):
            await self._dispatch(game, "none")
        night1.assert_not_awaited()
        self.assertEqual(game.no_host_day1_defense_phase, "pick")
        self.assertFalse(game.no_host_intro_night_started)

    async def test_back_restores_pick_panel_and_keeps_selections(self):
        game = self._game()
        from bot.bazpors_narrator import set_day_vote_pick_uids

        set_day_vote_pick_uids(game, {20})
        _, _ = await self._dispatch(game, "none")
        self.assertTrue(game.no_host_day1_defense_none_confirm_active)
        cb, _ = await self._dispatch(game, "nonb")
        self.assertFalse(game.no_host_day1_defense_none_confirm_active)
        self.assertEqual(game.no_host_day1_defense_phase, "pick")
        self.assertEqual(day_vote_pick_uids(game), {20})
        self.assertEqual(cb.answer.await_args.args[0], "بازگشت به پنل انتخاب دفاعیه.")
        kb = day1_defense_pick_keyboard_for(game, 10)
        labels = _btn_texts(kb)
        self.assertIn("⏭️ برو به مرحله بعد", labels)
        self.assertIn("🌙 دفاعیه نداریم", labels)
        yes_btns = [
            getattr(btn, "style", None)
            for btn in _player_buttons(kb)
            if btn.text.startswith("✅")
        ]
        self.assertEqual(yes_btns, ["danger"])

    async def test_confirm_yes_runs_existing_no_votes_exactly_once(self):
        game = self._game()
        _, _ = await self._dispatch(game, "none")
        with patch(
            "bot.main._no_host_day1_defense_no_votes", new=AsyncMock()
        ) as no_votes:
            cb, _ = await self._dispatch(game, "nonc")
            no_votes.assert_awaited_once()
        self.assertFalse(game.no_host_day1_defense_none_confirm_active)
        # duplicate: second press now rejected
        with patch(
            "bot.main._no_host_day1_defense_no_votes", new=AsyncMock()
        ) as no_votes2:
            cb2, _ = await self._dispatch(game, "nonc")
            no_votes2.assert_not_awaited()
        self.assertEqual(
            cb2.answer.await_args.args[0], "این مرحله دیگر فعال نیست."
        )

    async def test_confirm_yes_executes_real_night_transition_once(self):
        game = self._game()
        _, _ = await self._dispatch(game, "none")
        with patch(
            "bot.main.broadcast_to_alive_players", new=AsyncMock()
        ) as bc, patch(
            "bot.main.on_no_host_entered_night1", new=AsyncMock()
        ) as night1, patch(
            "bot.russian_mafia_flow.apply_russian_day_result",
            new=AsyncMock(return_value=False),
        ), patch(
            "bot.no_host_night_entry.dispatch_all_no_host_night_entry_panels",
            new=AsyncMock(),
        ):
            cb, _ = await self._dispatch(game, "nonc")
        bc.assert_awaited_once()
        night1.assert_awaited_once()
        self.assertFalse(game.no_host_day1_defense_none_confirm_active)
        self.assertTrue(game.no_host_assistant_narrator_active)
        self.assertEqual(
            cb.answer.await_args.args[0], "ثبت شد."
        )

    async def test_stale_confirm_without_open_stage_rejected(self):
        game = self._game()
        with patch(
            "bot.main._no_host_day1_defense_no_votes", new=AsyncMock()
        ) as no_votes:
            cb, _ = await self._dispatch(game, "nonc")
            no_votes.assert_not_awaited()
        self.assertEqual(
            cb.answer.await_args.args[0], "این مرحله دیگر فعال نیست."
        )
        cb2, _ = await self._dispatch(game, "nonb")
        self.assertEqual(
            cb2.answer.await_args.args[0], "این مرحله دیگر فعال نیست."
        )

    async def test_stale_confirm_after_phase_change_rejected(self):
        game = self._game()
        _, _ = await self._dispatch(game, "none")
        game.no_host_day1_defense_phase = "outcome"
        with patch(
            "bot.main._no_host_day1_defense_no_votes", new=AsyncMock()
        ) as no_votes:
            cb, _ = await self._dispatch(game, "nonc")
            no_votes.assert_not_awaited()
        self.assertEqual(
            cb.answer.await_args.args[0], "این مرحله دیگر فعال نیست."
        )

    async def test_toggle_and_confirm_candidates_unchanged(self):
        game = self._game()
        cb, _ = await self._dispatch(game, "tog", tid=20)
        self.assertIn(20, day_vote_pick_uids(game))
        self.assertEqual(cb.answer.await_args.args[0], "به‌روز شد.")
        # confirm path still clears the pending confirm stage flag
        game.no_host_day1_defense_none_confirm_active = True
        with patch(
            "bot.main.broadcast_to_alive_players", new=AsyncMock()
        ), patch(
            "bot.main.promote_mirror_prompt_to_panel",
            new=AsyncMock(return_value=True),
        ), patch(
            "bot.main.register_mirror_prompt_pair", new=AsyncMock()
        ):
            await self._dispatch(game, "confirm")
        self.assertFalse(game.no_host_day1_defense_none_confirm_active)
        self.assertEqual(game.no_host_day1_defense_phase, "outcome")

    async def test_non_bazpors_none_still_immediate(self):
        game = self._game(scenario="namayande", mode="no_host")
        with patch(
            "bot.main._no_host_day1_defense_no_votes", new=AsyncMock()
        ) as no_votes, patch(
            "bot.main._no_host_day1_defense_none_confirm_open", new=AsyncMock()
        ) as confirm_open:
            await self._dispatch(game, "none")
        no_votes.assert_awaited_once()
        confirm_open.assert_not_awaited()

    async def test_mason_confirm_stage_never_opened_by_stale_callback(self):
        game = self._game()
        game.scenario_name = "masoon"
        with patch(
            "bot.main.broadcast_to_alive_players", new=AsyncMock()
        ), patch(
            "bot.main.on_no_host_entered_night1", new=AsyncMock()
        ), patch(
            "bot.russian_mafia_flow.apply_russian_day_result",
            new=AsyncMock(return_value=False),
        ), patch(
            "bot.no_host_night_entry.dispatch_all_no_host_night_entry_panels",
            new=AsyncMock(),
        ):
            _, _ = await self._dispatch(game, "none")
        self.assertFalse(game.no_host_day1_defense_none_confirm_active)

    async def test_unknown_confirm_act_rejected(self):
        game = self._game(scenario="namayande", mode="no_host")
        cb, _ = await self._dispatch(game, "nonc")
        self.assertEqual(cb.answer.await_args.args[0], "عمل نامعتبر.")


if __name__ == "__main__":
    unittest.main()
