"""انتقال گردانندگی no_host → semi_auto."""

from __future__ import annotations

import html
import unittest
from unittest.mock import AsyncMock, MagicMock

from bot.bazpors_narrator import Role, clear_narrator_panel_ref
from bot.observer_delivery import player_should_receive_game_messages
from bot.game import GameManager
from bot.models import Game, Player
from bot.no_host_handoff import (
    GATE_AFTER_NIGHT_BEFORE_DAY,
    GATE_DAY1_AFTER_ELIM,
    NO_HOST_HANDOFF_OFFER,
    apply_handoff_to_semi_auto,
    build_handoff_offer_panel,
    deliver_no_host_handoff_offer_panels,
    enter_handoff_offer,
    handoff_available,
    handoff_candidate_uids,
    offer_handoff_day1_after_elim,
    process_handoff_narrator_cb,
)


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


class NoHostHandoffTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _no_host_game(self) -> Game:
        game = Game(
            room_code="88",
            host_id=1,
            scenario_name="bazpors",
            players={
                -1: _p(-1, 1, "گرداننده", Role.CITIZEN, alive=False),
                -2: _p(-2, 2, "شهروند", Role.CITIZEN, alive=True),
                -3: _p(-3, 3, "مافیا", Role.MAFIA, alive=True),
            },
        )
        game.bazpors_host_mode = "no_host"
        game.bot_assistant_user_id = 99
        game.no_host_assistant_narrator_active = True
        return game

    def test_only_no_host_with_assistant(self) -> None:
        game = self._no_host_game()
        self.assertTrue(handoff_available(game))
        game.bazpors_host_mode = "semi_auto"
        self.assertFalse(handoff_available(game))

    def test_candidates_are_eliminated_only(self) -> None:
        game = self._no_host_game()
        self.assertEqual(handoff_candidate_uids(game), [-1])

    def test_offer_day1_needs_candidate(self) -> None:
        game = self._no_host_game()
        self.assertTrue(offer_handoff_day1_after_elim(game))
        self.assertEqual(game.bazpors_narrator_step, NO_HOST_HANDOFF_OFFER)
        self.assertEqual(game.no_host_handoff_gate, GATE_DAY1_AFTER_ELIM)

    def test_no_offer_without_eliminated(self) -> None:
        game = self._no_host_game()
        game.players[-1].is_alive = True
        self.assertFalse(offer_handoff_day1_after_elim(game))

    def test_panel_lists_eliminated(self) -> None:
        game = self._no_host_game()
        enter_handoff_offer(game, GATE_AFTER_NIGHT_BEFORE_DAY)
        body, kb = build_handoff_offer_panel(game, self.gm)
        self.assertIn("انتقال گردانندگی", body)
        self.assertIn("فاز شب", body)
        self.assertIn(html.escape(self.gm.format_player_tag(game.players[-1])), body)
        self.assertNotIn("شهروند", body)
        self.assertNotIn("مافیا", body)
        self.assertIsNotNone(kb)

    def test_pick_validates_alive(self) -> None:
        game = self._no_host_game()
        enter_handoff_offer(game, GATE_DAY1_AFTER_ELIM)
        err = process_handoff_narrator_cb(game, self.gm, "handoff_pick", -2)
        self.assertEqual(err, "فقط بازیکن خارج‌شده قابل انتخاب است.")

    def test_apply_switches_to_semi_auto(self) -> None:
        game = self._no_host_game()
        game.bazpors_assistant_panel_chat_id = 99
        game.bazpors_assistant_panel_message_id = 123
        apply_handoff_to_semi_auto(game, -1)
        self.assertEqual(game.bazpors_host_mode, "semi_auto")
        self.assertEqual(game.host_id, -1)
        self.assertFalse(game.no_host_assistant_narrator_active)
        self.assertIsNone(game.bazpors_assistant_panel_chat_id)
        self.assertIsNone(game.bazpors_assistant_panel_message_id)

    def test_eliminated_semi_auto_host_still_receives_messages(self) -> None:
        game = self._no_host_game()
        apply_handoff_to_semi_auto(game, -1)
        self.assertFalse(game.players[-1].is_alive)
        self.assertTrue(player_should_receive_game_messages(game, -1))

    def test_clear_narrator_panel_ref(self) -> None:
        game = self._no_host_game()
        game.bazpors_assistant_panel_chat_id = 1
        game.bazpors_assistant_panel_message_id = 2
        clear_narrator_panel_ref(game)
        self.assertIsNone(game.bazpors_assistant_panel_chat_id)
        self.assertIsNone(game.bazpors_assistant_panel_message_id)


class NoHostHandoffAsyncTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _no_host_game(self) -> Game:
        game = Game(
            room_code="88",
            host_id=1,
            scenario_name="bazpors",
            players={
                -1: Player(
                    user_id=-1,
                    full_name="گرداننده",
                    username=None,
                    role=Role.CITIZEN,
                    seat=1,
                    is_alive=False,
                ),
                -2: Player(
                    user_id=-2,
                    full_name="شهروند",
                    username=None,
                    role=Role.CITIZEN,
                    seat=2,
                    is_alive=True,
                ),
            },
        )
        game.bazpors_host_mode = "no_host"
        game.bot_assistant_user_id = 99
        game.no_host_assistant_narrator_active = True
        return game

    async def test_handoff_offer_delivers_to_assistant_and_observer(self) -> None:
        game = self._no_host_game()
        game.observer_user_id = 300
        game.observer_prompt_status = "registered"
        game.no_host_observer_only_narrator_mirror = True
        enter_handoff_offer(game, GATE_DAY1_AFTER_ELIM)

        bot = AsyncMock()
        assistant_msg = MagicMock(chat=MagicMock(id=99), message_id=501)
        observer_msg = MagicMock(chat=MagicMock(id=300), message_id=601)

        async def _send(chat_id: int, *args, **kwargs):
            if chat_id == 99:
                return assistant_msg
            if chat_id == 300:
                return observer_msg
            return None

        bot.send_message = AsyncMock(side_effect=_send)
        bot.delete_message = AsyncMock()

        ok = await deliver_no_host_handoff_offer_panels(bot, game, self.gm)
        self.assertTrue(ok)

        def _chat_id(call) -> int:
            if "chat_id" in call.kwargs:
                return int(call.kwargs["chat_id"])
            return int(call.args[0])

        send_uids = [_chat_id(c) for c in bot.send_message.call_args_list]
        self.assertIn(99, send_uids)
        self.assertIn(300, send_uids)
        self.assertEqual(game.bazpors_assistant_panel_chat_id, 99)
        self.assertEqual(game.bazpors_assistant_panel_message_id, 501)
        obs_call = next(c for c in bot.send_message.call_args_list if _chat_id(c) == 300)
        obs_text = obs_call.kwargs.get("text") or obs_call.args[1]
        self.assertIn("ناظر", obs_text)
        self.assertIn("انتقال گردانندگی", obs_text)


if __name__ == "__main__":
    unittest.main()
