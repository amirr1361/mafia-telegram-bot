"""ناتویی — فقط سناریوی ماسون (جدا از بازپرس)."""

from __future__ import annotations

from bot.game import is_mafia_team
from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario

MASON_NATO_EXCLUDED_TOWN_ROLES: frozenset[Role] = frozenset(
    {Role.TOWN_SIMPLE, Role.CITIZEN}
)


def mason_nato_guess_roles_in_room(game: Game) -> list[Role]:
    """نقش‌های شهر (غیر از شهروند ساده) که در اتاق ثبت شده‌اند."""
    if not is_mason_scenario(game):
        return []
    found: set[Role] = set()
    for p in game.players.values():
        if p.role is None or p.role == Role.OBSERVER:
            continue
        if is_mafia_team(p.role):
            continue
        if p.role in MASON_NATO_EXCLUDED_TOWN_ROLES:
            continue
        found.add(p.role)
    from bot.bazpors_narrator import role_label_fa

    return sorted(found, key=lambda r: role_label_fa(r))


def mason_nato_target_pool(game: Game) -> list[Player]:
    """همهٔ بازیکنان زنده — برخلاف بازپرس که فقط غیرمافیا."""
    return [p for p in game.players.values() if p.is_alive]


def mark_mason_nato_selected_tonight(game: Game) -> None:
    """پس از انتخاب ناتویی توسط گادفادر — شلیک همان شب غیرفعال و مصرف یک‌بار."""
    game.mason_nato_used = True
    game.mason_nato_tonight = True


def commit_mason_nato_guess(
    game: Game, guess_role: Role, target_uid: int
) -> None:
    game.mason_nato_guess_role = guess_role
    game.mason_nato_guess_target_uid = target_uid
    game.mason_nato_confirmed = True


def resolve_mason_nato_elimination_uid(game: Game) -> int | None:
    """در پایان شب — اگر حدس درست باشد هدف حذف می‌شود."""
    if not is_mason_scenario(game):
        return None
    if not game.mason_nato_confirmed:
        return None
    if game.mason_nato_guess_role is None or game.mason_nato_guess_target_uid is None:
        return None
    target = game.players.get(game.mason_nato_guess_target_uid)
    if target is None or not target.is_alive:
        return None
    if target.role == game.mason_nato_guess_role:
        return target.user_id
    return None


def clear_mason_nato_night_state(game: Game) -> None:
    """صفر کردن state شبانهٔ ناتو (نه mason_nato_used)."""
    game.mason_nato_tonight = False
    game.mason_nato_pending_role = None
    game.mason_nato_pending_target_uid = None
    game.mason_nato_confirmed = False
    game.mason_nato_guess_role = None
    game.mason_nato_guess_target_uid = None
