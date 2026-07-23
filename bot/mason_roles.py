"""نقش‌های سناریوی ماسون — فقط masoon (۱۲ تا ۱۸ نفر)."""

from __future__ import annotations

from bot.models import Role

MASON_MIN_PLAYERS = 12
MASON_MAX_PLAYERS = 18
MASON_PLAYER_COUNTS = frozenset(range(MASON_MIN_PLAYERS, MASON_MAX_PLAYERS + 1))

_MAFIA_4 = (
    Role.GODFATHER,
    Role.SABOTEUR,
    Role.SPY,
    Role.APACHE,
)

_TOWN_8 = (
    Role.DOCTOR,
    Role.RUINTAN,
    Role.COWBOY,
    Role.SNIPER,
    Role.COMMANDER,
    Role.GUNMAN,
    Role.BODYGUARD,
    Role.MASON,
)

MASON_ROLE_LISTS_BY_COUNT: dict[int, tuple[Role, ...]] = {
    12: _MAFIA_4 + _TOWN_8,
    13: _MAFIA_4 + _TOWN_8 + (Role.TOWN_SIMPLE,),
    14: _MAFIA_4 + (Role.NATO,) + _TOWN_8 + (Role.TOWN_SIMPLE,),
    15: _MAFIA_4 + (Role.NATO,) + _TOWN_8 + (Role.TAILOR, Role.TOWN_SIMPLE),
    16: (
        Role.GODFATHER,
        Role.SABOTEUR,
        Role.SPY,
        Role.APACHE,
        Role.NATO,
        Role.MAFIA_BASIC,
        Role.DOCTOR,
        Role.RUINTAN,
        Role.COWBOY,
        Role.SNIPER,
        Role.COMMANDER,
        Role.GUNMAN,
        Role.BODYGUARD,
        Role.MASON,
        Role.TAILOR,
        Role.DETECTIVE,
    ),
    17: _MAFIA_4
    + (Role.NATO, Role.MAFIA_BASIC)
    + _TOWN_8
    + (Role.TAILOR, Role.DETECTIVE, Role.TOWN_SIMPLE),
    18: _MAFIA_4
    + (Role.NATO, Role.NATASHA)
    + _TOWN_8
    + (Role.TAILOR, Role.DETECTIVE, Role.PRIEST, Role.TOWN_SIMPLE),
}


def masoon_roles_for_count(n: int) -> list[Role]:
    """ترکیب رسمی نقش‌های ماسون برای ظرفیت ۱۲ تا ۱۸."""
    roles = MASON_ROLE_LISTS_BY_COUNT.get(n)
    if roles is None:
        raise ValueError(f"ماسون فقط برای ۱۲ تا ۱۸ بازیکن؛ الان {n}")
    return list(roles)


def mason_mafia_roles_for_count(n: int) -> list[Role]:
    from bot.game import is_mafia_team

    return [r for r in masoon_roles_for_count(n) if is_mafia_team(r)]


def mason_town_roles_for_count(n: int) -> list[Role]:
    from bot.game import is_mafia_team

    return [r for r in masoon_roles_for_count(n) if not is_mafia_team(r)]
