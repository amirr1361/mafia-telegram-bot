"""Role capability registry — Phase C coordination layer.

Maps Role enum values to existing Phase A role modules. Role-specific rules
remain in bot/roles/*.py; this module only coordinates lookup/dispatch.
"""

from __future__ import annotations

import types
from collections.abc import Callable
from typing import TYPE_CHECKING

from bot.models import Role

if TYPE_CHECKING:
    from bot.models import Game, Player

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
    mozakere_journalist,
    mozakere_negotiator,
    mozakere_armored,
    nato,
    ruintan,
    shiad,
    simple_citizen,
    simple_mafia,
    sniper,
)

# Canonical Role → Phase A module (one entry per capability module).
ROLE_CAPABILITIES: dict[Role, types.ModuleType] = {
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

# Additional Role values that share a registered module.
ROLE_ALIASES: dict[Role, Role] = {
    Role.MAFIA: Role.MAFIA_BASIC,
    Role.MAFIA_SIMPLE: Role.MAFIA_BASIC,
    Role.MAFIA_SIMPLE_2: Role.MAFIA_BASIC,
}

# Every Role enum value used in bazpors_roles_for_count (10–13 players).
BAZPORS_SCENARIO_ROLES: frozenset[Role] = frozenset(
    {
        Role.MAFIA_BOSS,
        Role.NATO,
        Role.SHIAD,
        Role.MAFIA_BASIC,
        Role.HUNTER,
        Role.INTERROGATOR,
        Role.DETECTIVE,
        Role.DOCTOR,
        Role.RUINTAN,
        Role.SNIPER,
        Role.CITIZEN,
    }
)

# Roles with no_host night entry / parallel collect panels.
NO_HOST_DISPATCH_ROLES: frozenset[Role] = frozenset(
    {
        Role.CITIZEN,
        Role.RUINTAN,
        Role.SHIAD,
        Role.DETECTIVE,
        Role.DOCTOR,
        Role.SNIPER,
        Role.INTERROGATOR,
        Role.HUNTER,
        Role.JOURNALIST,
        Role.MAFIA_BOSS,
        Role.NATO,
        Role.MAFIA_BASIC,
        Role.SHIAD,
    }
)

# Semi-auto narrator night substep → role (string keys match bazpors_narrator NS_*).
SEMI_AUTO_SUBSTEP_TO_ROLE: dict[str, Role] = {
    "ns_hunter": Role.HUNTER,
    "ns_shiad": Role.SHIAD,
    "ns_shiad_ack": Role.SHIAD,
    "ns_det": Role.DETECTIVE,
    "ns_det_ack": Role.DETECTIVE,
    "ns_doc": Role.DOCTOR,
    "ns_doc_nato_skip": Role.DOCTOR,
    "ns_doc_yaku_skip": Role.DOCTOR,
    "ns_sniper": Role.SNIPER,
    "ns_int1": Role.INTERROGATOR,
    "ns_int2": Role.INTERROGATOR,
    "ns_interrog_skip": Role.INTERROGATOR,
}

_FIND_ALIVE_SINGLE: dict[Role, Callable[["Game"], "Player | None"]] = {
    Role.DOCTOR: doctor.find_alive_doctor,
    Role.DETECTIVE: detective.find_alive_detective,
    Role.NATO: nato.find_alive_nato,
    Role.MAFIA_BOSS: mafia_boss.find_alive_boss,
    Role.SHIAD: shiad.find_alive_shiad,
    Role.HUNTER: hunter.find_alive_hunter,
    Role.INTERROGATOR: interrogator.find_alive_interrogator,
    Role.RUINTAN: ruintan.find_alive_ruintan,
    Role.SNIPER: sniper.find_alive_sniper,
    Role.JOURNALIST: mozakere_journalist.find_alive_journalist,
    Role.ARMORED: mozakere_armored.find_alive_armored,
    Role.APACHE: mason_apache.find_alive_mason_apache,
    Role.BODYGUARD: mason_guardian.find_alive_mason_guardian,
    Role.COWBOY: mason_cowboy.find_alive_mason_cowboy,
    Role.GUNMAN: mason_gunner.find_alive_mason_gunner,
    Role.SABOTEUR: mason_saboteur.find_alive_mason_saboteur,
    Role.MASON: mason_fraternity.find_alive_mason_role_holder,
    Role.SPY: mason_spy.find_alive_mason_spy,
    Role.NATASHA: mason_natasha.find_alive_mason_natasha,
    Role.PRIEST: mason_priest.find_alive_mason_priest,
}

_FIND_ALIVE_MANY: dict[Role, Callable[["Game"], list["Player"]]] = {
    Role.CITIZEN: simple_citizen.find_alive_simple_citizens,
    Role.MAFIA_BASIC: simple_mafia.find_alive_simple_mafia,
}


def resolve_registered_role(role: Role) -> Role | None:
    """Return canonical registry key for role, or None if unregistered."""
    if role in ROLE_CAPABILITIES:
        return role
    return ROLE_ALIASES.get(role)


def is_registered_role(role: Role) -> bool:
    return resolve_registered_role(role) is not None


def registered_roles() -> frozenset[Role]:
    """All Role values with a registry entry (canonical keys + aliases)."""
    return frozenset(ROLE_CAPABILITIES) | frozenset(ROLE_ALIASES)


def get_role_module(role: Role) -> types.ModuleType | None:
    key = resolve_registered_role(role)
    if key is None:
        return None
    return ROLE_CAPABILITIES[key]


def require_role_module(role: Role) -> types.ModuleType:
    """Registered module or ValueError — for call sites that require a module."""
    mod = get_role_module(role)
    if mod is None:
        raise ValueError(f"unregistered role: {role}")
    return mod


def role_supports_no_host_dispatch(role: Role) -> bool:
    key = resolve_registered_role(role)
    return key is not None and key in NO_HOST_DISPATCH_ROLES


def role_supports_semi_auto_dispatch(role: Role) -> bool:
    key = resolve_registered_role(role)
    if key is None:
        return False
    return key in _FIND_ALIVE_SINGLE or any(
        r == key for r in SEMI_AUTO_SUBSTEP_TO_ROLE.values()
    )


def substep_to_role(substep: str | None) -> Role | None:
    if not substep:
        return None
    return SEMI_AUTO_SUBSTEP_TO_ROLE.get(substep)


def find_alive_player(game: "Game", role: Role) -> "Player | None":
    """Alive holder for single-player roles; None if unregistered or absent."""
    key = resolve_registered_role(role)
    if key is None:
        return None
    finder = _FIND_ALIVE_SINGLE.get(key)
    if finder is None:
        return None
    return finder(game)


def find_alive_players(game: "Game", role: Role) -> list["Player"]:
    """Alive holders for multi-player roles (citizen, simple mafia); [] if N/A."""
    key = resolve_registered_role(role)
    if key is None:
        return []
    finder = _FIND_ALIVE_MANY.get(key)
    if finder is None:
        return []
    return finder(game)


def find_alive_role_holder(game: "Game", role: Role) -> "Player | None":
    """Alive player with exact ``role`` enum; uses module finder when registered."""
    key = resolve_registered_role(role)
    if key is not None and key in _FIND_ALIVE_SINGLE:
        return _FIND_ALIVE_SINGLE[key](game)
    for p in game.players.values():
        if p.is_alive and p.role == role:
            return p
    return None
