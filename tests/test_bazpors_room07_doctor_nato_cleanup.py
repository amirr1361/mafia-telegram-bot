"""Room 7 — Bazpors stale Doctor panel after NATO (focused tests).

Root cause: the NATO-blocked replacement was delivered with
``fresh_observer_copy=True``; ``update_mirror_prompt_pair`` popped the
tracked observer ref WITHOUT closing its live keyboard, so the Observer
kept both the original target-selection panel and the new OK-only panel.

Fix: ``_disable_superseded_doctor_panels`` runs BEFORE the replacement is
delivered (via ``apply_no_host_doctor_nato_blocked_panel`` →
``_send_doctor_panel``), while the tracked refs still exist: delete the
superseded copy, fall back to keyboard-only removal on Telegram errors;
the real player's copy keeps its in-place edit. Stale callbacks stay
rejected by the existing dispatch guards.
"""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.models import Game, Player, Role

ASSISTANT = 108214166
OBSERVER = 8620239861
SYN_DOC = -920006
REAL_DOC = 4242


def _p(uid: int, seat: int, name: str, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


def _game(doc_uid: int) -> Game:
    game = Game(
        room_code="07",
        host_id=ASSISTANT,
        scenario_name="bazpors",
        players={
            doc_uid: _p(doc_uid, 2, "doctor", Role.DOCTOR),
            1: _p(1, 1, "one", Role.CITIZEN),
            2: _p(2, 3, "two", Role.CITIZEN),
        },
    )
    game.bazpors_narrator_night_count = 1
    game.bazpors_host_mode = "no_host"
    from bot.bazpors_narrator import NIGHT_ACTIONS

    game.bazpors_narrator_step = NIGHT_ACTIONS
    game.no_host_assistant_narrator_active = True
    game.bot_assistant_user_id = ASSISTANT
    game.observer_user_id = OBSERVER
    game.observer_prompt_status = "registered"
    return game


class _RecordingBot:
    """Records ops in call order (delete/edit/send) for ordering asserts."""

    def __init__(self, delete_fail: bool = False) -> None:
        self.ops: list[tuple] = []
        self.delete_fail = delete_fail
        self._mid = 83450

    async def send_message(self, **kwargs):
        self._mid += 1
        mid = self._mid
        self.ops.append(("send", kwargs["chat_id"], mid))
        return type(
            "M",
            (),
            {"chat": type("C", (), {"id": kwargs["chat_id"]})(), "message_id": mid},
        )

    async def edit_message_text(self, **kwargs):
        self.ops.append(("edit_text", kwargs["chat_id"], kwargs["message_id"]))
        return True

    async def edit_message_reply_markup(self, **kwargs):
        self.ops.append(
            ("edit_kb", kwargs["chat_id"], kwargs["message_id"], kwargs.get("reply_markup"))
        )
        return True

    async def delete_message(self, chat_id, message_id, **kwargs):
        if self.delete_fail:
            from aiogram.exceptions import TelegramBadRequest

            raise TelegramBadRequest("Message to delete not found")
        self.ops.append(("delete", chat_id, message_id))
        return True


class _Cb:
    message = None

    def __init__(self) -> None:
        self.answers: list[tuple[str, bool]] = []

    async def answer(self, text: str = "", show_alert: bool = False):
        self.answers.append((text, show_alert))


def _docs_ui_key(game: Game, doc_uid: int) -> str:
    from bot.observer_delivery import mirror_ui_claim_key

    return mirror_ui_claim_key(game.room_code, "no_host_doctor", doc_uid)


class DoctorNatoCleanupTests(unittest.TestCase):
    def _setup_blocked(self, doc_uid: int, delete_fail: bool = False):
        from bot.no_host_doctor_night import _send_doctor_panel

        game = _game(doc_uid)
        bot = _RecordingBot(delete_fail=delete_fail)
        asyncio.new_event_loop().run_until_complete(
            _send_doctor_panel(
                bot, game, GameManager(), doc_uid, sig="1:doc:NS_DOC", nato_blocked=False
            )
        )
        entry = game.mirror_prompt_messages.get(_docs_ui_key(game, doc_uid)) or {}
        old_obs = entry.get("observer")
        old_player = entry.get("player")
        game.bazpors_nato_action_registered = True
        return game, bot, entry, old_obs, old_player

    def _apply_nato(self, game: Game, bot: _RecordingBot, doc_uid: int) -> None:
        from bot.no_host_doctor_night import apply_no_host_doctor_nato_blocked_panel

        asyncio.new_event_loop().run_until_complete(
            apply_no_host_doctor_nato_blocked_panel(bot, game, GameManager())
        )

    def _dispatch(self, game: Game, bot: _RecordingBot, doc_uid: int, act: str, tid: int):
        from bot.no_host_doctor_night import dispatch_no_host_doctor_night

        cb = _Cb()
        with patch(
            "bot.no_host_doctor_night.no_host_after_role_night_pick", new=AsyncMock()
        ), patch(
            "bot.no_host_doctor_night.no_host_parallel_night_collect_active",
            return_value=False,
        ):
            asyncio.new_event_loop().run_until_complete(
                dispatch_no_host_doctor_night(
                    cb, bot, game, GameManager(),
                    doc_uid=doc_uid, actor_uid=OBSERVER, act=act, tid=tid,
                )
            )
        return cb

    # ------------------------------------------------------------------

    def test_initial_selection_panel_tracked(self) -> None:
        game, bot, entry, _, old_player = self._setup_blocked(SYN_DOC)
        self.assertTrue(entry.get("observer"), "observer mirror must be tracked")
        self.assertIsNone(old_player, "synthetic doctor: no player DM")
        self.assertEqual(len(bot.ops), 1)
        self.assertEqual(bot.ops[0][0], "send")
        self.assertNotIn("عملیات ناتویی", entry["text"])

    def test_nato_closes_old_observer_panel_before_replacement(self) -> None:
        game, bot, entry, old_obs, _ = self._setup_blocked(SYN_DOC)
        old_id = tuple(old_obs)[1]

        self._apply_nato(game, bot, SYN_DOC)

        del_idx = bot.ops.index(("delete", OBSERVER, old_id))
        entry_after = game.mirror_prompt_messages.get(
            _docs_ui_key(game, SYN_DOC)
        ) or {}
        new_id = tuple(entry_after["observer"])[1]
        send_idx = bot.ops.index(("send", OBSERVER, new_id))
        self.assertLess(del_idx, send_idx, "old keyboard closed BEFORE new panel")
        self.assertEqual(sum(1 for o in bot.ops if o[0] == "delete"), 1)
        self.assertEqual(
            sum(
                1 for o in bot.ops if o[0] == "send" and o[1] == OBSERVER and o[2] != old_id
            ),
            1,
            "exactly ONE replacement panel",
        )
        self.assertIn("عملیات ناتویی", entry_after["text"])
        self.assertIn("اوکی", entry_after["text"])
        self.assertEqual(
            sum(1 for o in bot.ops if o[0] == "send"), 2, "no duplicate active panel"
        )

    def test_real_doctor_player_panel_edited_in_place(self) -> None:
        game, bot, entry, old_obs, old_player = self._setup_blocked(REAL_DOC)
        self.assertTrue(old_player, "real doctor gets a player DM copy")
        player_id = tuple(old_player)[1]
        ops_before = len(bot.ops)

        self._apply_nato(game, bot, REAL_DOC)

        entry_after = game.mirror_prompt_messages.get(
            _docs_ui_key(game, REAL_DOC)
        ) or {}
        # Player copy NOT deleted — superseded by the tracking in-place edit.
        self.assertNotIn(("delete", REAL_DOC, player_id), bot.ops)
        player_edit = [
            o for o in bot.ops[ops_before:] if o[0] == "edit_text" and o[1] == REAL_DOC
        ]
        self.assertTrue(player_edit, "player panel updated via tracked edit")
        self.assertFalse(
            any(o[0] == "send" and o[1] == REAL_DOC for o in bot.ops[ops_before:]),
            "no duplicate player-side panel",
        )
        self.assertIn("عملیات ناتویی", entry_after["text"])
        # Observer superseded copy cleaned and re-sent.
        old_obs_id = tuple(old_obs)[1]
        self.assertIn(("delete", OBSERVER, old_obs_id), bot.ops)
        new_obs = tuple(entry_after["observer"])[1]
        self.assertNotEqual(new_obs, old_obs_id)

    def test_delete_failure_falls_back_to_keyboard_removal(self) -> None:
        game, bot, entry, old_obs, _ = self._setup_blocked(SYN_DOC, delete_fail=True)
        old_id = tuple(old_obs)[1]

        self._apply_nato(game, bot, SYN_DOC)

        kb_removals = [
            o for o in bot.ops if o[0] == "edit_kb" and o[1] == OBSERVER and o[2] == old_id
        ]
        self.assertEqual(len(kb_removals), 1, "keyboard-only removal fallback ran")
        self.assertIsNone(kb_removals[0][3], "fallback removes the keyboard (kb=None)")
        entry_after = game.mirror_prompt_messages.get(
            _docs_ui_key(game, SYN_DOC)
        ) or {}
        self.assertIn("عملیات ناتویی", entry_after["text"])

    def test_stale_doctor_callback_rejected_after_nato(self) -> None:
        game, bot, *_ = self._setup_blocked(SYN_DOC)
        self._apply_nato(game, bot, SYN_DOC)
        before_saves = list(game.bazpors_doctor_save_uids)

        cb = self._dispatch(game, bot, SYN_DOC, act="dkt", tid=1)

        self.assertTrue(cb.answers, "stale press must get an alert")
        self.assertTrue(cb.answers[0][1], "alert-level rejection")
        self.assertIn("ناتویی", cb.answers[0][0])
        self.assertEqual(list(game.bazpors_doctor_save_uids), before_saves)
        self.assertFalse(game.no_host_doctor_pick_confirmed)

    def test_dko_commits_once_and_repeat_rejected(self) -> None:
        game, bot, entry, old_obs, _ = self._setup_blocked(SYN_DOC)
        old_id = tuple(old_obs)[1]
        self._apply_nato(game, bot, SYN_DOC)
        entry_after = game.mirror_prompt_messages.get(
            _docs_ui_key(game, SYN_DOC)
        ) or {}
        new_id = tuple(entry_after["observer"])[1]

        cb = self._dispatch(game, bot, SYN_DOC, act="dko", tid=0)
        self.assertTrue(game.no_host_doctor_pick_confirmed, "OK commits ONCE")
        closed = [
            o for o in bot.ops if o[0] == "edit_text" and o[1] == OBSERVER and o[2] == new_id
        ]
        self.assertTrue(closed, "acked panel closed via tracked ref")
        self.assertIn(("delete", OBSERVER, old_id), bot.ops)

        cb2 = self._dispatch(game, bot, SYN_DOC, act="dko", tid=0)
        self.assertTrue(cb2.answers and cb2.answers[0][1], "alert-level rejection")
        self.assertTrue(game.no_host_doctor_pick_confirmed, "no second commit")
        self.assertEqual(
            len(
                [
                    o
                    for o in bot.ops
                    if o[0] == "edit_text" and o[1] == OBSERVER and o[2] == new_id
                ]
            ),
            1,
            "ack close ran once",
        )


if __name__ == "__main__":
    unittest.main()
