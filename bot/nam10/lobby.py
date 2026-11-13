"""Fork lobby/role-deal helpers (snapshot of Bazpors 10-player no-host)."""

from __future__ import annotations

import random

from bot.game import is_mafia_team
from bot.models import Game, Role


def roles_for_count(n: int) -> list[Role]:
    """Authoritative Namayande fork composition for 10/11/12/13 players.

    10: Boss, Rebel (NATO), Hacker + seven town seats (2 citizens).
    11: the 10-player composition plus one more Simple Citizen.
    12: one independent Mafia NATO agent plus one Town Soldier added.
    13: the 12-player composition plus one more Simple Citizen.
    """
    if n not in (10, 11, 12, 13):
        raise ValueError("namayande fork supports 10, 11, 12 or 13 players")
    roles = [
        Role.MAFIA_BOSS,
        Role.NATO,
        Role.SHIAD,
        Role.HUNTER,
        Role.INTERROGATOR,
        Role.DETECTIVE,
        Role.DOCTOR,
        Role.RUINTAN,
        Role.CITIZEN,
        Role.CITIZEN,
    ]
    if n == 11:
        roles.append(Role.CITIZEN)
    elif n == 12:
        roles.extend([Role.NATO_AGENT, Role.SOLDIER])
    elif n == 13:
        roles.extend([Role.NATO_AGENT, Role.SOLDIER, Role.CITIZEN])
    return roles


def assign_roles_namayande10(game: Game) -> None:
    n = len(game.players)
    roles = roles_for_count(n)
    player_ids = list(game.players.keys())
    random.shuffle(player_ids)
    game.mafia_ids.clear()
    game.nmnd_mafia_recruit_ids.clear()
    for pid, role in zip(player_ids, roles):
        pl = game.players[pid]
        pl.role = role
        pl.nmnd_original_role = None
        pl.nmnd_converted_by_yakuza = False
        if is_mafia_team(role):
            game.mafia_ids.add(pid)


def assign_roles_by_player_namayande10(
    game: Game, role_by_player: dict[int, Role]
) -> None:
    """Pre-determined role application (players pick roles during deal)."""
    game.mafia_ids.clear()
    game.nmnd_mafia_recruit_ids.clear()
    for pid, pl in game.players.items():
        role = role_by_player.get(pid)
        if role is None:
            raise ValueError("همهٔ بازیکن‌ها باید نقش داشته باشند.")
        pl.role = role
        pl.nmnd_original_role = None
        pl.nmnd_converted_by_yakuza = False
        if is_mafia_team(role):
            game.mafia_ids.add(pid)


def sync_synthetic_player_display_names_nam10(game: Game) -> None:
    """Synthetic display names follow roles — same UX as Bazpors, fork-gated."""
    from bot.game import is_synthetic_player_uid, synthetic_player_base_name
    from bot.nam10.role_labels import nam10_role_label_fa

    if game.scenario_name != "namayande":
        return
    for p in sorted(
        game.players.values(),
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    ):
        if not is_synthetic_player_uid(p.user_id) or p.role is None:
            continue
        base = synthetic_player_base_name(p.full_name)
        p.full_name = f"{base}-{nam10_role_label_fa(p.role)}"
