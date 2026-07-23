"""پنل‌های کمک‌کنندهٔ ماسون — شروع رأی‌گیری و شروع شب."""

from __future__ import annotations

from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.main import no_host_bot_assistant_flow_enabled
from bot.models import Game
from bot.no_host_day_vote import no_host_night_ordinal_fa
from bot.observer_delivery import (
    apply_mirror_claim_winner,
    mirror_ui_claim_key,
    no_host_observer_registered,
    register_mirror_prompt_pair,
    update_mirror_prompt_pair,
)
from bot.room_mode import is_mason_scenario

if TYPE_CHECKING:
    from bot.game import GameManager


class MasonHelperCb(CallbackData, prefix="msh"):
    """کمک‌کنندهٔ ماسون — رأی یا شب."""

    code: str
    act: str = "go"
    kind: str = "vote"


def build_mason_vote_start_html() -> str:
    return "برای شروع رأی‌گیری دکمه زیر را فشار دهید."


def build_mason_vote_start_confirm_html() -> str:
    return (
        "⚠️ <b>تأیید شروع رأی‌گیری</b>\n\n"
        "پس از تأیید، پنل‌های روزانهٔ آپاچی و کابوی غیرفعال می‌شوند "
        "و رأی‌گیری روز اول آغاز می‌شود."
    )


def build_mason_night_start_html(game: Game) -> str:
    night_w = no_host_night_ordinal_fa(game.bazpors_narrator_night_count)
    return f"برای شروع شب {night_w} دکمه زیر را فشار دهید."


def build_mason_night_start_confirm_html(game: Game) -> str:
    night_w = no_host_night_ordinal_fa(game.bazpors_narrator_night_count)
    return (
        f"⚠️ <b>تأیید شروع شب {night_w}</b>\n\n"
        "پس از تأیید، پنل‌های شبانهٔ نقش‌ها برای بازیکنان ارسال می‌شود."
    )


def mason_team_consult_required(game: Game) -> bool:
    """مشورت تیم ماسون از شب دوم به بعد — قبل از شروع شب."""
    return is_mason_scenario(game) and max(1, game.bazpors_narrator_night_count) >= 2


def mason_team_consultation_prompts_suppressed(game: Game) -> bool:
    """پس از فروپاشی و یک روز کامل، پنل‌های معرفی/مشورت تیم ماسون حذف می‌شوند."""
    return is_mason_scenario(game) and game.mason_team_consultation_retired


def mason_team_consult_should_prompt(game: Game) -> bool:
    """پنل مشورت تیم ماسون قبل از شب — فقط اگر هنوز بازنشسته نشده باشد."""
    return (
        is_mason_scenario(game)
        and no_host_bot_assistant_flow_enabled(game)
        and mason_team_consult_required(game)
        and not mason_team_consultation_prompts_suppressed(game)
    )


def maybe_retire_mason_team_consultation_on_vote_start(game: Game) -> None:
    """اولین شروع رأی‌گیری پس از روز کامل بعد از فروپاشی — بازنشستن مشورت."""
    if not is_mason_scenario(game):
        return
    if game.mason_team_consultation_retired:
        return
    if game.mason_collapse_night_number is None:
        return
    if game.bazpors_narrator_host_day > game.mason_collapse_night_number:
        game.mason_team_consultation_retired = True


def build_mason_mafia_consult_html() -> str:
    return "مشورت قبل از شب تیم مافیا انجام شود."


def build_mason_mafia_consult_confirm_html(game: Game) -> str:
    if mason_team_consult_required(game):
        next_step = "پس از تأیید، پنل مشورت تیم ماسون برای کمک‌کننده ارسال می‌شود."
    else:
        next_step = "پس از تأیید، پنل شروع شب برای کمک‌کننده ارسال می‌شود."
    return (
        "⚠️ <b>تأیید پایان مشورت مافیا</b>\n\n"
        f"{next_step}"
    )


def build_mason_team_consult_html() -> str:
    return "مشورت قبل از شب تیم ماسون انجام شود."


