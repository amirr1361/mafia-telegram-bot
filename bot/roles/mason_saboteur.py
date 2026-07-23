"""قوانین خرابکار (SABOTEUR) — فقط سناریوی ماسون."""

from __future__ import annotations

from bot.game import is_mafia_team
from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario

HAS_NIGHT_ACTION = True
HAS_DAY_ACTION = False


def is_mason_saboteur(game: Game, player: Player) -> bool:
    return (
        is_mason_scenario(game)
        and player.is_alive
        and player.role == Role.SABOTEUR
    )


def find_alive_mason_saboteur(game: Game) -> Player | None:
    for p in game.players.values():
        if is_mason_saboteur(game, p):
            return p
    return None


def mason_saboteur_is_mafia(game: Game, player: Player) -> bool:
    return is_mason_saboteur(game, player) and is_mafia_team(player.role)


def mason_saboteur_night_target_pool(game: Game) -> list[Player]:
    if find_alive_mason_saboteur(game) is None:
        return []
    return [p for p in game.players.values() if p.is_alive]


def mason_saboteur_needs_night_pick(game: Game) -> bool:
    """خرابکار فقط وقتی پنل انتخاب می‌گیرد که تفنگ هنوز مصرف نشده باشد."""
    if not is_mason_scenario(game):
        return False
    from bot.roles.mason_gunner import mason_gun_is_spent

    return not mason_gun_is_spent(game)


def mason_saboteur_can_target(game: Game, saboteur: Player, target: Player) -> bool:
    if not is_mason_saboteur(game, saboteur):
        return False
    if not target.is_alive:
        return False
    return any(p.user_id == target.user_id for p in mason_saboteur_night_target_pool(game))


def commit_mason_saboteur_target(game: Game, saboteur: Player, target: Player) -> bool:
    if not mason_saboteur_needs_night_pick(game):
        return False
    if not mason_saboteur_can_target(game, saboteur, target):
        return False
    game.mason_saboteur_night_target_uid = target.user_id
    game.mason_saboteur_night_no_sabotage = False
    return True


def commit_mason_saboteur_no_sabotage(game: Game) -> bool:
    """خرابکار امشب کسی را خرابکاری نمی‌کند."""
    if not mason_saboteur_needs_night_pick(game):
        return False
    game.mason_saboteur_night_target_uid = None
    game.mason_saboteur_night_no_sabotage = True
    return True


def mason_saboteur_sabotages_gunner_target(game: Game) -> bool:
    """آیا هدف خرابکار با هدف تفنگدار یکی است (تفنگ خراب می‌شود)."""
    if not is_mason_scenario(game):
        return False
    gunner_target = game.mason_gunner_night_target_uid
    saboteur_target = game.mason_saboteur_night_target_uid
    return (
        gunner_target is not None
        and saboteur_target is not None
        and gunner_target == saboteur_target
    )


def clear_mason_saboteur_night_pick(game: Game) -> None:
    game.mason_saboteur_night_target_uid = None
    game.mason_saboteur_night_no_sabotage = False


def clear_mason_saboteur_night_state(game: Game) -> None:
    clear_mason_saboteur_night_pick(game)
