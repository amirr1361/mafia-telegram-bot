"""پیام خصوصی پنل‌های شبانهٔ نقش‌ها فقط برای مسیر «گردانندگی بدون گرداننده» (no_host).

قوانین همان زنجیرهٔ نیمه‌خودکار نریتور بازپرس است؛ بازیکن نقش‌دار دکمه‌ها را
خودش می‌زند (مجوز callback در ``no_host_night_role_player_may_act_bazpors_cb``).

رویین‌تن پنل انتخاب نقش ندارد؛ یادآوری شب در ``no_host_ruintan_night`` است.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot

from bot.models import Game

if TYPE_CHECKING:
    from bot.game import GameManager

async def dispatch_no_host_role_night_panels(
    bot: Bot, game: Game, gm: GameManager
) -> None:
    """پنل نقش‌ها از PlayerMirror ارسال می‌شود؛ دیگر از کیبورد دستیار کپی نمی‌شود."""
    return


async def no_host_send_doctor_night_selection_if_alive(
    bot: Bot, game: Game, gm: GameManager
) -> bool:
    from bot.no_host_doctor_night import start_no_host_doctor_night_flow

    return await start_no_host_doctor_night_flow(bot, game, gm)


async def no_host_send_detective_night_selection_if_in_game(
    bot: Bot, game: Game, gm: GameManager
) -> bool:
    from bot.no_host_detective_night import start_no_host_detective_night_flow

    return await start_no_host_detective_night_flow(bot, game, gm)


async def no_host_send_shiad_night_selection_if_alive(
    bot: Bot, game: Game, gm: GameManager
) -> bool:
    from bot.no_host_shiad_night import start_no_host_shiad_night_flow

    return await start_no_host_shiad_night_flow(bot, game, gm)


async def no_host_send_interrogator_night_selection_if_alive(
    bot: Bot, game: Game, gm: GameManager
) -> bool:
    from bot.no_host_interrogator_night import (
        dispatch_no_host_interrogator_night_panel,
    )

    await dispatch_no_host_interrogator_night_panel(bot, game, gm)
    return game.no_host_interrog_flow_active


async def no_host_send_sniper_night_selection_if_alive(
    bot: Bot, game: Game, gm: GameManager
) -> bool:
    from bot.no_host_sniper_night import start_no_host_sniper_night_flow

    return await start_no_host_sniper_night_flow(bot, game, gm)
