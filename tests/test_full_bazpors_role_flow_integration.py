"""End-to-end integration — full Bazpors 13p roster, no_host + semi_auto."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    NS_DOC,
    NS_HUNTER,
    NS_SNIPER,
    NIGHT_ACTIONS,
    NIGHT_START,
    _apply_night_resolution,
    _compose_full_night_report,
    _enter_night_from_day_end,
    build_host_message_and_keyboard,
    process_narrator_callback,
)
from bot.game import GameManager, bazpors_roles_for_count
from bot.models import Game, Phase, Player, Role
from bot.no_host_doctor_night import _commit_doctor_pick
from bot.no_host_night_ready import all_no_host_parallel_night_ready
from bot.no_host_night_resolve import (
    _apply_no_host_night_resolution,
    build_no_host_day_started_broadcast_html,
)
from bot.roles import (
    detective,
    doctor,
    hunter,
    interrogator,
    nato,
    ruintan,
    shiad,
    sniper,
)
from bot.roles.registry import (
    BAZPORS_SCENARIO_ROLES,
    find_alive_role_holder,
    get_role_module,
    is_registered_role,
    require_role_module,
    substep_to_role,
)


def _p(uid: int, seat: int, name: str, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=name,
        username=None,
        role=role,
        seat=seat,
        is_alive=alive,
    )


def make_full_bazpors_13p_game(*, host_mode: str) -> Game:
    """۱۳ نفره با تمام نقش‌های بازپرس — مطابق bazpors_roles_for_count(13)."""
    role_by_seat = {
        1: Role.MAFIA_BOSS,
        2: Role.NATO,
        3: Role.SHIAD,
        4: Role.MAFIA_BASIC,
        5: Role.HUNTER,
        6: Role.INTERROGATOR,
        7: Role.DETECTIVE,
        8: Role.DOCTOR,
        9: Role.RUINTAN,
        10: Role.SNIPER,
        11: Role.CITIZEN,
        12: Role.CITIZEN,
        13: Role.CITIZEN,
    }
    players = {
        -seat: _p(-seat, seat, f"P{seat}", role)
        for seat, role in role_by_seat.items()
    }
    game = Game(
        room_code="INT13",
        host_id=1,
        scenario_name="bazpors",
        players=players,
        max_players=13,
    )
    game.bazpors_host_mode = host_mode
    game.mafia_ids = {-1, -2, -3, -4}
    game.bazpors_narrator_night_count = 1
    game.bazpors_alive_at_night_start = {
        uid: p.is_alive for uid, p in game.players.items()
    }
    if host_mode == "no_host":
        game.no_host_assistant_narrator_active = True
        game.bot_assistant_user_id = 1
    return game


def _arm_semi_auto_night_actions(game: Game, gm: GameManager) -> None:
    game.bazpors_narrator_step = NIGHT_ACTIONS
    game.bazpors_narrator_host_day = 1

    hunter.commit_pick(game, -4)
    game.bazpors_mafia_shot_registered = True
    game.actions.mafia_target = -11
    shiad.commit_pick(game, -13, gm=gm, semi_auto=True)
    detective.commit_pick(game, -2)
    game.bazpors_det_ack_positive = True
    doctor.commit_pick(game, -9)
    interrogator.commit_first_nominee(game, -9)
    interrogator.commit_second_nominee(game, -10)
    game.bazpors_interrog_night_finished = True
    game.bazpors_interrog_ready_for_day = True
    sniper.clear_pick(game)


def _arm_no_host_night_actions(game: Game) -> None:
    hunter.apply_pick(game, -4)
    game.bazpors_mafia_shot_registered = True
    game.actions.mafia_target = -11
    shiad.commit_pick(game, -13)
    detective.commit_pick(game, -2)
    game.bazpors_det_ack_positive = True
    _commit_doctor_pick(game, -9)
    interrogator.commit_first_nominee(game, -12)
    interrogator.commit_second_nominee(game, -13)
    game.bazpors_interrog_night_finished = True
    game.no_host_interrog_pick_confirmed = True
    sniper.commit_pick(game, None)
    game.no_host_doctor_pick_confirmed = True
    game.no_host_detective_pick_confirmed = True
    game.no_host_shiad_pick_confirmed = True
    game.no_host_sniper_pick_confirmed = True
    game.no_host_night1_hunter_done = True
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_shot_done = True
    game.no_host_citizen_night_confirmed_uids = [-11, -12, -13]
    game.no_host_ruintan_night_confirmed = True


class RegistryFullRosterTests(unittest.TestCase):
    def test_every_dealt_role_registered(self) -> None:
        dealt = set(bazpors_roles_for_count(13))
        self.assertTrue(BAZPORS_SCENARIO_ROLES >= dealt)
        for role in dealt:
            with self.subTest(role=role):
                self.assertTrue(is_registered_role(role))
                self.assertIsNotNone(get_role_module(role))

    def test_require_role_module_matches_phase_a_modules(self) -> None:
        self.assertIs(require_role_module(Role.DOCTOR), doctor)
        self.assertIs(require_role_module(Role.DETECTIVE), detective)
        self.assertIs(require_role_module(Role.MAFIA_BASIC), __import__(
            "bot.roles.simple_mafia", fromlist=["simple_mafia"]
        ))


class SemiAutoFullNightFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_night_actions_commit_and_resolve(self) -> None:
        game = make_full_bazpors_13p_game(host_mode="semi_auto")
        _arm_semi_auto_night_actions(game, self.gm)

        alive_before = dict(game.bazpors_alive_at_night_start)
        _apply_night_resolution(game, self.gm)

        self.assertTrue(game.players[-9].is_alive)
        self.assertFalse(game.players[-11].is_alive)
        self.assertTrue(game.bazpors_interrog_ready_for_day)
        report = _compose_full_night_report(game, self.gm, alive_before)
        self.assertIn("گزارش", report)

    def test_callback_acts_still_route(self) -> None:
        game = make_full_bazpors_13p_game(host_mode="semi_auto")
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DOC
        doctor.commit_pick(game, -8)
        err = process_narrator_callback(game, self.gm, "dxd", 0, "")
        self.assertIsNone(err)

        game.bazpors_night_substep = NS_HUNTER
        err = process_narrator_callback(game, self.gm, "hs", 0, "")
        self.assertIsNone(err)

        game.bazpors_night_substep = NS_SNIPER
        err = process_narrator_callback(game, self.gm, "sn_skip", 0, "")
        self.assertIsNone(err)

    def test_registry_substep_and_alive_lookups(self) -> None:
        game = make_full_bazpors_13p_game(host_mode="semi_auto")
        self.assertEqual(substep_to_role(NS_DOC), Role.DOCTOR)
        self.assertEqual(find_alive_role_holder(game, Role.DOCTOR).user_id, -8)

    def test_persian_host_panels_unchanged(self) -> None:
        game = make_full_bazpors_13p_game(host_mode="semi_auto")
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.bazpors_night_substep = NS_DOC
        body, kb = build_host_message_and_keyboard(game, self.gm)
        self.assertIn("پزشک", body)
        self.assertIn("نجات نداد", " ".join(
            btn.text for row in (kb.inline_keyboard if kb else []) for btn in row
        ))

    def test_nato_guess_commits_without_crash(self) -> None:
        game = make_full_bazpors_13p_game(host_mode="semi_auto")
        ok = nato.commit_guess(game, Role.CITIZEN, -7)
        self.assertFalse(ok)
        self.assertTrue(game.bazpors_nato_action_registered)

    def test_ruintan_survives_mafia_shot(self) -> None:
        game = make_full_bazpors_13p_game(host_mode="semi_auto")
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -9
        _apply_night_resolution(game, self.gm)
        self.assertTrue(game.players[-9].is_alive)
        self.assertTrue(ruintan.mafia_shot_survives(game.players[-9]))

    def test_day_end_transitions_to_night_start(self) -> None:
        game = make_full_bazpors_13p_game(host_mode="semi_auto")
        game.phase = Phase.MANUAL
        game.bazpors_narrator_host_day = 1
        game.bazpors_narrator_night_count = 0
        _enter_night_from_day_end(game)
        self.assertEqual(game.bazpors_narrator_step, NIGHT_START)
        self.assertEqual(game.bazpors_narrator_night_count, 1)


class NoHostFullNightFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gm = GameManager()

    def test_registry_finds_all_single_holder_roles(self) -> None:
        game = make_full_bazpors_13p_game(host_mode="no_host")
        for role in (
            Role.DOCTOR,
            Role.DETECTIVE,
            Role.SHIAD,
            Role.HUNTER,
            Role.SNIPER,
            Role.INTERROGATOR,
            Role.RUINTAN,
            Role.NATO,
            Role.MAFIA_BOSS,
        ):
            with self.subTest(role=role):
                holder = find_alive_role_holder(game, role)
                self.assertIsNotNone(holder)

    def test_night_commits_and_resolve(self) -> None:
        game = make_full_bazpors_13p_game(host_mode="no_host")
        _arm_no_host_night_actions(game)
        _apply_no_host_night_resolution(game, self.gm)

        self.assertTrue(game.players[-9].is_alive)
        self.assertFalse(game.players[-11].is_alive)
        day_html = build_no_host_day_started_broadcast_html(game)
        self.assertIn("روز", day_html)

    def test_ruintan_survives_mafia_shot_no_host(self) -> None:
        game = make_full_bazpors_13p_game(host_mode="no_host")
        game.bazpors_mafia_shot_registered = True
        game.actions.mafia_target = -9
        _apply_no_host_night_resolution(game, self.gm)
        self.assertTrue(game.players[-9].is_alive)

    def test_parallel_ready_after_all_confirmations(self) -> None:
        game = make_full_bazpors_13p_game(host_mode="no_host")
        game.bazpors_narrator_step = NIGHT_ACTIONS
        game.no_host_night_parallel_collect_active = True
        _arm_no_host_night_actions(game)
        self.assertTrue(all_no_host_parallel_night_ready(game))


if __name__ == "__main__":
    unittest.main()
