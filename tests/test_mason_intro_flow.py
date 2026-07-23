"""تست جریان intro/day/night — فقط سناریوی ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.mason_day_ability import (
    build_mason_apache_elim_broadcast_html,
    build_mason_cowboy_elim_broadcast_html,
    mason_eliminated_team_line_fa,
)
from bot.mason_helper_flow import (
    MasonHelperCb,
    build_mason_night_start_html,
    build_mason_vote_start_html,
)
from bot.mason_intro_flow import (
    build_mason_intro_night_civilian_html,
    build_mason_intro_night_mafia_dm_html,
    deliver_mason_intro_night_started_messages,
)
from bot.mason_roles import masoon_roles_for_count
from bot.mason_night_entry import MASON_NIGHT_WAIT_TEXT as WAIT_TEXT
from bot.mason_night_ready import all_mason_parallel_night_ready
from bot.models import Player, Role
from bot.no_host_interrog_day import should_enter_no_host_interrog_day
from bot.roles import mason_apache as ms_ap


def _p(uid: int, name: str, role: Role, *, alive: bool = True, seat: int | None = None) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
        seat=seat,
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
    return game


class MasonIntroDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_apache_gets_civilian_intro(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(11, "Spy", Role.SPY))
        gm.add_player(game, _p(20, "Doc", Role.DOCTOR))
        bot = MagicMock()
        sent: dict[int, str] = {}

        async def _capture(bot_, uid, text, **kw):
            sent[uid] = text

        with patch("bot.mason_intro_flow.safe_send_message", side_effect=_capture):
            await deliver_mason_intro_night_started_messages(bot, game)
        civ = build_mason_intro_night_civilian_html()
        self.assertEqual(sent[10], civ)
        self.assertIn("تیم مافیا", sent[11])
        self.assertEqual(sent[20], civ)

    def test_mafia_intro_excludes_apache_from_list(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(11, "Spy", Role.SPY))
        html_msg = build_mason_intro_night_mafia_dm_html(game)
        self.assertIn("جاسوس", html_msg)
        self.assertNotIn("آپاچی", html_msg)

    def test_other_mafia_still_get_mafia_intro(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        spy = _p(11, "Spy", Role.SPY)
        gm.add_player(game, spy)
        self.assertTrue(ms_ap.apache_receives_mafia_intro(game, spy))


class MasonIntroObserverMirrorTests(unittest.IsolatedAsyncioTestCase):
    """آینهٔ per-player برای ناظر — فقط intro-night ماسون (Room-39 style)."""

    def _room39_style_game(self, gm: GameManager):
        game = _mason_game(gm, n=12)
        game.observer_prompt_status = "registered"
        game.observer_user_id = 999
        game.observer_full_name = "Observer"
        roles = masoon_roles_for_count(12)
        for seat, role in enumerate(roles, start=1):
            uid = 100 + seat
            gm.add_player(
                game,
                _p(uid, f"P{seat}", role, seat=seat),
            )
        return game

    async def test_observer_gets_mirror_for_every_player(self) -> None:
        gm = GameManager()
        game = self._room39_style_game(gm)
        bot = MagicMock()
        sends: list[tuple[int, str]] = []

        async def _capture(bot_, uid, text, **kw):
            sends.append((uid, text))

        with (
            patch("bot.mason_intro_flow.safe_send_message", side_effect=_capture),
            patch("bot.observer_delivery.safe_send_message", side_effect=_capture),
        ):
            await deliver_mason_intro_night_started_messages(bot, game)

        player_uids = [
            uid
            for uid, p in game.players.items()
            if p.is_alive and uid != 900
        ]
        observer_sends = [text for uid, text in sends if uid == 999]
        self.assertEqual(len(observer_sends), len(player_uids))

        civ = build_mason_intro_night_civilian_html()
        mafia = build_mason_intro_night_mafia_dm_html(game)

        def _mirror_for(uid: int) -> str:
            tag = game.players[uid].full_name
            return next(t for u, t in sends if u == 999 and tag in t)

        for uid in player_uids:
            mirror = _mirror_for(uid)
            self.assertIn("ناظر — پیام صندلی", mirror)

        apache_uid = next(
            uid for uid, p in game.players.items() if p.role == Role.APACHE
        )
        self.assertIn(civ, _mirror_for(apache_uid))
        self.assertNotIn("📋 <b>اعضای تیم مافیا:</b>", _mirror_for(apache_uid))

        for uid, p in game.players.items():
            if p.role in (Role.GODFATHER, Role.SABOTEUR, Role.SPY):
                self.assertIn(mafia, _mirror_for(uid))
            elif p.role == Role.APACHE:
                continue
            elif uid in player_uids:
                self.assertIn(civ, _mirror_for(uid))

    async def test_no_generic_civilian_only_observer_copy(self) -> None:
        gm = GameManager()
        game = self._room39_style_game(gm)
        bot = MagicMock()
        sends: list[tuple[int, str]] = []

        async def _capture(bot_, uid, text, **kw):
            sends.append((uid, text))

        with (
            patch("bot.mason_intro_flow.safe_send_message", side_effect=_capture),
            patch("bot.observer_delivery.safe_send_message", side_effect=_capture),
        ):
            await deliver_mason_intro_night_started_messages(bot, game)

        civ = build_mason_intro_night_civilian_html()
        bare_civilian_to_observer = [
            text
            for uid, text in sends
            if uid == 999 and text == civ
        ]
        self.assertEqual(bare_civilian_to_observer, [])

    async def test_bazpors_intro_observer_unchanged(self) -> None:
        from bot.main import (
            build_no_host_intro_night_civilian_html,
            deliver_no_host_intro_night_started_messages,
        )

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.observer_prompt_status = "registered"
        game.observer_user_id = 999
        gm.add_player(game, _p(10, "M1", Role.MAFIA_BOSS, seat=1))
        gm.add_player(game, _p(20, "C1", Role.CITIZEN, seat=2))
        bot = MagicMock()
        sends: list[tuple[int, str]] = []

        async def _capture(bot_, uid, text, **kw):
            sends.append((uid, text))

        with patch("bot.main.safe_send_message", side_effect=_capture):
            await deliver_no_host_intro_night_started_messages(bot, game)

        observer_sends = [text for uid, text in sends if uid == 999]
        self.assertEqual(len(observer_sends), 1)
        self.assertEqual(observer_sends[0], build_no_host_intro_night_civilian_html())
        self.assertNotIn("ناظر — پیام صندلی", observer_sends[0])


class MasonDayAbilityBroadcastTests(unittest.TestCase):
    def test_team_label_never_contains_role_name(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        line = mason_eliminated_team_line_fa(game, 20)
        self.assertIn("شهروندان", line)
        self.assertNotIn("شهروند ساده", line)

    def test_apache_broadcast_mafia_team(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(30, "Spy", Role.SPY))
        msg = build_mason_apache_elim_broadcast_html(game, gm, 30)
        self.assertIn("آپاچی", msg)
        self.assertIn("تیم مافیا", msg)
        self.assertNotIn("جاسوس", msg)

    def test_cowboy_broadcast_town_team(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        msg = build_mason_cowboy_elim_broadcast_html(game, gm, 20)
        self.assertIn("کابوی", msg)
        self.assertIn("شهروندان", msg)


class MasonHelperPanelTextTests(unittest.TestCase):
    def test_vote_start_text(self) -> None:
        self.assertIn("شروع رأی", build_mason_vote_start_html())

    def test_night_start_text(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.bazpors_narrator_night_count = 1
        self.assertIn("شروع شب", build_mason_night_start_html(game))


class MasonNightReadyTests(unittest.TestCase):
    def test_not_ready_until_wait_ok(self) -> None:
        from bot.bazpors_narrator import NIGHT_START

        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        game.no_host_assistant_narrator_active = True
        game.no_host_night_parallel_collect_active = True
        game.bazpors_narrator_step = NIGHT_START
        game.mason_night_saboteur_confirmed = True
        game.mason_night_doctor_confirmed = True
        game.mason_night_sniper_confirmed = True
        game.mason_night_commander_confirmed = True
        game.mason_night_gunner_confirmed = True
        game.mason_night_guardian_confirmed = True
        game.mason_night_mason_confirmed = True
        game.mason_night_detective_confirmed = True
        game.mason_night_natasha_confirmed = True
        game.mason_night_priest_confirmed = True
        game.no_host_mafia_night1_done = True
        game.no_host_mafia_night1_chosen_action = "shot"
        game.no_host_mafia_shot_done = True
        self.assertFalse(all_mason_parallel_night_ready(game))
        game.mason_night_wait_ok_uids = [20]
        self.assertTrue(all_mason_parallel_night_ready(game))


class MasonIsolationRegressionTests(unittest.TestCase):
    def test_bazpors_interrog_not_blocked(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        game.bot_assistant_user_id = 900
        game.no_host_assistant_narrator_active = True
        game.bazpors_interrog_ready_for_day = True
        self.assertTrue(should_enter_no_host_interrog_day(game))

    def test_mason_skips_interrog(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        game.no_host_assistant_narrator_active = True
        game.bazpors_interrog_ready_for_day = True
        self.assertFalse(should_enter_no_host_interrog_day(game))

    def test_mozakere_intro_unchanged(self) -> None:
        from bot.main import build_no_host_intro_night_mafia_dm_html

        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        boss = _p(10, "Boss", Role.MAFIA_BOSS)
        gm.add_player(game, boss)
        html_msg = build_no_host_intro_night_mafia_dm_html(game)
        self.assertIn("مافیا", html_msg)


class MasonFlowIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_intro_night_starts_day_ability_not_vote(self) -> None:
        from bot.main import _execute_no_host_intro_night_start

        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(40, "Cw", Role.COWBOY))
        cb = MagicMock()
        cb.message = MagicMock()
        cb.message.html_text = "panel"
        cb.answer = AsyncMock()
        bot = MagicMock()
        with (
            patch("bot.mason_intro_flow.deliver_mason_intro_night_started_messages", new=AsyncMock()),
            patch("bot.mason_day_ability.dispatch_mason_intro_day_ability_panels", new=AsyncMock()) as day_panels,
            patch("bot.mason_helper_flow.send_mason_vote_start_prompt", new=AsyncMock()) as vote_prompt,
            patch("bot.no_host_phase.no_host_run_day1_end_vote_flow", new=AsyncMock()) as vote_flow,
        ):
            await _execute_no_host_intro_night_start(
                cb, bot, game, 900, 900
            )
        day_panels.assert_awaited_once()
        vote_prompt.assert_awaited_once()
        vote_flow.assert_not_awaited()
        self.assertTrue(game.mason_intro_day_ability_open)

    async def test_apache_elimination_removes_both_immediately(self) -> None:
        from bot.mason_day_ability import _eliminate_apache_and_target

        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        bot = MagicMock()
        with patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            new=AsyncMock(),
        ):
            await _eliminate_apache_and_target(
                bot, game, gm, apache_uid=10, target_uid=20
            )
        self.assertFalse(game.players[10].is_alive)
        self.assertFalse(game.players[20].is_alive)

    async def test_night_entry_uses_wait_text(self) -> None:
        self.assertEqual(WAIT_TEXT, "منتظر اتمام شب باشید.")

    def test_mason_helper_callback_prefix(self) -> None:
        cb = MasonHelperCb(code="MS01", act="go", kind="vote")
        self.assertTrue(cb.pack().startswith("msh:"))


if __name__ == "__main__":
    unittest.main()
