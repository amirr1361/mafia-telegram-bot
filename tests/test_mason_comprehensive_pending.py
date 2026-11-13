"""A–G — بررسی جامع انتخاب موقت/تأیید پنل‌های شب ماسون.

A) دکمه‌های «بدون اقدام» = انتخاب موقت (آبی→قرمز) + تأیید نهایی؛ اجرا فقط پس از تأیید.
B) شلیک جزئی اسنایپر — گلولهٔ باقی‌مانده محفوظ می‌ماند.
C) بازطراحی پنل فرمانده — حالت الف (مستقیم) و حالت ب (تصمیم نامزدها).
D) دکمهٔ «🌙 اتمام شب» روی پنل یادآور — فقط برای کمک‌کننده.
E) گزارش حذف‌شدگان — شبِ حل‌نشده = گزارش موقت؛ پس از حل‌شدن شب قطعی می‌شود.
F) پزشک با ظرفیت ۱ — لمس بازیکن دیگر، هدف قبلی را جایگزین می‌کند.
G) جذب تایلر مرده — انتخاب موقت + تأیید نهایی.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.mason_night_role import (
    MASON_COMMANDER_DECISION_APPROVE_BOTH,
    MASON_COMMANDER_DECISION_APPROVE_ONE,
    MASON_COMMANDER_DECISION_REJECT_ALL,
    MASON_COMMANDER_DECISION_REJECT_ONE,
    MASON_COMMANDER_NO_SHOT_LABEL,
    MSC_CONFIRM,
    MSC_DEC_CONFIRM,
    MSC_DEC_PICK,
    MSC_DONE,
    MSC_NONE,
    MSC_PICK,
    MSD_CONFIRM,
    MSD_DONE,
    MSD_PICK,
    MGN_CONFIRM,
    MGN_NONE,
    MSB_CONFIRM,
    MSB_NONE,
    MSM_CONFIRM,
    MSM_NONE,
    MSM_TAILOR,
    MSB_PICK,
    MSS_CONFIRM,
    MSS_NONE,
    MSS_PICK,
    _show_mason_commander_panel,
    _show_mason_sniper_panel,
    dispatch_mason_night_role,
)
from bot.models import Phase, Player, Role
from bot.roles import mason_commander as ms_cmd
from bot.roles import mason_doctor as ms_doc
from bot.roles import mason_fraternity as ms_mf
from bot.roles import mason_sniper as ms_sn
from tests.mason_simulation_harness import MasonSimHarness


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(user_id=uid, full_name=name, username=None, role=role, is_alive=alive)


def _mason_game(gm: GameManager, *, n: int = 12):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.bot_assistant_user_id = 900
    return game


def _cb() -> MagicMock:
    cb = MagicMock()
    cb.answer = AsyncMock()
    return cb


def _buttons(kb) -> list[tuple[str, str]]:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            out.append((btn.text, getattr(btn, "style", "") or ""))
    return out


def _labels(kb) -> list[str]:
    return [t for t, _s in _buttons(kb)]


async def _press(game, gm, act, tid, uid, *, patched_panels=()):
    cb = _cb()
    bot = MagicMock()
    from contextlib import ExitStack

    with ExitStack() as stack:
        stack.enter_context(
            patch("bot.mason_night_role.register_mirror_prompt_pair", new=AsyncMock())
        )
        stack.enter_context(
            patch("bot.mason_night_role.sync_role_mirror_panel", new=AsyncMock())
        )
        stack.enter_context(
            patch(
                "bot.mason_night_role.finalize_no_host_role_pick_message",
                new=AsyncMock(),
            )
        )
        stack.enter_context(
            patch(
                "bot.mason_night_ready.maybe_finish_mason_parallel_night",
                new=AsyncMock(),
            )
        )
        for name in patched_panels:
            stack.enter_context(patch(name, new=AsyncMock()))
        await dispatch_mason_night_role(
            cb, bot, game, gm, as_uid=uid, actor_uid=uid, act=act, tid=tid
        )
    return cb


class SniperNoneShotFlowTests(unittest.IsolatedAsyncioTestCase):
    """A + B — اسنایپر: انتخاب موقت «بدون شلیک»، تعارض دوطرفه، گلولهٔ محفوظ."""

    async def test_no_shot_pending_then_confirm_spends_nothing(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.players[50] = _p(50, "Sn", Role.SNIPER)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        ms_sn.commit_mason_sniper_night_selection(game, [21])
        await _press(game, gm, MSS_NONE, 0, 50, patched_panels=(
            "bot.mason_night_role._show_mason_sniper_panel",
        ))
        # تعارض دوطرفه: «بدون شلیک» اهداف قبلی را پاک می‌کند
        self.assertEqual(ms_sn.mason_sniper_night_selected_uids(game), [])
        self.assertTrue(game.mason_sniper_night_no_shot)
        self.assertFalse(game.mason_night_sniper_confirmed)
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 0)
        await _press(game, gm, MSS_CONFIRM, 0, 50)
        self.assertTrue(game.mason_night_sniper_confirmed)
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 0)

    async def test_pick_clears_pending_no_shot(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.players[50] = _p(50, "Sn", Role.SNIPER)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        game.mason_sniper_night_no_shot = True
        await _press(game, gm, MSS_PICK, 21, 50, patched_panels=(
            "bot.mason_night_role._show_mason_sniper_panel",
        ))
        self.assertFalse(game.mason_sniper_night_no_shot)
        self.assertEqual(ms_sn.mason_sniper_night_selected_uids(game), [21])

    async def test_confirm_without_selection_or_no_shot_alerts(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.players[50] = _p(50, "Sn", Role.SNIPER)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        cb = await _press(game, gm, MSS_CONFIRM, 0, 50)
        self.assertFalse(game.mason_night_sniper_confirmed)
        cb.answer.assert_any_await("ابتدا انتخاب کنید.", show_alert=True)

    async def test_panel_none_button_red_when_pending(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.players[50] = _p(50, "Sn", Role.SNIPER)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        captured: list = []

        async def _sync(_bot_, _game_, _ui, _uid, _text, kb):
            captured.append(kb)

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair", new=AsyncMock()
        ), patch("bot.mason_night_role.sync_role_mirror_panel", side_effect=_sync):
            game.mason_sniper_night_no_shot = True
            await _show_mason_sniper_panel(MagicMock(), game, gm, 50)
        labels = _labels(captured[-1])
        self.assertIn("⭕ بدون شلیک", labels)
        self.assertIn("✅ تأیید انتخاب", labels)


class CommanderModeATests(unittest.IsolatedAsyncioTestCase):
    """C — حالت الف (اسنایپر نیست): انتخاب مستقیم + ظرفیت ۱ جایگزین + بدون شلیک."""

    def _arm(self, game: "object", *, dead_sniper: bool = True) -> None:
        # اسنایپر مرده → فرمانده حالت الف
        return None

    async def test_mode_a_cap1_replacement_then_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        game.players[10] = _p(10, "Sn", Role.SNIPER, alive=False)  # مرده → حالت الف
        game.players[40] = _p(40, "Cmd", Role.COMMANDER)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        game.players[22] = _p(22, "B", Role.TOWN_SIMPLE)
        self.assertTrue(ms_cmd.mason_commander_inherits_sniper_shooting(game))
        # ظرفیت ۱ = یک گلولهٔ باقی‌مانده
        game.mason_sniper_bullets_spent = ms_sn.mason_sniper_bullet_limit(game) - 1
        await _press(game, gm, MSC_PICK, 21, 40, patched_panels=(
            "bot.mason_night_role._show_mason_commander_panel",
        ))
        self.assertEqual(ms_sn.mason_sniper_night_selected_uids(game), [21])
        # ظرفیت ۱ — لمس بازیکن دیگر، هدف قبلی را جایگزین می‌کند
        await _press(game, gm, MSC_PICK, 22, 40, patched_panels=(
            "bot.mason_night_role._show_mason_commander_panel",
        ))
        self.assertEqual(ms_sn.mason_sniper_night_selected_uids(game), [22])
        self.assertFalse(game.mason_night_commander_confirmed)
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 1)
        await _press(game, gm, MSC_CONFIRM, 0, 40)
        self.assertTrue(game.mason_night_commander_confirmed)
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [22])
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 2)

    async def test_mode_a_no_shot_pending_then_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        game.players[10] = _p(10, "Sn", Role.SNIPER, alive=False)
        game.players[40] = _p(40, "Cmd", Role.COMMANDER)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        await _press(game, gm, MSC_NONE, 0, 40, patched_panels=(
            "bot.mason_night_role._show_mason_commander_panel",
        ))
        self.assertTrue(game.mason_commander_night_no_shot)
        self.assertFalse(game.mason_night_commander_confirmed)
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [])
        await _press(game, gm, MSC_CONFIRM, 0, 40)
        self.assertTrue(game.mason_night_commander_confirmed)
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [])
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 0)

    async def test_mode_a_pick_clears_pending_no_shot(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        game.players[10] = _p(10, "Sn", Role.SNIPER, alive=False)
        game.players[40] = _p(40, "Cmd", Role.COMMANDER)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        game.mason_commander_night_no_shot = True
        await _press(game, gm, MSC_PICK, 21, 40, patched_panels=(
            "bot.mason_night_role._show_mason_commander_panel",
        ))
        self.assertFalse(game.mason_commander_night_no_shot)
        self.assertEqual(ms_sn.mason_sniper_night_selected_uids(game), [21])

    async def test_mode_a_panel_shows_all_buttons_after_picks(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        game.players[10] = _p(10, "Sn", Role.SNIPER, alive=False)
        game.players[40] = _p(40, "Cmd", Role.COMMANDER)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        game.players[22] = _p(22, "B", Role.TOWN_SIMPLE)
        game.players[23] = _p(23, "C", Role.TOWN_SIMPLE)
        ms_sn.commit_mason_sniper_night_selection(game, [21])
        captured: list = []

        async def _sync(_bot_, _game_, _ui, _uid, _text, kb):
            captured.append(kb)

        with patch("bot.mason_night_role.sync_role_mirror_panel", side_effect=_sync):
            await _show_mason_commander_panel(MagicMock(), game, gm, 40)
        labels = _labels(captured[-1])
        # همهٔ دکمه‌های بازیکنان (پول کامل) + «انتخابی ندارم» + تأیید، همیشه دیده می‌شوند
        self.assertIn(MASON_COMMANDER_NO_SHOT_LABEL, labels)
        self.assertIn("✅ تأیید انتخاب", labels)
        names_in_buttons = sum(
            1 for l in labels for nm in ("A", "B", "C") if nm in l
        )
        self.assertGreaterEqual(names_in_buttons, 3)

    async def test_stale_done_button_alerts_without_commit(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        game.players[10] = _p(10, "Sn", Role.SNIPER, alive=False)
        game.players[40] = _p(40, "Cmd", Role.COMMANDER)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        ms_sn.commit_mason_sniper_night_selection(game, [21])
        cb = await _press(game, gm, MSC_DONE, 0, 40)
        self.assertFalse(game.mason_night_commander_confirmed)
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [])
        self.assertEqual(cb.answer.await_args.kwargs.get("show_alert"), True)


class CommanderModeBTests(unittest.IsolatedAsyncioTestCase):
    """C — حالت ب (نامزدهای اسنایپر): تصمیم موقت + تأیید نهایی."""

    def _setup_two(self, gm: GameManager):
        game = _mason_game(gm)
        game.players[10] = _p(10, "Sn", Role.SNIPER)
        game.players[40] = _p(40, "Cmd", Role.COMMANDER)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        game.players[22] = _p(22, "B", Role.TOWN_SIMPLE)
        ms_sn.commit_mason_sniper_night_selection(game, [21, 22])
        return game

    async def test_single_nominee_approve_then_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.players[10] = _p(10, "Sn", Role.SNIPER)
        game.players[40] = _p(40, "Cmd", Role.COMMANDER)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        ms_sn.commit_mason_sniper_night_selection(game, [21])
        await _press(game, gm, MSC_DEC_PICK, 1, 40, patched_panels=(
            "bot.mason_night_role._show_mason_commander_panel",
        ))
        self.assertEqual(game.mason_commander_pending_decision_uids, [21])
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 0)
        await _press(game, gm, MSC_DEC_CONFIRM, 0, 40)
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [21])
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 1)
        self.assertTrue(game.mason_night_commander_confirmed)
        self.assertEqual(game.mason_commander_pending_decision_uids, [])

    async def test_two_nominees_approve_both(self) -> None:
        game = self._setup_two(gm := GameManager())
        await _press(game, gm, MSC_DEC_PICK, 8, 40, patched_panels=(
            "bot.mason_night_role._show_mason_commander_panel",
        ))
        self.assertEqual(
            sorted(game.mason_commander_pending_decision_uids), [21, 22]
        )
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 0)
        await _press(game, gm, MSC_DEC_CONFIRM, 0, 40)
        self.assertEqual(
            sorted(ms_cmd.mason_commander_approved_shot_uids(game)), [21, 22]
        )
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 2)
        self.assertTrue(game.mason_night_commander_confirmed)

    async def test_two_nominees_reject_one_approves_other(self) -> None:
        game = self._setup_two(gm := GameManager())
        # تصمیم «تأیید شلیک به B» (tid=2)
        await _press(game, gm, MSC_DEC_PICK, 2, 40, patched_panels=(
            "bot.mason_night_role._show_mason_commander_panel",
        ))
        await _press(game, gm, MSC_DEC_CONFIRM, 0, 40)
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [22])
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 1)

    async def test_reject_all_pending_then_confirm(self) -> None:
        game = self._setup_two(gm := GameManager())
        await _press(game, gm, MSC_DEC_PICK, 9, 40, patched_panels=(
            "bot.mason_night_role._show_mason_commander_panel",
        ))
        self.assertTrue(game.mason_commander_pending_reject_all)
        self.assertEqual(game.mason_commander_pending_decision_uids, [])
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 0)
        await _press(game, gm, MSC_DEC_CONFIRM, 0, 40)
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [])
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 0)
        self.assertTrue(game.mason_night_commander_confirmed)

    async def test_three_nominees_subset_toggle(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        game.players[10] = _p(10, "Sn", Role.SNIPER)
        game.players[40] = _p(40, "Cmd", Role.COMMANDER)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        game.players[22] = _p(22, "B", Role.TOWN_SIMPLE)
        game.players[23] = _p(23, "C", Role.TOWN_SIMPLE)
        ms_sn.commit_mason_sniper_night_selection(game, [21, 22, 23])
        # ظرفیت = گلوله‌های باقی‌مانده (۳)
        await _press(game, gm, MSC_DEC_PICK, 21, 40, patched_panels=(
            "bot.mason_night_role._show_mason_commander_panel",
        ))
        await _press(game, gm, MSC_DEC_PICK, 23, 40, patched_panels=(
            "bot.mason_night_role._show_mason_commander_panel",
        ))
        self.assertEqual(
            sorted(game.mason_commander_pending_decision_uids), [21, 23]
        )
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 0)
        await _press(game, gm, MSC_DEC_CONFIRM, 0, 40)
        self.assertEqual(
            sorted(ms_cmd.mason_commander_approved_shot_uids(game)), [21, 23]
        )
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 2)

    async def test_mode_b_msc_none_is_stale(self) -> None:
        game = self._setup_two(gm := GameManager())
        cb = await _press(game, gm, MSC_NONE, 0, 40)
        self.assertFalse(game.mason_night_commander_confirmed)
        self.assertEqual(cb.answer.await_args.kwargs.get("show_alert"), True)
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [])

    async def test_mode_b_decision_panel_buttons(self) -> None:
        game = self._setup_two(gm := GameManager())
        cb = _cb()
        captured: list = []

        async def _sync(_bot_, _game_, _ui, _uid, _text, kb):
            captured.append(kb)

        with patch("bot.mason_night_role.sync_role_mirror_panel", side_effect=_sync):
            await _show_mason_commander_panel(MagicMock(), game, gm, 40)
        labels = _labels(captured[-1])
        self.assertIn(MASON_COMMANDER_DECISION_APPROVE_ONE.format(name="A"), labels)
        self.assertIn(MASON_COMMANDER_DECISION_APPROVE_ONE.format(name="B"), labels)
        self.assertIn(MASON_COMMANDER_DECISION_APPROVE_BOTH, labels)
        self.assertIn(MASON_COMMANDER_DECISION_REJECT_ALL, labels)
        self.assertIn("✅ تأیید انتخاب", labels)
        self.assertNotIn(MASON_COMMANDER_DECISION_REJECT_ONE, labels)


class DoctorCap1Tests(unittest.IsolatedAsyncioTestCase):
    """F — پزشک ظرفیت ۱: جایگزینی مستقیم + «انتخابی ندارم» موقت."""

    async def test_cap1_tap_replaces_previous_target(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)  # ۳ بازیکن زنده → ظرفیت ۱
        game.players[40] = _p(40, "Doc", Role.DOCTOR)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        game.players[22] = _p(22, "B", Role.TOWN_SIMPLE)
        self.assertEqual(ms_doc.mason_doctor_save_capacity(game), 1)
        await _press(game, gm, MSD_PICK, 21, 40, patched_panels=(
            "bot.mason_night_role._show_mason_doctor_panel",
        ))
        self.assertEqual(ms_doc.mason_doctor_night_save_uids(game), [21])
        await _press(game, gm, MSD_PICK, 22, 40, patched_panels=(
            "bot.mason_night_role._show_mason_doctor_panel",
        ))
        self.assertEqual(ms_doc.mason_doctor_night_save_uids(game), [22])
        self.assertFalse(game.mason_night_doctor_confirmed)

    async def test_none_pending_then_confirm_clears_saves(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        game.players[40] = _p(40, "Doc", Role.DOCTOR)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        await _press(game, gm, MSD_PICK, 21, 40, patched_panels=(
            "bot.mason_night_role._show_mason_doctor_panel",
        ))
        await _press(game, gm, MSD_DONE, 0, 40, patched_panels=(
            "bot.mason_night_role._show_mason_doctor_panel",
        ))
        self.assertTrue(game.mason_doctor_night_none_pending)
        self.assertEqual(ms_doc.mason_doctor_night_save_uids(game), [])
        self.assertFalse(game.mason_night_doctor_confirmed)
        await _press(game, gm, MSD_CONFIRM, 0, 40)
        self.assertTrue(game.mason_night_doctor_confirmed)
        self.assertEqual(ms_doc.mason_doctor_night_save_uids(game), [])


class SaboteurGunnerNoneTests(unittest.IsolatedAsyncioTestCase):
    """A — خرابکار/تفنگدار: انتخاب موقت + تعارض دوطرفه + تأیید."""

    async def test_saboteur_pick_clears_none_pending(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.players[10] = _p(10, "Sab", Role.SABOTEUR)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        # انتخاب موقت «انتخابی ندارم»
        await _press(game, gm, MSB_NONE, 0, 10, patched_panels=(
            "bot.mason_night_role._show_mason_saboteur_panel",
        ))
        self.assertTrue(game.mason_saboteur_night_no_sabotage)
        # لمس بازیکن — «انتخابی ندارم» موقت پاک می‌شود
        await _press(game, gm, MSB_PICK, 21, 10, patched_panels=(
            "bot.mason_night_role._show_mason_saboteur_panel",
        ))
        self.assertFalse(game.mason_saboteur_night_no_sabotage)
        self.assertEqual(game.mason_saboteur_night_target_uid, 21)

    async def test_gunner_none_pending_then_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.players[10] = _p(10, "Gn", Role.GUNMAN)
        game.players[21] = _p(21, "A", Role.TOWN_SIMPLE)
        await _press(game, gm, MGN_NONE, 0, 10, patched_panels=(
            "bot.mason_night_role._show_mason_gunner_panel",
        ))
        self.assertTrue(game.mason_gunner_night_no_give)
        self.assertFalse(game.mason_night_gunner_confirmed)
        await _press(game, gm, MGN_CONFIRM, 0, 10)
        self.assertTrue(game.mason_night_gunner_confirmed)
        self.assertTrue(game.mason_gunner_night_no_give)


class RecruitDeadTailorTests(unittest.IsolatedAsyncioTestCase):
    """G — جذب: «انتخابی ندارم» و تایلر مرده = انتخاب موقت + تأیید."""

    async def test_dead_tailor_pending_then_confirm(self) -> None:
        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.setup_night(night_count=1)
        game = h.game
        ms_uid = h.holder_uid(Role.MASON)
        assert ms_uid is not None
        # دکمهٔ تایلر مرده: تایلر در نقش‌های توزیع‌شده نیست یا مرده و مصرف‌نشده
        tailor = ms_mf.find_mason_tailor(game)
        if tailor is None or tailor.is_alive:
            self.skipTest("dead-tailor button not available in this deal")
        await _press(game, gm, MSM_TAILOR, tailor.user_id, ms_uid, patched_panels=(
            "bot.mason_night_role._show_mason_recruit_panel",
        ))
        self.assertTrue(ms_mf.mason_recruit_dead_tailor_pending(game))
        self.assertFalse(game.mason_night_mason_confirmed)
        self.assertFalse(game.mason_tyler_button_consumed)
        await _press(game, gm, MSM_CONFIRM, 0, ms_uid)
        self.assertTrue(game.mason_night_mason_confirmed)
        self.assertTrue(game.mason_tyler_button_consumed)
        self.assertFalse(game.mason_pending_recruit_uid)

    async def test_no_recruit_pending_then_confirm(self) -> None:
        gm = GameManager()
        h = MasonSimHarness.build(gm, max_players=16)
        h.setup_night(night_count=1)
        game = h.game
        ms_uid = h.holder_uid(Role.MASON)
        assert ms_uid is not None
        await _press(game, gm, MSM_NONE, 0, ms_uid, patched_panels=(
            "bot.mason_night_role._show_mason_recruit_panel",
        ))
        self.assertTrue(game.mason_mason_night_no_recruit)
        self.assertFalse(game.mason_night_mason_confirmed)
        await _press(game, gm, MSM_CONFIRM, 0, ms_uid)
        self.assertTrue(game.mason_night_mason_confirmed)


class ForceFinishButtonTests(unittest.IsolatedAsyncioTestCase):
    """D — دکمهٔ «🌙 اتمام شب» روی پنل یادآور؛ فقط کمک‌کننده."""

    def _active_game(self, gm: GameManager, *, assistant_uid: int = 900):
        game = _mason_game(gm)
        game.room_code = "FB1"
        game.bot_assistant_user_id = assistant_uid
        game.observer_prompt_status = "registered"
        game.observer_user_id = 999
        game.no_host_assistant_narrator_active = True
        game.bazpors_narrator_step = NIGHT_START
        game.bazpors_narrator_night_count = 1
        game.no_host_night_parallel_collect_active = True
        game.mason_night_entry_dispatched_night = 1
        gm.add_player(game, _p(assistant_uid, "Helper", Role.TOWN_SIMPLE))
        return game

    async def test_button_sends_yes_no_confirm_for_helper(self) -> None:
        gm = GameManager()
        game = self._active_game(gm)
        from bot.mason_force_finish_night import (
            MASON_FORCE_FINISH_BUTTON_TEXT,
            MASON_FORCE_FINISH_CONFIRM_TEXT,
            handle_mason_force_finish_button,
            mason_force_finish_button_keyboard,
        )

        kb = mason_force_finish_button_keyboard(game)
        self.assertEqual(_labels(kb), [MASON_FORCE_FINISH_BUTTON_TEXT])

        cb = _cb()
        bot = AsyncMock()
        await handle_mason_force_finish_button(
            cb, bot, game, gm, assistant_uid=900
        )
        bot.send_message.assert_awaited_once()
        args = bot.send_message.await_args
        self.assertEqual(args.args[1] if len(args.args) > 1 else args.kwargs["text"], MASON_FORCE_FINISH_CONFIRM_TEXT)
        self.assertIsNotNone(args.kwargs.get("reply_markup"))

    async def test_button_during_day_is_rejected(self) -> None:
        gm = GameManager()
        game = self._active_game(gm)
        game.no_host_night_parallel_collect_active = False
        from bot.mason_force_finish_night import (
            MASON_FORCE_FINISH_NOT_NIGHT_TEXT,
            handle_mason_force_finish_button,
        )

        cb = _cb()
        bot = AsyncMock()
        await handle_mason_force_finish_button(
            cb, bot, game, gm, assistant_uid=900
        )
        bot.send_message.assert_not_awaited()
        cb.answer.assert_awaited_once_with(
            MASON_FORCE_FINISH_NOT_NIGHT_TEXT, show_alert=True
        )

    async def test_non_helper_has_no_assistant_game(self) -> None:
        gm = GameManager()
        self._active_game(gm)
        from bot.mason_force_finish_night import find_mason_bot_assistant_game

        # مسیر msh: فقط پیام‌های کمک‌کنندهٔ بازی فعال به دکمه می‌رسند.
        self.assertIsNone(find_mason_bot_assistant_game(42, gm))


class ElimReportPendingNightTests(unittest.IsolatedAsyncioTestCase):
    """E — گزارش حذف‌شدگان: شب حل‌نشده = انتظار؛ پس از حل‌شدن قطعی."""

    def _dead_player_game(self, gm: GameManager):
        game = _mason_game(gm)
        game.room_code = "ER1"
        game.observer_prompt_status = "registered"
        game.observer_user_id = 999
        game.roles_dealt = True
        game.phase = Phase.NIGHT
        game.bazpors_narrator_night_count = 2
        game.players[500] = _p(500, "Victim", Role.TOWN_SIMPLE, alive=False)
        return game

    async def test_capture_midnight_sets_pending_night(self) -> None:
        game = self._dead_player_game(GameManager())
        with patch(
            "bot.mason_elim_report.build_mason_elim_cutoff_report_html",
            side_effect=lambda g, _gm: "<html-victim-1>",
        ):
            from bot.mason_elim_report import capture_mason_elim_report_cutoff

            entry = capture_mason_elim_report_cutoff(game, MagicMock(), 500)
        self.assertIsNotNone(entry)
        self.assertEqual(entry["pending_night"], 2)

    async def test_read_before_night_resolves_is_blocked(self) -> None:
        game = self._dead_player_game(GameManager())
        from bot.mason_elim_report import (
            capture_mason_elim_report_cutoff,
            handle_mason_elim_report_callback,
        )

        with patch(
            "bot.mason_elim_report.build_mason_elim_cutoff_report_html",
            side_effect=lambda g, _gm: "<html-victim-1>",
        ):
            capture_mason_elim_report_cutoff(game, MagicMock(), 500)
        cb = _cb()
        cb.from_user = MagicMock()
        cb.from_user.id = 500
        with patch(
            "bot.mason_elim_report.safe_callback_answer", new=AsyncMock()
        ) as ans, patch("bot.mason_elim_report.safe_send_message", new=AsyncMock()):
            await handle_mason_elim_report_callback(
                cb, MagicMock(), game, as_uid=500, gts=game.created_at.timestamp().__int__()
            )
        ans.assert_awaited()
        self.assertNotIn("<html-victim-1>", str(ans.await_args))

    async def test_refresh_after_night_resolves_finalizes(self) -> None:
        game = self._dead_player_game(GameManager())
        from bot.mason_elim_report import (
            capture_mason_elim_report_cutoff,
            refresh_mason_elim_cutoffs_after_night,
        )

        with patch(
            "bot.mason_elim_report.build_mason_elim_cutoff_report_html",
            side_effect=lambda g, _gm: "<html-victim-1>",
        ):
            entry = capture_mason_elim_report_cutoff(game, MagicMock(), 500)
        self.assertEqual(entry["pending_night"], 2)
        # شب ۲ حل می‌شود
        game.mason_final_night_outcomes.append(
            {"night": 2, "day": 2, "day_elims": [], "night_elims": [500], "finalized": True}
        )
        with patch(
            "bot.mason_elim_report.build_mason_elim_cutoff_report_html",
            side_effect=lambda g, _gm: "<html-victim-2>",
        ):
            refresh_mason_elim_cutoffs_after_night(game, MagicMock())
        self.assertIsNone(entry["pending_night"])
        self.assertEqual(entry["report_html"], "<html-victim-2>")


if __name__ == "__main__":
    unittest.main()
