"""Fork engine shim — neutral re-exports plus fork-scoped helpers.

Copies of the Bazpors engine helpers whose semantics must live on the fork
state namespace (``nmnd_*`` fields) are defined here; shared-neutral names
are transparent re-exports.
"""

from __future__ import annotations

from bot.game import (
    GameManager,  # noqa: F401
    _digits_fa,  # noqa: F401
    is_mafia_team,  # noqa: F401
    is_synthetic_player_uid,  # noqa: F401
    role_label_fa,  # noqa: F401
    synthetic_player_base_name,  # noqa: F401
)
from bot.models import Game, Player, Role


def nmnd_counts_as_mafia_faction(game: Game, p: Player) -> bool:
    """Mafia-faction identity on fork state (reports / table inquiry / sniper)."""
    if game.scenario_name != "namayande":
        return is_mafia_team(p.role)
    if p.user_id in game.nmnd_mafia_recruit_ids:
        return True
    return is_mafia_team(p.role)


def nmnd_counts_as_alive_mafia_for_win(game: Game, p: Player) -> bool:
    """Alive mafia (or yakuza-converted) for win checks; sniper victims never count."""
    if not p.is_alive:
        return False
    if p.user_id in game.nmnd_sniper_eliminated_uids:
        return False
    return nmnd_counts_as_mafia_faction(game, p)


def apply_bazpors_yakuzai_recruit(game: Game, p: Player) -> None:
    """Successful yakuza recruit (fork name kept for copy-import compatibility)."""
    if p.user_id in game.nmnd_sniper_eliminated_uids:
        return
    if p.nmnd_original_role is None:
        p.nmnd_original_role = p.role
    p.nmnd_converted_by_yakuza = True
    game.nmnd_mafia_recruit_ids.add(p.user_id)
    p.role = Role.MAFIA_BASIC
    game.mafia_ids.add(p.user_id)


def mark_bazpors_eliminated_by_sniper(game: Game, uid: int) -> None:
    """Successful sniper elimination (fork name kept for copy-import compatibility)."""
    if game.scenario_name != "namayande":
        return
    game.nmnd_sniper_eliminated_uids.add(uid)
    game.mafia_ids.discard(uid)
    game.nmnd_mafia_recruit_ids.discard(uid)


# Import-compat aliases: copies keep the original helper names.
bazpors_counts_as_mafia_faction = nmnd_counts_as_mafia_faction
bazpors_counts_as_alive_mafia_for_win = nmnd_counts_as_alive_mafia_for_win
