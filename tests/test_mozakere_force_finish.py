"""اتمام اجباری شب مذاکره — کمک‌کننده ربات."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.bazpors_narrator import NIGHT_START
from bot.game import GameManager
from bot.models import Player, Role
from bot.mozakere_force_finish_night import (
    MOZAKERE_NIGHT_PHASE_ENDED_TEXT,
    MozakereHelperCb,
    find_mozakere_bot_assistant_game,
    force_finish_mozakere_night,
    handle_mozakere_force_finish_callback,
    handle_mozakere_helper_action,
    mozakere_force_finish_button_keyboard,
    mozakere_night_act_is_closed_for_game,
    mozakere_night_force_finish_collection_active,
    mozakere_night_player_actions_closed,
    normalize_pending_mozakere_night_actions,
    pending_mozakere_force_finish_labels,
)
from bot.no_host_night_ready import (
    all_no_host_parallel_night_ready,
    no_host_parallel_night_collect_active,
)
from bot.roles.night_state import doctor_night_state, sniper_night_state


def _p(uid: int, name: str, role: Role, *, alive: bool = True, seat: int = 0) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
        seat=seat,
    )


def _active_mozakere_night_game(gm: GameManager, *, assistant_uid: int = 900):
    game = gm.create_game(
        host_id=1,
        scenario_name="mozakere",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.room_code = "MZF"
    gm.games["MZF"] = game
    game.bot_assistant_user_id = assistant_uid
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = NIGHT_START
    game.bazpors_narrator_night_count = 1
    game.no_host_night_parallel_collect_active = True
    game.no_host_night_entry_dispatched_night = 1
    return game


def _full_cast(gm: GameManager, game) -> None:
    gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS, seat=1))
    gm.add_player(game, _p(11, "Neg", Role.MAFIA_NEGOTIATOR, seat=2))
    gm.add_player(game, _p(12, "Mafia", Role.MAFIA_SIMPLE, seat=3))
    gm.add_player(game, _p(13, "Doc", Role.DOCTOR, seat=4))
    gm.add_player(game, _p(14, "Det", Role.DETECTIVE, seat=5))
    gm.add_player(game, _p(15, "Arm", Role.ARMORED, seat=6))
    gm.add_player(game, _p(16, "Snp", Role.SNIPER, seat=7))
    gm.add_player(game, _p(17, "Jrn", Role.JOURNALIST, seat=8))
    for i, uid in enumerate((18, 19, 20)):
        gm.add_player(game, _p(uid, f"C{i}", Role.CITIZEN, seat=9 + i))


class AccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_collection_active_matrix(self) -> None:
        gm = GameManager()
        game = _active_mozakere_night_game(gm)
        self.assertTrue(mozakere_night_force_finish_collection_active(game))
        self.assertTrue(no_host_parallel_night_collect_active(game))
        game.no_host_night_parallel_collect_active = False
        self.assertFalse(mozakere_night_force_finish_collection_active(game))
        game.no_host_night_parallel_collect_active = True
        game.no_host_night_entry_dispatched_night = 2
        self.assertFalse(mozakere_night_force_finish_collection_active(game))

    async def test_non_mozakere_never_active(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1, scenario_name="bazpors", max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bot_assistant_user_id = 900
        game.no_host_night_parallel_collect_active = True
        self.assertFalse(mozakere_night_force_finish_collection_active(game))

    async def test_only_helper_matches(self) -> None:
        gm = GameManager()
        _active_mozakere_night_game(gm)
        self.assertIsNotNone(find_mozakere_bot_assistant_game(900, gm))
        self.assertIsNone(find_mozakere_bot_assistant_game(42, gm))

    async def test_button_keyboard_has_single_finish_button(self) -> None:
        gm = GameManager()
        game = _active_mozakere_night_game(gm)
        kb = mozakere_force_finish_button_keyboard(game)
        self.assertIsNotNone(kb)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(labels, ["🌙 اتمام شب"])
        data = kb.inline_keyboard[0][0].callback_data
        self.assertTrue(data.startswith("mzh:"))

    async def test_closed_acts_guard(self) -> None:
        gm = GameManager()
        game = _active_mozakere_night_game(gm)
        self.assertFalse(mozakere_night_player_actions_closed(game))
        # Night-scoped latch: a REAL force-finish records the latched night;
        # latching the CURRENT night keeps the closed-acts contract intact
        # (legacy latches without a night identifier open again once parallel
        # collection is active — Room 91 mirror).
        game.mozakere_night_force_finished = True
        game.mozakere_night_force_finished_night = game.bazpors_narrator_night_count
        self.assertTrue(mozakere_night_player_actions_closed(game))
        for act in ("nms", "nmg", "nmc", "msk", "msc", "negp", "negc", "dkt", "dkc", "ndp", "ndc", "skt", "skc", "jrp", "jrc", "cic", "nwok"):
            self.assertTrue(mozakere_night_act_is_closed_for_game(game, act))


class NormalizeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()
        self.game = _active_mozakere_night_game(self.gm)
        _full_cast(self.gm, self.game)

    def test_menu_not_done_means_no_shot_no_negotiation(self) -> None:
        game = self.game
        game.no_host_mafia_night1_done = False
        game.mozakere_negotiation_tonight = True  # منو نیمه‌کاره
        dispositions = normalize_pending_mozakere_night_actions(game, self.gm)
        self.assertTrue(game.no_host_mafia_night1_done)
        self.assertTrue(game.no_host_mafia_shot_done)
        self.assertFalse(game.mozakere_negotiation_tonight)
        self.assertTrue(game.no_host_negotiator_pick_confirmed)
        self.assertIn("mafia", dispositions)
        for v in dispositions.values():
            self.assertEqual(v, "force_finished_no_action")

    def test_negotiate_chosen_but_unconfirmed_no_recruit(self) -> None:
        game = self.game
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "negotiate"
        game.mozakere_negotiation_tonight = True
        game.no_host_negotiator_flow_active = True
        game.no_host_negotiator_pending_tid = 18
        dispositions = normalize_pending_mozakere_night_actions(game, self.gm)
        self.assertTrue(game.no_host_negotiator_pick_confirmed)
        self.assertIsNone(game.no_host_negotiator_pending_tid)
        self.assertFalse(game.no_host_negotiator_flow_active)
        self.assertFalse(game.mozakere_negotiation_tonight)
        self.assertEqual(game.mozakere_mafia_recruit_ids, set())
        self.assertIn("negotiator", "".join(dispositions) + str(dispositions))

    def test_negotiate_confirmed_is_preserved(self) -> None:
        game = self.game
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "negotiate"
        game.mozakere_negotiation_tonight = True
        game.no_host_negotiator_pick_confirmed = True
        game.mozakere_negotiation_target_uid = 18
        normalize_pending_mozakere_night_actions(game, self.gm)
        self.assertTrue(game.mozakere_negotiation_tonight)
        self.assertEqual(game.mozakere_negotiation_target_uid, 18)

    def test_unconfirmed_shot_means_no_shot(self) -> None:
        game = self.game
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "shot"
        game.no_host_mafia_shot_flow_active = True
        game.no_host_mafia_shot_pending_uid = 20
        game.no_host_mafia_shot_awaiting_confirm = True
        dispositions = normalize_pending_mozakere_night_actions(game, self.gm)
        self.assertTrue(game.no_host_mafia_shot_done)
        self.assertIsNone(game.no_host_mafia_shot_pending_uid)
        self.assertFalse(game.no_host_mafia_shot_awaiting_confirm)

    def test_confirmed_shot_preserved(self) -> None:
        game = self.game
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "shot"
        game.no_host_mafia_shot_done = True
        normalize_pending_mozakere_night_actions(game, self.gm)
        self.assertTrue(game.no_host_mafia_shot_done)

    def test_doctor_incomplete_becomes_no_save(self) -> None:
        game = self.game
        game.no_host_doctor_flow_active = True
        game.no_host_doctor_pending_save_uids = [20]
        game.no_host_doctor_pending_none = False
        dispositions = normalize_pending_mozakere_night_actions(game, self.gm)
        self.assertEqual(doctor_night_state(game).get_save_uids(), [])
        self.assertTrue(game.no_host_doctor_pick_confirmed)
        self.assertEqual(game.no_host_doctor_pending_save_uids, [])
        self.assertIn("doctor", dispositions)

    def test_doctor_confirmed_preserved(self) -> None:
        game = self.game
        game.no_host_doctor_pick_confirmed = True
        dr = doctor_night_state(game)
        dr.set_save_target(20)
        normalize_pending_mozakere_night_actions(game, self.gm)
        self.assertEqual(doctor_night_state(game).get_save_uids(), [20])

    def test_detective_incomplete_becomes_no_inquiry(self) -> None:
        game = self.game
        game.no_host_detective_flow_active = True
        game.no_host_detective_pending_tid = 19
        dispositions = normalize_pending_mozakere_night_actions(game, self.gm)
        self.assertTrue(game.no_host_detective_pick_confirmed)
        self.assertIsNone(game.no_host_detective_pending_tid)
        self.assertIn("detective", dispositions)

    def test_sniper_incomplete_no_shot_ammo_preserved(self) -> None:
        game = self.game
        game.no_host_sniper_flow_active = True
        game.no_host_sniper_pending_target_uid = 20
        game.mozakere_sniper_shots_used = 1
        dispositions = normalize_pending_mozakere_night_actions(game, self.gm)
        self.assertTrue(game.no_host_sniper_pick_confirmed)
        self.assertIsNone(game.no_host_sniper_pending_target_uid)
        self.assertIsNone(sniper_night_state(game).night_target_uid)
        self.assertEqual(game.mozakere_sniper_shots_used, 1)
        self.assertIn("sniper", dispositions)

    def test_journalist_incomplete_forced_idle_or_pick(self) -> None:
        game = self.game
        game.no_host_journalist_flow_active = True
        game.no_host_journalist_pending_tid = 19
        dispositions = normalize_pending_mozakere_night_actions(game, self.gm)
        self.assertTrue(
            game.no_host_journalist_pick_confirmed
            or game.no_host_journalist_idle_confirmed
        )
        self.assertIsNone(game.no_host_journalist_pending_tid)
        self.assertIn("journalist", dispositions)

    def test_citizens_forced_acked(self) -> None:
        game = self.game
        dispositions = normalize_pending_mozakere_night_actions(game, self.gm)
        done = set(game.no_host_citizen_night_confirmed_uids)
        self.assertTrue({18, 19, 20}.issubset(done))
        self.assertIn("citizen", dispositions)

    def test_after_normalize_night_is_ready(self) -> None:
        game = self.game
        game.no_host_mafia_night1_done = False
        game.no_host_doctor_pending_save_uids = [20]
        game.no_host_sniper_pending_target_uid = 19
        normalize_pending_mozakere_night_actions(game, self.gm)
        self.assertTrue(all_no_host_parallel_night_ready(game))


class ForceFinishFlowTests(unittest.IsolatedAsyncioTestCase):
    async def _run_force_finish(self, game, gm) -> None:
        with patch(
            "bot.no_host_night_ready.finish_no_host_parallel_night_collect",
            new_callable=AsyncMock,
        ) as finish, patch(
            "bot.mozakere_force_finish_night.lock_mozakere_night_mirror_panels",
            new_callable=AsyncMock,
        ), patch(
            "bot.night_helper_reminder.cleanup_night_helper_reminder",
            new_callable=AsyncMock,
        ):
            await force_finish_mozakere_night(AsyncMock(), game, gm)
        return finish

    async def test_force_finish_sets_flag_normalizes_and_finishes(self) -> None:
        gm = GameManager()
        game = _active_mozakere_night_game(gm)
        _full_cast(gm, game)
        game.no_host_mafia_night1_done = False
        finish = await self._run_force_finish(game, gm)
        finish.assert_awaited_once()
        self.assertTrue(game.mozakere_night_force_finished)
        self.assertTrue(game.no_host_mafia_night1_done)
        self.assertTrue(mozakere_night_player_actions_closed(game))

    async def test_force_finish_is_idempotent_for_game_state(self) -> None:
        gm = GameManager()
        game = _active_mozakere_night_game(gm)
        _full_cast(gm, game)
        game.no_host_mafia_night1_done = False
        await self._run_force_finish(game, gm)
        first = game.no_host_citizen_night_confirmed_uids[:]
        await self._run_force_finish(game, gm)
        self.assertEqual(game.no_host_citizen_night_confirmed_uids, first)

    async def test_cancel_changes_nothing(self) -> None:
        gm = GameManager()
        game = _active_mozakere_night_game(gm)
        _full_cast(gm, game)
        game.no_host_mafia_night1_done = False
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.edit_text = AsyncMock()
        cb.answer = AsyncMock()
        await handle_mozakere_force_finish_callback(
            cb, AsyncMock(), game, gm, assistant_uid=900, act="no"
        )
        self.assertFalse(game.mozakere_night_force_finished)
        self.assertFalse(game.no_host_mafia_night1_done)
        cb.message.edit_text.assert_awaited_once()

    async def test_confirm_runs_force_finish(self) -> None:
        gm = GameManager()
        game = _active_mozakere_night_game(gm)
        _full_cast(gm, game)
        game.no_host_mafia_night1_done = False
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.edit_text = AsyncMock()
        cb.answer = AsyncMock()
        bot = AsyncMock()
        with patch(
            "bot.mozakere_force_finish_night.force_finish_mozakere_night",
            new_callable=AsyncMock,
        ) as ff:
            await handle_mozakere_force_finish_callback(
                cb, bot, game, gm, assistant_uid=900, act="yes"
            )
        ff.assert_awaited_once_with(bot, game, gm)

    async def test_helper_action_routes_button_and_confirm(self) -> None:
        gm = GameManager()
        game = _active_mozakere_night_game(gm)
        cb = MagicMock()
        cb.message = MagicMock()
        cb.answer = AsyncMock()
        with patch(
            "bot.mozakere_force_finish_night.handle_mozakere_force_finish_button",
            new_callable=AsyncMock,
        ) as btn:
            await handle_mozakere_helper_action(
                cb, AsyncMock(), game, gm,
                assistant_uid=900, actor_uid=900, act="go", kind="force_night_btn",
            )
        btn.assert_awaited_once()
        with patch(
            "bot.mozakere_force_finish_night.handle_mozakere_force_finish_callback",
            new_callable=AsyncMock,
        ) as confirm:
            await handle_mozakere_helper_action(
                cb, AsyncMock(), game, gm,
                assistant_uid=900, actor_uid=900, act="yes", kind="force_night",
            )
        confirm.assert_awaited_once()

    async def test_confirm_dialog_texts(self) -> None:
        from bot.mozakere_force_finish_night import (
            MOZAKERE_FORCE_FINISH_CONFIRM_TEXT,
        )

        self.assertEqual(
            MOZAKERE_FORCE_FINISH_CONFIRM_TEXT,
            "⚠️ آیا مطمئن هستید که می‌خواهید شب جاری را به پایان برسانید؟",
        )
        gm = GameManager()
        game = _active_mozakere_night_game(gm)
        cb = MagicMock()
        cb.message = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        bot.send_message = AsyncMock()
        from bot.mozakere_force_finish_night import (
            handle_mozakere_force_finish_button,
        )

        await handle_mozakere_force_finish_button(
            cb, bot, game, gm, assistant_uid=900
        )
        sent = bot.send_message.await_args
        self.assertEqual(sent.args[0] if sent.args else sent.kwargs.get("chat_id"), 900)
        self.assertIn("⚠️ آیا مطمئن هستید", sent.args[1] if sent.args else sent.kwargs.get("text"))
        kb = sent.kwargs.get("reply_markup")
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertEqual(labels, ["✅ بله، اتمام شب", "❌ انصراف"])




class ForceFinishUiSpecTests(unittest.IsolatedAsyncioTestCase):
    """متن تأیید، دکمهٔ سبز، تضمین تک‌اجرایی، حفظ زره و پوشش همهٔ تعداد نفرات."""

    def test_confirm_text_matches_spec_exactly(self):
        from bot.mozakere_force_finish_night import (
            MOZAKERE_FORCE_FINISH_CONFIRM_TEXT,
        )

        self.assertEqual(
            MOZAKERE_FORCE_FINISH_CONFIRM_TEXT,
            "⚠️ آیا مطمئن هستید که می‌خواهید شب جاری را به پایان برسانید؟",
        )

    def test_confirm_keyboard_yes_is_green_cancel_is_not(self):
        from bot.player_role_pick_common import inline_button_supports_style

        gm = GameManager()
        game = _active_mozakere_night_game(gm)
        from bot.mozakere_force_finish_night import _force_finish_confirm_keyboard

        kb = _force_finish_confirm_keyboard(game)
        yes = kb.inline_keyboard[0][0]
        cancel = kb.inline_keyboard[0][1]
        self.assertEqual(yes.text, "✅ بله، اتمام شب")
        self.assertEqual(cancel.text, "❌ انصراف")
        if inline_button_supports_style():
            self.assertEqual(yes.style, "success")
            self.assertNotEqual(getattr(cancel, "style", None), "success")

    async def test_duplicate_inflight_force_finish_ignored(self):
        gm = GameManager()
        game = _active_mozakere_night_game(gm)
        _full_cast(gm, game)
        from bot.mozakere_force_finish_night import (
            _FORCE_FINISH_INFLIGHT,
            force_finish_mozakere_night,
        )

        _FORCE_FINISH_INFLIGHT.add("MZF")
        try:
            with patch(
                "bot.mozakere_force_finish_night.normalize_pending_mozakere_night_actions"
            ) as norm, patch(
                "bot.mozakere_force_finish_night.lock_mozakere_night_mirror_panels",
                new=AsyncMock(),
            ), patch(
                "bot.no_host_night_ready.finish_no_host_parallel_night_collect",
                new=AsyncMock(),
            ):
                await force_finish_mozakere_night(AsyncMock(), game, gm)
            norm.assert_not_called()
            self.assertFalse(game.mozakere_night_force_finished)
        finally:
            _FORCE_FINISH_INFLIGHT.discard("MZF")

    async def test_stale_helper_confirm_after_close_is_rejected(self):
        gm = GameManager()
        game = _active_mozakere_night_game(gm)
        game.mozakere_night_force_finished = True
        game.no_host_night_parallel_collect_active = False
        cb = MagicMock()
        cb.message = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        await handle_mozakere_force_finish_callback(
            cb, bot, game, gm, assistant_uid=900, act="yes"
        )
        cb.answer.assert_awaited()
        args, kwargs = cb.answer.await_args
        self.assertEqual(args[0], "هنوز تو فاز شب نیستیم.")

    def test_force_finish_does_not_consume_unused_armor(self):
        gm = GameManager()
        game = _active_mozakere_night_game(gm)
        _full_cast(gm, game)
        armored = game.players[15]
        self.assertEqual(armored.role, Role.ARMORED)
        self.assertFalse(armored.mozakere_armored_armor_used)
        normalize_pending_mozakere_night_actions(game, gm)
        self.assertFalse(armored.mozakere_armored_armor_used)

    def test_ruintan_readiness_vacuous_for_mozakere(self):
        from bot.no_host_night_ready import _ruintan_ready

        gm = GameManager()
        game = _active_mozakere_night_game(gm)
        game.no_host_ruintan_night_confirmed = False
        normalize_pending_mozakere_night_actions(game, gm)
        # مذاکره صندلی رویین‌تن ندارد — آماده‌شدن بدون هیچ اجباری صادق است.
        self.assertTrue(_ruintan_ready(game))
        self.assertTrue(all_no_host_parallel_night_ready(game))

    def test_counter_and_normalize_across_all_supported_counts(self):
        from bot.game import mozakere_roles_for_count
        from bot.night_helper_reminder import (
            build_counted_night_reminder_text,
            night_reminder_outstanding_count,
        )

        for n in (10, 11, 12, 13, 15):
            gm = GameManager()
            game = _active_mozakere_night_game(gm)
            for i, role in enumerate(mozakere_roles_for_count(n)):
                gm.add_player(game, _p(500 + n * 100 + i, f"PL{n}_{i}", role, seat=i + 1))
            collection_active = mozakere_night_force_finish_collection_active(game)
            self.assertTrue(collection_active)
            count = night_reminder_outstanding_count(game)
            self.assertGreaterEqual(count, 4)
            text = build_counted_night_reminder_text(game, count)
            self.assertNotIn("PL", text)
            dispositions = normalize_pending_mozakere_night_actions(game, gm)
            self.assertEqual(night_reminder_outstanding_count(game), 0)
            self.assertTrue(all_no_host_parallel_night_ready(game))
            self.assertIn("doctor", dispositions)
            self.assertIn("mafia", dispositions)
            self.assertIn("citizen", dispositions)


if __name__ == "__main__":
    unittest.main()
