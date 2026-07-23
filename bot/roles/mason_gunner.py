"""قوانین تفنگدار (GUNMAN) — فقط سناریوی ماسون."""

from __future__ import annotations

from dataclasses import dataclass

from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario

HAS_NIGHT_ACTION = True
HAS_DAY_ACTION = False


@dataclass(frozen=True)
class MasonDayGunShotResult:
    """نتیجهٔ شلیک تفنگ روز — چه کسی از بازی خارج می‌شود."""

    gun_holder_uid: int
    target_uid: int
    sabotaged: bool
    eliminated_uid: int
    survivor_uid: int


def is_mason_gunner(game: Game, player: Player) -> bool:
    return (
        is_mason_scenario(game)
        and player.is_alive
        and player.role == Role.GUNMAN
    )


def find_alive_mason_gunner(game: Game) -> Player | None:
    for p in game.players.values():
        if is_mason_gunner(game, p):
            return p
    return None


def mason_gunner_is_town(game: Game, player: Player) -> bool:
    from bot.game import is_mafia_team

    return is_mason_gunner(game, player) and not is_mafia_team(player.role)


def mason_gunner_night_target_pool(game: Game) -> list[Player]:
    gunner = find_alive_mason_gunner(game)
    if gunner is None:
        return []
    return [
        p
        for p in game.players.values()
        if p.is_alive and p.user_id != gunner.user_id
    ]


def mason_gunner_can_target(game: Game, gunner: Player, target: Player) -> bool:
    if not is_mason_gunner(game, gunner):
        return False
    if not target.is_alive or target.user_id == gunner.user_id:
        return False
    return any(p.user_id == target.user_id for p in mason_gunner_night_target_pool(game))


def commit_mason_gunner_target(game: Game, gunner: Player, target: Player) -> bool:
    if not mason_gunner_can_give_gun(game):
        return False
    if not mason_gunner_can_target(game, gunner, target):
        return False
    game.mason_gunner_night_target_uid = target.user_id
    game.mason_gunner_night_no_give = False
    return True


def commit_mason_gunner_no_give(game: Game) -> bool:
    """تفنگدار امشب تفنگ نمی‌دهد — تفنگ مصرف نمی‌شود."""
    if not mason_gunner_can_give_gun(game):
        return False
    game.mason_gunner_night_target_uid = None
    game.mason_gunner_night_no_give = True
    return True


def mason_day_gun_holder_uid(game: Game) -> int | None:
    if not is_mason_scenario(game):
        return None
    return game.mason_day_gun_holder_uid


def mason_day_gun_is_sabotaged(game: Game) -> bool:
    if not is_mason_scenario(game):
        return False
    return bool(game.mason_day_gun_sabotaged)


def mason_day_gun_is_used(game: Game) -> bool:
    if not is_mason_scenario(game):
        return False
    return bool(game.mason_day_gun_used)


def mark_mason_gun_delivered_to_holder(game: Game) -> bool:
    """تفنگدار با تحویل پنل روز — تفنگ مصرف می‌شود (حتی اگر شلیک نشود)."""
    if not is_mason_scenario(game):
        return False
    if mason_gun_is_spent(game):
        return False
    if mason_day_gun_holder_uid(game) is None:
        return False
    game.mason_gun_spent = True
    return True


def mason_gun_is_spent(game: Game) -> bool:
    if not is_mason_scenario(game):
        return False
    return bool(game.mason_gun_spent)


def mason_gunner_can_give_gun(game: Game) -> bool:
    """تفنگدار فقط وقتی پنل شبانه می‌گیرد که تفنگ نزد خودش باشد."""
    if not is_mason_scenario(game):
        return False
    if mason_gun_is_spent(game):
        return False
    holder_uid = mason_day_gun_holder_uid(game)
    if holder_uid is None:
        return True
    holder = game.players.get(holder_uid)
    if holder is None or not holder.is_alive:
        return True
    return False


def mason_day_gun_available(game: Game) -> bool:
    """تفنگ روز هنوز قابل شلیک است — مستقل از mason_gun_spent (مصرف تفنگدار)."""
    holder_uid = mason_day_gun_holder_uid(game)
    if holder_uid is None or mason_day_gun_is_used(game):
        return False
    holder = game.players.get(holder_uid)
    return holder is not None and holder.is_alive


def refresh_mason_day_gun_holder_if_eliminated(game: Game) -> None:
    """اگر صاحب تفنگ قبل از استفاده بمیرد، تفنگ به تفنگدار برمی‌گردد."""
    if not is_mason_scenario(game) or mason_gun_is_spent(game):
        return
    holder_uid = mason_day_gun_holder_uid(game)
    if holder_uid is None or mason_day_gun_is_used(game):
        return
    holder = game.players.get(holder_uid)
    if holder is not None and holder.is_alive:
        return
    game.mason_day_gun_holder_uid = None
    game.mason_day_gun_sabotaged = False


