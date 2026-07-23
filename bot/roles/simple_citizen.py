"""منطق هستهٔ شهروند ساده — مشترک semi_auto و no_host."""

from __future__ import annotations

from bot.game import bazpors_counts_as_mafia_faction
from bot.models import Game, Player, Role


def is_simple_citizen_role(role: Role | None) -> bool:
    return role == Role.CITIZEN


def is_simple_citizen(player: Player) -> bool:
    return is_simple_citizen_role(player.role)


def find_alive_simple_citizens(game: Game) -> list[Player]:
    return sorted(
        (p for p in game.players.values() if p.is_alive and is_simple_citizen(p)),
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    )


def alive_simple_citizen_uids(game: Game) -> list[int]:
    return [p.user_id for p in find_alive_simple_citizens(game)]


def has_night_action() -> bool:
    """شهروند ساده در شب عملی نقشی ندارد — فقط انتظار."""
    return False


def is_nato_guessable_role(role: Role) -> bool:
    """شهروند ساده در فهرست نقش‌های قابل حدس ناتو نیست."""
    from bot.roles.nato import GUESS_ROLES

    return role in GUESS_ROLES


def yaku_negotiation_succeeds(role: Role | None, *, player_count: int) -> bool:
    """یاکوزایی روی شهروند ساده همیشه موفق است."""
    return role == Role.CITIZEN


def reads_as_town_for_detective(game: Game, player: Player) -> bool:
    """کارآگاه شهروند ساده را منفی (شهروندی) می‌بیند."""
    if not is_simple_citizen(player):
        return False
    return not bazpors_counts_as_mafia_faction(game, player)


def counts_as_chaos_citizen_team(game: Game, uid: int) -> bool:
    """فاز آشوب — شهروند ساده در تیم شهر (غیرمافیا)."""
    p = game.players.get(uid)
    if p is None:
        return False
    return not bazpors_counts_as_mafia_faction(game, p)


def is_special_town_role(role: Role | None) -> bool:
    """برای مرتب‌سازی فهرست — نقش‌دار قبل از شهروند ساده."""
    return role is not None and role != Role.CITIZEN
