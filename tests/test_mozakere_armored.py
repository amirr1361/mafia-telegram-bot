"""تست زره‌پوش در سناریوی مذاکره."""

from __future__ import annotations

import unittest

from bot.game import GameManager, is_mafia_team
from bot.models import Game, Phase, Player, Role
from bot.roles import mozakere_armored as arm_mod
from bot.roles import mozakere_journalist as jr_mod
from bot.roles.mozakere_negotiator import (
    MozakereNegotiationOutcome,
    commit_mozakere_negotiation,
    is_valid_mozakere_negotiation_target,
)
from bot.bazpors_narrator import (
    _apply_night_resolution,
    _eliminate_and_maybe_win_gate,
    eliminate_player_from_game,
)


def _p(uid: int, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=f"p{uid}",
        username=None,
        role=role,
        is_alive=alive,
    )


def _mozakere_game(*players: Player) -> Game:
    g = Game(
        room_code="MA1",
        host_id=1,
        scenario_name="mozakere",
        phase=Phase.NIGHT,
        max_players=12,
        players={p.user_id: p for p in players},
    )
    g.bazpors_mafia_shot_registered = True
    g.actions.mafia_target = None
    return g


class MozakereArmoredLogicTests(unittest.TestCase):
    def test_armored_is_town_not_mafia(self) -> None:
        self.assertFalse(is_mafia_team(Role.ARMORED))

    def test_armor_active_by_default(self) -> None:
        game = _mozakere_game(_p(40, Role.ARMORED))
        arm = game.players[40]
        self.assertTrue(arm_mod.mozakere_armored_armor_active(game, arm))

    def test_mafia_shot_blocked_while_armor_active(self) -> None:
        game = _mozakere_game(_p(40, Role.ARMORED))
        arm = game.players[40]
        self.assertTrue(arm_mod.mafia_shot_blocked_by_armor(game, arm))

    def test_mafia_shot_not_blocked_after_armor_used(self) -> None:
        game = _mozakere_game(_p(40, Role.ARMORED))
        arm = game.players[40]
        arm_mod.consume_mozakere_armored_armor(game, arm)
        self.assertFalse(arm_mod.mafia_shot_blocked_by_armor(game, arm))

    def test_night_resolution_spares_armored_from_mafia_shot(self) -> None:
        gm = GameManager()
        game = _mozakere_game(_p(40, Role.ARMORED))
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = 40
        _apply_night_resolution(game, gm)
        self.assertTrue(game.players[40].is_alive)

    def test_night_resolution_kills_armored_after_armor_used(self) -> None:
        gm = GameManager()
        game = _mozakere_game(_p(40, Role.ARMORED))
        game.players[40].mozakere_armored_armor_used = True
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = 40
        _apply_night_resolution(game, gm)
        self.assertFalse(game.players[40].is_alive)

    def test_day_vote_survival_consumes_armor(self) -> None:
        gm = GameManager()
        game = _mozakere_game(_p(40, Role.ARMORED))
        eliminated = _eliminate_and_maybe_win_gate(
            game, gm, 40, elim_source="day_vote"
        )
        self.assertFalse(eliminated)
        self.assertTrue(game.players[40].is_alive)
        self.assertTrue(game.players[40].mozakere_armored_armor_used)

    def test_day_vote_armor_consumed_announce_line_text(self) -> None:
        gm = GameManager()
        game = _mozakere_game(_p(40, Role.ARMORED))
        line = arm_mod.day_vote_armor_consumed_announce_line(game, gm, 40)
        self.assertEqual(
            line,
            "🛡️ p40 با نقش زره‌پوش در بازی می‌ماند؛ اما از این پس در برابر شات مافیا "
            "محافظت نمی‌شود و قابل مذاکره شدن هم نخواهد بود.",
        )
        self.assertNotIn("نجات یافت", line)
        self.assertNotIn("زره مصرف شد", line)

    def test_bazpors_day_vote_does_not_use_mozakere_armor_survival(self) -> None:
        gm = GameManager()
        game = Game(
            room_code="BZ1",
            host_id=1,
            scenario_name="bazpors",
            players={40: _p(40, Role.ARMORED)},
        )
        self.assertIsNone(
            arm_mod.try_survive_mozakere_day_vote_elimination(game, gm, 40)
        )
        eliminate_player_from_game(game, gm, 40, elim_source="day_vote")
        self.assertFalse(game.players[40].is_alive)

    def test_day_vote_second_time_eliminates_armored(self) -> None:
        gm = GameManager()
        game = _mozakere_game(_p(40, Role.ARMORED))
        game.players[40].mozakere_armored_armor_used = True
        eliminate_player_from_game(game, gm, 40, elim_source="day_vote")
        self.assertFalse(game.players[40].is_alive)

    def test_negotiation_valid_with_active_armor(self) -> None:
        game = _mozakere_game(_p(40, Role.ARMORED))
        self.assertTrue(is_valid_mozakere_negotiation_target(game, game.players[40]))

    def test_negotiation_invalid_after_armor_used(self) -> None:
        game = _mozakere_game(_p(40, Role.ARMORED))
        arm_mod.consume_mozakere_armored_armor(game, game.players[40])
        self.assertFalse(is_valid_mozakere_negotiation_target(game, game.players[40]))

    def test_successful_negotiation_on_armored(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(10, Role.MAFIA_NEGOTIATOR))
        gm.add_player(game, _p(20, Role.MAFIA_BOSS, alive=False))
        gm.add_player(game, _p(40, Role.ARMORED))
        game.mafia_ids.update({10, 20})
        result = commit_mozakere_negotiation(game, game.players[10], game.players[40])
        self.assertEqual(result.outcome, MozakereNegotiationOutcome.SUCCESS)
        self.assertIn(40, game.mozakere_mafia_recruit_ids)

    def test_failed_negotiation_on_armored_with_spent_armor(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(game, _p(10, Role.MAFIA_NEGOTIATOR))
        gm.add_player(game, _p(20, Role.MAFIA_BOSS, alive=False))
        gm.add_player(game, _p(40, Role.ARMORED))
        game.mafia_ids.update({10, 20})
        arm_mod.consume_mozakere_armored_armor(game, game.players[40])
        result = commit_mozakere_negotiation(game, game.players[10], game.players[40])
        self.assertEqual(result.outcome, MozakereNegotiationOutcome.INVALID_TARGET)
        self.assertNotIn(40, game.mozakere_mafia_recruit_ids)

    def test_journalist_positive_on_recruited_armored(self) -> None:
        game = _mozakere_game(_p(40, Role.ARMORED))
        game.mozakere_mafia_recruit_ids.add(40)
        result = jr_mod.evaluate_check(game, 40)
        self.assertTrue(result.is_positive)

    def test_bazpors_armored_logic_inert(self) -> None:
        game = Game(
            room_code="BZ1",
            host_id=1,
            scenario_name="bazpors",
            players={40: _p(40, Role.ARMORED)},
        )
        arm = game.players[40]
        self.assertFalse(arm_mod.is_mozakere_armored(game, arm))
        self.assertFalse(arm_mod.mafia_shot_blocked_by_armor(game, arm))


if __name__ == "__main__":
    unittest.main()
