"""تست bot/roles/registry.py — فاز C مرحله ۱."""

from __future__ import annotations

import types
import unittest

from bot.game import bazpors_roles_for_count
from bot.models import Game, Player, Role
from bot.roles import (
    detective,
    doctor,
    hunter,
    interrogator,
    mafia_boss,
    mason_apache,
    mason_cowboy,
    mason_guardian,
    mason_fraternity,
    mason_gunner,
    mason_natasha,
    mason_priest,
    mason_saboteur,
    mason_spy,
    mozakere_negotiator,
    mozakere_journalist,
    mozakere_armored,
    nato,
    ruintan,
    shiad,
    simple_citizen,
    simple_mafia,
    sniper,
)
from bot.roles.registry import (
    BAZPORS_SCENARIO_ROLES,
    ROLE_ALIASES,
    ROLE_CAPABILITIES,
    find_alive_player,
    find_alive_players,
    find_alive_role_holder,
    get_role_module,
    is_registered_role,
    registered_roles,
    require_role_module,
    resolve_registered_role,
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
    return Game(
        room_code="REG1",
        host_id=1,
        scenario_name="bazpors",
        players={p.user_id: p for p in players},
    )


class RoleRegistryMappingTests(unittest.TestCase):
    def test_every_capability_module_is_module_type(self) -> None:
        for role, mod in ROLE_CAPABILITIES.items():
            with self.subTest(role=role):
                self.assertIsInstance(mod, types.ModuleType)

    def test_expected_modules_mapped(self) -> None:
        expected = {
            Role.DOCTOR: doctor,
            Role.DETECTIVE: detective,
            Role.NATO: nato,
            Role.MAFIA_BOSS: mafia_boss,
            Role.MAFIA_NEGOTIATOR: mozakere_negotiator,
            Role.SHIAD: shiad,
            Role.CITIZEN: simple_citizen,
            Role.MAFIA_BASIC: simple_mafia,
            Role.HUNTER: hunter,
            Role.INTERROGATOR: interrogator,
            Role.RUINTAN: ruintan,
            Role.SNIPER: sniper,
            Role.JOURNALIST: mozakere_journalist,
            Role.ARMORED: mozakere_armored,
            Role.APACHE: mason_apache,
            Role.BODYGUARD: mason_guardian,
            Role.COWBOY: mason_cowboy,
            Role.GUNMAN: mason_gunner,
            Role.SABOTEUR: mason_saboteur,
            Role.MASON: mason_fraternity,
            Role.SPY: mason_spy,
            Role.NATASHA: mason_natasha,
            Role.PRIEST: mason_priest,
        }
        self.assertEqual(ROLE_CAPABILITIES, expected)

    def test_every_bazpors_scenario_role_is_registered(self) -> None:
        for n in (10, 11, 12, 13):
            dealt = set(bazpors_roles_for_count(n))
            with self.subTest(player_count=n):
                self.assertTrue(BAZPORS_SCENARIO_ROLES >= dealt)
                for role in dealt:
                    self.assertTrue(
                        is_registered_role(role),
                        f"{role} from bazpors_roles_for_count({n}) not registered",
                    )

    def test_mafia_aliases_resolve_to_simple_mafia_module(self) -> None:
        for alias in (Role.MAFIA, Role.MAFIA_SIMPLE, Role.MAFIA_SIMPLE_2):
            with self.subTest(alias=alias):
                self.assertEqual(resolve_registered_role(alias), Role.MAFIA_BASIC)
                self.assertIs(get_role_module(alias), simple_mafia)

    def test_unknown_role_not_registered(self) -> None:
        for role in (Role.KIDNAPPER, Role.GUARD, Role.GODFATHER):
            with self.subTest(role=role):
                self.assertFalse(is_registered_role(role))
                self.assertIsNone(get_role_module(role))
                self.assertIsNone(resolve_registered_role(role))

    def test_registered_roles_includes_passive_and_mafia_and_town(self) -> None:
        passive = {Role.CITIZEN, Role.RUINTAN}
        mafia = {Role.MAFIA_BOSS, Role.NATO, Role.MAFIA_BASIC, Role.SHIAD}
        town = {
            Role.DOCTOR,
            Role.DETECTIVE,
            Role.HUNTER,
            Role.INTERROGATOR,
            Role.SNIPER,
        }
        reg = registered_roles()
        self.assertTrue(passive <= reg)
        self.assertTrue(mafia <= reg or Role.MAFIA in reg)
        self.assertTrue(town <= reg)

    def test_alias_keys_in_registered_roles(self) -> None:
        self.assertTrue(set(ROLE_ALIASES) <= registered_roles())


class RoleRegistryLookupTests(unittest.TestCase):
    def test_find_alive_player_single_holder(self) -> None:
        game = _game(_p(1, Role.DOCTOR), _p(2, Role.CITIZEN))
        doc = find_alive_player(game, Role.DOCTOR)
        self.assertIsNotNone(doc)
        assert doc is not None
        self.assertEqual(doc.user_id, 1)

    def test_find_alive_player_absent_role(self) -> None:
        game = _game(_p(1, Role.CITIZEN))
        self.assertIsNone(find_alive_player(game, Role.DOCTOR))

    def test_find_alive_player_dead_holder(self) -> None:
        game = _game(_p(1, Role.DOCTOR, alive=False))
        self.assertIsNone(find_alive_player(game, Role.DOCTOR))

    def test_find_alive_player_unknown_role_safe(self) -> None:
        game = _game(_p(1, Role.KIDNAPPER))
        self.assertIsNone(find_alive_player(game, Role.KIDNAPPER))

    def test_find_alive_players_citizens(self) -> None:
        game = _game(
            _p(1, Role.CITIZEN),
            _p(2, Role.CITIZEN),
            _p(3, Role.DOCTOR),
        )
        citizens = find_alive_players(game, Role.CITIZEN)
        self.assertEqual({p.user_id for p in citizens}, {1, 2})

    def test_find_alive_players_unknown_role_empty(self) -> None:
        game = _game(_p(1, Role.CITIZEN))
        self.assertEqual(find_alive_players(game, Role.KIDNAPPER), [])

    def test_get_role_module_returns_none_for_missing(self) -> None:
        self.assertIsNone(get_role_module(Role.COMMANDO))

    def test_find_alive_role_holder_for_citizen(self) -> None:
        game = _game(
            _p(1, Role.CITIZEN),
            _p(2, Role.CITIZEN),
        )
        holder = find_alive_role_holder(game, Role.CITIZEN)
        self.assertIsNotNone(holder)
        assert holder is not None
        self.assertIn(holder.user_id, {1, 2})

    def test_require_role_module_raises_for_unknown(self) -> None:
        with self.assertRaises(ValueError):
            require_role_module(Role.COMMANDO)

    def test_substep_to_role_doctor(self) -> None:
        self.assertEqual(substep_to_role("ns_doc"), Role.DOCTOR)
