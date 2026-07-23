"""رأی‌گیری پایان روز — مسیر بدون گرداننده (روز اول و روزهای بعد)."""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.bazpors_narrator import (
    DAY_DISCUSS,
    _seat_fa,
    no_host_assistant_narrator_active,
)
from bot.observer_delivery import PlayerMirrorCb
from bot.models import Game
from bot.observer_delivery import (
    game_observer_mirror_active,
    mirror_ui_claim_key,
    mirrored_day1_vote_choice_keyboard,
    no_host_observer_registered,
    register_mirror_prompt_pair,
)


def no_host_day_ordinal_fa(day: int) -> str:
    d = max(1, day)
    if d == 1:
        return "اول"
    if d == 2:
        return "دوم"
    if d == 3:
        return "سوم"
    return _seat_fa(d)


def no_host_night_ordinal_fa(night_count: int) -> str:
    nc = max(1, night_count)
    if nc == 1:
        return "یک"
    if nc == 2:
        return "دو"
    if nc == 3:
        return "سه"
    return _seat_fa(nc)


def no_host_upcoming_night_ordinal_fa(game: Game) -> str:
    """شمارهٔ شبی که با پایان رأی روز جاری آغاز می‌شود."""
    return no_host_night_ordinal_fa(game.bazpors_narrator_night_count + 1)


def no_host_end_day_vote_cb_allowed(game: Game) -> bool:
    """دکمه‌های پایان روز (d1_skip / d1_vote) در این فازها مجازند."""
    if not no_host_assistant_narrator_active(game):
        return False
    if game.bazpors_ki_as_today:
        return False
    if not game.no_host_intro_night_started:
        return False
    if game.no_host_day1_vote_resolved:
        return False
    if game.bazpors_narrator_step == DAY_DISCUSS:
        return True
    return bool(game.no_host_day1_vote_prompt_sent)


def reset_no_host_day_vote_prompt_state(game: Game) -> None:
    """آماده برای نمایش پنل رأی روز جدید (معمولاً روز ۲ به بعد)."""
    game.no_host_day1_vote_prompt_sent = False
    game.no_host_day1_vote_resolved = False
    game.no_host_day1_defense_active = False
    game.no_host_day1_defense_phase = None
    game.no_host_day1_pending_elim_uid = None


def clear_no_host_day_mirror_prompts(game: Game) -> None:
    """حذف ارجاع پیام‌های آینهٔ رأی/دفاعیه تا promote روی پیام قدیمی نرود."""
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return
    room = game.room_code
    d = max(1, game.bazpors_narrator_host_day)
    vote_kind = "day1_vote_choice" if d == 1 else f"day_vote_choice_{d}"
    kinds = (
        vote_kind,
        "day1_defense_pick" if d == 1 else f"day_defense_pick_{d}",
        "day1_defense_outcome" if d == 1 else f"day_defense_outcome_{d}",
        "day1_defense_pick_elim" if d == 1 else f"day_defense_pick_elim_{d}",
        "day1_defense_confirm_elim"
        if d == 1
        else f"day_defense_confirm_elim_{d}",
    )
    for kind in kinds:
        key = mirror_ui_claim_key(room, kind, assistant_uid)
        game.mirror_prompt_messages.pop(key, None)
        game.mirror_action_claims.pop(key, None)


def build_no_host_day_vote_prompt_html(game: Game) -> str:
    day_word = no_host_day_ordinal_fa(game.bazpors_narrator_host_day)
    sun_line = (
        f"☀️ صحبت‌های روز {day_word} بازیکنان نیز انجام شد و پایان یافت و اکنون "
        f"به مرحله رأی‌گیری روز {day_word} رسیده‌ایم."
    )
    if max(1, game.bazpors_narrator_host_day) == 1:
        return (
            "🌙 شب معارفه برگزار شد و اعضای مافیا یکدیگر را شناختند "
            "و با هم مشورت کردند.\n\n"
            f"{sun_line}"
        )
    return sun_line


def no_host_day_vote_choice_ui_key(game: Game, assistant_uid: int) -> str:
    d = max(1, game.bazpors_narrator_host_day)
    kind = "day1_vote_choice" if d == 1 else f"day_vote_choice_{d}"
    return mirror_ui_claim_key(game.room_code, kind, assistant_uid)


def day_vote_choice_keyboard_for(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    if game_observer_mirror_active(game):
        return mirrored_day1_vote_choice_keyboard(game, assistant_uid)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔹 کسی برای دفاعیه انتخاب نشد؛ پس به فاز شب می‌رویم",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act="d1_skip",
                        as_uid=assistant_uid,
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔹 رأی‌گیری لازم است؛ پنل انتخاب بازیکن را نمایش بده",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act="d1_vote",
                        as_uid=assistant_uid,
                    ).pack(),
                ),
            ],
        ]
    )


async def send_no_host_day_vote_prompt(bot: Bot, game: Game) -> None:
    if not no_host_assistant_narrator_active(game):
        return
    if game.bazpors_ki_as_today:
        return
    if game.bot_assistant_user_id is None:
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None or game.no_host_day1_vote_prompt_sent:
        return
    host_day = max(1, game.bazpors_narrator_host_day)
    if host_day == 1 and not game.no_host_intro_night_started:
        return
    game.no_host_day1_vote_prompt_sent = True
    from bot.bazpors_narrator import begin_no_host_day1_defense_pick

    begin_no_host_day1_defense_pick(game)
    game.no_host_day1_vote_resolved = True
    from bot.main import send_no_host_day1_defense_pick_panel

    await send_no_host_day1_defense_pick_panel(bot, game)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_vote_panel_opened",
            assistant_uid=assistant_uid,
            actor_uid=assistant_uid,
        )
    except Exception:
        pass


