"""پنل انتخاب چندتایی شب — فقط سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.mason_multi_select_panels import (
    append_mason_selection_lines,
    build_mason_multi_select_panel_text,
    build_mason_multi_select_progress_text,
    build_mason_selected_players_lines,
    filter_player_pool,
    mason_multi_select_no_more_button_label,
    mason_multi_select_none_button_label,
    mason_selection_ordinal_fa,
)
from bot.mason_night_role import (
    MSC_DONE,
    MSC_PICK,
    MSD_DONE,
    MSD_PICK,
    MSS_NONE,
    MSS_PICK,
    _show_mason_commander_panel,
    _show_mason_doctor_panel,
    _show_mason_sniper_panel,
    dispatch_mason_night_role,
)
from bot.models import Player, Role
from bot.roles import mason_commander as ms_cmd
from bot.roles import mason_doctor as ms_doc
from bot.roles import mason_sniper as ms_sn


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
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
    game.observer_prompt_status = "registered"
    game.observer_user_id = 999
    return game


def _add_town_fillers(game, gm: GameManager, count: int, *, start_uid: int = 100) -> None:
    for i in range(count):
        gm.add_player(game, _p(start_uid + i, f"F{i}", Role.TOWN_SIMPLE))


class MasonMultiSelectHelperTests(unittest.TestCase):
    def test_ordinal_fa(self) -> None:
        self.assertEqual(mason_selection_ordinal_fa(1), "اول")
        self.assertEqual(mason_selection_ordinal_fa(3), "سوم")

    def test_progress_text(self) -> None:
        self.assertEqual(
            build_mason_multi_select_progress_text(1, 2),
            "انتخاب‌های مجاز شما: 1 از 2",
        )
        self.assertEqual(
            build_mason_multi_select_progress_text(0, 3),
            "انتخاب‌های مجاز شما: 0 از 3",
        )

    def test_no_more_button_labels(self) -> None:
        self.assertEqual(
            mason_multi_select_no_more_button_label(2),
            "انتخاب دوم ندارم",
        )
        self.assertEqual(
            mason_multi_select_no_more_button_label(3),
            "انتخاب سوم ندارم",
        )

    def test_none_button_label_first_vs_later_steps(self) -> None:
        self.assertEqual(
            mason_multi_select_none_button_label(
                0, first_step_label="بدون شلیک"
            ),
            "بدون شلیک",
        )
        self.assertEqual(
            mason_multi_select_none_button_label(
                1, first_step_label="بدون شلیک"
            ),
            "انتخاب دوم ندارم",
        )
        self.assertEqual(
            mason_multi_select_none_button_label(
                2, first_step_label="انتخابی ندارم"
            ),
            "انتخاب سوم ندارم",
        )

    def test_panel_text_includes_progress_and_selections(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "Alice", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "Bob", Role.TOWN_SIMPLE))
        text = build_mason_multi_select_panel_text(
            "🎯 header",
            game,
            gm,
            [20, 30],
            3,
        )
        self.assertIn("انتخاب‌های مجاز شما: 2 از 3", text)
        self.assertIn("انتخاب اول: Alice", text)
        self.assertIn("انتخاب دوم: Bob", text)

    def test_selection_lines_format(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "Alice", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "Bob", Role.TOWN_SIMPLE))
        lines = build_mason_selected_players_lines(game, gm, [20, 30])
        self.assertIn("انتخاب اول: Alice", lines)
        self.assertIn("انتخاب دوم: Bob", lines)

    def test_append_selection_lines(self) -> None:
        header = "🎯 header"
        body = append_mason_selection_lines(header, "انتخاب اول: A")
        self.assertEqual(body, "🎯 header\n\nانتخاب اول: A")
        self.assertEqual(append_mason_selection_lines(header, ""), header)

    def test_filter_player_pool_excludes_selected(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        a = _p(20, "A", Role.TOWN_SIMPLE)
        b = _p(30, "B", Role.TOWN_SIMPLE)
        gm.add_player(game, a)
        gm.add_player(game, b)
        pool = filter_player_pool([a, b], {20})
        self.assertEqual([p.user_id for p in pool], [30])


class MasonSniperPoolTests(unittest.TestCase):
    def test_available_pool_excludes_first_selection(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "B", Role.TOWN_SIMPLE))
        ms_sn.commit_mason_sniper_night_selection(game, [20])
        pool_ids = {p.user_id for p in ms_sn.mason_sniper_available_shot_pool(game)}
        self.assertNotIn(20, pool_ids)
        self.assertIn(30, pool_ids)


class MasonDoctorPoolTests(unittest.TestCase):
    def test_save_pool_excludes_already_saved(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE))
        ms_doc.commit_mason_doctor_save(game, 21)
        pool_ids = {p.user_id for p in ms_doc.mason_doctor_save_pool(game)}
        self.assertNotIn(21, pool_ids)
        self.assertIn(22, pool_ids)


class MasonCommanderPoolTests(unittest.TestCase):
    def test_approval_pool_excludes_already_approved(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "B", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(40, "Cmd", Role.COMMANDER))
        ms_sn.commit_mason_sniper_night_selection(game, [20, 30])
        ms_cmd.add_mason_commander_approval(game, 20)
        pool_ids = {p.user_id for p in ms_cmd.mason_commander_approval_pool(game)}
        self.assertNotIn(20, pool_ids)
        self.assertIn(30, pool_ids)

    def test_incremental_approval_bullet_delta(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(20, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(30, "B", Role.TOWN_SIMPLE))
        ms_sn.commit_mason_sniper_night_selection(game, [20, 30])
        self.assertTrue(ms_cmd.add_mason_commander_approval(game, 20))
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 1)
        self.assertTrue(ms_cmd.add_mason_commander_approval(game, 30))
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 2)


class MasonDoctorSelfSavePanelTests(unittest.IsolatedAsyncioTestCase):
    async def _capture_initial_panel(self, show_fn, game, gm, uid):
        bot = MagicMock()
        captured: list[tuple[str, list, list[str]]] = []

        async def _register(bot_, game_, player_uid, ui_key, text, kb, **kw):
            player_ids = []
            button_texts = []
            for row in kb.inline_keyboard:
                for btn in row:
                    button_texts.append(btn.text)
                    if btn.callback_data and btn.callback_data.startswith("pmr:"):
                        parts = btn.callback_data.split(":")
                        if len(parts) >= 5 and parts[4].isdigit():
                            player_ids.append(int(parts[4]))
            captured.append((text, player_ids, button_texts))

        with patch(
            "bot.mason_night_role.register_mirror_prompt_pair",
            side_effect=_register,
        ):
            await show_fn(bot, game, gm, uid, initial=True)

        return captured[-1]

    async def test_doctor_initial_panel_shows_self_save_line(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))

        text, player_ids, _ = await self._capture_initial_panel(
            _show_mason_doctor_panel, game, gm, 40
        )
        self.assertIn("🛡️ تعداد دفعات استفاده از نجات خود: ۰ از ۲", text)
        self.assertIn(40, player_ids)

    async def test_doctor_panel_after_one_self_save_shows_count(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        game.mason_doctor_self_save_count = 1

        text, _, _ = await self._capture_initial_panel(
            _show_mason_doctor_panel, game, gm, 40
        )
        self.assertIn("🛡️ تعداد دفعات استفاده از نجات خود: ۱ از ۲", text)

    async def test_doctor_panel_excludes_self_at_limit(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        game.mason_doctor_self_save_count = ms_doc.MASON_MAX_SELF_SAVES

        text, player_ids, _ = await self._capture_initial_panel(
            _show_mason_doctor_panel, game, gm, 40
        )
        self.assertIn("🛡️ تعداد دفعات استفاده از نجات خود: ۲ از ۲", text)
        self.assertNotIn(40, player_ids)
        self.assertIn(21, player_ids)

    async def test_doctor_refresh_panel_keeps_self_save_line(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        ms_doc.commit_mason_doctor_save(game, 21)
        bot = MagicMock()
        captured: list[str] = []

        async def _sync(bot_, game_, ui, as_uid, text, kb):
            captured.append(text)

        with patch(
            "bot.mason_night_role.sync_role_mirror_panel",
            side_effect=_sync,
        ):
            await _show_mason_doctor_panel(bot, game, gm, 40)

        self.assertIn("🛡️ تعداد دفعات استفاده از نجات خود: ۰ از ۲", captured[-1])


class MasonMultiSelectPanelRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def _capture_panel(self, show_fn, game, gm, uid):
        bot = MagicMock()
        captured: list[tuple[str, list, list[str]]] = []

        async def _sync(bot_, game_, ui, as_uid, text, kb):
            player_ids = []
            button_texts = []
            for row in kb.inline_keyboard:
                for btn in row:
                    button_texts.append(btn.text)
                    if btn.callback_data and btn.callback_data.startswith("pmr:"):
                        parts = btn.callback_data.split(":")
                        if len(parts) >= 5 and parts[4].isdigit():
                            player_ids.append(int(parts[4]))
            captured.append((text, player_ids, button_texts))

        with patch(
            "bot.mason_night_role.sync_role_mirror_panel",
            side_effect=_sync,
        ):
            await show_fn(bot, game, gm, uid)

        return captured[-1]

    async def test_sniper_initial_panel_shows_zero_progress(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))

        text, _, button_texts = await self._capture_panel(
            _show_mason_sniper_panel, game, gm, 50
        )
        self.assertIn("انتخاب‌های مجاز شما: 0 از 2", text)
        self.assertTrue(any("بدون شلیک" in t for t in button_texts))

    async def test_sniper_panel_text_and_buttons_after_first_pick(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE))
        ms_sn.commit_mason_sniper_night_selection(game, [21])

        text, player_ids, button_texts = await self._capture_panel(
            _show_mason_sniper_panel, game, gm, 50
        )
        self.assertIn("انتخاب‌های مجاز شما: 1 از 2", text)
        self.assertIn("انتخاب اول: A", text)
        self.assertNotIn(21, player_ids)
        self.assertIn(22, player_ids)
        self.assertTrue(any("انتخاب دوم ندارم" in t for t in button_texts))

    async def test_doctor_panel_text_and_buttons_after_first_save(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE))
        _add_town_fillers(game, gm, 10)
        ms_doc.commit_mason_doctor_save(game, 21)

        text, player_ids, button_texts = await self._capture_panel(
            _show_mason_doctor_panel, game, gm, 40
        )
        self.assertIn("انتخاب‌های مجاز شما: 1 از 3", text)
        self.assertIn("انتخاب اول: A", text)
        self.assertNotIn(21, player_ids)
        self.assertIn(22, player_ids)
        self.assertTrue(any("انتخاب دوم ندارم" in t for t in button_texts))

    async def test_doctor_third_step_button_after_two_saves(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=18)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(23, "C", Role.TOWN_SIMPLE))
        _add_town_fillers(game, gm, 14)
        ms_doc.commit_mason_doctor_save(game, 21)
        ms_doc.commit_mason_doctor_save(game, 22)

        text, _, button_texts = await self._capture_panel(
            _show_mason_doctor_panel, game, gm, 40
        )
        self.assertIn("انتخاب‌های مجاز شما: 2 از 4", text)
        self.assertTrue(any("انتخاب سوم ندارم" in t for t in button_texts))

    async def test_commander_panel_text_and_buttons_after_first_approval(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(40, "Cmd", Role.COMMANDER))
        ms_sn.commit_mason_sniper_night_selection(game, [21, 22])
        ms_cmd.add_mason_commander_approval(game, 21)

        text, player_ids, button_texts = await self._capture_panel(
            _show_mason_commander_panel, game, gm, 40
        )
        self.assertIn("انتخاب‌های مجاز شما: 1 از 2", text)
        self.assertIn("تأیید اول: A", text)
        self.assertNotIn(21, player_ids)
        self.assertIn(22, player_ids)
        self.assertTrue(any("انتخاب دوم ندارم" in t for t in button_texts))
        self.assertFalse(any("رد همه" in t for t in button_texts))


class MasonMultiSelectHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_sniper_none_after_one_target_keeps_selection(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        ms_sn.commit_mason_sniper_night_selection(game, [21])
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        captured: list[str] = []

        async def _capture_finalize(
            bot_, game_, gm_, uid, ui_key, selection_label, **kw
        ):
            captured.append(selection_label)

        with patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            side_effect=_capture_finalize,
        ), patch(
            "bot.mason_night_role.dispatch_mason_commander_panel",
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
                as_uid=50,
                actor_uid=50,
                act=MSS_NONE,
                tid=0,
            )
        self.assertEqual(ms_sn.mason_sniper_night_selected_uids(game), [21])
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 0)
        self.assertIn("A", captured[0])

    async def test_sniper_early_stop_with_one_target(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE))
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        with patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_role.dispatch_mason_commander_panel",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_role._show_mason_sniper_panel",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb, bot, game, gm, as_uid=50, actor_uid=50, act=MSS_PICK, tid=21
            )
            await dispatch_mason_night_role(
                cb, bot, game, gm, as_uid=50, actor_uid=50, act=MSS_NONE, tid=0
            )
        self.assertEqual(ms_sn.mason_sniper_night_selected_uids(game), [21])
        self.assertTrue(game.mason_night_sniper_confirmed)
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 0)

    async def test_doctor_early_stop_registers_one_save_only(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE))
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        with patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_role._show_mason_doctor_panel",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb, bot, game, gm, as_uid=40, actor_uid=40, act=MSD_PICK, tid=21
            )
            await dispatch_mason_night_role(
                cb, bot, game, gm, as_uid=40, actor_uid=40, act=MSD_DONE, tid=0
            )
        self.assertEqual(ms_doc.mason_doctor_night_save_uids(game), [21])
        self.assertTrue(game.mason_night_doctor_confirmed)
        self.assertFalse(game.mason_night_pending_doctor_self_save)

    async def test_commander_early_stop_approves_one_bullet_only(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(40, "Cmd", Role.COMMANDER))
        ms_sn.commit_mason_sniper_night_selection(game, [21, 22])
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()

        with patch(
            "bot.mason_night_role.finalize_no_host_role_pick_message",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_role._show_mason_commander_panel",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_role(
                cb, bot, game, gm, as_uid=40, actor_uid=40, act=MSC_PICK, tid=21
            )
            await dispatch_mason_night_role(
                cb, bot, game, gm, as_uid=40, actor_uid=40, act=MSC_DONE, tid=0
            )
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [21])
        self.assertEqual(ms_sn.mason_sniper_bullets_spent(game), 1)
        self.assertTrue(game.mason_night_commander_confirmed)

    async def test_sniper_pick_refreshes_panel_before_max(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE))
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        refreshed = AsyncMock()

        with patch(
            "bot.mason_night_role._show_mason_sniper_panel",
            refreshed,
        ):
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=50,
                actor_uid=50,
                act=MSS_PICK,
                tid=21,
            )
        refreshed.assert_awaited_once()
        self.assertFalse(game.mason_night_sniper_confirmed)

    async def test_doctor_pick_refreshes_panel_when_more_saves_allowed(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=15)
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE))
        _add_town_fillers(game, gm, 10)
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        refreshed = AsyncMock()

        with patch(
            "bot.mason_night_role._show_mason_doctor_panel",
            refreshed,
        ):
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=40,
                actor_uid=40,
                act=MSD_PICK,
                tid=21,
            )
        refreshed.assert_awaited_once()
        self.assertFalse(game.mason_night_doctor_confirmed)

    async def test_commander_pick_refreshes_panel_for_second_approval(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Sn", Role.SNIPER))
        gm.add_player(game, _p(21, "A", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(22, "B", Role.TOWN_SIMPLE))
        gm.add_player(game, _p(40, "Cmd", Role.COMMANDER))
        ms_sn.commit_mason_sniper_night_selection(game, [21, 22])
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        refreshed = AsyncMock()

        with patch(
            "bot.mason_night_role._show_mason_commander_panel",
            refreshed,
        ):
            await dispatch_mason_night_role(
                cb,
                bot,
                game,
                gm,
                as_uid=40,
                actor_uid=40,
                act=MSC_PICK,
                tid=21,
            )
        refreshed.assert_awaited_once()
        self.assertFalse(game.mason_night_commander_confirmed)
        self.assertEqual(ms_cmd.mason_commander_approved_shot_uids(game), [21])


class BazporsUnchangedRegressionTests(unittest.TestCase):
    def test_bazpors_sniper_still_single_shot(self) -> None:
        from bot.roles import sniper as sn

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.assertEqual(sn.shot_limit(game), 1)


if __name__ == "__main__":
    unittest.main()
