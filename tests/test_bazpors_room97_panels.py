"""Room 97 reported issues — regression tests (Bazpors only).

Covers the Room-97 fixes:

1. §1  Defence OUTCOME panel: «خروجی نداشتیم. شب کن» is a tentative
       selectable option (red on the SAME panel) — it no longer advances
       the game; the commit happens only through the green «✅ تأیید
       انتخاب» (d1ey/elim_yes). Selection state is mutually exclusive
       with the elimination pending picks.
2. §2  Hunter panel: «⭕ به کسی وصل نمی‌شوم» is a tentative pick too —
       red highlight on the same panel and commit only via «hnc»
       (previously it finalized instantly). Other scenarios keep the
       legacy instant behaviour.
3. §3  Sniper panel: the «انتخابی ندارم» option is highlighted red while
       it is the tentative pick (previously it stayed blue).
4. §4  Doctor panel: the same red highlight for «انتخابی ندارم».
5. §5  Interrog-day session-result panel: selection clicks keep the same
       message (in-place edit); after the commit the interactive panel is
       removed and a short non-interactive acknowledgement is sent; a
       duplicate «ih_vok» cannot apply the result twice.
6. §6  Day transition: the status inquiry cannot be applied twice
       (racing duplicate «tinq_ok»), the end-of-day vote / defence panel
       is never sent while the table-inquiry step is pending, and duplicate
       day-start events triggered by duplicate confirm callbacks are
       prevented by the committed-vote latch.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, patch

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.game import GameManager
from bot.models import Game, Player, Role


def _p(uid: int, seat: int, name: str, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


def _base_game(room_code: str = "97") -> tuple[Game, GameManager]:
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


_BRAND = "97"


class _StubCallback:
    """Minimal CallbackQuery stub — records confirmation popups."""

    def __init__(self) -> None:
        self.alerts: list[tuple[str, bool]] = []
        self.message: Message | None = None

    async def answer(self, text: str = "", show_alert: bool = False) -> None:
        self.alerts.append((text, show_alert))


class _RecordingMessage:
    def __init__(self, chat_id: int, message_id: int, text: str = "") -> None:
        self.chat = type("Chat", (), {"id": chat_id})()
        self.message_id = message_id
        self.html_text = text
        self.text = text


class _RecordingBot:
    """Records edit/delete/send calls; nothing must be mocked silently."""

    def __init__(self) -> None:
        self.edits: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []
        self.sends: list[dict[str, Any]] = []

    async def edit_message_text(self, **kwargs):
        self.edits.append(kwargs)
        return True

    async def delete_message(self, chat_id, message_id, **kwargs):
        self.deletes.append({"chat_id": chat_id, "message_id": message_id})
        return True

    async def send_message(self, **kwargs):
        self.sends.append(kwargs)
        return _RecordingMessage(
            kwargs.get("chat_id", 0), kwargs.get("reply_to_message_id", 891)
        )


def _buttons_by_act(kb: InlineKeyboardMarkup, act: str) -> list[Any]:
    out = []
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data is None:
                continue
            cb = _unpack_any(btn.callback_data)
            if cb is not None and cb[0] == act:
                out.append((btn, cb[1]))
    return out


def _unpack_any(callback_data: str):
    from bot.bazpors_narrator import BazporsNarrCb
    from bot.main import NoHostDay1DefenseCb
    from bot.observer_delivery import PlayerMirrorCb

    for cls in (PlayerMirrorCb, NoHostDay1DefenseCb, BazporsNarrCb):
        try:
            cb = cls.unpack(callback_data)
        except Exception:
            continue
        return cb.act, cb
    return None


# ---------------------------------------------------------------------------
# §2/§3/§4 — shared pick keyboards: «none» option must be highlightable
# ---------------------------------------------------------------------------


class PickKeyboardNoneHighlightTests(unittest.TestCase):
    def test_bazpors_none_row_blue_by_default(self) -> None:
        from bot.no_host_role_pick_common import build_pick_keyboard

        game, _gm = _base_game()
        players = [game.players[1], game.players[2]]
        kb = build_pick_keyboard(
            game,
            1,
            pick_act="skt",
            players=players,
            none_act="skn",
            none_text="⭕ انتخابی ندارم",
            selected_uids=[],
            none_selected=False,
        )
        nones = _buttons_by_act(kb, "skn")
        self.assertEqual(len(nones), 1)
        self.assertEqual(nones[0][0].style, "primary")

    def test_bazpors_none_row_red_when_pending_none(self) -> None:
        from bot.no_host_role_pick_common import build_pick_keyboard

        game, _gm = _base_game()
        players = [game.players[1], game.players[2]]
        kb = build_pick_keyboard(
            game,
            1,
            pick_act="skt",
            players=players,
            none_act="skn",
            none_text="⭕ انتخابی ندارم",
            selected_uids=[],
            none_selected=True,
        )
        nones = _buttons_by_act(kb, "skn")
        self.assertEqual(len(nones), 1)
        self.assertEqual(nones[0][0].style, "danger")
        # No other button stays highlighted.
        for btn, _cb in _buttons_by_act(kb, "skt"):
            self.assertEqual(btn.style, "primary")

    def test_bazpors_none_row_highlight_clears_when_switching_to_player(
        self,
    ) -> None:
        from bot.no_host_role_pick_common import build_pick_keyboard

        game, _gm = _base_game()
        players = [game.players[1], game.players[2]]
        kb = build_pick_keyboard(
            game,
            1,
            pick_act="skt",
            players=players,
            none_act="skn",
            none_text="⭕ انتخابی ندارم",
            selected_uids=[2],
            none_selected=False,
        )
        self.assertEqual(_buttons_by_act(kb, "skn")[0][0].style, "primary")
        picks = {cb.tid: btn.style for btn, cb in _buttons_by_act(kb, "skt")}
        self.assertEqual(picks.get(2), "danger")

    def test_sniper_none_highlights_red_on_real_panel(self) -> None:
        from bot.no_host_sniper_night import _pick_keyboard

        game, gm = _base_game()
        game.no_host_sniper_pending_none = True
        kb = _pick_keyboard(game, 1, gm)
        nones = _buttons_by_act(kb, "skn")
        self.assertEqual(len(nones), 1)
        self.assertEqual(nones[0][0].style, "danger")
        confirms = [btn for btn, _cb in _buttons_by_act(kb, "skc")]
        self.assertEqual(len(confirms), 1)
        self.assertEqual(confirms[0].style, "success")

    def test_sniper_none_blue_without_pending(self) -> None:
        from bot.no_host_sniper_night import _pick_keyboard

        game, gm = _base_game()
        kb = _pick_keyboard(game, 1, gm)
        self.assertEqual(_buttons_by_act(kb, "skn")[0][0].style, "primary")

    def test_doctor_none_highlights_red_on_real_panel(self) -> None:
        from bot.no_host_doctor_night import _pick_keyboard

        game, gm = _base_game()
        game.no_host_doctor_pending_none = True
        kb = _pick_keyboard(game, 1, gm)
        nones = _buttons_by_act(kb, "dkn")
        self.assertEqual(len(nones), 1)
        self.assertEqual(nones[0][0].style, "danger")
        confirms = [btn for btn, _cb in _buttons_by_act(kb, "dkc")]
        self.assertEqual(len(confirms), 1)
        self.assertEqual(confirms[0].style, "success")

    def test_doctor_none_blue_without_pending(self) -> None:
        from bot.no_host_doctor_night import _pick_keyboard

        game, gm = _base_game()
        kb = _pick_keyboard(game, 1, gm)
        self.assertEqual(_buttons_by_act(kb, "dkn")[0][0].style, "primary")


# ---------------------------------------------------------------------------
# §2 — Hunter: tentative no-connection + green confirm
# ---------------------------------------------------------------------------


class HunterNoNoneConfirmTests(unittest.IsolatedAsyncioTestCase):
    def _fresh(self, scenario: str = "bazpors") -> tuple[Game, GameManager]:
        game, gm = _base_game()
        game.scenario_name = scenario
        game.players[1].role = Role.HUNTER
        game.no_host_night1_hunter_flow_active = True
        game.observer_user_id = None
        return game, gm

    def test_initial_panel_none_blue_with_green_confirm(self) -> None:
        from bot.no_host_night1 import _hunter_pick_keyboard

        game, gm = self._fresh()
        kb = _hunter_pick_keyboard(game, 1, gm)
        nones = [btn for btn, _cb in _buttons_by_act(kb, "hns")]
        self.assertEqual(len(nones), 1)
        self.assertEqual(nones[0].style, "primary")
        confirms = [btn for btn, _cb in _buttons_by_act(kb, "hnc")]
        self.assertEqual(len(confirms), 1)
        self.assertEqual(confirms[0].style, "success")

    def test_pending_none_is_red(self) -> None:
        from bot.no_host_night1 import _hunter_pick_keyboard

        game, gm = self._fresh()
        game.no_host_hunter_pending_none = True
        kb = _hunter_pick_keyboard(game, 1, gm)
        self.assertEqual(_buttons_by_act(kb, "hns")[0][0].style, "danger")
        for btn, _cb in _buttons_by_act(kb, "hnp"):
            self.assertEqual(btn.style, "primary")

    async def _dispatch(self, game, gm, act: str, tid: int = 0):
        from bot.no_host_night1 import dispatch_no_host_hunter_night1

        cb = _StubCallback()
        with (
            patch(
                "bot.no_host_night1.sync_role_mirror_panel", new=AsyncMock()
            ),
        ):
            await dispatch_no_host_hunter_night1(
                cb, _RecordingBot(), game, gm, hunter_uid=1, actor_uid=1,
                act=act, tid=tid,
            )
        return cb

    async def test_hns_becomes_tentative_and_does_not_finalize(self) -> None:
        game, gm = self._fresh()
        with patch(
            "bot.no_host_night1._finalize_hunter_night1", new=AsyncMock()
        ) as finalize:
            cb = await self._dispatch(game, gm, "hns")
        finalize.assert_not_awaited()
        self.assertTrue(game.no_host_hunter_pending_none)
        self.assertIsNone(game.no_host_hunter_pending_pick_uid)
        self.assertIn(("انتخاب شد؛ تأیید کنید.", False), cb.alerts)
        # Flow still active until the confirmation.
        self.assertTrue(game.no_host_night1_hunter_flow_active)
        self.assertFalse(game.no_host_night1_hunter_done)

    async def test_hns_again_toggles_off(self) -> None:
        game, gm = self._fresh()
        game.no_host_hunter_pending_none = True
        with patch(
            "bot.no_host_night1._finalize_hunter_night1", new=AsyncMock()
        ) as finalize:
            cb = await self._dispatch(game, gm, "hns")
        finalize.assert_not_awaited()
        self.assertFalse(game.no_host_hunter_pending_none)
        self.assertEqual(cb.alerts[0][0], "انتخاب لغو شد.")

    async def test_hnp_clears_pending_none(self) -> None:
        game, gm = self._fresh()
        game.no_host_hunter_pending_none = True
        with patch(
            "bot.no_host_night1._finalize_hunter_night1", new=AsyncMock()
        ):
            await self._dispatch(game, gm, "hnp", tid=2)
        self.assertFalse(game.no_host_hunter_pending_none)
        self.assertEqual(game.no_host_hunter_pending_pick_uid, 2)

    async def test_hnc_commits_pending_none(self) -> None:
        game, gm = self._fresh()
        game.no_host_hunter_pending_none = True
        game.no_host_hunter_pending_pick_uid = None
        with patch(
            "bot.no_host_night1._finalize_hunter_night1", new=AsyncMock()
        ) as finalize:
            await self._dispatch(game, gm, "hnc")
        finalize.assert_awaited_once()
        self.assertIsNone(finalize.await_args.args[3])
        self.assertFalse(game.no_host_hunter_pending_none)

    async def test_hnc_without_any_selection_rejected(self) -> None:
        game, gm = self._fresh()
        with patch(
            "bot.no_host_night1._finalize_hunter_night1", new=AsyncMock()
        ) as finalize:
            cb = await self._dispatch(game, gm, "hnc")
        finalize.assert_not_awaited()
        self.assertTrue(cb.alerts and cb.alerts[-1][1])

    async def test_non_bazpors_hns_keeps_legacy_instant_finalize(self) -> None:
        game, gm = self._fresh("mozakere")
        with patch(
            "bot.no_host_night1._finalize_hunter_night1", new=AsyncMock()
        ) as finalize:
            await self._dispatch(game, gm, "hns")
        finalize.assert_awaited_once()
        self.assertIsNone(finalize.await_args.args[3])
        self.assertFalse(getattr(game, "no_host_hunter_pending_none", True))


# ---------------------------------------------------------------------------
# §1 — Defence outcome: tentative «خروجی نداشتیم. شب کن» + green confirm
# ---------------------------------------------------------------------------


class DefenseOutcomeNoElimTests(unittest.IsolatedAsyncioTestCase):
    def _outcome_game(self) -> tuple[Game, GameManager]:
        game, gm = _base_game()
        from bot.bazpors_narrator import set_day_vote_defender_uids

        set_day_vote_defender_uids(game, {2, 3})
        game.no_host_day1_defense_phase = "outcome"
        game.observer_user_id = None
        return game, gm

    def test_no_exit_button_red_when_pending_no_elim(self) -> None:
        from bot.main import _no_host_day1_defense_outcome_keyboard

        game, _gm = self._outcome_game()
        game.no_host_day1_pending_no_elim = True
        kb = _no_host_day1_defense_outcome_keyboard(game, 9999, mirror=False)
        no_exits = _buttons_by_act(kb, "no_exit")
        self.assertEqual(len(no_exits), 1)
        self.assertEqual(no_exits[0][0].style, "danger")
        for btn, _cb in _buttons_by_act(kb, "d1el"):
            self.assertEqual(btn.style, "primary")
        confirms = _buttons_by_act(kb, "elim_yes")
        self.assertEqual(len(confirms), 1)
        self.assertEqual(confirms[0][0].style, "success")

    async def test_no_exit_press_is_tentative_only(self) -> None:
        from bot.main import _no_host_day1_defense_outcome_no_exit_pick

        game, gm = self._outcome_game()
        with patch(
            "bot.main.send_no_host_day1_defense_outcome_panel", new=AsyncMock()
        ) as refresh, patch(
            "bot.main.on_no_host_entered_night1", new=AsyncMock()
        ), patch(
            "bot.main.no_host_day1_no_exit_enter_night"
        ) as enter_night:
            cb = _StubCallback()
            await _no_host_day1_defense_outcome_no_exit_pick(
                cb, _RecordingBot(), game, 9999, 9999
            )
        refresh.assert_awaited_once()
        enter_night.assert_not_called()
        self.assertTrue(game.no_host_day1_pending_no_elim)
        self.assertIsNone(game.no_host_day1_pending_elim_uid)
        self.assertEqual(game.no_host_day1_defense_phase, "outcome")
        self.assertIn(("انتخاب شد؛ تأیید کنید.", False), cb.alerts)

    async def test_no_exit_press_again_toggles_off(self) -> None:
        from bot.main import _no_host_day1_defense_outcome_no_exit_pick

        game, gm = self._outcome_game()
        game.no_host_day1_pending_no_elim = True
        with patch(
            "bot.main.send_no_host_day1_defense_outcome_panel", new=AsyncMock()
        ):
            cb = _StubCallback()
            await _no_host_day1_defense_outcome_no_exit_pick(
                cb, _RecordingBot(), game, 9999, 9999
            )
        self.assertFalse(game.no_host_day1_pending_no_elim)
        self.assertEqual(cb.alerts[0][0], "انتخاب لغو شد.")

    async def test_no_exit_and_elim_are_mutually_exclusive(self) -> None:
        from bot.main import _no_host_day1_defense_outcome_no_exit_pick

        game, gm = self._outcome_game()
        game.no_host_day1_pending_elim_uid = 2
        with patch(
            "bot.main.send_no_host_day1_defense_outcome_panel", new=AsyncMock()
        ):
            cb = _StubCallback()
            await _no_host_day1_defense_outcome_no_exit_pick(
                cb, _RecordingBot(), game, 9999, 9999
            )
        # Selecting «خروجی نداشتیم» removes any pending elimination pick.
        self.assertTrue(game.no_host_day1_pending_no_elim)
        self.assertIsNone(game.no_host_day1_pending_elim_uid)

    async def test_elim_press_clears_pending_no_elim(self) -> None:
        from bot.main import _no_host_day1_defense_pick_elim

        game, gm = self._outcome_game()
        game.no_host_day1_pending_no_elim = True
        with patch(
            "bot.main.send_no_host_day1_defense_outcome_panel", new=AsyncMock()
        ):
            cb = _StubCallback()
            await _no_host_day1_defense_pick_elim(
                cb, _RecordingBot(), game, 9999, 9999, 3
            )
        self.assertFalse(game.no_host_day1_pending_no_elim)
        self.assertEqual(game.no_host_day1_pending_elim_uid, 3)

    async def test_green_confirm_commits_no_elim_and_starts_night(
        self,
    ) -> None:
        from bot.main import _no_host_day1_defense_confirm_elim_yes

        game, gm = self._outcome_game()
        game.no_host_day1_pending_no_elim = True
        cb = _StubCallback()
        with patch(
            "bot.main.broadcast_to_alive_players", new=AsyncMock()
        ), patch(
            "bot.main.no_host_day1_no_exit_enter_night"
        ) as enter_night, patch(
            "bot.main.on_no_host_entered_night1", new=AsyncMock()
        ), patch(
            "bot.main.eliminate_player_from_game"
        ) as elim, patch(
            "bot.russian_mafia_flow.apply_russian_day_result",
            new=AsyncMock(return_value=False),
        ), patch(
            "bot.main.build_no_host_day1_defense_no_exit_broadcast_html",
            return_value="broadcast",
        ):
            await _no_host_day1_defense_confirm_elim_yes(
                cb, _RecordingBot(), game, 9999, 9999
            )
        elim.assert_not_called()
        enter_night.assert_called_once()
        self.assertFalse(game.no_host_day1_pending_no_elim)
        self.assertFalse(getattr(game, "no_host_day1_pending_no_elim", False))

    async def test_green_confirm_with_no_selection_does_not_advance(
        self,
    ) -> None:
        from bot.main import _no_host_day1_defense_confirm_elim_yes

        game, gm = self._outcome_game()
        cb = _StubCallback()
        with patch(
            "bot.main.no_host_day1_no_exit_enter_night"
        ) as enter_night, patch(
            "bot.main.on_no_host_entered_night1", new=AsyncMock()
        ), patch(
            "bot.main.eliminate_player_from_game"
        ) as elim, patch(
            "bot.main.send_no_host_day1_defense_outcome_panel", new=AsyncMock()
        ):
            await _no_host_day1_defense_confirm_elim_yes(
                cb, _RecordingBot(), game, 9999, 9999
            )
        elim.assert_not_called()
        enter_night.assert_not_called()
        self.assertTrue(cb.alerts and cb.alerts[-1][1])
        self.assertEqual(game.no_host_day1_defense_phase, "outcome")


# ---------------------------------------------------------------------------
# §5/§6 — interrog-day session-result panel + status-inquiry idempotency
# ---------------------------------------------------------------------------


class InterrogVoteIdempotencyTests(unittest.TestCase):
    def _vote_game(self) -> tuple[Game, GameManager]:
        from bot.no_host_interrog_day import IH_PHASE_VOTE, enter_no_host_interrog_day_step

        game, gm = _base_game()
        game.bazpors_interrog_first_uid = 2
        game.bazpors_interrog_second_uid = 3
        enter_no_host_interrog_day_step(game)
        game.no_host_interrog_day_phase = IH_PHASE_VOTE
        game.no_host_interrog_day_pending_vote = "tie"
        return game, gm

    def test_ih_vok_accepts_once(self) -> None:
        from bot.no_host_interrog_day import (
            process_no_host_interrog_day_narrator_cb,
        )

        game, gm = self._vote_game()
        self.assertIsNone(
            process_no_host_interrog_day_narrator_cb(game, gm, "ih_vok", 0)
        )
        # A duplicate / stale second press must NOT pass again.
        self.assertEqual(
            process_no_host_interrog_day_narrator_cb(game, gm, "ih_vok", 0),
            "نامعتبر.",
        )

    def test_vote_panel_initial_render_matches_contract(self) -> None:
        from bot.no_host_interrog_day import (
            IH_PHASE_VOTE,
            build_no_host_interrog_day_assistant_panel,
            enter_no_host_interrog_day_step,
        )

        game, gm = _base_game()
        enter_no_host_interrog_day_step(game)
        game.no_host_interrog_day_phase = IH_PHASE_VOTE
        body, kb = build_no_host_interrog_day_assistant_panel(game, gm)
        ties = [btn for btn, _cb in _buttons_by_act(kb, "ih_vtie")]
        self.assertEqual(len(ties), 1)
        self.assertEqual(ties[0].style, "primary")
        ok_btns = [btn for btn, _cb in _buttons_by_act(kb, "ih_vok")]
        self.assertEqual(len(ok_btns), 1)
        self.assertEqual(ok_btns[0].style, "success")

    def test_pending_tie_red_on_same_panel(self) -> None:
        from bot.no_host_interrog_day import (
            IH_PHASE_VOTE,
            build_no_host_interrog_day_assistant_panel,
            enter_no_host_interrog_day_step,
        )

        game, gm = _base_game()
        game.bazpors_interrog_first_uid = 2
        game.bazpors_interrog_second_uid = 3
        enter_no_host_interrog_day_step(game)
        game.no_host_interrog_day_phase = IH_PHASE_VOTE
        game.no_host_interrog_day_pending_vote = "tie"
        _body, kb = build_no_host_interrog_day_assistant_panel(game, gm)
        self.assertEqual(_buttons_by_act(kb, "ih_vtie")[0][0].style, "danger")
        pool_elim = [
            btn
            for btn, _cb in _buttons_by_act(kb, "ih_velim")
        ]
        self.assertTrue(pool_elim)
        for btn in pool_elim:
            self.assertEqual(btn.style, "primary")

    def test_new_committed_latch_field_persisted_default_clean(self) -> None:
        game, _gm = _base_game()
        self.assertFalse(game.no_host_interrog_day_vote_committed)


class TableInquiryIdempotencyTests(unittest.TestCase):
    def test_double_apply_cannot_run_day_start_twice(self) -> None:
        import asyncio

        from bot.no_host_table_inquiry import (
            apply_no_host_table_inquiry_confirm,
            enter_no_host_table_inquiry_before_day,
        )

        async def _run() -> None:
            game, gm = _base_game()
            enter_no_host_table_inquiry_before_day(game)
            game.no_host_table_inquiry_pending = "no"
            game.no_host_table_inquiry_phase = "confirm"
            with patch(
                "bot.no_host_table_inquiry.broadcast_to_alive_players",
                new=AsyncMock(),
            ), patch(
                "bot.no_host_handoff.maybe_prompt_handoff_before_day_start",
                new=AsyncMock(return_value=False),
            ), patch(
                "bot.no_host_table_inquiry.no_host_finish_day_start_after_table_inquiry",
                new=AsyncMock(return_value=None),
            ) as finish:
                await apply_no_host_table_inquiry_confirm(
                    None, game, gm
                )
                # A racing duplicate delivery — must be a no-op.
                await apply_no_host_table_inquiry_confirm(
                    None, game, gm
                )
            finish.assert_awaited_once()
            self.assertTrue(game.no_host_table_inquiry_resolved_for_day)

        asyncio.new_event_loop().run_until_complete(_run())


class DayVotePromptOrderingTests(unittest.IsolatedAsyncioTestCase):
    async def test_defence_panel_not_sent_while_table_inquiry_pending(
        self,
    ) -> None:
        from bot.no_host_day_vote import send_no_host_day_vote_prompt
        from bot.no_host_table_inquiry import (
            enter_no_host_table_inquiry_before_day,
        )

        game, gm = _base_game()
        enter_no_host_table_inquiry_before_day(game)
        game.no_host_intro_night_started = True
        with patch(
            "bot.main.send_no_host_day1_defense_pick_panel", new=AsyncMock()
        ) as panel, patch(
            "bot.bazpors_narrator.push_host_step", new=AsyncMock()
        ):
            await send_no_host_day_vote_prompt(None, game)
        panel.assert_not_awaited()
        self.assertFalse(game.no_host_day1_vote_prompt_sent)

    async def test_day_vote_prompt_sent_after_inquiry_resolved(self) -> None:
        from bot.no_host_day_vote import send_no_host_day_vote_prompt

        game, gm = _base_game()
        game.no_host_intro_night_started = True
        game.bazpors_narrator_step = "day_discuss"
        with patch(
            "bot.main.send_no_host_day1_defense_pick_panel", new=AsyncMock()
        ) as panel:
            await send_no_host_day_vote_prompt(None, game)
        panel.assert_awaited_once()
        self.assertTrue(game.no_host_day1_vote_prompt_sent)

    async def test_duplicate_prompt_does_not_send_twice(self) -> None:
        from bot.no_host_day_vote import send_no_host_day_vote_prompt

        game, gm = _base_game()
        game.no_host_intro_night_started = True
        game.bazpors_narrator_step = "day_discuss"
        with patch(
            "bot.main.send_no_host_day1_defense_pick_panel", new=AsyncMock()
        ) as panel:
            await send_no_host_day_vote_prompt(None, game)
            await send_no_host_day_vote_prompt(None, game)
        panel.assert_awaited_once()


class InterrogPanelInPlaceTests(unittest.IsolatedAsyncioTestCase):
    def _vote_game(self) -> tuple[Game, GameManager]:
        from bot.no_host_interrog_day import IH_PHASE_VOTE, enter_no_host_interrog_day_step

        game, gm = _base_game()
        enter_no_host_interrog_day_step(game)
        game.no_host_interrog_day_phase = IH_PHASE_VOTE
        game.no_host_interrog_day_pending_vote = "tie"
        return game, gm

    async def test_selection_click_edits_same_message_no_resend(self) -> None:
        from bot.bazpors_narrator import (
            _remember_assistant_panel_ref,
            _deliver_host_narrator_panel,
        )

        game, gm = self._vote_game()
        body, kb = (None, None)
        from bot.bazpors_narrator import build_host_message_and_keyboard

        body, kb = build_host_message_and_keyboard(game, gm)
        _remember_assistant_panel_ref(game, 9999, 777)
        bot = _RecordingBot()
        clicked = _RecordingMessage(9999, 777)
        delivered = await _deliver_host_narrator_panel(
            bot, game, gm, body, kb, edit_in_place=clicked
        )
        self.assertTrue(delivered)
        self.assertEqual(len(bot.deletes), 0)
        self.assertEqual(len(bot.sends), 0)
        self.assertEqual(len(bot.edits), 1)
        self.assertEqual(bot.edits[0]["chat_id"], 9999)
        self.assertEqual(bot.edits[0]["message_id"], 777)
        self.assertEqual(game.bazpors_assistant_panel_message_id, 777)

    async def test_other_no_host_panels_keep_delete_and_resend(
        self,
    ) -> None:
        from bot.no_host_table_inquiry import (
            enter_no_host_table_inquiry_before_day,
        )
        from bot.bazpors_narrator import (
            _deliver_host_narrator_panel,
            _remember_assistant_panel_ref,
        )

        game, gm = _base_game()
        enter_no_host_table_inquiry_before_day(game)
        body, kb = "panel", None
        from bot.bazpors_narrator import build_host_message_and_keyboard

        body, kb = build_host_message_and_keyboard(game, gm)
        _remember_assistant_panel_ref(game, 9999, 777)
        bot = _RecordingBot()
        delivered = await _deliver_host_narrator_panel(
            bot, game, gm, body, kb,
            edit_in_place=_RecordingMessage(9999, 777),
        )
        self.assertTrue(delivered)
        # Legacy convention for every other panel: previous copy removed and
        # a fresh message sent at the end of the chat (the clicked message
        # and the tracked ref are the same message, so the ids repeat).
        self.assertEqual(
            {(d["chat_id"], d["message_id"]) for d in bot.deletes},
            {(9999, 777)},
        )
        self.assertEqual(len(bot.sends), 1)
        self.assertEqual(len(bot.edits), 0)
        self.assertNotEqual(game.bazpors_assistant_panel_message_id, 777)


class InterrogAckTests(unittest.TestCase):
    def test_ack_text_tie(self) -> None:
        from bot.bazpors_narrator import build_no_host_interrog_result_ack_text

        game, gm = _base_game()
        text = build_no_host_interrog_result_ack_text(game, gm, "tie")
        self.assertIn("☑ نتیجه جلسه بازپرسی ثبت شد", text)
        self.assertIn("رأی‌ها مساوی شد", text)

    def test_ack_text_elim(self) -> None:
        from bot.bazpors_narrator import build_no_host_interrog_result_ack_text

        game, gm = _base_game()
        text = build_no_host_interrog_result_ack_text(game, gm, 2)
        self.assertIn("☑ نتیجه جلسه بازپرسی ثبت شد", text)
        self.assertIn("بازیکن", text)
        self.assertIn("خارج شد", text)

    def test_ack_text_has_no_markup(self) -> None:
        from bot.bazpors_narrator import build_no_host_interrog_result_ack_text

        game, gm = _base_game()
        text = build_no_host_interrog_result_ack_text(game, gm, None)
        self.assertNotIn("<b>", text)

    def test_close_panel_removes_tracked_copy(self) -> None:
        import asyncio

        from bot.bazpors_narrator import (
            _remember_assistant_panel_ref,
            close_no_host_interrog_vote_panel_after_commit,
        )
        from bot.bazpors_narrator import clear_observer_narrator_mirror_ref

        async def _run() -> None:
            game, _gm = _base_game()
            _remember_assistant_panel_ref(game, 9999, 777)
            clear_observer_narrator_mirror_ref(game)
            game.bazpors_observer_narrator_mirror_chat_id = 9999
            game.bazpors_observer_narrator_mirror_message_id = 778
            bot = _RecordingBot()
            msg = _RecordingMessage(9999, 777)
            await close_no_host_interrog_vote_panel_after_commit(
                bot, game, msg  # type: ignore[arg-type]
            )
            deleted = {(d["chat_id"], d["message_id"]) for d in bot.deletes}
            self.assertIn((9999, 777), deleted)
            self.assertIn((9999, 778), deleted)
            self.assertIsNone(game.bazpors_assistant_panel_chat_id)

        asyncio.new_event_loop().run_until_complete(_run())

    def test_close_panel_keeps_newer_ref_and_removes_stale_copy(self) -> None:
        import asyncio

        from bot.bazpors_narrator import (
            _remember_assistant_panel_ref,
            close_no_host_interrog_vote_panel_after_commit,
        )

        async def _run() -> None:
            game, _gm = _base_game()
            # The day-start path already re-pointed the ref at a newer panel.
            _remember_assistant_panel_ref(game, 9999, 900)
            bot = _RecordingBot()
            await close_no_host_interrog_vote_panel_after_commit(
                bot, game, _RecordingMessage(9999, 777)  # type: ignore[arg-type]
            )
            deleted = {(d["chat_id"], d["message_id"]) for d in bot.deletes}
            self.assertEqual(deleted, {(9999, 777)})
            # The newer panel ref stays untouched.
            self.assertEqual(game.bazpors_assistant_panel_message_id, 900)

        asyncio.new_event_loop().run_until_complete(_run())


class InterrogPostProcessAckTests(unittest.IsolatedAsyncioTestCase):
    """The ih_vok dispatch must close the panel and send the non-interactive
    ack once the room moved on (workflow advanced OR game ended)."""

    def _vote_game(self) -> tuple[Game, GameManager]:
        from bot.no_host_interrog_day import IH_PHASE_VOTE, enter_no_host_interrog_day_step

        game, gm = _base_game()
        enter_no_host_interrog_day_step(game)
        game.no_host_interrog_day_phase = IH_PHASE_VOTE
        game.no_host_interrog_day_pending_vote = "tie"
        return game, gm

    async def test_ended_room_closes_panel_and_sends_ack(self) -> None:
        import types

        from bot.bazpors_narrator import _remember_assistant_panel_ref

        game, gm = self._vote_game()
        _remember_assistant_panel_ref(game, 9999, 777)
        manager_stub = types.SimpleNamespace(get_game=lambda code: None)
        cb = _StubCallback()
        cb.message = _RecordingMessage(9999, 777)
        with patch(
            "bot.handlers.narrator_cb.manager", manager_stub
        ), patch(
            "bot.handlers.narrator_cb.safe_callback_answer", new=AsyncMock()
        ), patch(
            "bot.handlers.narrator_cb.safe_send_message", new=AsyncMock()
        ) as send, patch(
            "bot.handlers.narrator_cb.flush_elimination_notifications",
            new=AsyncMock(),
        ), patch(
            "bot.bazpors_narrator.close_no_host_interrog_vote_panel_after_commit",
            new=AsyncMock(),
        ) as close, patch(
            "bot.no_host_interrog_day.apply_no_host_interrog_day_narrator_async",
            new=AsyncMock(),
        ):
            from bot.handlers.narrator_cb import _post_process_assistant_panel

            await _post_process_assistant_panel(
                bot=_RecordingBot(),
                callback=cb,  # type: ignore[arg-type]
                game=game,
                act="ih_vok",
            )
        close.assert_awaited_once()
        send.assert_awaited_once()
        self.assertIn(
            "☑ نتیجه جلسه بازپرسی ثبت شد",
            send.await_args.args[2],
        )

    async def test_moved_workflow_closes_stale_copy_only(self) -> None:
        import types
        from unittest.mock import patch

        from bot.bazpors_narrator import _remember_assistant_panel_ref

        game, gm = self._vote_game()
        _remember_assistant_panel_ref(game, 9999, 777)
        # The day-start path already re-pointed the ref to a newer panel and
        # moved the narrator step past the interrog-day workflow.
        _remember_assistant_panel_ref(game, 9999, 900)
        game.bazpors_narrator_step = "day_discuss"
        stub_manager = types.SimpleNamespace(get_game=lambda code: game)
        cb = _StubCallback()
        cb.message = _RecordingMessage(9999, 777)
        bot = _RecordingBot()
        with patch(
            "bot.handlers.narrator_cb.manager", stub_manager
        ), patch(
            "bot.handlers.narrator_cb.safe_callback_answer", new=AsyncMock()
        ), patch(
            "bot.handlers.narrator_cb.safe_send_message", new=AsyncMock()
        ) as send, patch(
            "bot.handlers.narrator_cb.flush_elimination_notifications",
            new=AsyncMock(),
        ), patch(
            "bot.no_host_interrog_day.apply_no_host_interrog_day_narrator_async",
            new=AsyncMock(),
        ):
            from bot.handlers.narrator_cb import _post_process_assistant_panel

            await _post_process_assistant_panel(
                bot=bot,
                callback=cb,  # type: ignore[arg-type]
                game=game,
                act="ih_vok",
            )
        send.assert_awaited_once()
        self.assertIn(
            "☑ نتیجه جلسه بازپرسی ثبت شد",
            send.await_args.args[2],
        )
        # Only the stale clicked copy is removed; the newer panel ref stays.
        deleted = {(d["chat_id"], d["message_id"]) for d in bot.deletes}
        self.assertEqual(deleted, {(9999, 777)})
        self.assertEqual(game.bazpors_assistant_panel_message_id, 900)


if __name__ == "__main__":
    unittest.main()