def _holder_still_has_unused_gun(game: Game) -> bool:
    holder_uid = mason_day_gun_holder_uid(game)
    if holder_uid is None or mason_day_gun_is_used(game):
        return False
    holder = game.players.get(holder_uid)
    return holder is not None and holder.is_alive


def prepare_mason_day_gun_from_night_choices(game: Game) -> None:
    """انتقال شب به روز — صاحب تفنگ و وضعیت خرابکاری."""
    if not is_mason_scenario(game):
        return
    if mason_gun_is_spent(game):
        return
    refresh_mason_day_gun_holder_if_eliminated(game)
    if _holder_still_has_unused_gun(game):
        return
    gunner_target = game.mason_gunner_night_target_uid
    if gunner_target is None:
        return
    if not mason_gunner_can_give_gun(game):
        return
    holder = game.players.get(gunner_target)
    if holder is None or not holder.is_alive:
        return
    game.mason_day_gun_holder_uid = gunner_target
    saboteur_target = game.mason_saboteur_night_target_uid
    game.mason_day_gun_sabotaged = (
        saboteur_target is not None and saboteur_target == gunner_target
    )
    game.mason_day_gun_used = False
    game.mason_day_gun_shot_target_uid = None


def mason_day_gun_shot_pool(game: Game, gun_holder_uid: int) -> list[Player]:
    """همهٔ بازیکنان زنده به‌جز صاحب تفنگ — بدون فیلتر تیم/نقش."""
    holder = game.players.get(gun_holder_uid)
    if holder is None or not holder.is_alive:
        return []
    from bot.no_host_role_pick_common import sort_players_for_pick

    return sort_players_for_pick(
        [
            p
            for p in game.players.values()
            if p.is_alive and p.user_id != gun_holder_uid
        ]
    )


def mason_day_gun_holder_can_shoot(
    game: Game, gun_holder: Player, target: Player
) -> bool:
    if not mason_day_gun_available(game):
        return False
    if mason_day_gun_holder_uid(game) != gun_holder.user_id:
        return False
    if not gun_holder.is_alive or not target.is_alive:
        return False
    if target.user_id == gun_holder.user_id:
        return False
    return any(p.user_id == target.user_id for p in mason_day_gun_shot_pool(game, gun_holder.user_id))


def resolve_mason_day_gun_shot(
    game: Game, gun_holder: Player, target: Player
) -> MasonDayGunShotResult | None:
    """شلیک تفنگ روز — یک‌بار مصرف."""
    if not mason_day_gun_holder_can_shoot(game, gun_holder, target):
        return None
    sabotaged = mason_day_gun_is_sabotaged(game)
    if sabotaged:
        eliminated_uid = gun_holder.user_id
        survivor_uid = target.user_id
    else:
        eliminated_uid = target.user_id
        survivor_uid = gun_holder.user_id
    game.mason_day_gun_used = True
    game.mason_day_gun_shot_target_uid = target.user_id
    return MasonDayGunShotResult(
        gun_holder_uid=gun_holder.user_id,
        target_uid=target.user_id,
        sabotaged=sabotaged,
        eliminated_uid=eliminated_uid,
        survivor_uid=survivor_uid,
    )


def mason_faction_side_label_fa(game: Game, uid: int) -> str:
    """فقط ساید تیم — بدون نام نقش."""
    from bot.game import is_mafia_team

    pl = game.players.get(uid)
    if pl is None or pl.role is None:
        return "شهروند"
    if is_mafia_team(pl.role):
        return "مافیا"
    return "شهروند"


def clear_mason_gunner_night_pick(game: Game) -> None:
    game.mason_gunner_night_target_uid = None
    game.mason_gunner_night_no_give = False


def clear_mason_day_gun_state(game: Game) -> None:
    game.mason_day_gun_holder_uid = None
    game.mason_day_gun_sabotaged = False
    game.mason_day_gun_used = False
    game.mason_gun_spent = False
    game.mason_day_gun_shot_target_uid = None


def expire_mason_day_gun_for_vote_start(game: Game) -> int | None:
    """پایان مهلت تفنگ روز با شروع رأی — day gun بسته می‌شود؛ mason_gun_spent دست نمی‌خورد."""
    if not is_mason_scenario(game):
        return None
    if not mason_day_gun_available(game):
        return None
    holder_uid = mason_day_gun_holder_uid(game)
    if holder_uid is None:
        return None
    game.mason_day_gun_used = True
    game.mason_day_gun_holder_uid = None
    game.mason_day_gun_sabotaged = False
    game.mason_day_gun_shot_target_uid = None
    return holder_uid


def clear_mason_gunner_night_state(game: Game) -> None:
    clear_mason_gunner_night_pick(game)
