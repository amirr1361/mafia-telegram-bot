"""فازهای گردانندگی بدون گرداننده (no_host).

این ماژول **نقطهٔ ورود نام‌گذاری‌شده** برای جریان‌های no_host است؛ منطق جزئی
در `nam10_night1`، `nam10_mafia_*` و `main` باقی می‌ماند.

توابع عمده:

- ``run_no_host_night1_phase`` — ورود به شب ۱ (وکیل + منوی مافیا + ادامهٔ نریتور).
- ``nam10_night1_open_hunter_night_action`` / ``nam10_night1_open_mafia_team_night_action`` —
  اقدام شبانهٔ وکیل و تیم مافیا در شب ۱.
- ``nam10_run_mafia_shot_operation`` / ``nam10_run_mafia_yaku_operation`` /
  ``nam10_run_mafia_nato_operation`` — زیرعملیات انتخاب‌شدهٔ مافیا پس از تأیید منو.
- ``nam10_run_day1_end_vote_flow`` — شروع رأی‌گیری / دفاعیهٔ پایان روز اول.
- ``nam10_advance_narrator_after_night_work`` — پیش‌برد نریتور راهنما (محاسبه و مرحلهٔ بعد).
- ``dispatch_no_host_role_night_panels`` / ``nam10_send_*_night_selection_*`` —
  پیام خصوصی پنل شبانهٔ نقش‌ها در no_host (هماهنگ با ``push_host_step``).
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from aiogram import Bot

from bot.nam10.nmnd_narrator import NS_DISCIPLINE_ASK, NIGHT_START, push_host_step
from bot.models import Game
from bot.nam10.no_host_detective_night import (
    dispatch_no_host_detective_night_panel,
    flush_no_host_detective_result_pending,
    start_no_host_detective_night_flow,
)
from bot.nam10.no_host_doctor_night import (
    dispatch_no_host_doctor_night_panel,
    apply_no_host_doctor_nato_blocked_panel,
    start_no_host_doctor_night_flow,
)
from bot.nam10.no_host_citizen_night import (
    dispatch_no_host_citizen_night_panel,
    start_no_host_citizen_night_flow,
)
from bot.nam10.no_host_night_entry import (
    dispatch_all_no_host_night_entry_panels,
    complete_no_host_role_night_if_already_picked,
)
from bot.nam10.no_host_ruintan_night import (
    dispatch_no_host_ruintan_night_panel,
    start_no_host_ruintan_night_flow,
)
from bot.nam10.no_host_shiad_night import (
    dispatch_no_host_shiad_night_panel,
    flush_no_host_shiad_result_pending,
    start_no_host_shiad_night_flow,
)
from bot.nam10.no_host_sniper_night import (
    dispatch_no_host_sniper_night_panel,
    flush_no_host_sniper_result_pending,
    start_no_host_sniper_night_flow,
)
from bot.nam10.no_host_night_role_dms import (
    dispatch_no_host_role_night_panels,
    nam10_send_detective_night_selection_if_in_game,
    nam10_send_doctor_night_selection_if_alive,
    nam10_send_interrogator_night_selection_if_alive,
    nam10_send_shiad_night_selection_if_alive,
    nam10_send_sniper_night_selection_if_alive,
)

if TYPE_CHECKING:
    from bot.nam10.engine import GameManager


def reset_no_host_per_night_role_state(game: Game) -> None:
    """ریست پنل‌های شبانهٔ no_host برای شب جدید (وکیل، مافیا، نقش‌های DM)."""
    from bot.nam10.game_state import reset_no_host_per_night_role_state as _reset

    _reset(game)


__all__ = [
    "dispatch_no_host_detective_night_panel",
    "dispatch_no_host_doctor_night_panel",
    "apply_no_host_doctor_nato_blocked_panel",
    "dispatch_no_host_role_night_panels",
    "start_no_host_doctor_night_flow",
    "dispatch_all_no_host_night_entry_panels",
    "complete_no_host_role_night_if_already_picked",
    "dispatch_no_host_citizen_night_panel",
    "start_no_host_citizen_night_flow",
    "dispatch_no_host_ruintan_night_panel",
    "start_no_host_ruintan_night_flow",
    "dispatch_no_host_shiad_night_panel",
    "start_no_host_shiad_night_flow",
    "flush_no_host_shiad_result_pending",
    "dispatch_no_host_sniper_night_panel",
    "start_no_host_sniper_night_flow",
    "flush_no_host_sniper_result_pending",
    "flush_no_host_detective_result_pending",
    "start_no_host_detective_night_flow",
    "nam10_advance_narrator_after_night_work",
    "reset_no_host_per_night_role_state",
    "nam10_night1_open_hunter_night_action",
    "nam10_night1_open_mafia_team_night_action",
    "nam10_run_day1_end_vote_flow",
    "nam10_run_mafia_nato_operation",
    "nam10_run_mafia_shot_operation",
    "nam10_run_mafia_yaku_operation",
    "nam10_send_detective_night_selection_if_in_game",
    "nam10_send_doctor_night_selection_if_alive",
    "nam10_send_interrogator_night_selection_if_alive",
    "nam10_send_shiad_night_selection_if_alive",
    "nam10_send_sniper_night_selection_if_alive",
    "run_no_host_night1_phase",
]


async def nam10_night1_open_hunter_night_action(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پنل و اقدامات لازم برای نقش وکیل در شب ۱ (no_host)."""
    from bot.nam10.no_host_night1 import start_no_host_night1_hunter_flow

    await start_no_host_night1_hunter_flow(bot, game, gm)


