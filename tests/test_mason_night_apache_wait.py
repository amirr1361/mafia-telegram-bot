"""تست حذف پیام مافیا از آپاچی و پنل انتظار شب — فقط ماسون."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager, is_synthetic_player_uid
from bot.mason_night_entry import (
    MASON_NIGHT_WAIT_TEXT,
    _alive_players_for_wait_panels,
    _dispatch_mason_wait_panels,
    dispatch_mason_night_wait_ok,
    night_action_holder_uids,
)
from bot.mason_night_ready import _waiters_ready
from bot.models import Player, Role
from bot.no_host_mafia_nato import _broadcast_nato_wait_to_alive
from bot.no_host_mafia_night1 import notify_all_alive_mafia_team
from bot.roles import mason_apache as ms_ap


def _p(
    uid: int,
    name: str,
    role: Role,
    *,
    alive: bool = True,
    seat: int | None = None,
) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
        seat=seat,
    )


def _mason_game(gm: GameManager, *, n: int = 14):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    game.observer_prompt_status = "registered"
    game.observer_user_id = 999
    game.bot_assistant_user_id = 900
    game.no_host_assistant_narrator_active = True
    game.bazpors_narrator_step = "night_start"
    return game


def _room39_populate(game, gm: GameManager) -> None:
    roles = [
        (1, "GF", Role.GODFATHER),
        (2, "NATO", Role.NATO),
        (3, "Sab", Role.SABOTEUR),
        (4, "Spy", Role.SPY),
        (5, "Apache", Role.APACHE),
        (6, "Doc", Role.DOCTOR),
        (7, "Sniper", Role.SNIPER),
        (8, "Cmd", Role.COMMANDER),
        (9, "Mason", Role.MASON),
        (10, "Gun", Role.GUNMAN),
        (11, "Guard", Role.BODYGUARD),
        (12, "Cowboy", Role.COWBOY),
        (13, "Ruintan", Role.RUINTAN),
        (14, "Simple", Role.TOWN_SIMPLE),
    ]
    for seat, name, role in roles:
        gm.add_player(game, _p(100 + seat, name, role, seat=seat))


class MasonApacheMafiaMessageExclusionTests(unittest.IsolatedAsyncioTestCase):
    async def test_apache_excluded_from_mafia_operation_notify(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _room39_populate(game, gm)
        bot = MagicMock()
        sent: list[int] = []

        async def _capture(*args, **kw):
            sent.append(args[2])

        text = (
            "🌙 تیم مافیا: <b>🔫 شلیک</b> انتخاب شد.\n"
            "<i>تا پایان فاز شب منتظر بمانید.</i>"
        )
        with patch(
            "bot.no_host_mafia_night1.deliver_no_host_player_game_copy",
            side_effect=_capture,
        ), patch(
            "bot.no_host_mafia_night1.sync_mafia_mirror_panel",
            new=AsyncMock(),
        ):
            await notify_all_alive_mafia_team(bot, game, text)

        apache_uid = 105
        spy_uid = 104
        self.assertNotIn(apache_uid, sent)
        self.assertIn(spy_uid, sent)

    async def test_apache_included_in_nato_wait_public_broadcast(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _room39_populate(game, gm)
        bot = MagicMock()
        sent: list[int] = []

        async def _capture(*args, **kw):
            sent.append(args[2])

        with patch(
            "bot.observer_delivery.deliver_no_host_player_game_copy",
            side_effect=_capture,
        ):
            await _broadcast_nato_wait_to_alive(bot, game)

        apache_uid = 105
        town_uid = 114
        self.assertIn(apache_uid, sent)
        self.assertIn(town_uid, sent)

    def test_mason_receives_mafia_private_message_helper(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        apache = _p(105, "Apache", Role.APACHE)
        spy = _p(104, "Spy", Role.SPY)
        gm.add_player(game, apache)
        gm.add_player(game, spy)
        self.assertFalse(ms_ap.mason_receives_mafia_private_message(game, apache))
        self.assertTrue(ms_ap.mason_receives_mafia_private_message(game, spy))


class MasonNoActionWaitPanelTests(unittest.IsolatedAsyncioTestCase):
    async def test_synthetic_no_action_players_get_observer_mirror(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        synthetic_apache = -920010
        synthetic_spy = -920011
        gm.add_player(game, _p(101, "GF", Role.GODFATHER))
        gm.add_player(game, _p(synthetic_apache, "SynAp", Role.APACHE))
        gm.add_player(game, _p(synthetic_spy, "SynSpy", Role.SPY))
        bot = MagicMock()
        registered: list[tuple[int, str]] = []

        async def _capture_register(
            bot_,
            game_,
            player_uid,
            ui_key,
            text,
            kb,
            **kw,
        ):
            registered.append((player_uid, text))

        with patch(
            "bot.mason_night_entry.register_mirror_prompt_pair",
            side_effect=_capture_register,
        ):
            await _dispatch_mason_wait_panels(bot, game)

        uids = {uid for uid, _ in registered}
        self.assertIn(synthetic_apache, uids)
        self.assertIn(synthetic_spy, uids)
        for _, text in registered:
            self.assertEqual(text, MASON_NIGHT_WAIT_TEXT)

    def test_wait_readiness_includes_synthetic_players(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        synthetic_apache = -920010
        gm.add_player(game, _p(101, "GF", Role.GODFATHER))
        gm.add_player(game, _p(synthetic_apache, "SynAp", Role.APACHE))
        game.mason_night_wait_ok_uids = []
        self.assertFalse(_waiters_ready(game))
        game.mason_night_wait_ok_uids = [synthetic_apache]
        self.assertTrue(_waiters_ready(game))

    def test_alive_players_for_wait_includes_synthetic(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        syn = -920010
        gm.add_player(game, _p(syn, "Syn", Role.APACHE))
        uids = [p.user_id for p in _alive_players_for_wait_panels(game)]
        self.assertIn(syn, uids)
        self.assertTrue(is_synthetic_player_uid(syn))

    async def test_observer_ok_for_synthetic_wait_panel(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        syn = -920010
        gm.add_player(game, _p(101, "GF", Role.GODFATHER))
        gm.add_player(game, _p(syn, "SynAp", Role.APACHE))
        cb = MagicMock()
        cb.answer = AsyncMock()
        bot = MagicMock()
        with patch(
            "bot.observer_delivery.update_mirror_prompt_pair",
            new=AsyncMock(),
        ), patch(
            "bot.mason_night_ready.maybe_finish_mason_parallel_night",
            new=AsyncMock(),
        ):
            await dispatch_mason_night_wait_ok(
                cb,
                bot,
                game,
                gm,
                as_uid=syn,
                actor_uid=999,
            )
        self.assertIn(syn, game.mason_night_wait_ok_uids)

    def test_apache_not_night_action_holder(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        _room39_populate(game, gm)
        holders = night_action_holder_uids(game)
        self.assertNotIn(105, holders)


class BazporsMafiaNotifyRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_bazpors_mafia_notify_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(10, "Boss", Role.MAFIA_BOSS))
        gm.add_player(game, _p(11, "M1", Role.MAFIA_BASIC))
        bot = MagicMock()
        sent: list[int] = []

        async def _capture(*args, **kw):
            sent.append(args[2])

        with patch(
            "bot.no_host_mafia_night1.deliver_no_host_player_game_copy",
            side_effect=_capture,
        ), patch(
            "bot.no_host_mafia_night1.sync_mafia_mirror_panel",
            new=AsyncMock(),
        ):
            await notify_all_alive_mafia_team(bot, game, "test")

        self.assertEqual(set(sent), {10, 11})


if __name__ == "__main__":
    unittest.main()
