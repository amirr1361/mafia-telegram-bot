"""محافظ همیشه در برابر آپاچی محافظت‌شده تلقی می‌شود — فقط سناریوی ماسون.

Apache targeting the Guardian must reuse the exact same protected-target code
path that runs when Apache attacks a player protected by Guardian the previous
night (Apache leaves solo, Guardian survives).
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from bot.game import GameManager
from bot.mason_day_ability import (
    MASON_APACHE_SOLO_ELIM_BROADCAST_FA,
    _eliminate_apache_and_target,
)
from bot.models import Player, Role
from bot.roles import mason_apache as ms_ap
from bot.roles import mason_guardian as ms_gd


def _p(uid: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        is_alive=alive,
    )


def _mason_game(gm: GameManager, *, n: int = 12):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    return game


class GuardianAlwaysProtectedFromApacheTests(unittest.TestCase):
    def test_guardian_self_is_blocked_even_without_night_pick(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        self.assertIsNone(ms_gd.guardian_current_target(game))
        self.assertTrue(ms_gd.guardian_blocks_apache(game, 30))

    def test_guardian_self_blocked_after_protecting_other(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        ms_gd.commit_mason_guardian_night_pick(game, 20)
        ms_gd.activate_mason_guardian_day_protection(game)
        self.assertTrue(ms_gd.guardian_blocks_apache(game, 30))
        self.assertTrue(ms_gd.guardian_blocks_apache(game, 20))

    def test_dead_guardian_is_not_self_protected(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD, alive=False))
        self.assertFalse(ms_gd.guardian_blocks_apache(game, 30))

    def test_apache_would_not_succeed_against_guardian(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        ms_ap.commit_mason_apache_day_pick(game, 30, confirmed=True)
        self.assertTrue(ms_ap.mason_apache_day_elimination_blocked(game, 30))
        self.assertFalse(ms_ap.mason_apache_day_elimination_would_succeed(game, 30))


class GuardianApacheResolutionReusesProtectionFlow(unittest.IsolatedAsyncioTestCase):
    async def test_apache_targets_guardian_leaves_solo_guardian_survives(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        bot = MagicMock()
        broadcasts: list[str] = []

        async def _capture(_bot, _game, text, **kw):
            broadcasts.append(text)

        with patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            side_effect=_capture,
        ):
            await _eliminate_apache_and_target(
                bot, game, gm, apache_uid=10, target_uid=30
            )

        self.assertFalse(game.players[10].is_alive)
        self.assertTrue(game.players[30].is_alive)
        self.assertEqual(broadcasts, [MASON_APACHE_SOLO_ELIM_BROADCAST_FA])

    async def test_guardian_self_target_matches_protected_target_outcome(self) -> None:
        """Example 1/2: identical outcome to attacking last night's protected player."""
        gm = GameManager()

        # Reference: Apache attacks a normally-protected town player.
        ref_game = _mason_game(gm)
        ref_game.room_code = "REF"
        gm.add_player(ref_game, _p(10, "Ap", Role.APACHE))
        gm.add_player(ref_game, _p(30, "Gd", Role.BODYGUARD))
        gm.add_player(ref_game, _p(20, "T", Role.TOWN_SIMPLE))
        ms_gd.commit_mason_guardian_night_pick(ref_game, 20)
        ms_gd.activate_mason_guardian_day_protection(ref_game)

        # New rule: Apache attacks the Guardian directly.
        new_game = _mason_game(gm)
        new_game.room_code = "NEW"
        gm.add_player(new_game, _p(10, "Ap", Role.APACHE))
        gm.add_player(new_game, _p(30, "Gd", Role.BODYGUARD))
        gm.add_player(new_game, _p(20, "T", Role.TOWN_SIMPLE))

        bot = MagicMock()
        ref_bc: list[str] = []
        new_bc: list[str] = []

        async def _cap_ref(_bot, _game, text, **kw):
            ref_bc.append(text)

        async def _cap_new(_bot, _game, text, **kw):
            new_bc.append(text)

        with patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            side_effect=_cap_ref,
        ):
            await _eliminate_apache_and_target(
                bot, ref_game, gm, apache_uid=10, target_uid=20
            )
        with patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            side_effect=_cap_new,
        ):
            await _eliminate_apache_and_target(
                bot, new_game, gm, apache_uid=10, target_uid=30
            )

        self.assertEqual(ref_bc, new_bc)
        self.assertFalse(ref_game.players[10].is_alive)
        self.assertFalse(new_game.players[10].is_alive)
        self.assertTrue(ref_game.players[20].is_alive)
        self.assertTrue(new_game.players[30].is_alive)


class ExistingApacheBehaviorUnchanged(unittest.IsolatedAsyncioTestCase):
    async def test_apache_targets_unprotected_player_eliminates_both(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        bot = MagicMock()
        broadcasts: list[str] = []

        async def _capture(_bot, _game, text, **kw):
            broadcasts.append(text)

        with patch(
            "bot.mason_day_ability.broadcast_to_alive_players",
            side_effect=_capture,
        ):
            await _eliminate_apache_and_target(
                bot, game, gm, apache_uid=10, target_uid=20
            )

        self.assertFalse(game.players[10].is_alive)
        self.assertFalse(game.players[20].is_alive)
        self.assertNotEqual(broadcasts, [MASON_APACHE_SOLO_ELIM_BROADCAST_FA])

    def test_night_protection_of_other_player_unchanged(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        ms_gd.commit_mason_guardian_night_pick(game, 20)
        self.assertFalse(ms_gd.guardian_blocks_apache(game, 20))
        ms_gd.activate_mason_guardian_day_protection(game)
        self.assertTrue(ms_gd.guardian_blocks_apache(game, 20))
        ms_gd.clear_mason_guardian_day_protection(game)
        self.assertFalse(ms_gd.guardian_blocks_apache(game, 20))

    def test_no_block_for_other_players_without_protection(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "Ap", Role.APACHE))
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        gm.add_player(game, _p(20, "T", Role.TOWN_SIMPLE))
        self.assertFalse(ms_gd.guardian_blocks_apache(game, 20))


class OtherScenariosUnchanged(unittest.TestCase):
    def test_bazpors_guardian_block_returns_false(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        self.assertFalse(ms_gd.guardian_blocks_apache(game, 30))

    def test_mozakere_guardian_block_returns_false(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=12,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(30, "Gd", Role.BODYGUARD))
        self.assertFalse(ms_gd.guardian_blocks_apache(game, 30))


if __name__ == "__main__":
    unittest.main()
