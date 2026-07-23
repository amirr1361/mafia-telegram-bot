"""تست گادفادر و ناتویی — فقط سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from bot.game import GameManager
from bot.models import Player, Role
from bot.no_host_mafia_night1 import (
    MAFIA_ACTION_NATO,
    MAFIA_ACTION_SHOT,
    _available_mafia_actions,
    _mafia_menu_keyboard,
    build_mason_mafia_operation_menu_html,
    build_no_host_mafia_night1_menu_html,
)
from bot.no_host_mafia_chooser import (
    resolve_mafia_night1_panel_recipients,
    resolve_mafia_shot_chooser,
)
from bot.no_host_mafia_nato import (
    build_mason_nato_role_pick_html,
    build_mason_nato_wait_broadcast_html,
    _nato_guess_roles_in_room,
    _nato_player_pool,
    start_no_host_mafia_nato_flow,
)
from bot.roles.mason_godfather import mason_nato_can_register
from bot.roles.mason_nato import (
    clear_mason_nato_night_state,
    commit_mason_nato_guess,
    mark_mason_nato_selected_tonight,
    resolve_mason_nato_elimination_uid,
)


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mason_game(gm: GameManager, *, n: int = 14):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    return game


def _populate_mason_mafia_team(game, gm: GameManager) -> None:
    gm.add_player(game, _p(1, "GF", Role.GODFATHER))
    gm.add_player(game, _p(2, "NATO", Role.NATO))
    gm.add_player(game, _p(3, "Sab", Role.SABOTEUR))
    gm.add_player(game, _p(4, "Spy", Role.SPY))
    gm.add_player(game, _p(5, "Apache", Role.APACHE))
    gm.add_player(game, _p(6, "Doc", Role.DOCTOR))
    gm.add_player(game, _p(7, "Sniper", Role.SNIPER))
    gm.add_player(game, _p(8, "Cmd", Role.COMMANDER))
    gm.add_player(game, _p(9, "Mason", Role.MASON))
    gm.add_player(game, _p(10, "Gun", Role.GUNMAN))
    gm.add_player(game, _p(11, "Guard", Role.BODYGUARD))
    gm.add_player(game, _p(12, "Cowboy", Role.COWBOY))
    gm.add_player(game, _p(13, "Ruintan", Role.RUINTAN))
    gm.add_player(game, _p(14, "Simple", Role.TOWN_SIMPLE))


class MasonGodfatherMenuTests(unittest.TestCase):
    def test_eligible_godfather_sees_shoot_nato_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        actions = _available_mafia_actions(game, gm)
        self.assertEqual(actions, [MAFIA_ACTION_SHOT, MAFIA_ACTION_NATO])
        kb = _mafia_menu_keyboard(game, 1, gm)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertIn("🔫 شلیک", labels)
        self.assertIn("🎭 ناتویی", labels)
        self.assertIn(
            "یکی از گزینه‌های زیر را انتخاب کنید",
            build_no_host_mafia_night1_menu_html(game),
        )

    def test_nato_role_absent_only_shoot(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(1, "GF", Role.GODFATHER))
        gm.add_player(game, _p(2, "Sab", Role.SABOTEUR))
        actions = _available_mafia_actions(game, gm)
        self.assertEqual(actions, [MAFIA_ACTION_SHOT])

    def test_nato_dead_only_shoot(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        game.players[2].is_alive = False
        actions = _available_mafia_actions(game, gm)
        self.assertEqual(actions, [MAFIA_ACTION_SHOT])

    def test_godfather_dead_nato_alive_sees_shoot_nato_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        game.players[1].is_alive = False
        actions = _available_mafia_actions(game, gm)
        self.assertEqual(actions, [MAFIA_ACTION_SHOT, MAFIA_ACTION_NATO])
        kb = _mafia_menu_keyboard(game, 2, gm)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertIn("🔫 شلیک", labels)
        self.assertIn("🎭 ناتویی", labels)
        panel = resolve_mafia_night1_panel_recipients(game)
        self.assertEqual([p.user_id for p in panel], [2])

    def test_godfather_dead_nato_used_only_shoot(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        game.players[1].is_alive = False
        game.mason_nato_used = True
        actions = _available_mafia_actions(game, gm)
        self.assertEqual(actions, [MAFIA_ACTION_SHOT])
        panel = resolve_mafia_night1_panel_recipients(game)
        self.assertEqual([p.user_id for p in panel], [2])


class MasonNatoFlowTests(unittest.TestCase):
    def test_nato_broadcast_text(self) -> None:
        self.assertEqual(
            build_mason_nato_wait_broadcast_html(),
            "تیم مافیا در حال ناتویی...",
        )

    def test_nato_role_panel_text(self) -> None:
        self.assertEqual(
            build_mason_nato_role_pick_html(),
            "چه نقشی را برای ناتویی انتخاب می‌کنید؟",
        )

    def test_guess_roles_exclude_simple_citizen(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        roles = _nato_guess_roles_in_room(game)
        self.assertNotIn(Role.TOWN_SIMPLE, roles)
        self.assertNotIn(Role.CITIZEN, roles)
        self.assertIn(Role.DOCTOR, roles)
        self.assertIn(Role.SNIPER, roles)

    def test_player_pool_all_alive(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        pool = _nato_player_pool(game)
        self.assertEqual(len(pool), 14)

    def test_correct_guess_eliminates_at_night_end(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        mark_mason_nato_selected_tonight(game)
        commit_mason_nato_guess(game, Role.DOCTOR, 6)
        uid = resolve_mason_nato_elimination_uid(game)
        self.assertEqual(uid, 6)

    def test_wrong_guess_no_elimination(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        commit_mason_nato_guess(game, Role.SNIPER, 6)
        self.assertIsNone(resolve_mason_nato_elimination_uid(game))

    def test_nato_usable_only_once(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        mark_mason_nato_selected_tonight(game)
        self.assertTrue(game.mason_nato_used)
        self.assertFalse(mason_nato_can_register(game))

    def test_after_use_nato_option_disappears(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        game.mason_nato_used = True
        actions = _available_mafia_actions(game, gm)
        self.assertEqual(actions, [MAFIA_ACTION_SHOT])


class MasonShootingPriorityTests(unittest.TestCase):
    def test_godfather_controls_when_alive(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        ch = resolve_mafia_shot_chooser(game)
        assert ch is not None
        self.assertEqual(ch.user_id, 1)

    def test_nato_controls_when_godfather_dead(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        game.players[1].is_alive = False
        ch = resolve_mafia_shot_chooser(game)
        assert ch is not None
        self.assertEqual(ch.user_id, 2)

    def test_saboteur_when_godfather_and_nato_gone(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(1, "GF", Role.GODFATHER, alive=False))
        gm.add_player(game, _p(3, "Sab", Role.SABOTEUR))
        gm.add_player(game, _p(4, "Spy", Role.SPY))
        ch = resolve_mafia_shot_chooser(game)
        assert ch is not None
        self.assertEqual(ch.user_id, 3)

    def test_simple_mafia_when_higher_priority_gone(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=16)
        gm.add_player(game, _p(1, "GF", Role.GODFATHER, alive=False))
        gm.add_player(game, _p(5, "Basic", Role.MAFIA_BASIC))
        gm.add_player(game, _p(4, "Spy", Role.SPY))
        ch = resolve_mafia_shot_chooser(game)
        assert ch is not None
        self.assertEqual(ch.user_id, 5)


class MasonNatoStartFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_flow_broadcasts_and_sends_role_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        game.bazpors_host_mode = "no_host"
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_NATO
        mark_mason_nato_selected_tonight(game)

        with patch(
            "bot.no_host_mafia_nato.broadcast_to_alive_players",
            new_callable=AsyncMock,
        ) as broadcast, patch(
            "bot.no_host_mafia_nato.register_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as register:
            await start_no_host_mafia_nato_flow(AsyncMock(), game, gm)

        broadcast.assert_awaited_once()
        self.assertEqual(
            broadcast.await_args.args[2],
            "تیم مافیا در حال ناتویی...",
        )
        register.assert_awaited_once()
        self.assertEqual(
            register.await_args.args[4],
            "چه نقشی را برای ناتویی انتخاب می‌کنید؟",
        )
        self.assertTrue(game.no_host_mafia_nato_flow_active)


class MasonRoom86NatoAfterGodfatherDeathTests(unittest.TestCase):
    """Room 86 — گادفادر مرده، ناتو زنده باید پنل شلیک/ناتویی بگیرد."""

    def test_nato_can_register_without_godfather(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        game.players[1].is_alive = False
        self.assertTrue(mason_nato_can_register(game))

    def test_godfather_dead_nato_absent_saboteur_shoot_only(self) -> None:
        gm = GameManager()
        game = _mason_game(gm, n=12)
        gm.add_player(game, _p(1, "GF", Role.GODFATHER, alive=False))
        gm.add_player(game, _p(3, "Sab", Role.SABOTEUR))
        gm.add_player(game, _p(4, "Spy", Role.SPY))
        actions = _available_mafia_actions(game, gm)
        self.assertEqual(actions, [MAFIA_ACTION_SHOT])
        panel = resolve_mafia_night1_panel_recipients(game)
        self.assertEqual([p.user_id for p in panel], [3])

    def test_godfather_dead_nato_dead_saboteur_shoot_only(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        game.players[1].is_alive = False
        game.players[2].is_alive = False
        actions = _available_mafia_actions(game, gm)
        self.assertEqual(actions, [MAFIA_ACTION_SHOT])
        panel = resolve_mafia_night1_panel_recipients(game)
        self.assertEqual([p.user_id for p in panel], [3])


class MasonRoom86NatoNightStartFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_nato_receives_menu_when_godfather_dead(self) -> None:
        from bot.no_host_mafia_night1 import start_no_host_night1_mafia_flow

        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        game.players[1].is_alive = False
        game.bazpors_host_mode = "no_host"
        bot = AsyncMock()
        sent: list[tuple[int, str, object]] = []

        async def _capture(_bot, _game, uid, text, kb, _gm):
            sent.append((uid, text, kb))

        with patch(
            "bot.no_host_mafia_night1._send_mafia_prompt",
            side_effect=_capture,
        ):
            await start_no_host_night1_mafia_flow(bot, game, gm)

        self.assertTrue(game.no_host_mafia_night1_flow_active)
        self.assertEqual(game.no_host_mafia_night1_chooser_uid, 2)
        self.assertEqual(len(sent), 1)
        uid, text, kb = sent[0]
        self.assertEqual(uid, 2)
        self.assertIn("یکی از گزینه‌های زیر را انتخاب کنید", text)
        labels = [btn.text for row in kb.inline_keyboard for btn in row]
        self.assertIn("🔫 شلیک", labels)
        self.assertIn("🎭 ناتویی", labels)

    async def test_nato_direct_shot_when_nato_already_used(self) -> None:
        from bot.no_host_mafia_night1 import start_no_host_night1_mafia_flow

        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        game.players[1].is_alive = False
        game.mason_nato_used = True
        game.bazpors_host_mode = "no_host"
        bot = AsyncMock()
        sent: list[tuple[int, str]] = []

        async def _capture(_bot, _game, uid, text, _kb):
            sent.append((uid, text))

        with patch(
            "bot.no_host_mafia_shot._sync_mafia_shot_mirror_panel",
            side_effect=_capture,
        ), patch(
            "bot.no_host_mafia_night1.maybe_start_shiad_parallel_night_panels",
            new_callable=AsyncMock,
        ):
            await start_no_host_night1_mafia_flow(bot, game, gm)

        self.assertTrue(game.no_host_mafia_night1_done)
        self.assertEqual(game.no_host_mafia_night1_chosen_action, MAFIA_ACTION_SHOT)
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][0], 2)
        self.assertIn("شلیک", sent[0][1])


class MasonNatoOncePerGameGodfatherDeadTests(unittest.IsolatedAsyncioTestCase):
    async def test_nato_can_start_after_godfather_death(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _populate_mason_mafia_team(game, gm)
        game.players[1].is_alive = False
        game.bazpors_host_mode = "no_host"
        game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_NATO
        self.assertTrue(mason_nato_can_register(game))

        with patch(
            "bot.no_host_mafia_nato.broadcast_to_alive_players",
            new_callable=AsyncMock,
        ), patch(
            "bot.no_host_mafia_nato.register_mirror_prompt_pair",
            new_callable=AsyncMock,
        ) as register:
            await start_no_host_mafia_nato_flow(AsyncMock(), game, gm)

        register.assert_awaited_once()
        self.assertTrue(game.no_host_mafia_nato_flow_active)
        self.assertFalse(game.mason_nato_used)


class RegressionUnchangedScenarios(unittest.TestCase):
    def test_bazpors_shot_chooser_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(30, "B", Role.MAFIA_BOSS))
        gm.add_player(game, _p(20, "N", Role.NATO))
        ch = resolve_mafia_shot_chooser(game)
        assert ch is not None
        self.assertEqual(ch.user_id, 30)

    def test_mozakere_menu_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(30, "B", Role.MAFIA_BOSS))
        from bot.no_host_mafia_night1 import build_mozakere_mafia_operation_menu_html

        self.assertIn("مذاکره", build_mozakere_mafia_operation_menu_html(game))

    def test_bazpors_nato_guess_roles_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(1, "Det", Role.DETECTIVE))
        from bot.roles.nato import guess_roles_in_room

        roles = guess_roles_in_room(game)
        self.assertIn(Role.DETECTIVE, roles)
        self.assertNotIn(Role.COMMANDER, roles)


class MasonNightStateResetTests(unittest.TestCase):
    def test_clear_night_state_keeps_used_flag(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.mason_nato_used = True
        game.mason_nato_confirmed = True
        game.mason_nato_guess_role = Role.DOCTOR
        clear_mason_nato_night_state(game)
        self.assertTrue(game.mason_nato_used)
        self.assertFalse(game.mason_nato_confirmed)
        self.assertIsNone(game.mason_nato_guess_role)


if __name__ == "__main__":
    unittest.main()