async def nam10_night1_open_mafia_team_night_action(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """منوی انتخاب عمل تیم مافیا در شب ۱ — شات / یاکو / یاغی (no_host)."""
    from bot.nam10.no_host_mafia_night1 import start_no_host_night1_mafia_flow

    await start_no_host_night1_mafia_flow(bot, game, gm)


async def nam10_open_night1_assistant_panels(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پنل وکیل/مافیا برای صندلی مصنوعی — انسان‌ها (از جمله کمک‌کننده) در ورود شب."""
    from bot.nam10.no_host_night_common import (
        nam10_night1_needs_assistant_hunter,
        nam10_night1_needs_assistant_mafia,
    )

    tasks: list = []
    if nam10_night1_needs_assistant_hunter(game):
        tasks.append(nam10_night1_open_hunter_night_action(bot, game, gm))
    if nam10_night1_needs_assistant_mafia(game):
        tasks.append(nam10_night1_open_mafia_team_night_action(bot, game, gm))
    if tasks:
        await asyncio.gather(*tasks)


async def nam10_maybe_continue_after_night1_assistant(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پس از تأیید وکیل و مافیا در شب ۱ — ادامه به انضباط/محاسبه."""
    if game.nmnd_narrator_night_count != 1:
        await push_host_step(bot, game, gm)
        return
    if not game.nam10_night1_hunter_done or not game.nam10_mafia_night1_done:
        await push_host_step(bot, game, gm)
        return
    if game.nmnd_night_substep == NS_DISCIPLINE_ASK:
        await push_host_step(bot, game, gm)
        return
    from bot.nam10.nmnd_narrator import _goto_discipline_ask

    _goto_discipline_ask(game)
    await push_host_step(bot, game, gm)


async def run_no_host_night1_phase(bot: Bot, game: Game, gm: "GameManager") -> None:
    """ورود به فاز شب: فقط پنل‌های موازی نقش‌ها (وکیل/مافیا بعد از جمع‌آوری).

    از هر مسیری که به شب no_host برسیم باید همین تابع (یا معادلش
    ``on_no_host_entered_night``) فراخوانی شود.
    """
    if game.nmnd_narrator_step == NIGHT_START:
        await dispatch_all_no_host_night_entry_panels(bot, game, gm)


async def nam10_run_mafia_shot_operation(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """عملیات شات مافیا در شب ۱ (no_host)."""
    from bot.nam10.no_host_mafia_shot import start_no_host_mafia_shot_flow

    await start_no_host_mafia_shot_flow(bot, game, gm)


async def nam10_run_mafia_yaku_operation(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """عملیات یاکوزایی تیم مافیا در شب ۱ (no_host)."""
    from bot.nam10.no_host_mafia_yaku import start_no_host_mafia_yaku_flow

    await start_no_host_mafia_yaku_flow(bot, game, gm)


async def nam10_run_mafia_nato_operation(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """عملیات ناتویی در شب ۱ (no_host)."""
    from bot.nam10.no_host_mafia_nato import start_no_host_mafia_nato_flow

    await start_no_host_mafia_nato_flow(bot, game, gm)


async def nam10_run_day1_end_vote_flow(bot: Bot, game: Game) -> None:
    """شروع جریان رأی‌گیری و دفاعیهٔ پایان روز (no_host)."""
    from bot.nam10.no_host_day_vote import send_no_host_day_vote_prompt

    await send_no_host_day_vote_prompt(bot, game)


async def nam10_advance_narrator_after_night_work(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پیش‌برد نریتور راهنما: اعمال وضعیت شب و مرحلهٔ بعد (شامل محاسبات گام‌به‌گام).

    معادل فراخوانی ``push_host_step`` برای اتاق‌های no_host و سایر حالت‌ها
    که از همان نریتور استفاده می‌کنند.
    """
    await push_host_step(bot, game, gm)