def build_mason_team_consult_confirm_html() -> str:
    return (
        "⚠️ <b>تأیید پایان مشورت تیم ماسون</b>\n\n"
        "پس از تأیید، پنل شروع شب برای کمک‌کننده ارسال می‌شود."
    )


def build_mason_midday_step_html() -> str:
    return "مرحله خواب نیمروزی برای معرفی تیم ماسون را برگزار کن."


def build_mason_midday_step_confirm_html() -> str:
    return (
        "⚠️ <b>تأیید خواب نیمروزی</b>\n\n"
        "پس از تأیید، پنل اخراج انضباطی برای کمک‌کننده ارسال می‌شود."
    )


def _team_consult_start_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ انجام شد",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="go", kind="team_consult"
                    ).pack(),
                )
            ]
        ]
    )


def _team_consult_confirm_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="ok", kind="team_consult"
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ بازگشت",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="back", kind="team_consult"
                    ).pack(),
                )
            ],
        ]
    )


def _consult_start_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ انجام شد",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="go", kind="consult"
                    ).pack(),
                )
            ]
        ]
    )


def _consult_confirm_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="ok", kind="consult"
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ بازگشت",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="back", kind="consult"
                    ).pack(),
                )
            ],
        ]
    )


def _midday_start_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ برگزار شد",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="go", kind="midday"
                    ).pack(),
                )
            ]
        ]
    )


def _midday_confirm_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="ok", kind="midday"
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ بازگشت",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="back", kind="midday"
                    ).pack(),
                )
            ],
        ]
    )


def _team_consult_ui_key(game: Game, assistant_uid: int) -> str:
    nc = game.bazpors_narrator_night_count
    return mirror_ui_claim_key(
        game.room_code, f"mason_team_consult_{nc}", assistant_uid
    )


def _consult_ui_key(game: Game, assistant_uid: int) -> str:
    nc = game.bazpors_narrator_night_count
    return mirror_ui_claim_key(
        game.room_code, f"mason_mafia_consult_{nc}", assistant_uid
    )


def _midday_ui_key(game: Game, assistant_uid: int) -> str:
    nc = game.bazpors_narrator_night_count
    return mirror_ui_claim_key(game.room_code, f"mason_midday_{nc}", assistant_uid)


async def send_mason_team_consult_prompt(bot: Bot, game: Game) -> bool:
    if not mason_team_consult_should_prompt(game):
        return False
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None or game.mason_team_consult_prompt_sent:
        return False
    game.mason_team_consult_prompt_sent = True
    game.mason_team_consult_done = False
    text = build_mason_team_consult_html()
    kb = _team_consult_start_keyboard(game)
    ui_key = _team_consult_ui_key(game, assistant_uid)
    await register_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        ui_key,
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=True,
        parse_mode="HTML",
    )
    return True


async def send_mason_mafia_consult_prompt(bot: Bot, game: Game) -> None:
    if not is_mason_scenario(game) or not no_host_bot_assistant_flow_enabled(game):
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None or game.mason_mafia_consult_prompt_sent:
        return
    game.mason_mafia_consult_prompt_sent = True
    game.mason_mafia_consult_done = False
    text = build_mason_mafia_consult_html()
    kb = _consult_start_keyboard(game)
    ui_key = _consult_ui_key(game, assistant_uid)
    await register_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        ui_key,
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=True,
        parse_mode="HTML",
    )


async def send_mason_midday_step_prompt(bot: Bot, game: Game) -> None:
    if (
        not is_mason_scenario(game)
        or not no_host_bot_assistant_flow_enabled(game)
        or mason_team_consultation_prompts_suppressed(game)
    ):
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None or game.mason_midday_step_prompt_sent:
        return
    game.mason_midday_step_prompt_sent = True
    game.mason_midday_step_done = False
    text = build_mason_midday_step_html()
    kb = _midday_start_keyboard(game)
    ui_key = _midday_ui_key(game, assistant_uid)
    await register_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        ui_key,
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=True,
        parse_mode="HTML",
    )


def _vote_start_keyboard(game: Game, assistant_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🗳 شروع رأی‌گیری",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="go", kind="vote"
                    ).pack(),
                )
            ]
        ]
    )


