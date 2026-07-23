"""تعیین بازیکن مجاز برای منو/شات مافیا — رئیس → ناتو → شیاد (یا گادفادر ماسون)."""

from __future__ import annotations

from bot.models import Game, Player, Role
from bot.room_mode import is_mason_scenario
from bot.roles.registry import require_role_module

_boss_role = require_role_module(Role.MAFIA_BOSS)
_simple_mafia_role = require_role_module(Role.MAFIA_BASIC)

_alive_mafia_members = _boss_role.alive_mafia_members
_is_yakuza_recruit = _boss_role.is_yaku_recruit
_alive_yakuza_recruits = _boss_role.alive_yakuza_recruits
_yaku_recruit_panel_fallback = _boss_role.yaku_recruit_panel_fallback
_is_simple_mafia_role = _simple_mafia_role.is_simple_mafia_role
should_start_shiad_direct_shot_menu = _boss_role.should_start_shiad_direct_shot_menu


def resolve_mafia_shot_chooser(game: Game) -> Player | None:
    if is_mason_scenario(game):
        from bot.roles.mason_godfather import resolve_mason_shot_chooser

        return resolve_mason_shot_chooser(game)
    return _boss_role.resolve_shot_chooser(game)


def resolve_mafia_night1_menu_recipients(game: Game) -> list[Player]:
    if is_mason_scenario(game):
        from bot.roles.mason_godfather import resolve_mason_night1_menu_recipients

        return resolve_mason_night1_menu_recipients(game)
    return _boss_role.resolve_night1_menu_recipients(game)


def resolve_mafia_night1_panel_recipients(game: Game) -> list[Player]:
    """سازگاری با نام قدیمی — همان منوی شب ۱."""
    return resolve_mafia_night1_menu_recipients(game)


async def maybe_start_shiad_parallel_night_panels(
    bot, game: Game, gm
) -> None:
    """اگر مجری شات شیاد است، پنل شیادی را هم‌زمان با شات باز کن."""
    from bot.no_host_shiad_night import (
        _shiad_panel_already_sent_for_night,
        start_no_host_shiad_night_flow,
    )

    chooser = resolve_mafia_shot_chooser(game)
    if chooser is None or chooser.role != Role.SHIAD:
        return
    if game.no_host_shiad_pick_confirmed:
        return
    nc = game.bazpors_narrator_night_count
    if _shiad_panel_already_sent_for_night(game, nc):
        return
    await start_no_host_shiad_night_flow(bot, game, gm, at_night_entry=True)
