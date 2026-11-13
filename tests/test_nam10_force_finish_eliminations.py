"""اتمام اجباری شب نماینده ۱۲/۱۳ — حذف سرباز/اسنایپر موقتِ بی‌تأیید.

Soldier / temporary-Sniper force-finish eliminations: only Namayande
compositions containing the Soldier (12/13). Uses the existing
normalize + resolution pipeline; isolated in-memory games.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.models import Phase, Player, Role
from bot.nam10.night2 import (
    ELIM_CAUSE_FORCE_SOLDIER,
    ELIM_CAUSE_FORCE_SNIPER,
    GRANT_STATUS_DELIVERED,
    GRANT_STATUS_PENDING,
    PENDING_COLLECTING,
    _soldier_key,
    _sniper_key,
    night2_maybe_finish,
    night2_required_keys,
    night2_run_resolution,
)
from bot.nam10.night_force_finish import (
    _normalize_pending_nam10_night_actions,
    force_finish_nam10_night,
)
from bot.nam10.night2_publish import night2_night_report_extra_section


def _p(uid, name, role, *, alive=True, seat=0):
    return Player(
        user_id=uid, full_name=name, username=None, role=role,
        is_alive=alive, seat=seat,
    )


def _nam13_game(gm, *, assistant_uid=900, extra_players=()):
    game = gm.create_game(
        host_id=1, scenario_name="namayande", max_players=13,
        nam10_no_host=True,
    )
    assert game is not None
    for pl in (
        _p(30, "SoldierX", Role.SOLDIER, seat=1),
        _p(31, "TownA", Role.CITIZEN, seat=2),
        _p(32, "TownB", Role.CITIZEN, seat=3),
        _p(33, "RecipA", Role.CITIZEN, seat=4),
        *extra_players,
    ):
        err = gm.add_player(game, pl)
        assert err is None, err
    game.room_code = "RNF"
    gm.games["RNF"] = game
    game.bot_assistant_user_id = assistant_uid
    game.no_host_assistant_narrator_active = True
    game.phase = Phase.NIGHT
    game.nmnd_narrator_night_count = 2
    game.nmnd_night2_night_count = 2
    game.nmnd_night2_mode = True
    game.nmnd_night2_phase = PENDING_COLLECTING
    game.nmnd_night2_entry_dispatched = True
    return game


def _make_soldier_panel_available(game, uid=30):
    """پنل انتخاب سرباز با موفقیت تحویل شده باشد."""
    game.mirror_prompt_messages[_soldier_key(game, uid)] = {
        "player": (uid, 111),
        "text": "panel",
    }


def _make_sniper_panel_available(game, uid=33):
    game.mirror_prompt_messages[_sniper_key(game, uid)] = {
        "player": (uid, 222),
        "text": "panel",
    }


def _force_elim_records(game):
    return [
        rec for rec in game.nmnd_night2_eliminations
        if rec.get("cause")
        in (ELIM_CAUSE_FORCE_SOLDIER, ELIM_CAUSE_FORCE_SNIPER)
    ]


class SoldierForceEliminationTests(unittest.IsolatedAsyncioTestCase):
    async def test_unconfirmed_selection_force_finished_eliminated(self):
        gm = GameManager()
        game = _nam13_game(gm)
        _make_soldier_panel_available(game)
        # سرباز زنده، شارژ مصرف نشده، هیچ انتخاب تأییدشده‌ای ثبت نشده
        self.assertIsNone(game.nmnd_night2_soldier_uid)
        dispositions = await _normalize_pending_nam10_night_actions(
            MagicMock(), game
        )
        self.assertEqual(dispositions.get("soldier_force_eliminated"), "force_finished_no_action")
        soldier = game.players[30]
        self.assertFalse(soldier.is_alive)
        recs = [r for r in game.nmnd_night2_eliminations if r.get("uid") == 30]
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["cause"], ELIM_CAUSE_FORCE_SOLDIER)
        # بدون گیرندهٔ خیالی و بدون تحویل اسنایپر
        self.assertIsNone(game.nmnd_night2_soldier_uid)
        self.assertNotEqual(game.nmnd_night2_soldier_grant_status, GRANT_STATUS_DELIVERED)

    async def test_elimination_belongs_to_current_night(self):
        gm = GameManager()
        game = _nam13_game(gm)
        _make_soldier_panel_available(game)
        await _normalize_pending_nam10_night_actions(MagicMock(), game)
        recs = _force_elim_records(game)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["night"], 2)

    async def test_confirmed_recipient_not_penalty(self):
        gm = GameManager()
        game = _nam13_game(gm)
        _make_soldier_panel_available(game)
        # سرباز بازیکن ۳۳ را انتخاب و تأیید کرده (گرانت در انتظار تحویل)
        game.nmnd_night2_soldier_uid = 33
        game.nmnd_night2_soldier_grant_status = GRANT_STATUS_PENDING
        dispositions = await _normalize_pending_nam10_night_actions(
            MagicMock(), game
        )
        self.assertIsNone(dispositions.get("soldier_force_eliminated"))
        self.assertTrue(game.players[30].is_alive)
        self.assertFalse(_force_elim_records(game))

    async def test_later_night_missed_ack_not_penalty(self):
        gm = GameManager()
        game = _nam13_game(gm)
        # شارژ در شب قبلی مصرف شده؛ امشب فقط اوکی انتظار
        game.nmnd_night2_soldier_used = True
        game.nmnd_night2_soldier_used_night = 1
        dispositions = await _normalize_pending_nam10_night_actions(
            MagicMock(), game
        )
        self.assertEqual(dispositions.get("soldier_ack"), "force_finished_no_action")
        self.assertTrue(game.players[30].is_alive)
        self.assertIn(30, game.nmnd_night2_waiting_acked.get(Role.SOLDIER.value, []))
        self.assertFalse(_force_elim_records(game))

    async def test_intercepted_history_then_fail_penalty_applies(self):
        gm = GameManager()
        game = _nam13_game(gm)
        _make_soldier_panel_available(game)
        # شب قبل گرانت توسط هکر قطع شد؛ شبی جدید reset شده و سرباز
        # دوباره پنل انتخاب دارد ولی تأیید نمی‌کند → حذف
        game.nmnd_night2_soldier_used = False
        game.nmnd_night2_soldier_used_night = None
        game.nmnd_night2_soldier_uid = None
        game.nmnd_night2_soldier_grant_status = None
        dispositions = await _normalize_pending_nam10_night_actions(
            MagicMock(), game
        )
        self.assertIn("soldier_force_eliminated", dispositions)
        self.assertFalse(game.players[30].is_alive)

    async def test_panel_not_delivered_safe_path_no_penalty(self):
        gm = GameManager()
        game = _nam13_game(gm)
        # کلید ثبت شده ولی هیچ مرجع ارسال موفق ثبت نشده (خطای ارسال)
        game.mirror_prompt_messages[_soldier_key(game, 30)] = {"text": "panel"}
        dispositions = await _normalize_pending_nam10_night_actions(
            MagicMock(), game
        )
        self.assertIn("soldier_forfeited_panel_unavailable", dispositions)
        self.assertTrue(game.players[30].is_alive)
        self.assertTrue(game.nmnd_night2_soldier_forfeited)
        self.assertFalse(_force_elim_records(game))

    async def test_no_duplicate_elimination_on_repeat(self):
        gm = GameManager()
        game = _nam13_game(gm)
        _make_soldier_panel_available(game)
        await _normalize_pending_nam10_night_actions(MagicMock(), game)
        await _normalize_pending_nam10_night_actions(MagicMock(), game)
        recs = _force_elim_records(game)
        self.assertEqual(len(recs), 1)

    async def test_no_soldier_composition_no_penalty_code(self):
        gm = GameManager()
        game = _nam13_game(gm)
        game.players[30].role = Role.CITIZEN
        _make_soldier_panel_available(game, uid=30)
        dispositions = await _normalize_pending_nam10_night_actions(
            MagicMock(), game
        )
        self.assertFalse(_force_elim_records(game))
        self.assertNotIn("soldier_force_eliminated", dispositions)


class TempSniperForceEliminationTests(unittest.IsolatedAsyncioTestCase):
    def _delivered_state(self, game, *, target=None):
        game.nmnd_night2_soldier_uid = 33
        game.nmnd_night2_soldier_grant_status = GRANT_STATUS_DELIVERED
        game.nmnd_night2_soldier_used = True
        game.nmnd_night2_soldier_used_night = 2
        game.nmnd_night2_sniper_night = 2
        if target is not None:
            game.nmnd_night2_sniper_resolved = True
            game.nmnd_night2_sniper_target_uid = target

    async def test_delivered_panel_no_target_force_finished_eliminated(self):
        gm = GameManager()
        game = _nam13_game(gm)
        self._delivered_state(game)
        _make_sniper_panel_available(game)
        dispositions = await _normalize_pending_nam10_night_actions(
            MagicMock(), game
        )
        self.assertIn("sniper_force_eliminated", dispositions)
        # گیرنده (۳۳) حذف شد — نه سرباز (۳۰)
        self.assertFalse(game.players[33].is_alive)
        self.assertTrue(game.players[30].is_alive)
        recs = _force_elim_records(game)
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["cause"], ELIM_CAUSE_FORCE_SNIPER)
        self.assertEqual(recs[0]["uid"], 33)
        self.assertEqual(recs[0]["night"], 2)
        # شلیک خیالی ثبت نمی‌شود
        self.assertIsNone(game.nmnd_night2_sniper_target_uid)
        self.assertTrue(game.nmnd_night2_sniper_skipped)
        self.assertTrue(game.nmnd_night2_sniper_resolved)
        # شارژ مادام‌العمر سرباز مصرف‌شده می‌ماند
        self.assertTrue(game.nmnd_night2_soldier_used)

    async def test_confirmed_shot_preserved_and_resolved(self):
        gm = GameManager()
        game = _nam13_game(
            gm, extra_players=[_p(39, "Recruit", Role.CITIZEN, seat=6)]
        )
        # ۳۹ عضو تیم مافیا (رهگیری‌شده) به‌عنوان هدف تأییدشده
        game.nmnd_mafia_recruit_ids = {39}
        self._delivered_state(game, target=39)
        _make_sniper_panel_available(game)
        dispositions = await _normalize_pending_nam10_night_actions(
            MagicMock(), game
        )
        self.assertNotIn("sniper_force_eliminated", dispositions)
        self.assertNotIn("sniper_no_shot_panel_unavailable", dispositions)
        self.assertTrue(game.players[39].is_alive)
        self.assertTrue(game.players[33].is_alive)
        self.assertTrue(night2_maybe_finish(game, force=True))
        night2_run_resolution(game)
        out = (game.nmnd_night2_outcome or {}).get("soldier_sniper") or {}
        self.assertEqual(out.get("reason"), "mafia_member_eliminated")
        self.assertEqual(out.get("eliminated_uid"), 39)
        self.assertFalse(game.players[39].is_alive)
        self.assertTrue(game.players[33].is_alive)
        self.assertTrue(game.players[30].is_alive)

    async def test_panel_not_delivered_no_penalty(self):
        gm = GameManager()
        game = _nam13_game(gm)
        self._delivered_state(game)
        # کلید بدون مرجع ارسال موفق (خطای تحویل) → مسیر امن
        game.mirror_prompt_messages[_sniper_key(game, 33)] = {"text": "panel"}
        dispositions = await _normalize_pending_nam10_night_actions(
            MagicMock(), game
        )
        self.assertIn("sniper_no_shot_panel_unavailable", dispositions)
        self.assertTrue(game.players[33].is_alive)
        self.assertFalse(_force_elim_records(game))
        self.assertTrue(game.nmnd_night2_sniper_skipped)

    async def test_soldier_not_penalized_for_recipient_failure(self):
        gm = GameManager()
        game = _nam13_game(gm)
        self._delivered_state(game)
        _make_sniper_panel_available(game)
        await _normalize_pending_nam10_night_actions(MagicMock(), game)
        recs = _force_elim_records(game)
        self.assertEqual([r["uid"] for r in recs], [33])
        self.assertTrue(game.players[30].is_alive)

    async def test_no_duplicate_after_repeat(self):
        gm = GameManager()
        game = _nam13_game(gm)
        self._delivered_state(game)
        _make_sniper_panel_available(game)
        await _normalize_pending_nam10_night_actions(MagicMock(), game)
        await _normalize_pending_nam10_night_actions(MagicMock(), game)
        recs = _force_elim_records(game)
        self.assertEqual(len(recs), 1)


class ForceFinishReportAndFlowTests(unittest.IsolatedAsyncioTestCase):
    def _eliminated(self, game):
        return not game.players[30].is_alive

    async def test_host_report_contains_soldier_force_cause(self):
        gm = GameManager()
        game = _nam13_game(gm)
        _make_soldier_panel_available(game)
        await _normalize_pending_nam10_night_actions(MagicMock(), game)
        game.nmnd_night2_outcome = {"soldier_sniper": {}}
        lines = night2_night_report_extra_section(game, gm)
        self.assertIn(
            "🪖 سرباز: SoldierX به دلیل ثبت‌نکردن انتخاب خود هنگام اتمام اجباری شب از بازی خارج شد.",
            lines,
        )

    async def test_host_report_contains_sniper_force_cause(self):
        gm = GameManager()
        game = _nam13_game(gm)
        game.nmnd_night2_soldier_uid = 33
        game.nmnd_night2_soldier_grant_status = GRANT_STATUS_DELIVERED
        game.nmnd_night2_soldier_used = True
        game.nmnd_night2_soldier_used_night = 2
        game.nmnd_night2_sniper_night = 2
        _make_sniper_panel_available(game)
        await _normalize_pending_nam10_night_actions(MagicMock(), game)
        game.nmnd_night2_outcome = {
            "soldier_sniper": {
                "soldier_uid": 30,
                "recipient_uid": 33,
                "grant_status": "delivered",
                "skipped": True,
            }
        }
        lines = night2_night_report_extra_section(game, gm)
        self.assertIn(
            "🪖 سرباز: قابلیت اسنایپر به RecipA داده شد.",
            lines,
        )
        self.assertIn(
            "🎯 اسنایپر موقت: RecipA به دلیل ثبت‌نکردن هدف شلیک هنگام اتمام اجباری شب از بازی خارج شد.",
            lines,
        )

    async def test_full_force_finish_flow_single_elimination(self):
        gm = GameManager()
        game = _nam13_game(gm)
        _make_soldier_panel_available(game)
        bot = MagicMock()
        bot.send_message = AsyncMock(return_value=MagicMock(message_id=1))
        bot.edit_message_text = AsyncMock()
        bot.delete_message = AsyncMock()
        with patch(
            "bot.nam10.night2_publish.nam10_night2_publish_tick",
            new=AsyncMock(),
        ) as tick:
            await force_finish_nam10_night(bot, game, gm)
        tick.assert_awaited()
        self.assertTrue(game.nmnd_night2_force_finished)
        self.assertFalse(game.players[30].is_alive)
        self.assertEqual(len([r for r in game.nmnd_night2_eliminations if r.get("cause") == ELIM_CAUSE_FORCE_SOLDIER]), 1)
        # شمارندهٔ یادآور پاک شده و callback برای شب بسته
        self.assertIsNone(game.night_helper_reminder_message_id)

    async def test_ten_player_composition_unaffected(self):
        gm = GameManager()
        game = gm.create_game(
            host_id=1, scenario_name="namayande", max_players=10,
            nam10_no_host=True,
        )
        err = gm.add_player(game, _p(30, "TownA", Role.CITIZEN, seat=1))
        assert err is None, err
        game.room_code = "RN10"
        gm.games["RN10"] = game
        game.bot_assistant_user_id = 900
        game.no_host_assistant_narrator_active = True
        game.phase = Phase.NIGHT
        game.nmnd_narrator_night_count = 2
        game.nmnd_night2_night_count = 2
        game.nmnd_night2_mode = True
        game.nmnd_night2_phase = PENDING_COLLECTING
        game.nmnd_night2_entry_dispatched = True
        gm.add_player(game, _p(30, "TownA", Role.CITIZEN, seat=1))
        dispositions = await _normalize_pending_nam10_night_actions(
            MagicMock(), game
        )
        self.assertFalse(_force_elim_records(game))
        self.assertNotIn("soldier_force_eliminated", dispositions)
        self.assertNotIn("sniper_force_eliminated", dispositions)


if __name__ == "__main__":
    unittest.main()