def _vote_confirm_keyboard(game: Game, assistant_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="ok", kind="vote"
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ بازگشت",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="back", kind="vote"
                    ).pack(),
                )
            ],
        ]
    )


def _night_start_keyboard(game: Game, assistant_uid: int) -> InlineKeyboardMarkup:
    night_w = no_host_night_ordinal_fa(game.bazpors_narrator_night_count)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🌙 شروع شب {night_w}",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="go", kind="night"
                    ).pack(),
                )
            ]
        ]
    )


def _night_confirm_keyboard(game: Game, assistant_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="ok", kind="night"
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ بازگشت",
                    callback_data=MasonHelperCb(
                        code=game.room_code, act="back", kind="night"
                    ).pack(),
                )
            ],
        ]
    )


def _vote_ui_key(game: Game, assistant_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "mason_vote_start", assistant_uid)


def _night_ui_key(game: Game, assistant_uid: int) -> str:
    nc = game.bazpors_narrator_night_count
    return mirror_ui_claim_key(game.room_code, f"mason_night_start_{nc}", assistant_uid)


async def send_mason_vote_start_prompt(bot: Bot, game: Game) -> None:
    if not is_mason_scenario(game) or not no_host_bot_assistant_flow_enabled(game):
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None or game.mason_vote_start_prompt_sent:
        return
    game.mason_vote_start_prompt_sent = True
    text = build_mason_vote_start_html()
    kb = _vote_start_keyboard(game, assistant_uid)
    ui_key = _vote_ui_key(game, assistant_uid)
    await register_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        ui_key,
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=True,
        parse_mode="HTML",
    )


async def send_mason_night_start_prompt(bot: Bot, game: Game) -> None:
    if not is_mason_scenario(game) or not no_host_bot_assistant_flow_enabled(game):
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return
    nc = game.bazpors_narrator_night_count
    if game.mason_night_start_pending_night == nc and game.mason_night_start_prompt_sent:
        return
    game.mason_night_start_pending_night = nc
    game.mason_night_start_prompt_sent = True
    text = build_mason_night_start_html(game)
    kb = _night_start_keyboard(game, assistant_uid)
    ui_key = _night_ui_key(game, assistant_uid)
    await register_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        ui_key,
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=True,
        parse_mode="HTML",
    )


async def _refresh_helper_panel(
    bot: Bot,
    game: Game,
    assistant_uid: int,
    *,
    kind: str,
    phase: str,
    callback_message,
) -> None:
    if kind == "vote":
        ui_key = _vote_ui_key(game, assistant_uid)
        if phase == "confirm":
            text = build_mason_vote_start_confirm_html()
            kb = _vote_confirm_keyboard(game, assistant_uid)
        else:
            text = build_mason_vote_start_html()
            kb = _vote_start_keyboard(game, assistant_uid)
    elif kind == "consult":
        ui_key = _consult_ui_key(game, assistant_uid)
        if phase == "confirm":
            text = build_mason_mafia_consult_confirm_html(game)
            kb = _consult_confirm_keyboard(game)
        else:
            text = build_mason_mafia_consult_html()
            kb = _consult_start_keyboard(game)
    elif kind == "team_consult":
        ui_key = _team_consult_ui_key(game, assistant_uid)
        if phase == "confirm":
            text = build_mason_team_consult_confirm_html()
            kb = _team_consult_confirm_keyboard(game)
        else:
            text = build_mason_team_consult_html()
            kb = _team_consult_start_keyboard(game)
    elif kind == "midday":
        ui_key = _midday_ui_key(game, assistant_uid)
        if phase == "confirm":
            text = build_mason_midday_step_confirm_html()
            kb = _midday_confirm_keyboard(game)
        else:
            text = build_mason_midday_step_html()
            kb = _midday_start_keyboard(game)
    else:
        ui_key = _night_ui_key(game, assistant_uid)
        if phase == "confirm":
            text = build_mason_night_start_confirm_html(game)
            kb = _night_confirm_keyboard(game, assistant_uid)
        else:
            text = build_mason_night_start_html(game)
            kb = _night_start_keyboard(game, assistant_uid)
    entry = game.mirror_prompt_messages.get(ui_key) or {}
    if entry.get("player") or entry.get("observer"):
        await update_mirror_prompt_pair(
            bot, game, ui_key, text, kb, assistant_uid=assistant_uid, parse_mode="HTML"
        )
    else:
        try:
            await callback_message.edit_text(text, parse_mode="HTML", reply_markup=kb)
        except Exception:
            pass


