"""ناظر بازی — حالت گردانندگی بدون گرداننده."""

from __future__ import annotations

import unittest

from bot.game import GameManager, role_label_fa
from bot.main import (
    build_no_host_assistant_announcement_html,
    build_no_host_bot_assistant_prompt_html,
    build_no_host_intro_night_confirm_html,
    build_no_host_intro_night_civilian_html,
    build_no_host_intro_night_mafia_dm_html,
    build_no_host_intro_night_start_html,
    build_no_host_observer_prompt_html,
    pick_random_no_host_bot_assistant,
)
from bot.models import Phase, Player, Role
from bot.observer_delivery import (
    build_observer_players_roster_html,
    no_host_observer_registered,
)


class NoHostObserverTest(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_ensure_observer_code_four_digits(self) -> None:
        game = self.gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        code = self.gm.ensure_observer_code(game)
        self.assertEqual(len(code), 4)
        self.assertTrue(code.isdigit())
        self.assertEqual(self.gm.ensure_observer_code(game), code)

    def test_register_observer_rejects_creator_and_players(self) -> None:
        game = self.gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=100, full_name="Creator", username=None)
        )
        self.gm.add_player(
            game, Player(user_id=200, full_name="P2", username=None)
        )
        self.gm.ensure_observer_code(game)
        game.observer_prompt_status = "pending"
        game.phase = Phase.MANUAL
        game.roles_dealt = True

        self.assertEqual(
            self.gm.register_game_observer(
                game, 100, full_name="Creator", username=None
            ),
            "creator_is_player",
        )
        self.assertEqual(
            self.gm.register_game_observer(
                game, 200, full_name="P2", username=None
            ),
            "is_player",
        )
        self.assertIsNone(
            self.gm.register_game_observer(
                game, 300, full_name="Observer", username="obs"
            )
        )
        self.assertEqual(game.observer_user_id, 300)
        self.assertEqual(game.observer_prompt_status, "registered")
        self.assertEqual(self.gm.get_room_for_observer(300), game.room_code)

    def test_register_blocked_when_skipped(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.ensure_observer_code(game)
        game.observer_prompt_status = "skipped"
        self.assertEqual(
            self.gm.register_game_observer(
                game, 99, full_name="X", username=None
            ),
            "skipped",
        )

    def test_prompt_html_contains_code_and_command(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        html_msg = build_no_host_observer_prompt_html(game)
        code = game.observer_code
        assert code is not None
        self.assertIn(f"/observer_{code}", html_msg)
        self.assertIn("ناظر بازی", html_msg)

    def test_observer_role_label(self) -> None:
        self.assertEqual(role_label_fa(Role.OBSERVER), "ناظر بازی")

    def test_observer_players_roster_html(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        p1 = Player(user_id=10, full_name="Ali", username="ali", seat=1)
        p1.role = Role.CITIZEN
        p2 = Player(user_id=20, full_name="Boss", username=None, seat=2)
        p2.role = Role.MAFIA_BOSS
        self.gm.add_player(game, p1)
        self.gm.add_player(game, p2)
        game.roles_dealt = True
        html_msg = build_observer_players_roster_html(game, self.gm)
        self.assertIn("فهرست بازیکنان و نقش", html_msg)
        self.assertIn("Ali", html_msg)
        self.assertIn("Boss", html_msg)
        self.assertIn(role_label_fa(Role.CITIZEN), html_msg)
        self.assertIn(role_label_fa(Role.MAFIA_BOSS), html_msg)

    def test_bot_assistant_prompt_html(self) -> None:
        text = build_no_host_bot_assistant_prompt_html()
        self.assertIn("کمک‌کننده ربات", text)
        self.assertIn("انتخاب تصادفی", text)

    def test_bot_assistant_keyboard_lists_all_real_players(self) -> None:
        from bot.main import no_host_bot_assistant_pick_keyboard

        game = self.gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=100, full_name="Creator", username=None, seat=1)
        )
        self.gm.add_player(
            game, Player(user_id=200, full_name="P2", username=None, seat=2)
        )
        kb = no_host_bot_assistant_pick_keyboard(game)
        labels = [b.text for row in kb.inline_keyboard for b in row]
        self.assertEqual(len(labels), 3)
        self.assertIn("🎲 انتخاب تصادفی", labels)
        self.assertTrue(any("Creator" in t for t in labels))
        self.assertTrue(any("P2" in t for t in labels))

    def test_pick_random_bot_assistant_skips_synthetic(self) -> None:
        game = self.gm.create_game(
            host_id=100,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=100, full_name="Creator", username=None)
        )
        self.gm.add_player(
            game, Player(user_id=200, full_name="P2", username=None)
        )
        picked = pick_random_no_host_bot_assistant(game)
        self.assertIn(picked, (100, 200))

    def test_announcement_includes_observer_when_registered(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=10, full_name="A", username=None)
        )
        game.observer_prompt_status = "registered"
        game.observer_user_id = 99
        game.observer_full_name = "ناظر"
        html_msg = build_no_host_assistant_announcement_html(game, 10)
        self.assertIn("کمک‌کننده ربات", html_msg)
        self.assertIn("ناظر بازی", html_msg)
        self.assertIn("پیام‌های خصوصی", html_msg)

    def test_observer_active_after_code_sent_when_already_registered(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.observer_user_id = 300
        game.observer_full_name = "Obs"
        game.observer_prompt_status = "registered"
        game.observer_prompt_status = "code_sent"
        self.assertTrue(no_host_observer_registered(game))

    def test_bot_assistant_disabled_for_semi_auto(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=10, full_name="A", username=None)
        )
        self.assertIsNone(pick_random_no_host_bot_assistant(game))
        self.assertIsNone(game.bot_assistant_user_id)

    def test_intro_night_prompt_and_broadcast_html(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=10, full_name="Ali", username="ali")
        )
        game.bot_assistant_user_id = 10
        self.assertIn("شروع شب معارفه", build_no_host_intro_night_start_html())
        self.assertIn("روز معارفه", build_no_host_intro_night_start_html())
        self.assertIn("تأیید شروع", build_no_host_intro_night_confirm_html())
        civ = build_no_host_intro_night_civilian_html()
        self.assertIn("شب معارفه آغاز شد", civ)
        self.assertIn("چشم‌های خود را ببندید", civ)
        game.players[10].role = Role.CITIZEN
        game.players[10].is_alive = True
        p_boss = Player(user_id=20, full_name="Boss", username=None, role=Role.MAFIA_BOSS, seat=1, is_alive=True)
        p_maf = Player(user_id=30, full_name="Maf", username=None, role=Role.MAFIA_BASIC, seat=2, is_alive=True)
        game.players[20] = p_boss
        game.players[30] = p_maf
        mafia_dm = build_no_host_intro_night_mafia_dm_html(game)
        self.assertIn("اعضای تیم مافیا", mafia_dm)
        self.assertIn("Boss", mafia_dm)
        self.assertIn("Maf", mafia_dm)
        boss_pos = mafia_dm.index("Boss")
        maf_pos = mafia_dm.index("Maf")
        self.assertLess(boss_pos, maf_pos)

    def test_announcement_omits_observer_when_skipped(self) -> None:
        game = self.gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=10, full_name="A", username=None)
        )
        game.observer_prompt_status = "skipped"
        html_msg = build_no_host_assistant_announcement_html(game, 10)
        self.assertIn("کمک‌کننده ربات", html_msg)
        self.assertNotIn("ناظر بازی", html_msg)


class NoHostObserverPromptCallbackTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _no_host_game(self, *, scenario: str, host_id: int = 5001):
        game = self.gm.create_game(
            host_id=host_id,
            scenario_name=scenario,
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self.gm.add_player(
            game, Player(user_id=host_id, full_name="Host", username=None)
        )
        game.phase = Phase.MANUAL
        game.roles_dealt = True
        game.observer_prompt_status = "pending"
        self.gm.ensure_observer_code(game)
        return game

    def _callback(self, *, host_id: int, room_code: str, act: str):
        from unittest.mock import AsyncMock, MagicMock

        from aiogram.enums import ChatType

        from bot.main import NoHostObserverPrompt

        cb = MagicMock()
        cb.from_user = MagicMock()
        cb.from_user.id = host_id
        cb.message = MagicMock()
        cb.message.chat = MagicMock()
        cb.message.chat.type = ChatType.PRIVATE
        cb.message.html_text = "prompt"
        cb.message.edit_text = AsyncMock()
        cb.message.edit_reply_markup = AsyncMock()
        cb.answer = AsyncMock()
        data = NoHostObserverPrompt(code=room_code, act=act)
        return cb, data

    async def test_code_sent_mozakere(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from bot.handlers.lobby import cb_no_host_observer_prompt

        game = self._no_host_game(scenario="mozakere")
        cb, data = self._callback(
            host_id=5001, room_code=game.room_code, act="code_sent"
        )
        bot = MagicMock()
        with (
            patch("bot.handlers.lobby.manager", self.gm),
            patch(
                "bot.handlers.lobby.send_no_host_bot_assistant_prompt",
                new=AsyncMock(),
            ) as assistant,
        ):
            await cb_no_host_observer_prompt(cb, data, bot)
        self.assertEqual(game.observer_prompt_status, "code_sent")
        assistant.assert_awaited_once()

    async def test_skip_mozakere(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from bot.handlers.lobby import cb_no_host_observer_prompt

        game = self._no_host_game(scenario="mozakere", host_id=5002)
        cb, data = self._callback(
            host_id=5002, room_code=game.room_code, act="skip"
        )
        bot = MagicMock()
        with (
            patch("bot.handlers.lobby.manager", self.gm),
            patch(
                "bot.handlers.lobby.send_no_host_bot_assistant_prompt",
                new=AsyncMock(),
            ) as assistant,
        ):
            await cb_no_host_observer_prompt(cb, data, bot)
        self.assertEqual(game.observer_prompt_status, "skipped")
        assistant.assert_awaited_once()

    async def test_skip_bazpors_regression(self) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from bot.handlers.lobby import cb_no_host_observer_prompt

        game = self._no_host_game(scenario="bazpors", host_id=5003)
        cb, data = self._callback(
            host_id=5003, room_code=game.room_code, act="skip"
        )
        bot = MagicMock()
        with (
            patch("bot.handlers.lobby.manager", self.gm),
            patch(
                "bot.handlers.lobby.send_no_host_bot_assistant_prompt",
                new=AsyncMock(),
            ) as assistant,
        ):
            await cb_no_host_observer_prompt(cb, data, bot)
        self.assertEqual(game.observer_prompt_status, "skipped")
        assistant.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
