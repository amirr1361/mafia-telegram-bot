"""جریان اصلی بازی ماسون — no_host (معارفه تا چرخهٔ روز/شب)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot

from bot.models import Game
from bot.room_mode import is_mason_scenario, no_host_bot_assistant_flow_enabled

if TYPE_CHECKING:
    from bot.game import GameManager


async def mason_on_day_started_after_inquiry(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پس از استعلام/آمار — شروع روز جدید: محافظت، سکوت، پنل‌های روز."""
    if not is_mason_scenario(game):
        return

    from bot.mason_day_ability import dispatch_mason_day_start_panels
    from bot.mason_helper_flow import send_mason_vote_start_prompt
    from bot.no_host_day_vote import clear_no_host_day_mirror_prompts
    from bot.observer_delivery import broadcast_to_alive_players
    from bot.roles import mason_guardian as ms_gd
    from bot.roles import mason_natasha as ms_nat
    from bot.game import is_synthetic_player_uid

    ms_gd.activate_mason_guardian_day_protection(game)
    ms_gd.clear_mason_guardian_night_pick(game)

    silence = ms_nat.resolve_mason_natasha_day_effect(game)
    if silence:
        await broadcast_to_alive_players(
            bot,
            game,
            silence,
            is_synthetic_uid=is_synthetic_player_uid,
        )
    ms_nat.clear_mason_natasha_night_pick(game)

    from bot.roles import mason_priest as ms_pr

    ms_pr.clear_mason_priest_night_pick(game)

    game.mason_intro_day_ability_open = True
    game.mason_intro_day_ability_locked = False
    game.mason_vote_start_prompt_sent = False
    clear_no_host_day_mirror_prompts(game)

    await dispatch_mason_day_start_panels(bot, game, gm)

    from bot.bazpors_narrator import push_host_step

    await push_host_step(bot, game, gm)
    await send_mason_vote_start_prompt(bot, game)


async def mason_finish_parallel_night_collect(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پس از جمع‌آوری شب — محاسبهٔ خاموش، سپس خواب نیمروزی."""
    from bot.bazpors_narrator import NIGHT_ACTIONS
    from bot.mason_helper_flow import send_mason_midday_step_prompt
    from bot.mason_night_resolve import apply_mason_night_resolution
    from bot.mason_night_reminder import cleanup_mason_night_helper_reminder

    try:
        await cleanup_mason_night_helper_reminder(bot, game)
    except Exception:
        pass
    game.no_host_night_parallel_collect_active = False
    game.bazpors_narrator_step = NIGHT_ACTIONS
    apply_mason_night_resolution(game, gm)
    game.mason_midday_step_prompt_sent = False
    game.mason_midday_step_done = False
    await send_mason_midday_step_prompt(bot, game)


async def _disable_mason_helper_panel(
    bot: Bot, game: Game, ui_key: str, done_text: str
) -> None:
    """پنل کمک‌کنندهٔ قبلی را قفل کن (حذف دکمه‌ها) تا دیگر قابل استفاده نباشد."""
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return
    entry = game.mirror_prompt_messages.get(ui_key) or {}
    if not (entry.get("player") or entry.get("observer")):
        return
    from bot.observer_delivery import update_mirror_prompt_pair

    base = entry.get("text") or ""
    text = f"{base}\n\n<i>{done_text}</i>" if base else done_text
    await update_mirror_prompt_pair(
        bot,
        game,
        ui_key,
        text,
        None,
        assistant_uid=assistant_uid,
        parse_mode="HTML",
        observer_same_text=True,
    )


async def _mason_auto_start_vote(bot: Bot, game: Game) -> None:
    """معادل خودکارِ «شروع رأی‌گیری» کمک‌کننده (بدون کلیک)."""
    from bot.mason_day_ability import dismiss_mason_day_ability_panels
    from bot.mason_helper_flow import (
        _vote_ui_key,
        maybe_retire_mason_team_consultation_on_vote_start,
    )
    from bot.no_host_phase import no_host_run_day1_end_vote_flow

    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is not None:
        await _disable_mason_helper_panel(
            bot, game, _vote_ui_key(game, assistant_uid), "✅ رأی‌گیری آغاز شد."
        )
    maybe_retire_mason_team_consultation_on_vote_start(game)
    game.mason_intro_day_ability_open = False
    await dismiss_mason_day_ability_panels(bot, game)
    await no_host_run_day1_end_vote_flow(bot, game)


async def _mason_auto_choose_no_defense(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """معادل خودکارِ «کسی برای دفاعیه انتخاب نشد» کمک‌کننده (بدون کلیک)."""
    if game.no_host_day1_defense_phase != "pick":
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return
    from bot.bazpors_narrator import (
        no_host_day1_defense_no_votes_enter_night,
        set_day_vote_defender_uids,
        set_day_vote_pick_uids,
    )
    from bot.game import is_synthetic_player_uid
    from bot.main import (
        _no_host_day1_defense_pick_ui_key,
        build_no_host_day1_no_defense_votes_broadcast_html,
    )
    from bot.no_host_night1 import on_no_host_entered_night1
    from bot.observer_delivery import broadcast_to_alive_players

    set_day_vote_pick_uids(game, set())
    set_day_vote_defender_uids(game, set())
    await _disable_mason_helper_panel(
        bot,
        game,
        _no_host_day1_defense_pick_ui_key(game, assistant_uid),
        "✅ پیام پایان روز برای بازیکنان ارسال شد؛ وارد شب می‌شویم.",
    )
    broadcast = build_no_host_day1_no_defense_votes_broadcast_html(game, assistant_uid)
    await broadcast_to_alive_players(
        bot,
        game,
        broadcast,
        exclude=assistant_uid,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    no_host_day1_defense_no_votes_enter_night(game)
    await on_no_host_entered_night1(bot, game, gm)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_defense_no_votes",
            assistant_uid=assistant_uid,
            actor_uid=assistant_uid,
            source="auto_apache",
        )
    except Exception:
        pass


async def mason_auto_continue_after_apache_result(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پس از اعلام نتیجهٔ آپاچی — ادامهٔ خودکار تا پنل مشورت مافیا.

    معادل این است که کمک‌کننده به‌ترتیب «شروع رأی‌گیری» و سپس «کسی برای
    دفاعیه انتخاب نشد» را زده باشد. سپس روی پنل «مشورت قبل از شب تیم مافیا
    انجام شود.» متوقف می‌شود؛ دکمهٔ «انجام شد» به‌صورت خودکار زده نمی‌شود.
    """
    if not is_mason_scenario(game):
        return
    if not no_host_bot_assistant_flow_enabled(game):
        return
    if game.bot_assistant_user_id is None:
        return
    if game.no_host_day1_vote_prompt_sent or game.no_host_day1_vote_resolved:
        return
    await _mason_auto_start_vote(bot, game)
    await _mason_auto_choose_no_defense(bot, game, gm)


async def mason_after_midday_step_confirmed(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پس از تأیید خواب نیمروزی — پنل اخراج انضباطی (نه انتظار هانتر/مافیا)."""
    if not is_mason_scenario(game):
        return
    from bot.bazpors_narrator import _goto_discipline_ask, push_host_step

    _goto_discipline_ask(game)
    await push_host_step(bot, game, gm, force_new_host_message=True)

    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "mason.parallel_night_collect_finished",
            night_count=game.bazpors_narrator_night_count,
        )
    except Exception:
        pass
