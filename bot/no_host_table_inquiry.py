"""استعلام وضعیت میز قبل از شروع روز — مسیر بدون گرداننده."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING, Literal

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.bazpors_narrator import (
    BazporsNarrCb,
    Role,
    _mark_day_start_alive_snapshot,
    _seat_fa,
    _sync_ki_as_today,
    no_host_assistant_narrator_active,
    push_host_step,
)
from bot.game import bazpors_counts_as_mafia_faction, is_synthetic_player_uid
from bot.models import Game
from bot.no_host_night_resolve import (
    build_no_host_day_started_broadcast_html,
)
from bot.observer_delivery import (
    broadcast_to_alive_players,
    deliver_no_host_player_game_copy,
)

if TYPE_CHECKING:
    from bot.game import GameManager

NO_HOST_TABLE_INQUIRY = "no_host_table_inquiry"

TABLE_INQUIRY_FLOW_ACTS = frozenset(
    {"tinq_yes", "tinq_no", "tinq_back", "tinq_ok"}
)

PHASE_ASK = "ask"
PHASE_CONFIRM = "confirm"

PendingChoice = Literal["yes", "no"]


def reset_no_host_table_inquiry_state(game: Game) -> None:
    game.no_host_table_inquiry_phase = None
    game.no_host_table_inquiry_pending = None


def _assistant_tag(game: Game, gm: "GameManager") -> str:
    uid = game.bot_assistant_user_id
    if uid is not None and uid in game.players:
        return gm.format_player_tag(game.players[uid])
    return "کمک‌کننده ربات"


def _dead_faction_counts(game: Game) -> tuple[int, int]:
    mafia_dead = 0
    citizen_dead = 0
    for p in game.players.values():
        if p.is_alive or p.role == Role.OBSERVER:
            continue
        if bazpors_counts_as_mafia_faction(game, p):
            mafia_dead += 1
        else:
            citizen_dead += 1
    return mafia_dead, citizen_dead


def build_table_inquiry_ask_panel() -> str:
    return (
        "📢 آیا بازیکنان حاضر در بازی، به اتفاق آرا خواهان استعلام وضعیت میز "
        "هستند؟\n\n"
        "⚠️ در صورت انتخاب و تأیید نهایی هرکدام از گزینه‌ها، پیام مربوطه برای "
        "تمامی بازیکنان حاضر در بازی ارسال خواهد شد."
    )


def build_table_inquiry_confirm_panel(choice: PendingChoice) -> str:
    label = "بله — استعلام وضعیت میز" if choice == "yes" else "خیر — بدون استعلام"
    return (
        f"{build_table_inquiry_ask_panel()}\n\n"
        f"انتخاب شما: <b>{html.escape(label)}</b>\n\n"
        "آیا تأیید می‌کنید؟"
    )


def build_table_inquiry_yes_broadcast_html(game: Game, gm: "GameManager") -> str:
    tag = html.escape(_assistant_tag(game, gm))
    mafia_n, citizen_n = _dead_faction_counts(game)
    return (
        f"📢 🎭 <b>{tag}</b> به نمایندگی از سایر بازیکنان، درخواست استعلام "
        "وضعیت میز را ثبت کرده است.\n\n"
        "📋 تاکنون از بازی:\n"
        f"🔪 {_seat_fa(mafia_n)} عضو مافیا\n"
        "و\n"
        f"👥 {_seat_fa(citizen_n)} شهروند\n"
        "خارج شده‌اند."
    )


def build_table_inquiry_no_broadcast_html(game: Game, gm: "GameManager") -> str:
    tag = html.escape(_assistant_tag(game, gm))
    return (
        f"📢 🎭 <b>{tag}</b> به نمایندگی از سایر بازیکنان اعلام کرد که "
        "استعلام وضعیت میز لازم نیست."
    )


async def _broadcast_to_all_game_participants(
    bot: Bot, game: Game, text: str, *, parse_mode: str = "HTML"
) -> None:
    """همهٔ بازیکنان ثبت‌شده در اتاق (زنده و خارج‌شده)، بدون ناظر."""
    for uid, p in sorted(game.players.items(), key=lambda x: x[0]):
        if p.role == Role.OBSERVER:
            continue
        await deliver_no_host_player_game_copy(
            bot,
            game,
            uid,
            text,
            parse_mode=parse_mode,
            is_synthetic_uid=is_synthetic_player_uid,
        )


def enter_no_host_table_inquiry_before_day(game: Game) -> None:
    game.bazpors_narrator_step = NO_HOST_TABLE_INQUIRY
    game.no_host_table_inquiry_phase = PHASE_ASK
    game.no_host_table_inquiry_pending = None


async def no_host_enter_table_inquiry_before_day(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if not no_host_assistant_narrator_active(game):
        return
    enter_no_host_table_inquiry_before_day(game)


async def no_host_prompt_table_inquiry_before_day(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """ورود به فاز استعلام میز و ارسال پنل کمک‌کننده (مثلاً پس از رد انتقال گردانندگی)."""
    if not no_host_assistant_narrator_active(game):
        return
    enter_no_host_table_inquiry_before_day(game)
    await push_host_step(bot, game, gm, force_new_host_message=True)


async def no_host_finish_day_start_after_table_inquiry(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    from bot.bazpors_narrator import DAY_DISCUSS

    game.bazpors_narrator_host_day += 1
    _mark_day_start_alive_snapshot(game)
    _sync_ki_as_today(game, gm)
    from bot.room_mode import is_mason_scenario

    if is_mason_scenario(game):
        from bot.mason_chaos import sync_mason_chaos_today

        sync_mason_chaos_today(game, gm)
    game.bazpors_interrog_ready_for_day = False
    game.bazpors_interrog_cancel_next_day = False
    game.bazpors_narrator_step = DAY_DISCUSS
    reset_no_host_table_inquiry_state(game)

    exclude = game.bot_assistant_user_id
    day_text = f"☀️ {build_no_host_day_started_broadcast_html(game, gm)}"
    await broadcast_to_alive_players(
        bot,
        game,
        day_text,
        exclude=exclude,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    from bot.no_host_day_vote import (
        clear_no_host_day_mirror_prompts,
        reset_no_host_day_vote_prompt_state,
        send_no_host_day_vote_prompt,
    )

    reset_no_host_day_vote_prompt_state(game)
    clear_no_host_day_mirror_prompts(game)
    ki_as_day = game.bazpors_ki_as_today and not gm.check_winner(game)

    if is_mason_scenario(game):
        if ki_as_day:
            from bot.mason_chaos import start_mason_chaos_flow

            await start_mason_chaos_flow(bot, game, gm)
        else:
            from bot.mason_game_flow import mason_on_day_started_after_inquiry

            await mason_on_day_started_after_inquiry(bot, game, gm)
    elif ki_as_day:
        from bot.chaos_handshake import ensure_chaos_handshake_started

        await ensure_chaos_handshake_started(bot, game, gm)
    else:
        await push_host_step(bot, game, gm)
        await send_no_host_day_vote_prompt(bot, game)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day_started_after_night",
            host_day=game.bazpors_narrator_host_day,
            night_count=game.bazpors_narrator_night_count,
            ki_as_today=ki_as_day,
        )
    except Exception:
        pass


def build_no_host_table_inquiry_assistant_panel(
    game: Game, gm: "GameManager"
) -> tuple[str, InlineKeyboardMarkup | None]:
    code = game.room_code
    phase = game.no_host_table_inquiry_phase or PHASE_ASK

    if phase == PHASE_ASK:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔘 بله",
                        callback_data=BazporsNarrCb(
                            code=code, act="tinq_yes", tid=0
                        ).pack(),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="🔘 خیر",
                        callback_data=BazporsNarrCb(
                            code=code, act="tinq_no", tid=0
                        ).pack(),
                    )
                ],
            ]
        )
        return build_table_inquiry_ask_panel(), kb

    if phase == PHASE_CONFIRM:
        pending = game.no_host_table_inquiry_pending
        if pending not in ("yes", "no"):
            return "خطا: انتخاب نامشخص.", None
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✅ تأیید",
                        callback_data=BazporsNarrCb(
                            code=code, act="tinq_ok", tid=0
                        ).pack(),
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="↩️ بازگشت",
                        callback_data=BazporsNarrCb(
                            code=code, act="tinq_back", tid=0
                        ).pack(),
                    )
                ],
            ]
        )
        return build_table_inquiry_confirm_panel(pending), kb

    return "خطا: فاز استعلام میز نامشخص.", None


def process_no_host_table_inquiry_narrator_cb(
    game: Game, gm: "GameManager", act: str, tid: int
) -> str | None:
    if game.bazpors_narrator_step != NO_HOST_TABLE_INQUIRY:
        return "نامعتبر."
    phase = game.no_host_table_inquiry_phase

    if act == "tinq_yes":
        if phase != PHASE_ASK:
            return "نامعتبر."
        game.no_host_table_inquiry_pending = "yes"
        game.no_host_table_inquiry_phase = PHASE_CONFIRM
        return None

    if act == "tinq_no":
        if phase != PHASE_ASK:
            return "نامعتبر."
        game.no_host_table_inquiry_pending = "no"
        game.no_host_table_inquiry_phase = PHASE_CONFIRM
        return None

    if act == "tinq_back":
        if phase != PHASE_CONFIRM:
            return "نامعتبر."
        game.no_host_table_inquiry_pending = None
        game.no_host_table_inquiry_phase = PHASE_ASK
        return None

    if act == "tinq_ok":
        if phase != PHASE_CONFIRM:
            return "نامعتبر."
        if game.no_host_table_inquiry_pending not in ("yes", "no"):
            return "خطا."
        return None

    return "نامعتبر."


async def apply_no_host_table_inquiry_confirm(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    choice = game.no_host_table_inquiry_pending
    game.no_host_table_inquiry_resolved_for_day = True
    if choice == "yes":
        text = build_table_inquiry_yes_broadcast_html(game, gm)
        await _broadcast_to_all_game_participants(bot, game, text)
    elif choice == "no":
        text = build_table_inquiry_no_broadcast_html(game, gm)
        await broadcast_to_alive_players(
            bot,
            game,
            text,
            parse_mode="HTML",
            is_synthetic_uid=is_synthetic_player_uid,
        )
    if game.no_host_interrog_night_gate_pending:
        game.no_host_interrog_night_gate_pending = False
        reset_no_host_table_inquiry_state(game)
        from bot.no_host_interrog_day import (
            bootstrap_no_host_interrog_day_after_night,
            enter_no_host_interrog_day_step,
        )

        enter_no_host_interrog_day_step(game)
        await bootstrap_no_host_interrog_day_after_night(bot, game, gm)
        try:
            from bot.game_audit_log import log_event

            log_event(
                game,
                "no_host.table_inquiry_resolved",
                choice=choice,
                host_day=game.bazpors_narrator_host_day,
                before_interrog=True,
            )
        except Exception:
            pass
        return
    from bot.no_host_handoff import maybe_prompt_handoff_before_day_start

    reset_no_host_table_inquiry_state(game)
    if await maybe_prompt_handoff_before_day_start(bot, game, gm):
        try:
            from bot.game_audit_log import log_event

            log_event(
                game,
                "no_host.table_inquiry_resolved",
                choice=choice,
                host_day=game.bazpors_narrator_host_day,
                handoff_offered=True,
            )
        except Exception:
            pass
        return
    await no_host_finish_day_start_after_table_inquiry(bot, game, gm)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.table_inquiry_resolved",
            choice=choice,
            host_day=game.bazpors_narrator_host_day,
        )
    except Exception:
        pass
