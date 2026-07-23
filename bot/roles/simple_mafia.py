"""منطق هستهٔ مافیا ساده — مشترک semi_auto و no_host."""

from __future__ import annotations

from bot.game import bazpors_counts_as_mafia_faction, is_mafia_team
from bot.models import Game, Player, Role

SIMPLE_MAFIA_ROLES: frozenset[Role] = frozenset(
    {
        Role.MAFIA,
        Role.MAFIA_SIMPLE,
        Role.MAFIA_SIMPLE_2,
        Role.MAFIA_BASIC,
    }
)

MAFIA_TEAM_NIGHT_ROLES: frozenset[Role] = frozenset(
    {
        Role.MAFIA_BOSS,
        Role.MAFIA_BASIC,
        Role.NATO,
        Role.MAFIA,
        Role.MAFIA_SIMPLE,
        Role.MAFIA_NEGOTIATOR,
    }
)


def is_simple_mafia_role(role: Role | None) -> bool:
    return role is not None and role in SIMPLE_MAFIA_ROLES


def is_simple_mafia(player: Player) -> bool:
    return is_simple_mafia_role(player.role)


def find_alive_simple_mafia(game: Game) -> list[Player]:
    from bot.bazpors_narrator import _visually_mafia

    return sorted(
        (
            p
            for p in game.players.values()
            if p.is_alive
            and is_simple_mafia(p)
            and _visually_mafia(game, p)
        ),
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    )


def is_mafia_aligned(game: Game, player: Player) -> bool:
    return bazpors_counts_as_mafia_faction(game, player)


def participates_in_mafia_team_night(role: Role | None) -> bool:
    """نقش‌هایی که در آمادگی شب موازی no_host برای تیم مافیا شمار می‌شوند."""
    if role is None:
        return False
    if is_simple_mafia_role(role):
        return True
    return role in MAFIA_TEAM_NIGHT_ROLES


def has_mafia_team_member_alive(game: Game) -> bool:
    return any(
        p.is_alive and participates_in_mafia_team_night(p.role)
        for p in game.players.values()
    )


def reads_positive_for_detective(game: Game, player: Player) -> bool:
    return is_mafia_aligned(game, player)
