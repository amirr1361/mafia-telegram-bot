"""تست dispatch/lookup فاز C — no_host و semi_auto از registry."""

from __future__ import annotations

import unittest

from bot.bazpors_narrator import (
    NS_DET,
    NS_DOC,
    NS_HUNTER,
    NS_INT1,
    NS_SHIAD,
    NS_SNIPER,
    _find_alive_role,
    no_host_night_role_player_may_act_bazpors_cb,
)
from bot.models import Game, Player, Role
from bot.roles.registry import (
    NO_HOST_DISPATCH_ROLES,
    SEMI_AUTO_SUBSTEP_TO_ROLE,
    find_alive_role_holder,
    get_role_module,
    require_role_module,
    role_supports_no_host_dispatch,
    role_supports_semi_auto_dispatch,
    substep_to_role,
)


def _p(uid: int, role: Role, *, alive: bool = True) -> Player:
    return Player(
        user_id=uid,
        full_name=f"p{uid}",
        username=None,
        role=role,
        seat=uid,
        is_alive=alive,
    )


def _game(*players: Player) -> Game:
    g = Game(
        room_code="DISP1",
        host_id=1,
        scenario_name="bazpors",
        players={p.user_id: p for p in players},
    )
    g.bazpors_host_mode = "no_host"
    g.no_host_assistant_narrator_active = True
    return g


class RegistryDispatchMetadataTests(unittest.TestCase):
    def test_no_host_dispatch_roles_cover_active_night_roles(self) -> None:
        for role in (
            Role.DOCTOR,
            Role.DETECTIVE,
            Role.SHIAD,
            Role.HUNTER,
            Role.SNIPER,
            Role.INTERROGATOR,
            Role.CITIZEN,
            Role.RUINTAN,
        ):
            with self.subTest(role=role):
                self.assertTrue(role_supports_no_host_dispatch(role))

    def test_semi_auto_substep_mapping(self) -> None:
        self.assertEqual(substep_to_role(NS_DOC), Role.DOCTOR)
        self.assertEqual(substep_to_role(NS_DET), Role.DETECTIVE)
        self.assertEqual(substep_to_role(NS_SHIAD), Role.SHIAD)
        self.assertEqual(substep_to_role(NS_HUNTER), Role.HUNTER)
        self.assertEqual(substep_to_role(NS_SNIPER), Role.SNIPER)
        self.assertEqual(substep_to_role(NS_INT1), Role.INTERROGATOR)
        self.assertIsNone(substep_to_role("ns_unknown"))

    def test_semi_auto_support_flags(self) -> None:
        self.assertTrue(role_supports_semi_auto_dispatch(Role.DOCTOR))
        self.assertFalse(role_supports_semi_auto_dispatch(Role.KIDNAPPER))

    def test_require_role_module_matches_get(self) -> None:
        self.assertIs(
            require_role_module(Role.DOCTOR),
            get_role_module(Role.DOCTOR),
        )


class RegistryAliveLookupParityTests(unittest.TestCase):
    def test_find_alive_role_holder_matches_shim_for_registered_roles(self) -> None:
        game = _game(
            _p(1, Role.DOCTOR),
            _p(2, Role.DETECTIVE),
            _p(3, Role.SHIAD),
        )
        for role in (Role.DOCTOR, Role.DETECTIVE, Role.SHIAD):
            with self.subTest(role=role):
                self.assertEqual(
                    find_alive_role_holder(game, role),
                    _find_alive_role(game, role),
                )

    def test_unknown_unregistered_role_uses_exact_match_fallback(self) -> None:
        game = _game(_p(1, Role.KIDNAPPER))
        self.assertIs(get_role_module(Role.KIDNAPPER), None)
        holder = find_alive_role_holder(game, Role.KIDNAPPER)
        self.assertIsNotNone(holder)
        assert holder is not None
        self.assertEqual(holder.user_id, 1)


class NoHostInterrogatorDispatchTests(unittest.TestCase):
    def test_interrogator_may_act_on_int1_substep(self) -> None:
        game = _game(_p(10, Role.INTERROGATOR))
        game.bazpors_host_mode = "no_host"
        game.bazpors_narrator_step = "night_actions"
        game.bazpors_night_substep = NS_INT1
        self.assertTrue(no_host_night_role_player_may_act_bazpors_cb(game, 10))
        self.assertFalse(no_host_night_role_player_may_act_bazpors_cb(game, 99))

    def test_passive_citizen_not_in_semi_auto_substep_map(self) -> None:
        self.assertNotIn(Role.CITIZEN, SEMI_AUTO_SUBSTEP_TO_ROLE.values())
        self.assertIn(Role.CITIZEN, NO_HOST_DISPATCH_ROLES)
