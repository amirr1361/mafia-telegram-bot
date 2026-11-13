"""Mozakere negotiation panel lifecycle — regression tests.

Covers the Room 44 audit fixes:
* Journalist: exactly ONE actionable post-negotiation selection panel
  (edit-in-place of the previous panel; no duplicate from the readiness
  reconcile loop or the host-step push).
* Detective (and the shared reset path): the invalidated pre-negotiation
  panel is closed (deleted / keyboard stripped, player + observer mirror)
  BEFORE the replacement panel is delivered, and refs are never
  overwritten before cleanup.
* Superseded-panel callbacks are rejected even while the night is active.
* Per-night reset clears the post-negotiation panel marker.
"""

from __future__ import annotations

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.models import Game, Player, Role

JR = 303
DET = 302
DOC = 301
NEG = 201
CIT1 = 401
OBS = 999
ASSISTANT = 108214166


def _p(uid: int, seat: int, name: str, role: Role) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=True,
    )


class StubBot:
    """Records send/edit/delete; aiogram-compatible enough for the flows."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.edits: list[tuple[int, int]] = []
        self.deleted: list[tuple[int, int]] = []
        self._mid = 5000

    async def send_message(self, chat_id, text=None, **kw):  # noqa: ANN001
        self._mid += 1
        self.sent.append((int(chat_id), str(text)))
        return SimpleNamespace(message_id=self._mid, chat=SimpleNamespace(id=chat_id))

    async def edit_message_text(self, chat_id, message_id, text=None, **kw):  # noqa: ANN001
        self.edits.append((int(chat_id), int(message_id)))
        return True

    async def edit_message_reply_markup(self, chat_id, message_id, reply_markup=None, **kw):  # noqa: ANN001
        return True

    async def delete_message(self, chat_id, message_id):  # noqa: ANN001
        self.deleted.append((int(chat_id), int(message_id)))
        return True


class Cb:
    def __init__(self, uid: int, msg_id: int) -> None:
        self.from_user = SimpleNamespace(id=uid)
        self.message = SimpleNamespace(message_id=msg_id)
        self.alerts: list[tuple[str | None, bool]] = []

    async def answer(self, text=None, show_alert=False, **kw):  # noqa: ANN001
        self.alerts.append((text, show_alert))


def make_game(*, with_observer: bool = False) -> tuple[GameManager, Game]:
    gm = GameManager()
    game = gm.create_game(
        host_id=1,
        scenario_name="mozakere",
        max_players=12,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.room_code = "RM1"
    gm.games["RM1"] = game
    roster = (
        (NEG, 1, "مذاکره‌کننده", Role.MAFIA_NEGOTIATOR),
        (202, 2, "مافیا ساده", Role.MAFIA_SIMPLE),
        (DOC, 3, "پزشک", Role.DOCTOR),
        (DET, 4, "کارآگاه", Role.DETECTIVE),
        (JR, 5, "خبرنگار", Role.JOURNALIST),
        (CIT1, 6, "شهروند", Role.CITIZEN),
        (402, 7, "شهروند۲", Role.CITIZEN),
    )
    for seat, (uid, seat_no, name, role) in enumerate(roster, start=1):
        gm.add_player(game, _p(uid, seat_no, name, role))
    game.bot_assistant_user_id = ASSISTANT
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = "night_start"
    game.bazpors_narrator_night_count = 1
    if with_observer:
        game.observer_user_id = OBS
        game.observer_full_name = "ناظر"
        game.observer_prompt_status = "registered"
    return gm, game


def negotiate(game: Game) -> None:
    """Mark the negotiation as performed (journalist becomes active)."""
    from bot.roles.night_state import mozakere_negotiation_night_state

    st = mozakere_negotiation_night_state(game)
    st.used = True
    st.tonight = True


def tracked(game: Game, ui_key: str, role: str = "player"):
    ref = (game.mirror_prompt_messages.get(ui_key) or {}).get(role)
    return tuple(int(x) for x in ref) if isinstance(ref, tuple) else None


def journalist_ui_key(game: Game) -> str:
    from bot.no_host_journalist_night import _journalist_ui_key

    return _journalist_ui_key(game, JR)


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class JournalistPanelLifecycleTests(unittest.TestCase):
    def test_idle_panel_before_negotiation_and_no_duplicate(self) -> None:
        gm, game = make_game()
        bot = StubBot()
        from bot.no_host_journalist_night import start_no_host_journalist_night_flow

        ok = run(start_no_host_journalist_night_flow(bot, game, gm, at_night_entry=True))
        self.assertTrue(ok)
        # exactly one DM to the journalist, idle (OK) panel
        jr_sends = [s for s in bot.sent if s[0] == JR]
        self.assertEqual(len(jr_sends), 1)
        self.assertIn("خبرنگار", jr_sends[0][1])
        self.assertIn("مذاکره هنوز انجام نشده", jr_sends[0][1])
        self.assertIsNotNone(tracked(game, journalist_ui_key(game)))
        self.assertEqual(game.no_host_journalist_dm_signature, "1:journalist:night_entry:idle")
        self.assertEqual(game.no_host_journalist_neg_panel_sent_night, 0)
        # reconcile re-run must not re-send
        again = run(start_no_host_journalist_night_flow(bot, game, gm, at_night_entry=True))
        self.assertFalse(again)
        self.assertEqual(len([s for s in bot.sent if s[0] == JR]), 1)

    def test_idle_confirm_on_tracked_panel_works(self) -> None:
        gm, game = make_game()
        bot = StubBot()
        from bot.no_host_journalist_night import (
            dispatch_no_host_journalist_night,
            start_no_host_journalist_night_flow,
        )

        run(start_no_host_journalist_night_flow(bot, game, gm, at_night_entry=True))
        msg_id = tracked(game, journalist_ui_key(game))[1]
        cb = Cb(JR, msg_id)
        run(
            dispatch_no_host_journalist_night(
                cb, bot, game, gm, jr_uid=JR, actor_uid=JR, act="jic", tid=0
            )
        )
        self.assertTrue(game.no_host_journalist_idle_confirmed)
        self.assertEqual(tracked(game, journalist_ui_key(game))[1], msg_id)
        self.assertIn((JR, msg_id), bot.edits)

    def test_activation_edits_in_place_single_panel(self) -> None:
        gm, game = make_game()
        bot = StubBot()
        from bot.no_host_journalist_night import (
            activate_journalist_after_mozakere_negotiation,
            dispatch_no_host_journalist_night_panel,
            start_no_host_journalist_night_flow,
        )

        run(start_no_host_journalist_night_flow(bot, game, gm, at_night_entry=True))
        first_id = tracked(game, journalist_ui_key(game))[1]
        sends_before = len(bot.sent)
        negotiate(game)
        run(activate_journalist_after_mozakere_negotiation(bot, game, gm))
        # NO new message: the previous panel was edited into the pick panel
        self.assertEqual(len(bot.sent), sends_before)
        self.assertIn((JR, first_id), bot.edits)
        self.assertEqual(
            game.no_host_journalist_dm_signature, "1:journalist:night_entry:pick"
        )
        self.assertEqual(game.no_host_journalist_neg_panel_sent_night, 1)
        self.assertEqual(tracked(game, journalist_ui_key(game))[1], first_id)
        # readiness reconcile + host-step push must NOT send a second panel
        self.assertFalse(
            run(start_no_host_journalist_night_flow(bot, game, gm, at_night_entry=True))
        )
        self.assertFalse(run(start_no_host_journalist_night_flow(bot, game, gm)))
        with patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new=AsyncMock(),
        ):
            run(dispatch_no_host_journalist_night_panel(bot, game, gm))
        self.assertEqual(len(bot.sent), sends_before)

    def test_activation_without_previous_refs_sends_exactly_one_panel(self) -> None:
        gm, game = make_game()
        bot = StubBot()
        from bot.no_host_journalist_night import (
            activate_journalist_after_mozakere_negotiation,
            start_no_host_journalist_night_flow,
        )

        negotiate(game)
        run(activate_journalist_after_mozakere_negotiation(bot, game, gm))
        jr_sends = [s for s in bot.sent if s[0] == JR]
        self.assertEqual(len(jr_sends), 1)
        self.assertIsNotNone(tracked(game, journalist_ui_key(game)))
        self.assertEqual(
            game.no_host_journalist_dm_signature, "1:journalist:night_entry:pick"
        )
        self.assertFalse(
            run(start_no_host_journalist_night_flow(bot, game, gm, at_night_entry=True))
        )
        self.assertFalse(run(start_no_host_journalist_night_flow(bot, game, gm)))

    def test_journalist_pick_and_confirm_single_target(self) -> None:
        gm, game = make_game()
        bot = StubBot()
        from bot.no_host_journalist_night import (
            activate_journalist_after_mozakere_negotiation,
            dispatch_no_host_journalist_night,
        )

        negotiate(game)
        run(activate_journalist_after_mozakere_negotiation(bot, game, gm))
        msg_id = tracked(game, journalist_ui_key(game))[1]
        cb = Cb(JR, msg_id)
        run(
            dispatch_no_host_journalist_night(
                cb, bot, game, gm, jr_uid=JR, actor_uid=JR, act="jrp", tid=DOC
            )
        )
        self.assertEqual(game.no_host_journalist_pending_tid, DOC)
        with patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new=AsyncMock(),
        ):
            run(
                dispatch_no_host_journalist_night(
                    cb, bot, game, gm, jr_uid=JR, actor_uid=JR, act="jrc", tid=DOC
                )
            )
        self.assertTrue(game.no_host_journalist_pick_confirmed)
        self.assertIsNone(game.no_host_journalist_pending_tid)

    def test_superseded_journalist_callbacks_rejected(self) -> None:
        gm, game = make_game()
        bot = StubBot()
        from bot.no_host_journalist_night import (
            activate_journalist_after_mozakere_negotiation,
            dispatch_no_host_journalist_night,
        )

        negotiate(game)
        run(activate_journalist_after_mozakere_negotiation(bot, game, gm))
        stale = Cb(JR, 424242)  # not the tracked panel message
        run(
            dispatch_no_host_journalist_night(
                stale, bot, game, gm, jr_uid=JR, actor_uid=JR, act="jrp", tid=DOC
            )
        )
        self.assertTrue(any("قدیمی" in (a[0] or "") for a in stale.alerts))
        self.assertIsNone(game.no_host_journalist_pending_tid)
        # stale press AFTER confirm is also rejected (not double-recorded)
        good = Cb(JR, tracked(game, journalist_ui_key(game))[1])
        run(
            dispatch_no_host_journalist_night(
                good, bot, game, gm, jr_uid=JR, actor_uid=JR, act="jrp", tid=DOC
            )
        )
        with patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new=AsyncMock(),
        ):
            run(
                dispatch_no_host_journalist_night(
                    good, bot, game, gm, jr_uid=JR, actor_uid=JR, act="jrc", tid=DOC
                )
            )
        self.assertTrue(game.no_host_journalist_pick_confirmed)
        stale2 = Cb(JR, 424242)
        run(
            dispatch_no_host_journalist_night(
                stale2, bot, game, gm, jr_uid=JR, actor_uid=JR, act="jrp", tid=CIT1
            )
        )
        self.assertTrue(any("قدیمی" in (a[0] or "") for a in stale2.alerts))

    def test_night_reset_clears_negotiation_panel_marker(self) -> None:
        gm, game = make_game()
        game.no_host_journalist_neg_panel_sent_night = 3
        from bot.bazpors_narrator import _reset_night_flags

        _reset_night_flags(game)
        self.assertEqual(game.no_host_journalist_neg_panel_sent_night, 0)
        self.assertIsNone(game.no_host_journalist_dm_signature)


class DetectivePanelReplacementTests(unittest.TestCase):
    def test_reset_closes_old_panel_and_delivers_replacement(self) -> None:
        gm, game = make_game(with_observer=True)
        bot = StubBot()
        from bot.no_host_detective_night import start_no_host_detective_night_flow
        from bot.no_host_mozakere_negotiation_reset import (
            apply_mozakere_negotiation_citizen_resets,
        )
        from bot.observer_delivery import mirror_ui_claim_key

        run(start_no_host_detective_night_flow(bot, game, gm, at_night_entry=True))
        det_key = mirror_ui_claim_key("RM1", "no_host_detective", DET)
        old_player = tracked(game, det_key, "player")
        old_observer = tracked(game, det_key, "observer")
        self.assertIsNotNone(old_player)
        self.assertIsNotNone(old_observer)
        # detective had confirmed an inquiry before the negotiation
        game.no_host_detective_pick_confirmed = True
        negotiate(game)

        with patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new=AsyncMock(),
        ):
            run(apply_mozakere_negotiation_citizen_resets(bot, game, gm))

        # old player panel AND observer mirror closed (deleted) before replace
        self.assertIn((DET, old_player[1]), bot.deleted)
        self.assertIn((OBS, old_observer[1]), bot.deleted)
        # a fresh replacement panel was delivered and tracked
        new_player = tracked(game, det_key, "player")
        new_observer = tracked(game, det_key, "observer")
        self.assertIsNotNone(new_player)
        self.assertIsNotNone(new_observer)
        self.assertNotEqual(new_player[1], old_player[1])
        self.assertNotEqual(new_observer[1], old_observer[1])
        self.assertEqual(game.no_host_detective_dm_signature, "1:det:mozakere_pick")
        self.assertFalse(game.no_host_detective_pick_confirmed)
        # new panel is actionable
        cb = Cb(DET, new_player[1])
        run(
            _det_dispatch(cb, bot, game, gm, act="ndp", tid=NEG)
        )
        self.assertEqual(game.no_host_detective_pending_tid, NEG)

    def test_superseded_detective_callback_rejected(self) -> None:
        gm, game = make_game()
        bot = StubBot()
        from bot.no_host_detective_night import start_no_host_detective_night_flow
        from bot.no_host_mozakere_negotiation_reset import (
            apply_mozakere_negotiation_citizen_resets,
        )

        run(start_no_host_detective_night_flow(bot, game, gm, at_night_entry=True))
        game.no_host_detective_pick_confirmed = True
        negotiate(game)
        with patch(
            "bot.no_host_night_ready.maybe_finish_no_host_parallel_night",
            new=AsyncMock(),
        ):
            run(apply_mozakere_negotiation_citizen_resets(bot, game, gm))
        # press on the OLD (deleted) message id — must be rejected
        stale = Cb(DET, 424242)
        run(_det_dispatch(stale, bot, game, gm, act="ndp", tid=NEG))
        self.assertTrue(any("قدیمی" in (a[0] or "") for a in stale.alerts))
        self.assertIsNone(game.no_host_detective_pending_tid)


async def _det_dispatch(cb, bot, game, gm, *, act, tid):  # noqa: ANN001
    from bot.no_host_detective_night import dispatch_no_host_detective_night

    await dispatch_no_host_detective_night(
        cb, bot, game, gm, det_uid=DET, actor_uid=DET, act=act, tid=tid
    )


class SharedHelpersTests(unittest.TestCase):
    def test_close_mirror_panel_refs_deletes_and_untracks(self) -> None:
        gm, game = make_game(with_observer=True)
        bot = StubBot()
        from bot.no_host_role_pick_common import close_mirror_panel_refs
        from bot.observer_delivery import mirror_ui_claim_key, register_mirror_prompt_pair

        async def send():
            await register_mirror_prompt_pair(
                bot,
                game,
                DET,
                mirror_ui_claim_key("RM1", "no_host_detective", DET),
                "t",
                None,
                send_player=True,
                send_observer=True,
            )

        run(send())
        det_key = mirror_ui_claim_key("RM1", "no_host_detective", DET)
        player_ref = tracked(game, det_key, "player")
        observer_ref = tracked(game, det_key, "observer")
        closed = run(close_mirror_panel_refs(bot, game, det_key))
        self.assertEqual(closed, 2)
        self.assertIn((DET, player_ref[1]), bot.deleted)
        self.assertIn((OBS, observer_ref[1]), bot.deleted)
        self.assertIsNone(tracked(game, det_key, "player"))
        self.assertIsNone(tracked(game, det_key, "observer"))

    def test_mirror_panel_superseded_semantics(self) -> None:
        gm, game = make_game()
        from bot.no_host_role_pick_common import mirror_panel_superseded

        key = journalist_ui_key(game)
        game.mirror_prompt_messages[key] = {"player": (JR, 11), "observer": (OBS, 12)}
        self.assertFalse(mirror_panel_superseded(game, key, 11))
        self.assertFalse(mirror_panel_superseded(game, key, 12))
        self.assertTrue(mirror_panel_superseded(game, key, 13))
        self.assertFalse(mirror_panel_superseded(game, key, None))
        # no tracked refs at all → not superseded (previous behavior)
        game.mirror_prompt_messages.pop(key)
        self.assertFalse(mirror_panel_superseded(game, key, 11))


if __name__ == "__main__":
    unittest.main()