async def handle_mason_helper_action(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    assistant_uid: int,
    actor_uid: int,
    act: str,
    kind: str,
) -> None:
    if callback.message is None:
        return
    if kind == "force_night":
        from bot.mason_force_finish_night import handle_mason_force_finish_callback

        await handle_mason_force_finish_callback(
            callback,
            bot,
            game,
            gm,
            assistant_uid=assistant_uid,
            act=act,
        )
        return
    if kind == "vote":
        if game.no_host_day1_vote_prompt_sent or game.no_host_day1_vote_resolved:
            await callback.answer("رأی‌گیری قبلاً شروع شده است.", show_alert=True)
            return
        if act == "go":
            await callback.answer()
            await _refresh_helper_panel(
                bot,
                game,
                assistant_uid,
                kind="vote",
                phase="confirm",
                callback_message=callback.message,
            )
            return
        if act == "back":
            await callback.answer()
            await _refresh_helper_panel(
                bot,
                game,
                assistant_uid,
                kind="vote",
                phase="start",
                callback_message=callback.message,
            )
            return
        if act != "ok":
            await callback.answer("نامعتبر.", show_alert=True)
            return
        ui_key = _vote_ui_key(game, assistant_uid)
        await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
        maybe_retire_mason_team_consultation_on_vote_start(game)
        await callback.answer("رأی‌گیری آغاز شد.")
        try:
            base = callback.message.html_text or callback.message.text or ""
            await callback.message.edit_text(
                base + "\n\n<i>✅ رأی‌گیری آغاز شد.</i>",
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass
        from bot.mason_day_ability import dismiss_mason_day_ability_panels
        from bot.no_host_phase import no_host_run_day1_end_vote_flow

        game.mason_intro_day_ability_open = False
        await dismiss_mason_day_ability_panels(bot, game)
        await no_host_run_day1_end_vote_flow(bot, game)
        return

    if kind == "consult":
        if game.mason_mafia_consult_done:
            await callback.answer("مشورت قبلاً ثبت شده است.", show_alert=True)
            return
        if act == "go":
            await callback.answer()
            await _refresh_helper_panel(
                bot,
                game,
                assistant_uid,
                kind="consult",
                phase="confirm",
                callback_message=callback.message,
            )
            return
        if act == "back":
            await callback.answer()
            await _refresh_helper_panel(
                bot,
                game,
                assistant_uid,
                kind="consult",
                phase="start",
                callback_message=callback.message,
            )
            return
        if act != "ok":
            await callback.answer("نامعتبر.", show_alert=True)
            return
        ui_key = _consult_ui_key(game, assistant_uid)
        await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
        game.mason_mafia_consult_done = True
        await callback.answer("ثبت شد.")
        try:
            base = callback.message.html_text or callback.message.text or ""
            await callback.message.edit_text(
                base + "\n\n<i>✅ مشورت مافیا ثبت شد.</i>",
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass
        await _advance_after_mafia_consult_confirmed(bot, game)
        return

    if kind == "team_consult":
        if mason_team_consultation_prompts_suppressed(game):
            await callback.answer("این مرحله برای این بازی غیرفعال است.", show_alert=True)
            return
        if not mason_team_consult_required(game):
            await callback.answer("این مرحله برای این شب فعال نیست.", show_alert=True)
            return
        if game.mason_team_consult_done:
            await callback.answer("مشورت قبلاً ثبت شده است.", show_alert=True)
            return
        if act == "go":
            await callback.answer()
            await _refresh_helper_panel(
                bot,
                game,
                assistant_uid,
                kind="team_consult",
                phase="confirm",
                callback_message=callback.message,
            )
            return
        if act == "back":
            await callback.answer()
            await _refresh_helper_panel(
                bot,
                game,
                assistant_uid,
                kind="team_consult",
                phase="start",
                callback_message=callback.message,
            )
            return
        if act != "ok":
            await callback.answer("نامعتبر.", show_alert=True)
            return
        ui_key = _team_consult_ui_key(game, assistant_uid)
        await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
        game.mason_team_consult_done = True
        await callback.answer("ثبت شد.")
        try:
            base = callback.message.html_text or callback.message.text or ""
            await callback.message.edit_text(
                base + "\n\n<i>✅ مشورت تیم ماسون ثبت شد.</i>",
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass
        game.mason_night_start_prompt_sent = False
        await send_mason_night_start_prompt(bot, game)
        return

    if kind == "midday":
        if mason_team_consultation_prompts_suppressed(game):
            await callback.answer("این مرحله برای این بازی غیرفعال است.", show_alert=True)
            return
        if game.mason_midday_step_done:
            await callback.answer("این مرحله قبلاً ثبت شده است.", show_alert=True)
            return
        if act == "go":
            await callback.answer()
            await _refresh_helper_panel(
                bot,
                game,
                assistant_uid,
                kind="midday",
                phase="confirm",
                callback_message=callback.message,
            )
            return
        if act == "back":
            await callback.answer()
            await _refresh_helper_panel(
                bot,
                game,
                assistant_uid,
                kind="midday",
                phase="start",
                callback_message=callback.message,
            )
            return
        if act != "ok":
            await callback.answer("نامعتبر.", show_alert=True)
            return
        ui_key = _midday_ui_key(game, assistant_uid)
        await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
        game.mason_midday_step_done = True
        await callback.answer("ثبت شد.")
        try:
            base = callback.message.html_text or callback.message.text or ""
            await callback.message.edit_text(
                base + "\n\n<i>✅ خواب نیمروزی ثبت شد.</i>",
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception:
            pass
        from bot.mason_game_flow import mason_after_midday_step_confirmed

        await mason_after_midday_step_confirmed(bot, game, gm)
        return

    # night start
    nc = game.bazpors_narrator_night_count
    if game.mason_night_entry_dispatched_night == nc:
        await callback.answer("شب قبلاً شروع شده است.", show_alert=True)
        return
    if act == "go":
        await callback.answer()
        await _refresh_helper_panel(
            bot,
            game,
            assistant_uid,
            kind="night",
            phase="confirm",
            callback_message=callback.message,
        )
        return
    if act == "back":
        await callback.answer()
        await _refresh_helper_panel(
            bot,
            game,
            assistant_uid,
            kind="night",
            phase="start",
            callback_message=callback.message,
        )
        return
    if act != "ok":
        await callback.answer("نامعتبر.", show_alert=True)
        return
    ui_key = _night_ui_key(game, assistant_uid)
    await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
    await callback.answer("شب آغاز شد.")
    try:
        base = callback.message.html_text or callback.message.text or ""
        await callback.message.edit_text(
            base + "\n\n<i>✅ شب آغاز شد.</i>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        pass
    from bot.mason_night_entry import dispatch_mason_night_entry_panels

    await dispatch_mason_night_entry_panels(bot, game, gm)


async def _advance_after_mafia_consult_confirmed(bot: Bot, game: Game) -> None:
    """پس از تأیید مشورت مافیا — مشورت تیم ماسون یا شروع شب."""
    game.mason_night_start_prompt_sent = False
    if mason_team_consult_should_prompt(game):
        if await send_mason_team_consult_prompt(bot, game):
            return
    await send_mason_night_start_prompt(bot, game)


async def mason_on_no_host_entered_night(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پس از پایان رأی روز — ابتدا مشورت مافیا، سپس شروع شب."""
    game.mason_night_start_prompt_sent = False
    game.mason_mafia_consult_prompt_sent = False
    game.mason_team_consult_prompt_sent = False
    game.mason_team_consult_done = False
    await send_mason_mafia_consult_prompt(bot, game)
