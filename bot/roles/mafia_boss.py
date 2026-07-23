"""منطق هستهٔ رئیس مافیا — مشترک semi_auto و no_host."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.game import is_mafia_team
from bot.models import Game, Player, Role
from bot.room_mode import is_mozakere_scenario

if TYPE_CHECKING:
    from bot.game import GameManager

from bot.roles import simple_mafia as _simple_mafia_role
from bot.roles.night_state import yaku_night_state

_SIMPLE_MAFIA_ROLES = _simple_mafia_role.SIMPLE_MAFIA_ROLES
is_simple_mafia_role = _simple_mafia_role.is_simple_mafia_role


def find_alive_boss(game: Game) -> Player | None:
    for p in game.players.values():
        if p.is_alive and p.role == Role.MAFIA_BOSS:
            return p
    return None


def is_mafia_shot_decider(game: Game, p: Player) -> bool:
    """آیا این بازیکن مجری شلیک شب مافیاست؟ (مذاکره: رئیس؛ بازپرس: رئیس/ناتو/شیاد/…)."""
    chooser = resolve_shot_chooser(game)
    return chooser is not None and chooser.user_id == p.user_id


def is_yaku_recruit(game: Game, p: Player) -> bool:
    if is_mozakere_scenario(game):
        return False
    if not p.is_alive:
        return False
    if p.user_id in game.bazpors_mafia_recruit_ids:
        return True
    return bool(getattr(p, "bazpors_converted_by_yakuza", False))


def alive_mafia_members(game: Game) -> list[Player]:
    from bot.bazpors_narrator import _alive, _visually_mafia

    return sorted(
        (p for p in _alive(game) if _visually_mafia(game, p)),
        key=lambda p: (p.seat if p.seat is not None else 999, p.user_id),
    )


def alive_yakuza_recruits(game: Game) -> list[Player]:
    if is_mozakere_scenario(game):
        return []
    from bot.bazpors_narrator import _alive

    return sorted(
        (p for p in _alive(game) if is_yaku_recruit(game, p)),
        key=lambda p: (p.seat if p.seat is not None else 999, p.user_id),
    )


def yaku_recruit_panel_fallback(game: Game) -> list[Player]:
    """همهٔ مافیاهای نقش‌دار مرده‌اند؛ فقط یاکوزایی‌شدهٔ زنده پنل می‌گیرد."""
    if is_mozakere_scenario(game):
        return []
    if not yaku_night_state(game).used:
        return []
    return alive_yakuza_recruits(game)


def _mozakere_resolve_shot_chooser(game: Game) -> Player | None:
    """مذاکره — فقط رئیس زنده؛ وگرنه اولین عضو زندهٔ تیم مافیا."""
    boss = find_alive_boss(game)
    if boss is not None:
        return boss
    mafia_alive = alive_mafia_members(game)
    return mafia_alive[0] if mafia_alive else None


def _bazpors_resolve_shot_chooser(game: Game) -> Player | None:
    """بازپرس — رئیس زنده، وگرنه ناتو، وگرنه شیاد، وگرنه اولین مافیا."""
    from bot.bazpors_narrator import _find_alive_role, _visually_mafia

    mafia_alive = alive_mafia_members(game)
    if not mafia_alive:
        recruits = yaku_recruit_panel_fallback(game)
        return recruits[0] if recruits else None
    for role in (Role.MAFIA_BOSS, Role.NATO, Role.SHIAD):
        p = _find_alive_role(game, role)
        if p is not None and p.is_alive and _visually_mafia(game, p):
            return p
    return mafia_alive[0]


def resolve_shot_chooser(game: Game) -> Player | None:
    if is_mozakere_scenario(game):
        return _mozakere_resolve_shot_chooser(game)
    return _bazpors_resolve_shot_chooser(game)


def _mozakere_resolve_night1_menu_recipients(game: Game) -> list[Player]:
    """مذاکره — فقط مجری شلیک (رئیس یا جایگزین پس از مرگ رئیس)."""
    chooser = _mozakere_resolve_shot_chooser(game)
    return [chooser] if chooser is not None else []


def _bazpors_resolve_night1_menu_recipients(game: Game) -> list[Player]:
    """بازپرس — منوی شات/یاکو/ناتو: فقط رئیس؛ وگرنه ناتو؛ وگرنه مافیاهای غیرساده."""
    from bot.bazpors_narrator import _find_alive_role, _visually_mafia

    mafia_alive = alive_mafia_members(game)
    if not mafia_alive:
        return yaku_recruit_panel_fallback(game)
    boss = find_alive_boss(game)
    if boss is not None:
        return [boss]
    nato = _find_alive_role(game, Role.NATO)
    if nato is not None and nato.is_alive and _visually_mafia(game, nato):
        return [nato]
    non_simple = [
        p for p in mafia_alive if p.role and not is_simple_mafia_role(p.role)
    ]
    if non_simple:
        return non_simple
    return mafia_alive


def resolve_night1_menu_recipients(game: Game) -> list[Player]:
    if is_mozakere_scenario(game):
        return _mozakere_resolve_night1_menu_recipients(game)
    return _bazpors_resolve_night1_menu_recipients(game)


def should_start_shiad_direct_shot_menu(game: Game) -> bool:
    """بدون رئیس و ناتو — شیاد مستقیم پنل شات (شب ۱ یا ۲+)."""
    if is_mozakere_scenario(game):
        return False
    from bot.bazpors_narrator import _find_alive_role

    if find_alive_boss(game) is not None:
        return False
    if _find_alive_role(game, Role.NATO) is not None:
        return False
    sh = _find_alive_role(game, Role.SHIAD)
    return sh is not None and sh.is_alive


def yaku_sacrifice_pool(game: Game) -> list[Player]:
    """مافیاهایی که می‌توانند فدا شوند؛ اگر بیش از یک مافیا زنده باشد رئیس حذف می‌شود."""
    if is_mozakere_scenario(game):
        return []
    from bot.bazpors_narrator import _alive

    mafs = [p for p in _alive(game) if p.role and is_mafia_team(p.role)]
    if len(mafs) > 1:
        return [p for p in mafs if p.role != Role.MAFIA_BOSS]
    return mafs


def yakuzai_allowed(game: Game, gm: "GameManager") -> bool:
    if is_mozakere_scenario(game):
        return False
    if yaku_night_state(game).used:
        return False
    if find_alive_boss(game) is None:
        return False
    if gm.check_winner(game):
        return False
    if not yaku_sacrifice_pool(game):
        return False
    from bot.bazpors_narrator import _alive, _visually_mafia

    return any(not _visually_mafia(game, p) for p in _alive(game))


def hunter_chain_eliminates_link(game: Game, link_player: Player) -> bool:
    """با مرگ هانتر فقط وصل به مافیا (غیر از رئیس مافیا) همراه خارج می‌شود."""
    if link_player.role == Role.MAFIA_BOSS:
        return False
    from bot.bazpors_narrator import _visually_mafia

    return _visually_mafia(game, link_player)


def sniper_boss_immune(target: Player) -> bool:
    return target.role == Role.MAFIA_BOSS


def reads_negative_for_detective(target: Player) -> bool:
    return target.role == Role.MAFIA_BOSS


def yaku_boss_uid(game: Game) -> int | None:
    """رییس مافیا — تنها کسی که فدا و هدف یاکوزایی را انتخاب می‌کند."""
    if is_mozakere_scenario(game):
        return None
    boss = find_alive_boss(game)
    return boss.user_id if boss is not None else None


def yaku_boss_actor_may_act(game: Game, actor_uid: int, boss_uid: int) -> bool:
    """فقط رییس مافیا (یا ناظر برای صندلی مصنوعی رییس) می‌تواند یاکوزایی را انجام دهد."""
    if is_mozakere_scenario(game):
        return False
    from bot.game import is_synthetic_player_uid
    from bot.observer_delivery import no_host_observer_registered

    if actor_uid == boss_uid:
        return True
    return bool(
        is_synthetic_player_uid(boss_uid)
        and no_host_observer_registered(game)
        and game.observer_user_id == actor_uid
    )
