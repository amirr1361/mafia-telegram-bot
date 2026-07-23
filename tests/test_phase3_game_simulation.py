"""فاز ۳ — شبیه‌سازی چند بازی semi_auto و no_host از لابی تا پخش نقش."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager, is_mafia_team, is_synthetic_player_uid
from bot.game_state import no_host_night_state, reset_no_host_per_night_role_state
from bot.models import Phase, Player, Role
from bot.no_host_handoff import apply_handoff_to_semi_auto
from bot.room_mode import (
    host_receives_moderator_deal_messages,
    is_bazpors_no_host_room,
    is_bazpors_semi_auto_room,
    players_receive_post_deal_hub_message,
)


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.send_message = AsyncMock(return_value=MagicMock())
    bot.send_photo = AsyncMock(return_value=MagicMock())
    return bot


class Phase3GameSimulationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _add_host(self, game, uid: int, name: str) -> None:
        err = self.gm.add_player(
            game,
            Player(user_id=uid, full_name=name, username=None),
        )
        self.assertIsNone(err)

    async def _deal_without_telegram(self, game) -> str | None:
        from bot.main import deal_roles_full_pipeline

        bot = _make_bot()
        with (
            patch("bot.main.send_private_role", new=AsyncMock(return_value=True)),
            patch(
                "bot.main.notify_players_after_roles_dealt",
                new=AsyncMock(),
            ),
            patch(
                "bot.main.begin_narrator_assist_after_roles_dealt",
                new=AsyncMock(),
            ),
            patch("bot.main.send_host_secret_role_roster", new=AsyncMock()),
            patch("bot.main.send_host_post_deal_panel", new=AsyncMock()),
            patch("bot.main.send_no_host_observer_prompt", new=AsyncMock()),
        ):
            return await deal_roles_full_pipeline(bot, game)

    def test_semi_auto_lobby_fill_and_roles(self) -> None:
        """چند اتاق semi_auto: پر کردن لابی، صندلی، assign_roles."""
        for n in (10, 11, 12):
            with self.subTest(players=n):
                game = self.gm.create_game(
                    host_id=9000 + n,
                    host_full_name="گرداننده",
                    host_username=None,
                    scenario_name="bazpors",
                    max_players=n,
                    bazpors_host_mode="semi_auto",
                )
                assert game is not None
                self._add_host(game, 9000 + n, "Host")
                err = self.gm.fill_bazpors_semi_auto_synthetic_lobby(game)
                self.assertIsNone(err)
                self.assertEqual(len(game.players), n)
                self.assertTrue(is_bazpors_semi_auto_room(game))
                self.assertTrue(host_receives_moderator_deal_messages(game))
                self.assertFalse(players_receive_post_deal_hub_message(game))
                self.gm.assign_roles(game)
                roles = {p.role for p in game.players.values()}
                self.assertTrue(all(r is not None for r in roles))
                mafia_roles = [r for r in roles if r and is_mafia_team(r)]
                self.assertTrue(len(mafia_roles) >= 2)

    def test_no_host_lobby_fill_and_roles(self) -> None:
        """چند اتاق no_host: سازنده + synthetic + assign_roles."""
        for n in (10, 12):
            with self.subTest(players=n):
                creator = 8000 + n
                game = self.gm.create_game(
                    host_id=creator,
                    host_full_name="سازنده",
                    host_username=None,
                    scenario_name="bazpors",
                    max_players=n,
                    bazpors_host_mode="no_host",
                )
                assert game is not None
                self._add_host(game, creator, "Creator")
                err = self.gm.fill_bazpors_no_host_synthetic_lobby(game)
                self.assertIsNone(err)
                real = sum(
                    1 for u in game.players if not is_synthetic_player_uid(u)
                )
                self.assertEqual(real, 1)
                self.assertEqual(len(game.players), n)
                self.assertTrue(is_bazpors_no_host_room(game))
                self.assertFalse(host_receives_moderator_deal_messages(game))
                self.gm.assign_roles(game)
                self.assertTrue(all(p.role for p in game.players.values()))

    async def test_semi_auto_deal_pipeline(self) -> None:
        game = self.gm.create_game(
            host_id=7001,
            host_full_name="H",
            host_username=None,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        self._add_host(game, 7001, "H")
        self.gm.fill_bazpors_semi_auto_synthetic_lobby(game)
        game.seats_finalized = True
        err = await self._deal_without_telegram(game)
        self.assertIsNone(err)
        self.assertTrue(game.roles_dealt)
        self.assertEqual(game.phase, Phase.MANUAL)

    async def test_no_host_deal_pipeline_and_night_reset(self) -> None:
        game = self.gm.create_game(
            host_id=6001,
            host_full_name="C",
            host_username=None,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self._add_host(game, 6001, "C")
        self.gm.fill_bazpors_no_host_synthetic_lobby(game)
        game.seats_finalized = True
        err = await self._deal_without_telegram(game)
        self.assertIsNone(err)
        self.assertTrue(game.roles_dealt)
        # شبیه‌سازی فعال شدن پنل‌های شب و reset شب بعد
        night = no_host_night_state(game)
        night.role_pick("doctor").flow_active = True
        game.no_host_mafia_night1_flow_active = True
        reset_no_host_per_night_role_state(game)
        self.assertFalse(game.no_host_doctor_flow_active)
        self.assertFalse(game.no_host_mafia_night1_flow_active)

    def test_no_host_to_semi_auto_handoff_chain(self) -> None:
        """انتقال گردانندگی پس از چند شب no_host."""
        game = self.gm.create_game(
            host_id=5001,
            host_full_name="C",
            host_username=None,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        self._add_host(game, 5001, "C")
        self.gm.fill_bazpors_no_host_synthetic_lobby(game)
        self.gm.assign_roles(game)
        game.bazpors_narrator_night_count = 1
        game.no_host_intro_night_started = True
        game.no_host_day1_vote_resolved = True
        apply_handoff_to_semi_auto(game, 5001)
        self.assertEqual(game.bazpors_host_mode, "semi_auto")
        self.assertTrue(is_bazpors_semi_auto_room(game))
        self.assertTrue(host_receives_moderator_deal_messages(game))

    async def test_multiple_games_isolated(self) -> None:
        """چند بازی همزمان — room_code و state مستقل."""
        games = []
        for i, mode in enumerate(("semi_auto", "no_host", "semi_auto", "no_host")):
            host = 4000 + i
            game = self.gm.create_game(
                host_id=host,
                host_full_name=f"H{i}",
                host_username=None,
                scenario_name="bazpors",
                max_players=10,
                bazpors_host_mode=mode,
            )
            assert game is not None
            self._add_host(game, host, f"H{i}")
            if mode == "no_host":
                self.gm.fill_bazpors_no_host_synthetic_lobby(game)
            else:
                self.gm.fill_bazpors_semi_auto_synthetic_lobby(game)
            game.seats_finalized = True
            games.append(game)

        codes = {g.room_code for g in games}
        self.assertEqual(len(codes), len(games))

        for game in games:
            err = await self._deal_without_telegram(game)
            self.assertIsNone(err, msg=f"deal failed room {game.room_code}")

        for game in games:
            self.assertTrue(game.roles_dealt)

    def test_import_main_and_wire_handlers(self) -> None:
        import bot.main as main_mod

        self.assertTrue(hasattr(main_mod, "deal_roles_full_pipeline"))
        self.assertTrue(hasattr(main_mod, "_wire_handlers"))


if __name__ == "__main__":
    unittest.main()
