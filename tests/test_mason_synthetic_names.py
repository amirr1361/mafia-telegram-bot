"""نام نمایشی بازیکنان ساختگی — فقط سناریوی ماسون."""

from __future__ import annotations

import unittest

from bot.game import (
    GameManager,
    SYNTHETIC_PLAYER_NAME_POOL,
    is_synthetic_player_uid,
    mozakere_role_label_fa,
    role_label_fa,
    scenario_role_label_fa,
    synthetic_player_base_name,
)
from bot.mason_synthetic_names import (
    MASON_SYNTHETIC_NAME_SEP,
    append_mason_role_labels_to_synthetic_players,
)
from bot.models import Player, Role


def _mason_game(gm: GameManager, *, n: int = 12):
    game = gm.create_game(
        host_id=1,
        scenario_name="masoon",
        max_players=n,
        bazpors_host_mode="no_host",
    )
    assert game is not None
    return game


class MasonSyntheticNameTests(unittest.TestCase):
    def test_synthetic_players_get_role_suffix_after_assign(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(
            game,
            Player(user_id=1, full_name="Creator", username=None),
        )
        self.assertIsNone(gm.fill_no_host_synthetic_lobby(game))
        gm.assign_roles(game)
        for p in game.players.values():
            if not is_synthetic_player_uid(p.user_id):
                continue
            self.assertIsNotNone(p.role)
            base = synthetic_player_base_name(p.full_name)
            self.assertIn(base, SYNTHETIC_PLAYER_NAME_POOL)
            self.assertEqual(
                p.full_name,
                f"{base}{MASON_SYNTHETIC_NAME_SEP}{scenario_role_label_fa(game, p.role)}",
            )

    def test_real_players_unchanged(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(
            game,
            Player(user_id=1, full_name="امیر", username=None),
        )
        self.assertIsNone(gm.fill_no_host_synthetic_lobby(game))
        gm.assign_roles(game)
        self.assertEqual(game.players[1].full_name, "امیر")

    def test_idempotent_no_double_append(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        uid = -920001
        gm.add_player(
            game,
            Player(
                user_id=uid,
                full_name="امیر",
                username=None,
                role=Role.APACHE,
            ),
        )
        append_mason_role_labels_to_synthetic_players(game)
        first = game.players[uid].full_name
        self.assertEqual(first, f"امیر{MASON_SYNTHETIC_NAME_SEP}آپاچی")
        append_mason_role_labels_to_synthetic_players(game)
        self.assertEqual(game.players[uid].full_name, first)

    def test_base_name_strips_mason_suffix(self) -> None:
        self.assertEqual(
            synthetic_player_base_name("امیر - آپاچی"),
            "امیر",
        )
        self.assertEqual(
            synthetic_player_base_name("امیر-شیاد"),
            "امیر",
        )


class BazporsMozakereSyntheticNameRegressionTests(unittest.TestCase):
    def test_bazpors_synthetic_format_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        self.assertIsNone(gm.fill_bazpors_semi_auto_synthetic_lobby(game))
        gm.assign_roles(game)
        for p in game.players.values():
            if not is_synthetic_player_uid(p.user_id):
                continue
            base = p.full_name.split("-", 1)[0]
            self.assertIn(base, SYNTHETIC_PLAYER_NAME_POOL)
            self.assertNotIn(MASON_SYNTHETIC_NAME_SEP, p.full_name)
            self.assertEqual(
                p.full_name,
                f"{base}-{role_label_fa(p.role)}",
            )

    def test_mozakere_synthetic_format_unchanged(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="mozakere",
            max_players=10,
            bazpors_host_mode="no_host",
        )
        assert game is not None
        gm.add_player(
            game,
            Player(user_id=1, full_name="Host", username=None),
        )
        self.assertIsNone(gm.fill_no_host_synthetic_lobby(game))
        gm.assign_roles(game)
        for p in game.players.values():
            if not is_synthetic_player_uid(p.user_id):
                continue
            base = synthetic_player_base_name(p.full_name)
            self.assertIn(base, SYNTHETIC_PLAYER_NAME_POOL)
            self.assertNotIn(MASON_SYNTHETIC_NAME_SEP, p.full_name)
            self.assertEqual(
                p.full_name,
                f"{base}-{mozakere_role_label_fa(p.role)}",
            )

    def test_mason_helper_noop_on_bazpors(self) -> None:
        gm = GameManager()
        game = gm.create_game(
            host_id=1,
            scenario_name="bazpors",
            max_players=10,
            bazpors_host_mode="semi_auto",
        )
        assert game is not None
        self.assertIsNone(gm.fill_bazpors_semi_auto_synthetic_lobby(game))
        gm.assign_roles(game)
        before = {
            uid: p.full_name
            for uid, p in game.players.items()
            if is_synthetic_player_uid(uid)
        }
        append_mason_role_labels_to_synthetic_players(game)
        after = {
            uid: p.full_name
            for uid, p in game.players.items()
            if is_synthetic_player_uid(uid)
        }
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
