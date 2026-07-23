"""زنجیرهٔ هانتر هنگام خروج با رأی (بازپرسی / پایان روز)."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    Role,
    _apply_night_resolution,
    _effective_hunter_link_uid,
    _eliminate_player,
    _hunter_chain_companion_uid,
    _hunter_chain_warning_html,
    hunter_chain_broadcast_suffix_html,
    hunter_chain_confirm_alert_text,
    hunter_vote_elim_names_html_block,
    hunter_chain_public_disclosure,
)
from bot.game import GameManager
from bot.models import Game, Player


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


class HunterVoteChainTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def _game_with_hunter(self) -> Game:
        return Game(
            room_code="hc",
            host_id=1,
            scenario_name="bazpors",
            players={
                1: _p(1, 1, "هانتر", Role.HUNTER),
                2: _p(2, 2, "مافیا", Role.MAFIA_BASIC),
                3: _p(3, 3, "رییس", Role.MAFIA_BOSS),
                4: _p(4, 4, "شهروند", Role.CITIZEN),
            },
        )

    def test_effective_link_falls_back_to_report(self) -> None:
        game = self._game_with_hunter()
        game.bazpors_hunter_link_uid = None
        game.bazpors_hunter_report_link_uid = 2
        self.assertEqual(_effective_hunter_link_uid(game), 2)

    def test_chain_companion_mafia_basic(self) -> None:
        game = self._game_with_hunter()
        game.bazpors_hunter_link_uid = 2
        self.assertEqual(_hunter_chain_companion_uid(game, 1), 2)
        self.assertIn("زنجیره", _hunter_chain_warning_html(game, self.gm, 1))
        self.assertIn("مافیا", hunter_chain_broadcast_suffix_html(game, self.gm, 1))

    def test_no_chain_to_boss_or_citizen(self) -> None:
        game = self._game_with_hunter()
        game.bazpors_hunter_link_uid = 3
        self.assertIsNone(_hunter_chain_companion_uid(game, 1))
        game.bazpors_hunter_link_uid = 4
        self.assertIsNone(_hunter_chain_companion_uid(game, 1))

    def test_mafia_shot_kills_hunter_linked_to_boss_only(self) -> None:
        """اتاق ۵۷ — شات مافیا روی هانتر وصل به رئیس؛ فقط هانتر خارج می‌شود."""
        game = self._game_with_hunter()
        game.bazpors_hunter_link_uid = 3
        game.bazpors_hunter_report_link_uid = 3
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = 1
        _apply_night_resolution(game, self.gm)
        self.assertFalse(game.players[1].is_alive)
        self.assertTrue(game.players[3].is_alive)

    def test_eliminate_hunter_kills_linked_mafia_basic(self) -> None:
        game = self._game_with_hunter()
        game.bazpors_hunter_link_uid = 2
        game.bazpors_hunter_report_link_uid = 2
        note = _eliminate_player(game, self.gm, 1)
        self.assertFalse(game.players[1].is_alive)
        self.assertFalse(game.players[2].is_alive)
        self.assertTrue(game.players[3].is_alive)
        self.assertIn("زنجیره", note)
        self.assertIsNotNone(hunter_chain_confirm_alert_text(game, self.gm, 1))

    def test_eliminate_hunter_leaves_citizen_link(self) -> None:
        game = self._game_with_hunter()
        game.bazpors_hunter_link_uid = 4
        note = _eliminate_player(game, self.gm, 1)
        self.assertFalse(game.players[1].is_alive)
        self.assertTrue(game.players[4].is_alive)
        self.assertEqual(note, "")
        self.assertIsNone(hunter_chain_confirm_alert_text(game, self.gm, 1))

    def test_interrog_vote_chain_is_public(self) -> None:
        game = self._game_with_hunter()
        game.bazpors_hunter_link_uid = 2
        self.assertTrue(hunter_chain_public_disclosure("interrog_vote"))
        suffix = hunter_chain_broadcast_suffix_html(game, self.gm, 1)
        self.assertIn("مافیا", suffix)
        self.assertNotIn("زنجیرهٔ هانتر", suffix)
        self.assertIsNotNone(hunter_chain_confirm_alert_text(game, self.gm, 1))

    def test_vote_broadcast_names_after_elim_includes_chain_companion(self) -> None:
        """اتاق ۷۸ — پس از حذف، همراه مرده هم در بلوک نام همگانی می‌آید."""
        game = self._game_with_hunter()
        game.bazpors_hunter_link_uid = 2
        game.bazpors_hunter_report_link_uid = 2
        _eliminate_player(game, self.gm, 1, elim_source="day_vote")
        block = hunter_vote_elim_names_html_block(game, self.gm, 1)
        self.assertIn("هانتر", block)
        self.assertIn("مافیا", block)
        self.assertEqual(block.count("💀"), 2)

    def test_night_resolve_chain_is_secret(self) -> None:
        game = self._game_with_hunter()
        game.bazpors_hunter_link_uid = 2
        game.bazpors_hunter_report_link_uid = 2
        self.assertFalse(hunter_chain_public_disclosure("night_resolve"))
        note = _eliminate_player(game, self.gm, 1, elim_source="night_resolve")
        self.assertEqual(note, "")
        self.assertIsNone(game.bazpors_hunter_report_chain_line)
        self.assertIn("زنجیره", game.bazpors_elim_private_extra_html.get(1, ""))
        self.assertFalse(game.players[2].is_alive)
        self.assertIsNone(hunter_chain_confirm_alert_text(game, self.gm, 1, public=False))
