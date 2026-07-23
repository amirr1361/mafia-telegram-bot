"""مصونیت رویین‌تن — فقط سناریوی ماسون (شات مافیا و اسنایپر/فرمانده)."""

from __future__ import annotations

import unittest

from bot.game import GameManager
from bot.mason_night_resolve import apply_mason_night_resolution
from bot.models import Player, Role
from bot.roles import mason_commander as ms_cmd
from bot.roles import mason_doctor as ms_doc
from bot.roles import mason_sniper as ms_sn
from bot.roles.night_state import mafia_night_state


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


class MasonRuintanMafiaShotImmunityTests(unittest.TestCase):
    def test_mafia_shot_does_not_kill_ruintan_without_doctor(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "M", Role.MAFIA_BASIC))
        gm.add_player(game, _p(13, "Ruintan", Role.RUINTAN))
        mafia_night_state(game).commit_shot(13)
        apply_mason_night_resolution(game, gm)
        self.assertTrue(game.players[13].is_alive)

    def test_mafia_shot_still_kills_others(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "M", Role.MAFIA_BASIC))
        gm.add_player(game, _p(20, "Town", Role.TOWN_SIMPLE))
        mafia_night_state(game).commit_shot(20)
        apply_mason_night_resolution(game, gm)
        self.assertFalse(game.players[20].is_alive)


class MasonRuintanSniperImmunityTests(unittest.TestCase):
    def test_sniper_selection_does_not_kill_ruintan(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(13, "Ruintan", Role.RUINTAN))
        ms_sn.commit_mason_sniper_night_selection(game, [13])
        game.mason_commander_night_approved_uids = [13]
        apply_mason_night_resolution(game, gm)
        self.assertTrue(game.players[13].is_alive)

    def test_commander_approved_shot_does_not_kill_ruintan(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(50, "Sn", Role.SNIPER))
        gm.add_player(game, _p(40, "Cmd", Role.COMMANDER))
        gm.add_player(game, _p(13, "Ruintan", Role.RUINTAN))
        ms_sn.commit_mason_sniper_night_selection(game, [13])
        ms_cmd.commit_mason_commander_approval(game, [13])
        self.assertEqual(ms_sn.mason_approved_shots_that_kill(game), [])
        apply_mason_night_resolution(game, gm)
        self.assertTrue(game.players[13].is_alive)

    def test_doctor_save_not_required_for_ruintan(self) -> None:
        gm = GameManager()
        game = _mason_game(gm)
        gm.add_player(game, _p(10, "M", Role.MAFIA_BASIC))
        gm.add_player(game, _p(40, "Doc", Role.DOCTOR))
        gm.add_player(game, _p(13, "Ruintan", Role.RUINTAN))
        mafia_night_state(game).commit_shot(13)
        self.assertFalse(
            ms_doc.mason_mafia_shot_blocked_by_doctor_save(game, 13)
        )
        apply_mason_night_resolution(game, gm)
        self.assertTrue(game.players[13].is_alive)


class MasonRuintanIsolationTests(unittest.TestCase):
    def test_bazpors_narrator_resolution_unchanged(self) -> None:
        from pathlib import Path

        text = (Path(__file__).resolve().parents[1] / "bot" / "bazpors_narrator.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_ruintan_role.mafia_shot_survives(pl)", text)
