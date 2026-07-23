"""گادفادر و اولویت شلیک مافیا — فقط سناریوی ماسون."""

from __future__ import annotations

from bot.game import is_mafia_team
from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario


def find_alive_godfather(game: Game) -> Player | None:
    for p in game.players.values():
        if p.is_alive and p.role == Role.GODFATHER:
            return p
    return None


def nato_role_in_game(game: Game) -> bool:
    return any(p.role == Role.NATO for p in game.players.values())


def find_alive_nato(game: Game) -> Player | None:
    for p in game.players.values():
        if p.is_alive and p.role == Role.NATO:
            return p
    return None


def mason_nato_can_register(game: Game) -> bool:
    """ناتویی — یک‌بار در بازی؛ نقش ناتو در نقش‌های اولیه، ناتو زنده (گادفادر لازم نیست)."""
    if not is_mason_scenario(game):
        return False
    if game.mason_nato_used:
        return False
    if not nato_role_in_game(game):
        return False
    return find_alive_nato(game) is not None


def resolve_mason_shot_chooser(game: Game) -> Player | None:
    """گادفادر → ناتو → خرابکار → مافیا ساده."""
    if not is_mason_scenario(game):
        return None
    gf = find_alive_godfather(game)
    if gf is not None:
        return gf
    nato = find_alive_nato(game)
    if nato is not None:
        return nato
    for p in game.players.values():
        if p.is_alive and p.role == Role.SABOTEUR:
            return p
    for p in game.players.values():
        if p.is_alive and p.role == Role.MAFIA_BASIC:
            return p
    mafs = [
        p
        for p in game.players.values()
        if p.is_alive and p.role is not None and is_mafia_team(p.role)
    ]
    return mafs[0] if mafs else None


def resolve_mason_night1_menu_recipients(game: Game) -> list[Player]:
    """منوی شلیک/ناتو — گادفادر زنده؛ وگرنه مجری اقدام مافیا (ناتو، خرابکار، …)."""
    if not is_mason_scenario(game):
        return []
    gf = find_alive_godfather(game)
    if gf is not None:
        return [gf]
    chooser = resolve_mason_shot_chooser(game)
    return [chooser] if chooser is not None else []


def resolve_mason_mafia_action_holder_label(game: Game) -> str:
    """برچسب نقش مجری اقدام شبانهٔ مافیا — برای گزارش دیباگ."""
    if not is_mason_scenario(game):
        return "Mafia"
    if find_alive_godfather(game) is not None:
        return "Godfather"
    if find_alive_nato(game) is not None:
        return "NATO"
    for p in game.players.values():
        if p.is_alive and p.role == Role.SABOTEUR:
            return "Saboteur"
    for p in game.players.values():
        if p.is_alive and p.role == Role.MAFIA_BASIC:
            return "Simple Mafia"
    for p in game.players.values():
        if p.is_alive and p.role == Role.APACHE:
            return "Apache"
    return "Mafia"
