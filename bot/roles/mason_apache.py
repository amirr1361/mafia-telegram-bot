"""قوانین آپاچی — فقط سناریوی ماسون (مافیأ مستقل)."""

from __future__ import annotations

from bot.game import is_mafia_team
from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario

HAS_NIGHT_ACTION = False
HAS_DAY_ACTION = True


def is_mason_apache(game: Game, player: Player) -> bool:
    return (
        is_mason_scenario(game)
        and player.is_alive
        and player.role == Role.APACHE
    )


def find_alive_mason_apache(game: Game) -> Player | None:
    for p in game.players.values():
        if is_mason_apache(game, p):
            return p
    return None


def apache_counts_as_mafia(game: Game, player: Player) -> bool:
    """آپاچی برای برد/شمار مافیا عضو تیم مافیا است."""
    if not is_mason_scenario(game):
        return False
    return player.is_alive and player.role == Role.APACHE


def mason_counts_as_mafia_faction(game: Game, player: Player) -> bool:
    """شمارش فکشن مافیا در ماسون — شامل آپاچی."""
    if not is_mason_scenario(game):
        return False
    return is_mafia_team(player.role)


def apache_receives_mafia_intro(game: Game, player: Player) -> bool:
    if not is_mason_scenario(game):
        return True
    if player.role == Role.APACHE:
        return False
    return is_mafia_team(player.role)


def apache_receives_mafia_panels(game: Game, player: Player) -> bool:
    if not is_mason_scenario(game):
        return True
    if player.role == Role.APACHE:
        return False
    return is_mafia_team(player.role)


def mason_receives_mafia_private_message(game: Game, player: Player) -> bool:
    """آپاچی پیام هماهنگی/عملیات/وضعیت شبانهٔ مافیا نمی‌گیرد."""
    return apache_receives_mafia_panels(game, player)


def mafia_member_informed_about_apache(game: Game, player: Player) -> bool:
    """اعضای مافیا از وجود آپاچی مطلع نمی‌شوند."""
    if not is_mason_scenario(game):
        return True
    if player.role == Role.APACHE:
        return False
    if is_mafia_team(player.role):
        return False
    return False


def mason_apache_day_target_pool(game: Game) -> list[Player]:
    apache = find_alive_mason_apache(game)
    if apache is None:
        return []
    return [p for p in game.players.values() if p.is_alive and p.user_id != apache.user_id]


def mason_apache_day_target_valid(game: Game, target_uid: int) -> bool:
    return any(p.user_id == target_uid for p in mason_apache_day_target_pool(game))


def commit_mason_apache_day_pick(game: Game, target_uid: int, *, confirmed: bool) -> bool:
    """ثبت انتخاب روز آپاچی — اعمال واقعی در فاز بعدی."""
    if not is_mason_scenario(game):
        return False
    if find_alive_mason_apache(game) is None:
        return False
    if not mason_apache_day_target_valid(game, target_uid):
        return False
    game.mason_apache_day_target_uid = target_uid
    game.mason_apache_day_pick_confirmed = confirmed
    return True


def clear_mason_apache_day_pick(game: Game) -> None:
    game.mason_apache_day_target_uid = None
    game.mason_apache_day_pick_confirmed = False


def mark_mason_apache_day_action_used(game: Game) -> None:
    """آپاچی قابلیت روزانهٔ خود را تأیید کرد — از شب بعد محافظ نیازی به انتخاب ندارد."""
    if is_mason_scenario(game):
        game.mason_apache_day_action_used = True


def mason_apache_day_elimination_blocked(game: Game, target_uid: int) -> bool:
    from bot.roles.mason_guardian import guardian_blocks_apache

    return guardian_blocks_apache(game, target_uid)


def mason_apache_day_elimination_would_succeed(game: Game, target_uid: int) -> bool:
    if not is_mason_scenario(game):
        return False
    if not game.mason_apache_day_pick_confirmed:
        return False
    if game.mason_apache_day_target_uid != target_uid:
        return False
    if not mason_apache_day_target_valid(game, target_uid):
        return False
    return not mason_apache_day_elimination_blocked(game, target_uid)
