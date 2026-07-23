"""قوانین تک‌تیرانداز — فقط سناریوی ماسون."""

from __future__ import annotations

from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario
from bot.roles.mason_armored import mason_armored_sniper_immune

def is_mason_sniper(game: Game, player: Player) -> bool:
    return (
        is_mason_scenario(game)
        and player.is_alive
        and player.role == Role.SNIPER
    )


def find_alive_mason_sniper(game: Game) -> Player | None:
    for p in game.players.values():
        if is_mason_sniper(game, p):
            return p
    return None


def mason_sniper_bullet_limit(game: Game) -> int:
    """کل گلوله‌ها در بازی: ≤۱۲ نفر → ۲؛ ≥۱۵ نفر → ۳؛ ۱۳–۱۴ → ۲."""
    n = game.max_players
    if n <= 12:
        return 2
    if n >= 15:
        return 3
    return 2


def mason_sniper_total_bullets(game: Game) -> int:
    return mason_sniper_bullet_limit(game)


def mason_sniper_bullets_spent(game: Game) -> int:
    return game.mason_sniper_bullets_spent


def mason_sniper_bullets_remaining(game: Game) -> int:
    return max(0, mason_sniper_bullet_limit(game) - mason_sniper_bullets_spent(game))


def mason_sniper_can_select_shots(game: Game) -> bool:
    return mason_sniper_bullets_remaining(game) > 0


def mason_sniper_needs_night_pick(game: Game) -> bool:
    """اسنایپر فقط وقتی پنل انتخاب می‌گیرد که گلولهٔ باقی‌مانده داشته باشد."""
    if not is_mason_scenario(game):
        return False
    return mason_sniper_can_select_shots(game)


def mason_sniper_max_targets_this_night(game: Game) -> int:
    """حداکثر انتخاب در یک شب — برابر تیرهای باقی‌مانده در کل بازی."""
    return mason_sniper_bullets_remaining(game)


def build_mason_sniper_remaining_bullets_line(game: Game) -> str:
    from bot.game import _digits_fa

    remaining = mason_sniper_bullets_remaining(game)
    total = mason_sniper_total_bullets(game)
    return (
        f"تعداد تیرهای باقی‌مانده شما: "
        f"{_digits_fa(remaining)} از {_digits_fa(total)}"
    )


def build_mason_sniper_shoot_instructions(game: Game) -> str:
    from bot.game import _digits_fa

    remaining = mason_sniper_bullets_remaining(game)
    if remaining <= 0:
        return ""
    if remaining == 1:
        return "می‌توانید صفر یا یک هدف برای شلیک انتخاب کنید."
    return f"می‌توانید تا {_digits_fa(remaining)} هدف برای شلیک انتخاب کنید."


def mason_sniper_shot_pool(game: Game) -> list[Player]:
    sn = find_alive_mason_sniper(game)
    return [
        p
        for p in game.players.values()
        if p.is_alive and (sn is None or p.user_id != sn.user_id)
    ]


def mason_sniper_available_shot_pool(game: Game) -> list[Player]:
    """اهداف قابل انتخاب — بدون اهداف قبلاً انتخاب‌شده."""
    selected = set(mason_sniper_night_selected_uids(game))
    return [
        p for p in mason_sniper_shot_pool(game) if p.user_id not in selected
    ]


def mason_target_in_shot_pool(game: Game, target_uid: int) -> bool:
    return any(p.user_id == target_uid for p in mason_sniper_shot_pool(game))


def mason_sniper_night_selected_uids(game: Game) -> list[int]:
    return list(game.mason_sniper_night_selected_uids)


def mason_commander_approved_shot_uids(game: Game) -> list[int]:
    return list(game.mason_commander_night_approved_uids)


def mason_sniper_never_dies_for_shot() -> bool:
    """در ماسون اسنایپر هرگز به‌خاطر شلیک اشتباه از بازی خارج نمی‌شود."""
    return True


def mason_mafia_boss_sniper_immune(player: Player) -> bool:
    """پدرخوانده (رئیس مافیا در ماسون) در برابر شلیک اسنایپر مصون است."""
    return player.role == Role.GODFATHER


def mason_sniper_shot_immune(game: Game, player: Player) -> bool:
    if not is_mason_scenario(game):
        return False
    if mason_mafia_boss_sniper_immune(player):
        return True
    return mason_armored_sniper_immune(game, player)


def validate_mason_sniper_night_selection(game: Game, target_uids: list[int]) -> bool:
    if not is_mason_scenario(game):
        return False
    if len(target_uids) > mason_sniper_max_targets_this_night(game):
        return False
    if len(set(target_uids)) != len(target_uids):
        return False
    return all(mason_target_in_shot_pool(game, uid) for uid in target_uids)


def commit_mason_sniper_night_selection(game: Game, target_uids: list[int]) -> bool:
    """انتخاب شبانه — گلوله تا تأیید فرمانده مصرف نمی‌شود."""
    if not validate_mason_sniper_night_selection(game, target_uids):
        return False
    game.mason_sniper_night_selected_uids = list(target_uids)
    return True


def clear_mason_sniper_night_selection(game: Game) -> None:
    game.mason_sniper_night_selected_uids = []


def mason_approved_shots_that_kill(game: Game) -> list[int]:
    """اهداف تأییدشده که واقعاً از بازی خارج می‌شوند (بدون مصونیت)."""
    kills: list[int] = []
    for uid in mason_commander_approved_shot_uids(game):
        p = game.players.get(uid)
        if p is None or not p.is_alive:
            continue
        if mason_sniper_shot_immune(game, p):
            continue
        kills.append(uid)
    return kills


def mason_approved_shots_attempted(game: Game) -> list[int]:
    """همهٔ اهداف تأییدشده — حتی مصون."""
    return mason_commander_approved_shot_uids(game)


def clear_mason_sniper_night_state(game: Game) -> None:
    game.mason_sniper_night_selected_uids = []
    game.mason_commander_night_approved_uids = []
