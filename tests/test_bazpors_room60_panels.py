"""Room 60 reported issues — additive contract tests (Bazpors only).

Covers the six UX fixes shipped together on top of the unified
green-confirm panels:

 1. §1  Interrogator NIGHT panel closes for player+observer after a
        confirmed no-action / opt-out (same message, kb=None).
 2. §2  Force-finish reminder is ONE message for the whole lifecycle:
        initial «🌙 قابلیت اتمام شب» → confirm on the SAME message_id →
        cancel restores the counted reminder → success deletes.
 3. §2  Live counter refresh must not overwrite an open confirmation.
 4. §2  Stale yes/cancel callbacks are rejected after the night closed.
 5. §3  Doctor panel is closed for player+observer when the NATO-blocked
        panel is already acked (sync with kb=None).
 6. §4  Day-decision panel: options blue, pending red, exactly one green
        «✅ تأیید انتخاب» from the initial render; commits only on confirm.
 7. §4  Confirm without pending selection rejected; toggling allowed.
 8. §6  Interrogation VOTE panel keeps the pending result in place and
        commits only via the green confirm (legacy VOTE_CONFIRM valid).
 9. §5  Defence OUTCOME panel (Bazpors): d1el sets a replaceable pending
        in place; green confirm reuses the existing confirm-elim commit.
10. §5  Other scenarios (russian_mafia) keep the previous outcome panel.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aiogram.types import InlineKeyboardMarkup

from bot.game import GameManager
from bot.models import Game, Player, Role
from bot.observer_delivery import PlayerMirrorCb


def _p(uid: int, seat: int, name: str, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


def _base_game(room_code: str = "55") -> tuple[Game, GameManager]:
    game = Game(
        room_code=room_code,
        host_id=9301,
        scenario_name="bazpors",
        players={
            1: _p(1, 1, "بازیکن یک", Role.CITIZEN),
            2: _p(2, 2, "بازیکن دو", Role.CITIZEN),
            3: _p(3, 3, "بازیکن سه", Role.CITIZEN),
            4: _p(4, 4, "بازیکن چهار", Role.CITIZEN),
        },
    )
    game.bazpors_narrator_night_count = 1
    game.bot_assistant_user_id = 9999
    game.bazpors_host_mode = "no_host"
    game.no_host_assistant_narrator_active = True
    return game, GameManager()


def _buttons_by_act(kb: InlineKeyboardMarkup, act: str) -> list[tuple]:
    out: list[tuple] = []
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data is None:
                continue
            cb = _unpack_any(btn.callback_data)
            if cb is not None and cb[0] == act:
                out.append((btn, cb))
    return out


def _unpack_any(callback_data: str):
    """Return (act, cb, cls) for any known CallbackData payload."""
    from bot.bazpors_narrator import BazporsNarrCb
    from bot.main import NoHostDay1DefenseCb

    for cls in (PlayerMirrorCb, NoHostDay1DefenseCb, BazporsNarrCb):
        try:
            cb = cls.unpack(callback_data)
        except Exception:
            continue
        return cb.act, cb, cls
    return None


class _StubCallback:
    def __init__(self, message_id: int | None = None) -> None:
        self.alerts: list[str] = []
        self.message = None

    async def answer(self, text: str = "", show_alert: bool = False) -> None:
        self.alerts.append(text)


class _RecordingMessage:
    def __init__(self, message_id: int, text: str = "") -> None:
        self.message_id = message_id
        self.html_text = text
        self.text = text


class _RecordingBot:
    """Records bot calls; fresh games have no mirror bindings by default."""

    def __init__(self) -> None:
        self.edits: list[dict] = []
        self.deletes: list[dict] = []
        self.sends: list[dict] = []

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)
        return True

    async def delete_message(self, **kwargs):
        self.deletes.append(kwargs)
        return True

    async def send_message(self, **kwargs):
        self.sends.append(kwargs)
        return _RecordingMessage(kwargs.get("chat_id") or 0)


# ---------------------------------------------------------------------------
# §1 — night skip / already-used commit closes the panel
# ---------------------------------------------------------------------------


class NightSkipCommitClosesPanelTests(unittest.IsolatedAsyncioTestCase):
    def _night_game(self) -> tuple[Game, GameManager]:
        game, gm = _base_game()
        game.players[1].role = Role.INTERROGATOR
        game.bazpors_narrator_step = "NIGHT_START"
        return game, gm

    async def test_skip_commit_finalizes_same_message_no_ack_panel(self) -> None:
        from bot.no_host_interrogator_night import (
            PHASE_SKIP_ACK,
            _after_interrog_commit,
        )

        game, gm = self._night_game()
        game.no_host_interrog_ui_phase = PHASE_SKIP_ACK
        with patch(
            "bot.no_host_interrogator_night.finalize_no_host_role_pick_message",
            new=AsyncMock(),
        ) as finalize, patch(
            "bot.no_host_interrogator_night.publish_no_host_night_ack_panel",
            new=AsyncMock(),
        ) as publish, patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new=AsyncMock(),
        ) as maybe_finish:
            await _after_interrog_commit(_RecordingBot(), game, gm, 1)
        finalize.assert_awaited_once()
        label = finalize.await_args.args[-1]
        self.assertEqual(label, "کسی را انتخاب نکردم")
        self.assertEqual(finalize.await_args.args[3], 1)
        publish.assert_not_awaited()
        maybe_finish.assert_awaited_once()

    async def test_once_done_commit_finalizes_same_message(self) -> None:
        from bot.no_host_interrogator_night import _after_interrog_commit

        game, gm = self._night_game()
        game.bazpors_interrog_once_done = True
        with patch(
            "bot.no_host_interrogator_night.finalize_no_host_role_pick_message",
            new=AsyncMock(),
        ) as finalize, patch(
            "bot.no_host_interrogator_night.publish_no_host_night_ack_panel",
            new=AsyncMock(),
        ) as publish, patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new=AsyncMock(),
        ):
            await _after_interrog_commit(_RecordingBot(), game, gm, 1)
        finalize.assert_awaited_once()
        label = finalize.await_args.args[-1]
        self.assertEqual(label, "بازپرسی قبلاً انجام شده است")
        publish.assert_not_awaited()

    def test_finalize_body_format_is_player_and_observer_safe(self) -> None:
        from bot.no_host_night_common import finalize_no_host_role_pick_message

        # The finalize helper edits the SAME message (update_mirror_prompt_pair
        # inside) with no keyboard; the label flows into the body.
        import inspect

        src = inspect.getsource(finalize_no_host_role_pick_message)
        self.assertIn("update_mirror_prompt_pair", src)
        self.assertIn("None,", src)


# ---------------------------------------------------------------------------
# §2 — single-message force-finish lifecycle
# ---------------------------------------------------------------------------


class _ForceFinishFixture(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.game, self.gm = _base_game()
        self.game.night_helper_reminder_chat_id = 8888
        self.game.night_helper_reminder_message_id = 555
        self.game.night_helper_reminder_last_count = 3
        self.bot = _RecordingBot()
        self.kb = MagicMock()

    def _predicates(self, count: int, ready: bool = False):
        import bot.night_helper_reminder as nhr

        cm_open = patch.object(
            nhr, "night_reminder_collect_active", return_value=True
        )
        cm_ready = patch.object(
            nhr, "night_reminder_all_ready", return_value=ready
        )
        cm_count = patch.object(
            nhr, "night_reminder_outstanding_count", return_value=count
        )
        cm_kb = patch.object(nhr, "_force_finish_keyboard_for", return_value=self.kb)
        return cm_open, cm_ready, cm_count, cm_kb

    def _collection_active(self):
        return patch(
            "bot.bazpors_force_finish_night.bazpors_night_force_finish_collection_active",
            return_value=True,
        )


class ForceFinishLifecycleTests(_ForceFinishFixture):
    async def test_button_edits_same_bound_message_no_second_message(self) -> None:
        from bot.bazpors_force_finish_night import handle_bazpors_force_finish_button

        with self._collection_active():
            cb = _StubCallback()
            await handle_bazpors_force_finish_button(
                cb, self.bot, self.game, self.gm, assistant_uid=8888
            )
        self.assertFalse(self.bot.sends)  # never a second message
        self.assertEqual(len(self.bot.edits), 1)
        edit = self.bot.edits[0]
        self.assertEqual(edit["chat_id"], 8888)
        self.assertEqual(edit["message_id"], 555)
        self.assertIn("⚠️ تأیید اتمام شب", edit["text"])
        self.assertIn("بله، اتمام شب", edit["reply_markup"].inline_keyboard[0][0].text)
        self.assertTrue(self.game.night_helper_reminder_force_confirm_open)

    async def test_button_twice_does_not_reedit(self) -> None:
        from bot.bazpors_force_finish_night import handle_bazpors_force_finish_button

        with self._collection_active():
            await handle_bazpors_force_finish_button(
                _StubCallback(), self.bot, self.game, self.gm, assistant_uid=8888
            )
            await handle_bazpors_force_finish_button(
                _StubCallback(), self.bot, self.game, self.gm, assistant_uid=8888
            )
        self.assertEqual(len(self.bot.edits), 1)
        self.assertFalse(self.bot.sends)

    async def test_cancel_restores_counted_reminder_on_same_message(self) -> None:
        from bot.bazpors_force_finish_night import handle_bazpors_force_finish_callback

        self.game.night_helper_reminder_force_confirm_open = True
        o, r, c, k = self._predicates(count=3)
        with self._collection_active(), o, r, c, k:
            cb = _StubCallback()
            cb.message = _RecordingMessage(555)
            await handle_bazpors_force_finish_callback(
                cb, self.bot, self.game, self.gm,
                assistant_uid=8888, act="no",
            )
        self.assertEqual(len(self.bot.edits), 1)
        edit = self.bot.edits[0]
        self.assertEqual(edit["message_id"], 555)
        self.assertIn("قابلیت اتمام شب", edit["text"])
        self.assertIn("3", edit["text"].replace("۳", "3"))
        # the «اتمام شب» force-finish button is restored on the same message
        self.assertIs(edit["reply_markup"], self.kb)
        self.assertFalse(self.game.night_helper_reminder_force_confirm_open)
        self.assertEqual(self.game.night_helper_reminder_last_count, 3)

    async def test_confirm_open_blocks_counter_overwrite_but_cleanup_runs(self) -> None:
        from bot.night_helper_reminder import refresh_night_helper_reminder

        self.game.night_helper_reminder_force_confirm_open = True
        # Counter changed while confirm is open → must NOT edit the text…
        o, r, c, k = self._predicates(count=5)
        with o, r, c, k:
            await refresh_night_helper_reminder(self.bot, self.game)
        self.assertEqual(self.bot.edits, [])
        # …but count 0 still deletes (stale reminder cleanup branch).
        o, r, c, k = self._predicates(count=0)
        with o, r, c, k:
            await refresh_night_helper_reminder(self.bot, self.game)
        self.assertEqual(len(self.bot.deletes), 1)
        self.assertIsNone(self.game.night_helper_reminder_message_id)

    async def test_yes_has_no_intermediate_edit_and_triggers_force_finish(self) -> None:
        from bot.bazpors_force_finish_night import (
            force_finish_bazpors_night,
            handle_bazpors_force_finish_callback,
        )

        cb = _StubCallback()
        cb.message = _RecordingMessage(555)
        self.game.night_helper_reminder_force_confirm_open = True
        with patch(
            "bot.bazpors_force_finish_night.force_finish_bazpors_night",
            new=AsyncMock(),
        ) as ff, self._collection_active():
            await handle_bazpors_force_finish_callback(
                cb, self.bot, self.game, self.gm,
                assistant_uid=8888, act="yes",
            )
        ff.assert_awaited_once()
        # No text edit and no fallback send on the bound reminder path.
        self.assertEqual(self.bot.edits, [])
        self.assertFalse(self.bot.sends)
        self.assertFalse(self.game.night_helper_reminder_force_confirm_open)

    async def test_stale_yes_after_finished_is_rejected(self) -> None:
        from bot.bazpors_force_finish_night import handle_bazpors_force_finish_callback

        self.game.bazpors_night_force_finished = True
        cb = _StubCallback()
        cb.message = _RecordingMessage(555)
        await handle_bazpors_force_finish_callback(
            cb, self.bot, self.game, self.gm, assistant_uid=8888, act="yes"
        )
        self.assertIn("فاز شب به پایان رسیده است.", cb.alerts[0])
        self.assertEqual(self.bot.edits, [])


# ---------------------------------------------------------------------------
# §3 — doctor panel closed when NATO-blocked panel already acked
# ---------------------------------------------------------------------------


class DoctorNatoBlockedSyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_nato_blocked_panel_sent_with_dko_only_keyboard(self) -> None:
        from bot.bazpors_narrator import NIGHT_START

        game, gm = _base_game()
        game.players[1].role = Role.DOCTOR
        game.bazpors_nato_action_registered = True
        game.bazpors_narrator_step = NIGHT_START
        with patch(
            "bot.no_host_doctor_night.publish_mirror_prompt_pair",
            new=AsyncMock(),
        ) as publish, patch(
            "bot.no_host_doctor_night.sync_role_mirror_panel", new=AsyncMock()
        ):
            from bot.no_host_doctor_night import (
                apply_no_host_doctor_nato_blocked_panel,
            )

            await apply_no_host_doctor_nato_blocked_panel(
                _RecordingBot(), game, gm
            )
        publish.assert_awaited_once()
        kb = publish.await_args.args[5]
        oks = _buttons_by_act(kb, "dko")
        self.assertEqual(len(oks), 1)
        # OK buttons stay blue by contract (only selection confirms are green)
        self.assertEqual(oks[0][0].style, "primary")
        self.assertTrue(game.no_host_doctor_nato_blocked_panel)

    async def test_dko_ack_closes_panel_for_player_and_observer(self) -> None:
        from bot.bazpors_narrator import NIGHT_START

        game, gm = _base_game()
        game.players[1].role = Role.DOCTOR
        game.bazpors_nato_action_registered = True
        game.bazpors_narrator_step = NIGHT_START
        game.no_host_doctor_flow_active = True
        game.no_host_doctor_nato_blocked_panel = True
        game.no_host_doctor_dm_signature = "1:doc:nato_blocked"
        with patch(
            "bot.no_host_doctor_night.sync_role_mirror_panel",
            new=AsyncMock(),
        ) as sync, patch(
            "bot.no_host_doctor_night.no_host_parallel_night_collect_active",
            return_value=True,
        ), patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new=AsyncMock(),
        ):
            from bot.no_host_doctor_night import dispatch_no_host_doctor_night

            cb = _StubCallback()
            await dispatch_no_host_doctor_night(
                cb, _RecordingBot(), game, gm,
                doc_uid=1, actor_uid=1, act="dko", tid=0,
            )
        self.assertIn("ثبت شد.", cb.alerts[0])
        self.assertTrue(game.no_host_doctor_pick_confirmed)
        sync.assert_awaited_once()
        # kb=None → the SAME panel copies (player + observer) are closed
        self.assertIsNone(sync.await_args.args[-1])

    async def test_nato_blocked_rejects_non_ok_buttons(self) -> None:
        from bot.no_host_doctor_night import dispatch_no_host_doctor_night

        game, gm = _base_game()
        game.players[1].role = Role.DOCTOR
        game.no_host_doctor_nato_blocked_panel = True
        game.no_host_doctor_flow_active = True
        game.no_host_doctor_pick_confirmed = False
        cb = _StubCallback()
        await dispatch_no_host_doctor_night(
            cb, _RecordingBot(), game, gm,
            doc_uid=1, actor_uid=1, act="dkt", tid=2,
        )
        self.assertIn("امکان انتخاب ندارید", cb.alerts[0])


# ---------------------------------------------------------------------------
# §4 — day-decision panel: pending + green confirm
# ---------------------------------------------------------------------------


class DayDecisionPanelTests(unittest.TestCase):
    def _day_game(self) -> tuple[Game, GameManager]:
        game, gm = _base_game()
        game.players[1].role = Role.INTERROGATOR
        return game, gm

    def test_initial_render_has_exactly_one_green_confirm(self) -> None:
        from bot.no_host_interrog_day import _interrogator_keyboard

        game, _gm = self._day_game()
        kb = _interrogator_keyboard(game, 1)
        confirms = _buttons_by_act(kb, "ihck")
        self.assertEqual(len(confirms), 1)
        btn, cb = confirms[0]
        self.assertEqual(btn.style, "success")
        self.assertIn("تأیید انتخاب", btn.text)
        self.assertEqual((cb[1].as_uid), 1)

    def test_options_blue_without_pending_and_red_with_pending(self) -> None:
        from bot.no_host_interrog_day import _interrogator_keyboard

        game, _gm = self._day_game()
        kb = _interrogator_keyboard(game, 1)
        for act in ("ihco", "ihdi"):
            for btn, _cb in _buttons_by_act(kb, act):
                self.assertEqual(btn.style, "primary")

        game.no_host_interrog_day_pending_decision = "continue"
        kb = _interrogator_keyboard(game, 1)
        self.assertEqual(_buttons_by_act(kb, "ihco")[0][0].style, "danger")
        self.assertEqual(_buttons_by_act(kb, "ihdi")[0][0].style, "primary")

        game.no_host_interrog_day_pending_decision = "dissolve"
        kb = _interrogator_keyboard(game, 1)
        self.assertEqual(_buttons_by_act(kb, "ihdi")[0][0].style, "danger")
        self.assertEqual(_buttons_by_act(kb, "ihco")[0][0].style, "primary")

    def test_pending_does_not_set_decision(self) -> None:
        game, _gm = self._day_game()
        game.no_host_interrog_day_pending_decision = "dissolve"
        self.assertIsNone(game.no_host_interrog_day_decision)


class DayDecisionDispatchTests(unittest.IsolatedAsyncioTestCase):
    def _day_session(self) -> tuple[Game, GameManager]:
        game, gm = _base_game()
        game.players[1].role = Role.INTERROGATOR
        from bot.no_host_interrog_day import NO_HOST_INTERROG_DAY

        game.bazpors_narrator_step = NO_HOST_INTERROG_DAY
        game.no_host_interrog_day_phase = "session"
        return game, gm

    async def test_press_sets_pending_only_and_resyncs_with_confirm(self) -> None:
        from bot.no_host_interrog_day import dispatch_no_host_interrog_day_player

        game, gm = self._day_session()
        with patch(
            "bot.no_host_interrog_day.update_mirror_prompt_pair",
            new=AsyncMock(),
        ) as upd, patch(
            "bot.no_host_interrog_day._resolve_session_if_ready",
            new=AsyncMock(),
        ):
            cb = _StubCallback()
            await dispatch_no_host_interrog_day_player(
                cb, _RecordingBot(), game, gm,
                as_uid=1, actor_uid=1, act="ihco",
            )
        self.assertEqual(game.no_host_interrog_day_pending_decision, "continue")
        self.assertIsNone(game.no_host_interrog_day_decision)
        self.assertIn("انتخاب شد؛ تأیید کنید.", cb.alerts[0])
        upd.assert_awaited_once()
        kb = upd.await_args.args[4]
        self.assertEqual(len(_buttons_by_act(kb, "ihck")), 1)
        self.assertEqual(_buttons_by_act(kb, "ihck")[0][0].style, "success")

    async def test_press_again_toggles_off(self) -> None:
        from bot.no_host_interrog_day import dispatch_no_host_interrog_day_player

        game, gm = self._day_session()
        with patch(
            "bot.no_host_interrog_day.update_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_interrog_day._resolve_session_if_ready",
            new=AsyncMock(),
        ):
            cb = _StubCallback()
            await dispatch_no_host_interrog_day_player(
                cb, _RecordingBot(), game, gm,
                as_uid=1, actor_uid=1, act="ihco",
            )
            cb2 = _StubCallback()
            await dispatch_no_host_interrog_day_player(
                cb2, _RecordingBot(), game, gm,
                as_uid=1, actor_uid=1, act="ihco",
            )
        self.assertIsNone(game.no_host_interrog_day_pending_decision)
        self.assertEqual(cb2.alerts[0], "انتخاب لغو شد.")

    async def test_confirm_without_pending_rejected(self) -> None:
        from bot.no_host_interrog_day import dispatch_no_host_interrog_day_player

        game, gm = self._day_session()
        cb = _StubCallback()
        await dispatch_no_host_interrog_day_player(
            cb, _RecordingBot(), game, gm,
            as_uid=1, actor_uid=1, act="ihck",
        )
        self.assertIn("ابتدا یکی از دو گزینه", cb.alerts[0])
        self.assertIsNone(game.no_host_interrog_day_decision)

    async def test_confirm_commits_decision_and_closes_panel(self) -> None:
        from bot.no_host_interrog_day import dispatch_no_host_interrog_day_player

        game, gm = self._day_session()
        game.no_host_interrog_day_pending_decision = "dissolve"
        with patch(
            "bot.no_host_interrog_day.update_mirror_prompt_pair",
            new=AsyncMock(),
        ) as upd, patch(
            "bot.no_host_interrog_day._resolve_session_if_ready",
            new=AsyncMock(),
        ) as resolve:
            cb = _StubCallback()
            await dispatch_no_host_interrog_day_player(
                cb, _RecordingBot(), game, gm,
                as_uid=1, actor_uid=1, act="ihck",
            )
        self.assertEqual(game.no_host_interrog_day_decision, "dissolve")
        self.assertIn("ثبت شد: انحلال بازپرسی.", cb.alerts[0])
        upd.assert_awaited_once()
        self.assertIsNone(upd.await_args.args[4])  # kb=None on the same message
        resolve.assert_awaited_once()

    async def test_session_ready_ignores_pending_before_confirm(self) -> None:
        from bot.no_host_interrog_day import _session_ready

        game, _gm = self._day_session()
        game.no_host_interrog_day_ok_uids.append(2)
        game.no_host_interrog_day_ok_uids.append(3)
        game.no_host_interrog_day_ok_uids.append(4)
        game.no_host_interrog_day_pending_decision = "continue"
        # decision (no_host_interrog_day_decision) not set → not ready
        self.assertFalse(_session_ready(game))
        game.no_host_interrog_day_decision = "continue"
        self.assertTrue(_session_ready(game))


# ---------------------------------------------------------------------------
# §6 — interrogation VOTE panel keeps pending in place + green confirm
# ---------------------------------------------------------------------------


class InterrogVotePanelTests(unittest.IsolatedAsyncioTestCase):
    def _vote_game(self) -> tuple[Game, GameManager]:
        game, gm = _base_game()
        from bot.roles.night_state import interrogator_night_state

        state = interrogator_night_state(game)
        state.first_uid = 2
        state.second_uid = 3
        from bot.no_host_interrog_day import NO_HOST_INTERROG_DAY

        game.bazpors_narrator_step = NO_HOST_INTERROG_DAY
        game.no_host_interrog_day_phase = "vote"
        return game, gm

    def test_initial_vote_panel_has_exactly_one_green_confirm(self) -> None:
        from bot.no_host_interrog_day import build_no_host_interrog_day_assistant_panel

        game, gm = self._vote_game()
        body, kb = build_no_host_interrog_day_assistant_panel(game, gm)
        self.assertIn("تأیید", body or "")
        confirms = _buttons_by_act(kb, "ih_vok")
        self.assertEqual(len(confirms), 1)
        btn, _cb = confirms[0]
        self.assertEqual(btn.style, "success")
        self.assertIn("تأیید انتخاب", btn.text)
        for btn, _cb in _buttons_by_act(kb, "ih_vtie"):
            self.assertEqual(btn.style, "primary")

    def test_pending_tie_red_and_pending_elim_red(self) -> None:
        from bot.no_host_interrog_day import build_no_host_interrog_day_assistant_panel

        game, gm = self._vote_game()
        game.no_host_interrog_day_pending_vote = "tie"
        _body, kb = build_no_host_interrog_day_assistant_panel(game, gm)
        self.assertEqual(_buttons_by_act(kb, "ih_vtie")[0][0].style, "danger")
        self.assertEqual(_buttons_by_act(kb, "ih_velim")[0][0].style, "primary")

        game.no_host_interrog_day_pending_vote = 3
        _body, kb = build_no_host_interrog_day_assistant_panel(game, gm)
        reds = {
            cb[1].tid
            for btn, cb in _buttons_by_act(kb, "ih_velim")
            if btn.style == "danger"
        }
        self.assertEqual(reds, {3})
        self.assertEqual(_buttons_by_act(kb, "ih_vtie")[0][0].style, "primary")

    def test_press_keeps_vote_phase_and_commits_only_on_ok(self) -> None:
        from bot.no_host_interrog_day import NO_HOST_INTERROG_DAY
        from bot.no_host_interrog_day import process_no_host_interrog_day_narrator_cb

        game, gm = self._vote_game()
        # pending set, stays in VOTE phase (no separate confirm jump)
        self.assertIsNone(
            process_no_host_interrog_day_narrator_cb(game, gm, "ih_velim", 3)
        )
        self.assertEqual(game.no_host_interrog_day_pending_vote, 3)
        self.assertEqual(game.no_host_interrog_day_phase, "vote")
        # pressing another option replaces the pending
        self.assertIsNone(
            process_no_host_interrog_day_narrator_cb(game, gm, "ih_vtie", 0)
        )
        self.assertEqual(game.no_host_interrog_day_pending_vote, "tie")
        self.assertIsNone(
            process_no_host_interrog_day_narrator_cb(game, gm, "ih_velim", 2)
        )
        self.assertEqual(game.no_host_interrog_day_pending_vote, 2)
        # ok with a pending selection is valid in the VOTE phase too
        self.assertIsNone(
            process_no_host_interrog_day_narrator_cb(game, gm, "ih_vok", 0)
        )
        self.assertEqual(game.bazpors_narrator_step, NO_HOST_INTERROG_DAY)

    def test_ok_without_pending_rejected(self) -> None:
        from bot.no_host_interrog_day import process_no_host_interrog_day_narrator_cb

        game, gm = self._vote_game()
        self.assertEqual(
            process_no_host_interrog_day_narrator_cb(game, gm, "ih_vok", 0),
            "خطا.",
        )

    def test_legacy_vote_confirm_phase_still_valid(self) -> None:
        from bot.no_host_interrog_day import build_no_host_interrog_day_assistant_panel
        from bot.no_host_interrog_day import process_no_host_interrog_day_narrator_cb

        game, gm = self._vote_game()
        game.no_host_interrog_day_phase = "vote_confirm"
        game.no_host_interrog_day_pending_vote = 2
        # legacy restored panels keep ih_vok valid
        self.assertIsNone(
            process_no_host_interrog_day_narrator_cb(game, gm, "ih_vok", 0)
        )
        # legacy panel renders its green confirm too
        _body, kb = build_no_host_interrog_day_assistant_panel(game, gm)
        confirms = _buttons_by_act(kb, "ih_vok")
        self.assertEqual(len(confirms), 1)
        self.assertEqual(confirms[0][0].style, "success")
        # back clears pending and returns to VOTE phase
        self.assertIsNone(
            process_no_host_interrog_day_narrator_cb(game, gm, "ih_vback", 0)
        )
        self.assertIsNone(game.no_host_interrog_day_pending_vote)
        self.assertEqual(game.no_host_interrog_day_phase, "vote")

    async def test_result_applies_only_after_green_confirm(self) -> None:
        from bot.no_host_interrog_day import (
            apply_no_host_interrog_day_narrator_async,
        )

        game, gm = self._vote_game()
        game.no_host_interrog_day_pending_vote = 3
        with patch(
            "bot.no_host_interrog_day._apply_vote_result", new=AsyncMock()
        ) as apply_result:
            await apply_no_host_interrog_day_narrator_async(
                _RecordingBot(), game, gm, "ih_vok"
            )
            apply_result.assert_awaited_once()
            apply_result.reset_mock()
            await apply_no_host_interrog_day_narrator_async(
                _RecordingBot(), game, gm, "ih_velim"
            )
            await apply_no_host_interrog_day_narrator_async(
                _RecordingBot(), game, gm, "ih_vtie"
            )
            apply_result.assert_not_awaited()


# ---------------------------------------------------------------------------
# §5 — defence outcome panel: pending + green confirm (Bazpors)
# ---------------------------------------------------------------------------


class DefenseOutcomePanelTests(unittest.TestCase):
    def _out_game(self, scenario: str = "bazpors") -> tuple[Game, GameManager]:
        game, gm = _base_game()
        game.scenario_name = scenario
        from bot.bazpors_narrator import set_day_vote_defender_uids

        set_day_vote_defender_uids(game, {2, 3})
        return game, gm

    def test_bazpors_initial_panel_blue_with_single_green_confirm(self) -> None:
        from bot.main import _no_host_day1_defense_outcome_keyboard

        game, _gm = self._out_game()
        kb = _no_host_day1_defense_outcome_keyboard(game, 9999, mirror=False)
        for btn, _cb in _buttons_by_act(kb, "d1el"):
            self.assertEqual(btn.style, "primary")
        rotates = _buttons_by_act(kb, "no_exit")
        self.assertEqual(len(rotates), 1)
        self.assertEqual(rotates[0][0].style, "primary")
        confirms = _buttons_by_act(kb, "elim_yes")
        self.assertEqual(len(confirms), 1)
        btn, _cb = confirms[0]
        self.assertEqual(btn.style, "success")
        self.assertIn("تأیید انتخاب", btn.text)

    def test_bazpors_pending_elim_is_red_on_same_panel(self) -> None:
        from bot.main import _no_host_day1_defense_outcome_keyboard

        game, _gm = self._out_game()
        game.no_host_day1_pending_elim_uid = 3
        kb = _no_host_day1_defense_outcome_keyboard(game, 9999, mirror=False)
        styles = {
            cb[1].tid: btn.style
            for btn, cb in _buttons_by_act(kb, "d1el")
        }
        self.assertEqual(styles, {2: "primary", 3: "danger"})
        self.assertEqual(_buttons_by_act(kb, "elim_yes")[0][0].style, "success")

    def test_russian_outcome_panel_unchanged(self) -> None:
        from bot.main import _no_host_day1_defense_outcome_keyboard

        game, _gm = self._out_game("russian_mafia")
        kb = _no_host_day1_defense_outcome_keyboard(game, 9999, mirror=False)
        self.assertEqual(_buttons_by_act(kb, "elim_yes"), [])
        for btn, _cb in _buttons_by_act(kb, "d1el"):
            self.assertEqual(btn.style, "primary")


class DefenseOutcomeDispatchTests(unittest.IsolatedAsyncioTestCase):
    def _outcome_game(self) -> tuple[Game, GameManager]:
        game, gm = _base_game()
        from bot.bazpors_narrator import set_day_vote_defender_uids

        set_day_vote_defender_uids(game, {2, 3})
        game.no_host_day1_defense_phase = "outcome"
        game.observer_user_id = None
        return game, gm

    async def test_d1el_outcome_sets_pending_without_leaving_panel(self) -> None:
        from bot.main import _no_host_day1_defense_pick_elim

        game, gm = self._outcome_game()
        with patch(
            "bot.main.send_no_host_day1_defense_outcome_panel",
            new=AsyncMock(),
        ) as resend:
            cb = _StubCallback()
            await _no_host_day1_defense_pick_elim(
                cb, _RecordingBot(), game, 9999, 9999, 3
            )
        self.assertEqual(game.no_host_day1_pending_elim_uid, 3)
        self.assertEqual(game.no_host_day1_defense_phase, "outcome")
        resend.assert_awaited_once()
        self.assertIn("انتخاب شد؛ تأیید کنید.", cb.alerts[0])
        # pressing the same target again toggles off
        cb2 = _StubCallback()
        with patch(
            "bot.main.send_no_host_day1_defense_outcome_panel",
            new=AsyncMock(),
        ):
            await _no_host_day1_defense_pick_elim(
                cb2, _RecordingBot(), game, 9999, 9999, 3
            )
        self.assertIsNone(game.no_host_day1_pending_elim_uid)
        self.assertEqual(cb2.alerts[0], "انتخاب لغو شد.")

    async def test_d1el_invalid_target_rejected(self) -> None:
        from bot.main import _no_host_day1_defense_pick_elim

        game, gm = self._outcome_game()
        cb = _StubCallback()
        await _no_host_day1_defense_pick_elim(
            cb, _RecordingBot(), game, 9999, 9999, 4
        )
        self.assertIn("فقط بازیکنان ثبت‌شده", cb.alerts[0])
        self.assertIsNone(game.no_host_day1_pending_elim_uid)

    async def test_green_confirm_elim_commits_via_existing_path(self) -> None:
        from bot.main import _no_host_day1_defense_confirm_elim_yes

        game, gm = self._outcome_game()
        game.no_host_day1_pending_elim_uid = 2

        def _kill(game_obj, mgr, uid, elim_source):
            game_obj.players[uid].is_alive = False

        cb = _StubCallback()
        cb.message = _RecordingMessage(777, "<br/>")
        with patch(
            "bot.main.eliminate_player_from_game", side_effect=_kill
        ) as elim, patch(
            "bot.russian_mafia_flow.finish_russian_confirmed_elimination",
            new=AsyncMock(return_value=False),
        ), patch(
            "bot.bazpors_narrator.hunter_chain_confirm_alert_text",
            return_value=None,
        ), patch(
            "bot.main.flush_elimination_notifications", new=AsyncMock()
        ), patch(
            "bot.main.close_mirror_prompt_keyboards", new=AsyncMock()
        ) as close, patch(
            "bot.main.broadcast_to_alive_players", new=AsyncMock()
        ), patch(
            "bot.no_host_mafia_win.no_host_maybe_end_on_faction_win",
            new=AsyncMock(return_value=False),
        ), patch(
            "bot.no_host_handoff.offer_handoff_day1_after_elim",
            return_value=False,
        ), patch(
            "bot.main.no_host_day1_after_elim_enter_night"
        ) as enter_night, patch(
            "bot.main.on_no_host_entered_night1", new=AsyncMock()
        ):
            await _no_host_day1_defense_confirm_elim_yes(
                cb, _RecordingBot(), game, 9999, 9999
            )
        elim.assert_called_once()
        self.assertEqual(elim.call_args.args[2], 2)
        self.assertIsNone(game.no_host_day1_pending_elim_uid)
        self.assertFalse(game.players[2].is_alive)
        # outcome mirror key closed
        closed_keys = [c.args[2] for c in close.await_args_list]
        self.assertTrue(any("day1_defense_outcome" in k for k in closed_keys))
        enter_night.assert_called()

    async def test_green_confirm_without_pending_rejected(self) -> None:
        from bot.main import _no_host_day1_defense_confirm_elim_yes

        game, gm = self._outcome_game()
        cb = _StubCallback()
        await _no_host_day1_defense_confirm_elim_yes(
            cb, _RecordingBot(), game, 9999, 9999
        )
        # Room 97: the unified outcome panel asks for a selection first.
        self.assertIn("انتخاب کنید", cb.alerts[0])

    async def test_stale_confirm_wrong_phase_rejected(self) -> None:
        from bot.main import _no_host_day1_defense_confirm_elim_yes

        game, gm = self._outcome_game()
        game.no_host_day1_defense_phase = "pick"
        game.no_host_day1_pending_elim_uid = 2
        cb = _StubCallback()
        await _no_host_day1_defense_confirm_elim_yes(
            cb, _RecordingBot(), game, 9999, 9999
        )
        self.assertIn("این مرحله دیگر فعال نیست.", cb.alerts[0])


# ---------------------------------------------------------------------------
# Models — persisted lifecycle fields
# ---------------------------------------------------------------------------


class PersistedFieldTests(unittest.TestCase):
    def test_new_lifecycle_fields_exist_and_default_clean(self) -> None:
        game, _gm = _base_game()
        self.assertIsNone(game.no_host_interrog_day_pending_decision)
        self.assertFalse(game.night_helper_reminder_force_confirm_open)

    def test_clear_reminder_state_resets_confirm_flag(self) -> None:
        from bot.night_helper_reminder import clear_night_helper_reminder_state

        game, _gm = _base_game()
        game.night_helper_reminder_force_confirm_open = True
        game.night_helper_reminder_message_id = 42
        clear_night_helper_reminder_state(game)
        self.assertFalse(game.night_helper_reminder_force_confirm_open)
        self.assertIsNone(game.night_helper_reminder_message_id)


if __name__ == "__main__":
    unittest.main()
