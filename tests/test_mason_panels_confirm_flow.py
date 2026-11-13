"""پنل‌های هدف ماسون — انتخاب موقت، رنگ آبی/قرمز و تأیید نهایی.

فقط سناریوی ماسون؛ جریان اجرای قابلیت‌ها بدون تغییر (فقط UI/تأیید).
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.mason_day_ability import (
    MASON_APACHE_BACK_ACT,
    MASON_APACHE_CONFIRM_ACT,
    MASON_APACHE_DECL_INTENT_ACT,
    MASON_APACHE_DECL_OK_ACT,
    MASON_APACHE_PICK_ACT,
    MASON_COWBOY_BACK_ACT,
    MASON_COWBOY_CONFIRM_ACT,
    MASON_COWBOY_DECL_INTENT_ACT,
    MASON_COWBOY_DECL_OK_ACT,
    MASON_COWBOY_PICK_ACT,
    MASON_DAY_GUN_CONFIRM_ACT,
    MASON_DAY_GUN_PICK_ACT,
    _dispatch_mason_day_gun_panel,
    dispatch_mason_day_ability,
    dispatch_mason_intro_day_ability_panels,
)
from bot.mason_multi_select_panels import (
    MASON_DECL_BUTTON_LABEL,
    MASON_DECL_CONFIRM_QUESTION,
    MASON_FINAL_CONFIRM_LABEL,
)
from bot.mason_night_role import (
    MGD_BACK,
    MGD_CONFIRM,
    MGD_PICK,
    MGN_BACK,
    MGN_CONFIRM,
    MGN_PICK,
    MSB_BACK,
    MSB_CONFIRM,
    MSB_NONE,
    MSB_PICK,
    MSD_CONFIRM,
    MSD_DONE,
    MSD_PICK,
    MSM_BACK,
    MSM_CONFIRM,
    MSM_PICK,
    MSS_CONFIRM,
    MSS_NONE,
    MSS_PICK,
    dispatch_mason_night_role,
)
from bot.models import Player, Role
from bot.roles import mason_doctor as ms_doc
from bot.roles import mason_gunner as ms_gn
from bot.roles import mason_sniper as ms_sn


def _p(
    uid: int,
    name: str,
    role: Role,
    *,
    alive: bool = True,
    seat: int | None = None,
) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
        seat=seat,
    )


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


def _buttons(kb):
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            parts = (btn.callback_data or "").split(":")
            tid = (
                int(parts[4])
                if len(parts) >= 5 and parts[4].isdigit()
                else 0
            )
            out.append((btn.text, parts[2] if len(parts) >= 3 else "", tid, btn.style))
    return out


class MasonNightPanelFlowTests(unittest.IsolatedAsyncioTestCase):
    """الگوی مشترک: انتخاب موقت (قرمز) + تأیید نهایی — شب."""

    async def _drive(self, game, gm, presses):
        bot = MagicMock()
        registered: list[tuple[int, str, str, object]] = []
        synced: list[tuple[int, str, str, object]] = []
        finalized: list[str] = []

        async def _reg(bot_, game_, uid, ui, text, kb, **kw):
            registered.append((uid, ui, text, kb))

        async def _syn(bot_, game_, ui, uid, text, kb):
            synced.append((uid, ui, text, kb))

        async def _fin(bot_, game_, gm_, uid, ui_key, label, **kw):
            finalized.append(label)

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_reg,
        ), patch(
            "bot.mason_night_role.sync_role_mirror_panel",
            side_effect=_syn,
        ), patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            side_effect=_fin,
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ), patch(
            "bot.observer_delivery.deliver_no_host_player_game_copy",
            new=AsyncMock(),
        ):
            for act, tid, uid in presses:
                cb = MagicMock()
                cb.answer = AsyncMock()
                await dispatch_mason_night_role(
                    cb,
                    bot,
                    game,
                    gm,
                    as_uid=uid,
                    actor_uid=uid,
                    act=act,
                    tid=tid,
                )
        return registered + synced, finalized

    # --- Saboteur ---

    async def test_saboteur_pick_is_pending_not_confirmed(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Sab", Role.SABOTEUR))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        gm.add_player(game, _p(21, "B", Role.TOWN_SIMPLE, seat=3))
        panels, _ = await self._drive(game, gm, [(MSB_PICK, 20, 10)])
        self.assertEqual(game.mason_saboteur_night_target_uid, 20)
        self.assertFalse(game.mason_night_saboteur_confirmed)
        btns = _buttons(panels[-1][3])
        self.assertTrue(any(t == MASON_FINAL_CONFIRM_LABEL for t, _, _, _ in btns))
        by_tid = {tid: style for _, act, tid, style in btns if tid}
        self.assertEqual(by_tid.get(20), "danger")
        self.assertEqual(by_tid.get(21), "primary")

    async def test_saboteur_repick_same_target_deselects(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Sab", Role.SABOTEUR))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        gm.add_player(game, _p(21, "B", Role.TOWN_SIMPLE, seat=3))
        panels, _ = await self._drive(
            game, gm, [(MSB_PICK, 20, 10), (MSB_PICK, 20, 10)]
        )
        self.assertIsNone(game.mason_saboteur_night_target_uid)
        self.assertFalse(game.mason_night_saboteur_confirmed)
        btns = _buttons(panels[-1][3])
        by_tid = {tid: style for _, act, tid, style in btns if tid}
        self.assertEqual(by_tid.get(20), "primary")
        self.assertFalse(any(t == MASON_FINAL_CONFIRM_LABEL for t, _, _, _ in btns))

    async def test_saboteur_confirm_commits_exactly_once(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Sab", Role.SABOTEUR))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        _, finalized = await self._drive(
            game, gm, [(MSB_PICK, 20, 10), (MSB_CONFIRM, 0, 10)]
        )
        self.assertTrue(game.mason_night_saboteur_confirmed)
        self.assertEqual(len(finalized), 1)
        self.assertIn("A", finalized[0])
        # stale re-confirm: no second finalize
        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair", new=AsyncMock()
        ), patch(
            "bot.mason_night_role.sync_role_mirror_panel", new=AsyncMock()
        ), patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            cb = MagicMock()
            cb.answer = AsyncMock()
            await dispatch_mason_night_role(
                cb, MagicMock(), game, gm,
                as_uid=10, actor_uid=10, act=MSB_CONFIRM, tid=0,
            )
            cb.answer.assert_awaited_with(
                "این مرحله دیگر فعال نیست.", show_alert=True
            )

    async def test_saboteur_back_clears_pending(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Sab", Role.SABOTEUR))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        _, _ = await self._drive(
            game, gm, [(MSB_PICK, 20, 10), (MSB_BACK, 0, 10)]
        )
        self.assertIsNone(game.mason_saboteur_night_target_uid)
        self.assertFalse(game.mason_night_saboteur_confirmed)

    async def test_saboteur_none_pending_then_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Sab", Role.SABOTEUR))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        _, _ = await self._drive(
            game, gm, [(MSB_NONE, 0, 10), (MSB_CONFIRM, 0, 10)]
        )
        self.assertTrue(game.mason_night_saboteur_confirmed)

    # --- Doctor ---

    async def test_doctor_capacity_no_longer_auto_confirms(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE, seat=2))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE, seat=3))
        gm.add_player(game, _p(23, "C", Role.TOWN_SIMPLE, seat=4))
        gm.add_player(game, _p(24, "D", Role.TOWN_SIMPLE, seat=5))
        cap = ms_doc.mason_doctor_save_capacity(game)
        self.assertGreaterEqual(cap, 1)
        uids = [21, 22, 23, 24][: cap] + [99]
        presses = [(MSD_PICK, uid, 40) for uid in uids[: cap + 1]]
        panels, _ = await self._drive(game, gm, presses)
        self.assertFalse(game.mason_night_doctor_confirmed)
        self.assertEqual(len(game.mason_doctor_night_save_uids), cap)
        btns = _buttons(panels[-1][3])
        self.assertTrue(any(t == MASON_FINAL_CONFIRM_LABEL for t, _, _, _ in btns))

    async def test_doctor_deselect_restores_slot(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE, seat=2))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE, seat=3))
        _, _ = await self._drive(
            game,
            gm,
            [(MSD_PICK, 21, 40), (MSD_PICK, 21, 40), (MSD_PICK, 22, 40)],
        )
        self.assertEqual(game.mason_doctor_night_save_uids, [22])
        self.assertFalse(game.mason_night_doctor_confirmed)

    async def test_doctor_none_pending_then_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE, seat=2))
        _, finalized = await self._drive(
            game, gm, [(MSD_DONE, 0, 40), (MSD_CONFIRM, 0, 40)]
        )
        self.assertTrue(game.mason_night_doctor_confirmed)
        self.assertEqual(len(finalized), 1)
        self.assertEqual(game.mason_doctor_night_save_uids, [])

    # --- Sniper ---

    async def test_sniper_limit_no_longer_auto_confirms(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE, seat=2))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE, seat=3))
        gm.add_player(game, _p(23, "C", Role.TOWN_SIMPLE, seat=4))
        gm.add_player(game, _p(24, "D", Role.TOWN_SIMPLE, seat=5))
        max_targets = ms_sn.mason_sniper_max_targets_this_night(game)
        uids = [21, 22, 23, 24][: max_targets] + [99]
        presses = [(MSS_PICK, uid, 50) for uid in uids[: max_targets + 1]]
        panels, _ = await self._drive(game, gm, presses)
        self.assertFalse(game.mason_night_sniper_confirmed)
        self.assertEqual(len(game.mason_sniper_night_selected_uids), max_targets)
        btns = _buttons(panels[-1][3])
        self.assertTrue(any(t == MASON_FINAL_CONFIRM_LABEL for t, _, _, _ in btns))

    async def test_sniper_none_pending_clears_selection_then_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE, seat=2))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE, seat=3))
        _, finalized = await self._drive(
            game,
            gm,
            [
                (MSS_PICK, 21, 50),
                (MSS_PICK, 21, 50),
                (MSS_PICK, 22, 50),
                (MSS_NONE, 0, 50),
                (MSS_CONFIRM, 0, 50),
            ],
        )
        self.assertEqual(game.mason_sniper_night_selected_uids, [])
        self.assertTrue(game.mason_sniper_night_no_shot)
        self.assertTrue(game.mason_night_sniper_confirmed)
        self.assertEqual(len(finalized), 1)

    # --- Gunner ---

    async def test_gunner_pick_pending_then_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Gn", Role.GUNMAN))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        gm.add_player(game, _p(21, "B", Role.TOWN_SIMPLE, seat=3))
        panels, finalized = await self._drive(game, gm, [(MGN_PICK, 20, 10)])
        self.assertEqual(game.mason_gunner_night_target_uid, 20)
        self.assertFalse(game.mason_night_gunner_confirmed)
        self.assertEqual(len(finalized), 0)
        btns = _buttons(panels[-1][3])
        self.assertTrue(any(t == MASON_FINAL_CONFIRM_LABEL for t, _, _, _ in btns))
        by_tid = {tid: style for _, act, tid, style in btns if tid}
        self.assertEqual(by_tid.get(20), "danger")
        panels, finalized = await self._drive(game, gm, [(MGN_CONFIRM, 0, 10)])
        self.assertTrue(game.mason_night_gunner_confirmed)
        self.assertEqual(len(finalized), 1)

    async def test_gunner_back_clears_pending(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Gn", Role.GUNMAN))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        _, _ = await self._drive(
            game, gm, [(MGN_PICK, 20, 10), (MGN_BACK, 0, 10)]
        )
        self.assertIsNone(game.mason_gunner_night_target_uid)
        self.assertFalse(game.mason_night_gunner_confirmed)

    # --- Guardian ---

    async def test_guardian_pick_pending_then_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=3))
        panels, finalized = await self._drive(game, gm, [(MGD_PICK, 20, 30)])
        self.assertEqual(game.mason_guardian_night_target_uid, 20)
        self.assertFalse(game.mason_night_guardian_confirmed)
        self.assertEqual(len(finalized), 0)
        btns = _buttons(panels[-1][3])
        self.assertTrue(any(t == MASON_FINAL_CONFIRM_LABEL for t, _, _, _ in btns))
        _, finalized = await self._drive(game, gm, [(MGD_CONFIRM, 0, 30)])
        self.assertTrue(game.mason_night_guardian_confirmed)
        self.assertEqual(len(finalized), 1)
        self.assertIn("A", finalized[0])

    async def test_guardian_back_and_self_excluded(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=3))
        gm.add_player(game, _p(21, "B", Role.TOWN_SIMPLE, seat=4))
        _, _ = await self._drive(
            game, gm, [(MGD_PICK, 20, 30), (MGD_BACK, 0, 30)]
        )
        self.assertIsNone(game.mason_guardian_night_target_uid)
        # انتخاب خودش مجاز نیست
        _, _ = await self._drive(game, gm, [(MGD_PICK, 30, 30)])
        self.assertIsNone(game.mason_guardian_night_target_uid)

    # --- Mason recruit ---

    async def test_mason_pick_pending_membership_only_after_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ms", Role.MASON))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        gm.add_player(game, _p(30, "Tl", Role.TAILOR, seat=3))
        panels, _ = await self._drive(game, gm, [(MSM_PICK, 20, 10)])
        self.assertEqual(game.mason_pending_recruit_uid, 20)
        self.assertFalse(game.mason_night_mason_confirmed)
        # عضویت هنوز ثبت نشده
        self.assertNotIn(20, game.mason_team_member_ids)
        btns = _buttons(panels[-1][3])
        self.assertTrue(any(t == MASON_FINAL_CONFIRM_LABEL for t, _, _, _ in btns))
        by_tid = {tid: style for _, act, tid, style in btns if tid}
        self.assertEqual(by_tid.get(20), "danger")
        _, finalized = await self._drive(game, gm, [(MSM_CONFIRM, 0, 10)])
        self.assertTrue(game.mason_night_mason_confirmed)
        self.assertIn(20, game.mason_team_member_ids)
        self.assertEqual(len(finalized), 1)

    async def test_mason_back_clears_pending(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ms", Role.MASON))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        _, _ = await self._drive(
            game, gm, [(MSM_PICK, 20, 10), (MSM_BACK, 0, 10)]
        )
        self.assertIsNone(game.mason_pending_recruit_uid)
        self.assertFalse(game.mason_night_mason_confirmed)


class MasonDayDeclarationFlowTests(unittest.IsolatedAsyncioTestCase):
    """دو مرحلهٔ اعلام نقش (آپاچی/کابوی) — فقط ماسون."""

    async def _drive_day(self, game, gm, presses):
        bot = MagicMock()
        registered: list[tuple[int, str, str, object]] = []
        synced: list[tuple[int, str, str, object]] = []

        async def _reg(bot_, game_, uid, ui, text, kb, **kw):
            registered.append((uid, ui, text, kb))

        async def _syn(bot_, game_, ui, uid, text, kb):
            synced.append((uid, ui, text, kb))

        with patch(
            "bot.mason_day_ability.register_mirror_prompt_pair",
            side_effect=_reg,
        ), patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            side_effect=_syn,
        ):
            game.mason_intro_day_ability_open = True
            await dispatch_mason_intro_day_ability_panels(bot, game, gm)
            for act, tid, uid in presses:
                cb = MagicMock()
                cb.answer = AsyncMock()
                await dispatch_mason_day_ability(
                    cb, bot, game, gm,
                    as_uid=uid, actor_uid=uid, act=act, tid=tid,
                )
        return registered + synced

    async def test_apache_initial_panel_is_declaration_button(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        panels = await self._drive_day(game, gm, [])
        self.assertTrue(game.mason_apache_day_flow_active)
        self.assertFalse(game.mason_apache_day_action_used)
        _, ui, text, kb = panels[0]
        self.assertIn("آپاچی", text)
        btns = _buttons(kb)
        self.assertEqual(len(btns), 1)
        label, act, tid, style = btns[0]
        self.assertEqual(label, MASON_DECL_BUTTON_LABEL)
        self.assertEqual(act, MASON_APACHE_DECL_INTENT_ACT)
        self.assertEqual(style, "primary")

    async def test_apache_declaration_confirm_stage(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        panels = await self._drive_day(
            game, gm, [(MASON_APACHE_DECL_INTENT_ACT, 0, 10)]
        )
        text, kb = panels[-1][2], panels[-1][3]
        self.assertIn(MASON_DECL_CONFIRM_QUESTION, text)
        btns = _buttons(kb)
        labels = [t for t, _, _, _ in btns]
        self.assertIn("✅ تأیید", labels)
        self.assertIn("❌ انصراف", labels)
        # هیچ چیز مصرف نشده
        self.assertIsNone(game.mason_apache_day_pending_uid)
        self.assertFalse(game.mason_apache_day_action_used)

    async def test_apache_cancel_returns_to_declaration_button(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        panels = await self._drive_day(
            game,
            gm,
            [(MASON_APACHE_DECL_INTENT_ACT, 0, 10), (MASON_APACHE_BACK_ACT, 0, 10)],
        )
        btns = _buttons(panels[-1][3])
        self.assertEqual(len(btns), 1)
        self.assertEqual(btns[0][0], MASON_DECL_BUTTON_LABEL)
        self.assertFalse(game.mason_apache_day_action_used)

    async def test_apache_target_stage_pending_confirm_executes(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        gm.add_player(game, _p(21, "B", Role.TOWN_SIMPLE, seat=3))
        executed: list[dict] = []

        async def _elim(bot_, game_, gm_, *, apache_uid, target_uid):
            executed.append({"apache": apache_uid, "target": target_uid})

        with patch(
            "bot.mason_day_ability.register_mirror_prompt_pair", new=AsyncMock()
        ), patch(
            "bot.mason_day_ability.sync_role_mirror_panel", new=AsyncMock()
        ), patch(
            "bot.mason_day_ability._eliminate_apache_and_target",
            side_effect=_elim,
        ):
            game.mason_intro_day_ability_open = True
            await dispatch_mason_intro_day_ability_panels(
                MagicMock(), game, gm
            )
            for act, tid in (
                (MASON_APACHE_DECL_INTENT_ACT, 0),
                (MASON_APACHE_DECL_OK_ACT, 0),
                (MASON_APACHE_PICK_ACT, 20),
            ):
                cb = MagicMock()
                cb.answer = AsyncMock()
                await dispatch_mason_day_ability(
                    cb, MagicMock(), game, gm,
                    as_uid=10, actor_uid=10, act=act, tid=tid,
                )
            self.assertEqual(game.mason_apache_day_pending_uid, 20)
            self.assertFalse(game.mason_apache_day_pick_confirmed)
            self.assertFalse(game.mason_apache_day_action_used)
            cb = MagicMock()
            cb.answer = AsyncMock()
            await dispatch_mason_day_ability(
                cb, MagicMock(), game, gm,
                as_uid=10, actor_uid=10, act=MASON_APACHE_CONFIRM_ACT, tid=0,
            )
        self.assertTrue(game.mason_apache_day_pick_confirmed)
        self.assertTrue(game.mason_apache_day_action_used)
        self.assertEqual(executed, [{"apache": 10, "target": 20}])

    async def test_apache_target_stage_self_excluded(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        panels = await self._drive_day(
            game,
            gm,
            [(MASON_APACHE_DECL_INTENT_ACT, 0, 10), (MASON_APACHE_DECL_OK_ACT, 0, 10)],
        )
        btns = _buttons(panels[-1][3])
        tids = [tid for _, act, tid, _ in btns if tid]
        self.assertNotIn(10, tids)
        self.assertIn(20, tids)
        self.assertTrue(all(style == "primary" for _, act, tid, style in btns if tid))
        # همیشه «↩️ بازگشت» موجود است
        self.assertTrue(any(t == "↩️ بازگشت" for t, _, _, _ in btns))

    async def test_cowboy_declaration_flow(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(11, "Cw", Role.COWBOY))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        panels = await self._drive_day(
            game,
            gm,
            [(MASON_COWBOY_DECL_INTENT_ACT, 0, 11), (MASON_COWBOY_DECL_OK_ACT, 0, 11)],
        )
        # پنل اولیه: فقط دکمهٔ اعلام
        cowboy_panels = [p for p in panels if "mason_cowboy" in p[1]]
        self.assertGreaterEqual(len(cowboy_panels), 3)
        _, ui, text, kb = cowboy_panels[0]
        btns = _buttons(kb)
        self.assertEqual(len(btns), 1)
        self.assertEqual(btns[0][0], MASON_DECL_BUTTON_LABEL)
        # مرحلهٔ تأیید اعلام
        text, kb = cowboy_panels[1][2], cowboy_panels[1][3]
        self.assertIn(MASON_DECL_CONFIRM_QUESTION, text)
        labels = [t for t, _, _, _ in _buttons(kb)]
        self.assertIn("✅ تأیید", labels)
        self.assertIn("❌ انصراف", labels)
        self.assertFalse(game.mason_cowboy_day_pick_confirmed)

    async def test_cowboy_cancel_returns_to_declaration_button(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(11, "Cw", Role.COWBOY))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE, seat=2))
        panels = await self._drive_day(
            game,
            gm,
            [(MASON_COWBOY_DECL_INTENT_ACT, 0, 11), (MASON_COWBOY_BACK_ACT, 0, 11)],
        )
        btns = _buttons(panels[-1][3])
        self.assertEqual(len(btns), 1)
        self.assertEqual(btns[0][0], MASON_DECL_BUTTON_LABEL)
        self.assertFalse(game.mason_cowboy_day_pick_confirmed)


class MasonDayGunPendingFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_day_gun_pick_pending_then_confirm(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Gn", Role.GUNMAN))
        gm.add_player(game, _p(20, "Holder", Role.TOWN_SIMPLE, seat=2))
        gm.add_player(game, _p(21, "Victim", Role.TOWN_SIMPLE, seat=3))
        ms_gn.commit_mason_gunner_target(game, game.players[10], game.players[20])
        ms_gn.prepare_mason_day_gun_from_night_choices(game)
        bot = MagicMock()
        synced: list[tuple[str, object]] = []

        async def _syn(bot_, game_, ui, uid, text, kb):
            synced.append((text, kb))

        resolved: list[tuple[int, int]] = []

        async def _elim(bot_, game_, gm_, *, holder_uid, target_uid):
            resolved.append((holder_uid, target_uid))

        with patch(
            "bot.mason_day_ability.register_mirror_prompt_pair", new=AsyncMock()
        ), patch(
            "bot.mason_day_ability.sync_role_mirror_panel",
            side_effect=_syn,
        ), patch(
            "bot.mason_day_ability._eliminate_day_gun_shot",
            side_effect=_elim,
        ):
            game.mason_intro_day_ability_open = True
            await _dispatch_mason_day_gun_panel(bot, game, gm)
            self.assertIsNone(game.mason_day_gun_shot_target_uid)
            cb = MagicMock()
            cb.answer = AsyncMock()
            await dispatch_mason_day_ability(
                cb, bot, game, gm,
                as_uid=20, actor_uid=20, act=MASON_DAY_GUN_PICK_ACT, tid=21,
            )
            self.assertEqual(game.mason_day_gun_shot_target_uid, 21)
            btns = _buttons(synced[-1][1])
            self.assertTrue(any(t == MASON_FINAL_CONFIRM_LABEL for t, _, _, _ in btns))
            by_tid = {tid: style for _, act, tid, style in btns if tid}
            self.assertEqual(by_tid.get(21), "danger")
            cb = MagicMock()
            cb.answer = AsyncMock()
            await dispatch_mason_day_ability(
                cb, bot, game, gm,
                as_uid=20, actor_uid=20,
                act=MASON_DAY_GUN_CONFIRM_ACT, tid=0,
            )
        self.assertEqual(resolved, [(20, 21)])


if __name__ == "__main__":
    unittest.main()
