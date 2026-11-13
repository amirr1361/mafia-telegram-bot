"""منطق هستهٔ مین‌گذار — مشترک semi_auto و no_host."""

from __future__ import annotations

from bot.models import Game, Player, Role


def is_ruintan_role(role: Role | None) -> bool:
    return role == Role.RUINTAN


def is_ruintan(player: Player) -> bool:
    return is_ruintan_role(player.role)


def find_alive_ruintan(game: Game) -> Player | None:
    for p in game.players.values():
        if p.is_alive and is_ruintan(p):
            return p
    return None


def mafia_shot_survives(target: Player) -> bool:
    """شات شب مافیا روی مین‌گذار نمی‌نشیند."""
    return is_ruintan(target)


def mafia_shot_allowed(game: Game) -> bool:
    """اگر فقط مین‌گذار زنده بماند، شات مافیا مجاز نیست."""
    from bot.nam10.nmnd_narrator import _alive

    return any(not is_ruintan_role(p.role) for p in _alive(game))


def yaku_negotiation_succeeds(role: Role | None, *, player_count: int) -> bool:
    """مین‌گذار در ۱۳ نفره قابل یاکوزایی نیست؛ در ۱۲ نفره بله."""
    if role != Role.RUINTAN:
        return False
    return player_count != 13


def is_nato_guessable_role(role: Role) -> bool:
    from bot.nam10.roles_nato import GUESS_ROLES

    return role in GUESS_ROLES


def reads_as_town_for_detective(game: Game, player: Player) -> bool:
    """محافظ مین‌گذار را منفی (شهروندی) می‌بیند."""
    if not is_ruintan(player):
        return False
    from bot.nam10.engine import bazpors_counts_as_mafia_faction as nmnd_counts_as_mafia_faction

    return not nmnd_counts_as_mafia_faction(game, player)
