"""Handler router: lobby."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from bot.app_state import manager
from bot.app_state import waiting_join_user_ids
from bot.game import (
    BAZPORS_PLAYER_COUNTS,
    BAZPORS_SALAMAT_TEST_PLAYER_COUNTS,
    LOBBY_LEAVE_BLOCKED_AFTER_ROLES_MSG,
    LOBBY_LEAVE_BROADCAST_MSG,
    LOBBY_LEAVE_SUCCESS_MSG,
    MASOON2_PLAYER_COUNTS,
    MASOON_PLAYER_COUNTS,
    MOZAKERE_PLAYER_COUNTS,
    NAMAYANDEH_PLAYER_COUNTS,
    TAKAVAR_PLAYER_COUNTS,
    is_synthetic_player_uid,
    role_roster_banner_text,
)
from bot.main import (
    CREATE_PLAYER_COUNTS,
    CreatePickHostMode,
    CreatePickPlayers,
    CreatePickScenario,
    JOIN_CODE_TEXT_RE,
    JoinConfirmCb,
    MOZAKERE_HOST_MODE_STUB_HTML,
    NoHostBotAssistantPick,
    NoHostObserverPrompt,
    SemiAutoDevLobby,
    _do_join,
    _execute_confirmed_join,
    _join_cancel_input,
    _no_host_bot_assistant_candidate_uids,
    _require_private,
    bazpors_host_mode_keyboard,
    bazpors_host_mode_prompt_html,
    bazpors_lobby_dev_fill_enabled,
    build_host_mode_created_room_html,
    broadcast_game,
    build_join_preview_html,
    deal_roles_full_pipeline,
    finalize_no_host_bot_assistant,
    format_roster_plain_to_html,
    is_no_host_player_room,
    no_host_bot_assistant_flow_enabled,
    pick_random_no_host_bot_assistant,
    player_count_keyboard,
    refresh_lobby_status_messages,
    register_observer_via_command,
    scenario_menu_keyboard,
    semi_auto_lobby_dev_keyboard,
    send_host_lobby_full_prompt,
    send_no_host_bot_assistant_prompt,
    _OBSERVER_CMD_RE,
)
from bot.room_mode import (
    is_no_host_player_room,
    is_russian_mafia_host_helper_room,
    lobby_dev_fill_enabled,
)
from bot.main import JoinFlowResult
from bot.models import Game, Phase, Player, Role
from bot.post_game_flow import resolve_game_context
from bot.text_fa import fa_digits as _fa_digits
from bot.tg_send import safe_callback_answer
import html


logger = logging.getLogger(__name__)
router = Router(name="lobby")

_HOST_MODE_PLAYER_COUNTS: dict[str, frozenset[int]] = {
    "bazpors": BAZPORS_PLAYER_COUNTS,
    "mozakere": MOZAKERE_PLAYER_COUNTS,
    "masoon": MASOON_PLAYER_COUNTS,
}
_HOST_MODE_INVALID_COUNT_ALERT: dict[str, str] = {
    "bazpors": "بازپرس: ۱۰، ۱۱، ۱۲ یا ۱۳ بازیکن.",
    "mozakere": "مذاکره: ۱۰، ۱۱، ۱۲، ۱۳ یا ۱۵ بازیکن.",
    "masoon": "ماسون: ۱۲ تا ۱۸ بازیکن.",
}


def register_lobby_handlers(dp) -> None:
    dp.include_router(router)


@router.callback_query(JoinConfirmCb.filter())
async def cb_join_confirm(
    callback: CallbackQuery,
    callback_data: JoinConfirmCb,
    bot: Bot,
) -> None:
    if not callback.from_user or callback.message is None:
        return
    if callback.from_user.id != callback_data.uid:
        await safe_callback_answer(
            callback, "⛔ این درخواست متعلق به شما نیست.", show_alert=True
        )
        return
    key = manager.normalize_join_code(callback_data.code)
    if key is None or key != callback_data.code:
        await safe_callback_answer(callback, "کد اتاق نامعتبر است.", show_alert=True)
        return
    if callback_data.act == "no":
        await safe_callback_answer(callback, "ثبت شد.")
        try:
            await callback.message.edit_text(
                "❌ شما عضو این اتاق نشدید.",
                reply_markup=None,
            )
        except TelegramBadRequest:
            pass
        return
    if callback_data.act != "yes":
        await safe_callback_answer(callback, "نامعتبر.", show_alert=True)
        return
    err = await _execute_confirmed_join(
        bot,
        callback.from_user.id,
        callback.from_user.full_name or "",
        callback.from_user.username,
        key,
    )
    if err:
        await safe_callback_answer(callback, err, show_alert=True)
        return
    game = manager.get_game(key)
    await safe_callback_answer(callback, "✅ به اتاق پیوستید.")
    try:
        if game:
            await callback.message.edit_text(
                build_join_preview_html(game)
                + "\n\n✅ شما با موفقیت به این اتاق پیوستید.",
                parse_mode="HTML",
                reply_markup=None,
            )
        else:
            await callback.message.edit_text(
                "✅ شما با موفقیت به این اتاق پیوستید.",
                reply_markup=None,
            )
    except TelegramBadRequest:
        pass


@router.message(Command("create"))
async def create_cmd(msg: Message, bot: Bot) -> None:
    if not _require_private(msg):
        await msg.answer("فقط در چت خصوصی با ربات.")
        return

    if manager.get_room_for_user(msg.from_user.id) or manager.get_room_for_host(
        msg.from_user.id
    ):
        await msg.answer(
            "شما همین الان در یک اتاق هستید (بازیکن یا گرداننده). اول /leave بزنید."
        )
        return

    await msg.answer(
        "🎭 یک سناریو انتخاب کنید:",
        reply_markup=scenario_menu_keyboard(),
    )


@router.callback_query(CreatePickScenario.filter())
async def cb_create_scenario(
    callback: CallbackQuery,
    callback_data: CreatePickScenario,
) -> None:
    if not callback.message or callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer("فقط در چت خصوصی با ربات.", show_alert=True)
        return
    if callback_data.slug not in manager.scenarios:
        await callback.answer("سناریوی نامعتبر.", show_alert=True)
        return
    await callback.answer()
    label = manager.scenario_display_name(callback_data.slug)
    await callback.message.edit_text(
        f"🎭 سناریو: {label}\n\n👥 تعداد بازیکنان را انتخاب کنید:",
        reply_markup=player_count_keyboard(callback_data.slug),
    )


@router.callback_query(CreatePickPlayers.filter())
async def cb_create_players(
    callback: CallbackQuery,
    callback_data: CreatePickPlayers,
    bot: Bot,
) -> None:
    if not callback.message or callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer("فقط در چت خصوصی با ربات.", show_alert=True)
        return
    uid = callback.from_user.id
    if manager.get_room_for_user(uid) or manager.get_room_for_host(uid):
        await callback.answer(
            "شما همین الان در یک اتاق هستید. اول /leave بزنید.",
            show_alert=True,
        )
        return
    if callback_data.slug not in manager.scenarios:
        await callback.answer("انتخاب نامعتبر است.", show_alert=True)
        return
    if callback_data.slug == "russian_mafia":
        from bot.russian_mafia import PLAYER_COUNTS, russian_host_mode_keyboard

        if callback_data.count not in PLAYER_COUNTS:
            await callback.answer("مافیای روسی: فقط ۸ یا ۹ بازیکن.", show_alert=True)
            return
        await callback.answer()
        if callback.message:
            label = manager.scenario_display_name(callback_data.slug)
            await callback.message.edit_text(
                "🎭 سناریو: " + label + "\n\nنوع گردانندگی را انتخاب کنید:",
                reply_markup=russian_host_mode_keyboard(callback_data.count),
            )
        return
    if callback_data.slug in _HOST_MODE_PLAYER_COUNTS:
        allowed = _HOST_MODE_PLAYER_COUNTS[callback_data.slug]
        if callback_data.count not in allowed:
            await callback.answer(
                _HOST_MODE_INVALID_COUNT_ALERT[callback_data.slug],
                show_alert=True,
            )
            return
        await callback.answer()
        if not callback.message:
            return
        label = manager.scenario_display_name(callback_data.slug)
        await callback.message.edit_text(
            bazpors_host_mode_prompt_html(label, callback_data.count),
            parse_mode="HTML",
            reply_markup=bazpors_host_mode_keyboard(
                callback_data.slug, callback_data.count
            ),
        )
        return
    elif callback_data.slug == "bazpors_salamat_test":
        if callback_data.count not in BAZPORS_SALAMAT_TEST_PLAYER_COUNTS:
            await callback.answer(
                "تست شبکه سلامت: فقط ۱۲ بازیکن.",
                show_alert=True,
            )
            return
    elif callback_data.slug == "takavar":
        if callback_data.count not in TAKAVAR_PLAYER_COUNTS:
            await callback.answer(
                "تکاور: ۱۰، ۱۱، ۱۲، ۱۳ یا ۱۵ بازیکن.",
                show_alert=True,
            )
            return
    elif callback_data.slug == "masoon2":
        if callback_data.count not in MASOON2_PLAYER_COUNTS:
            await callback.answer(
                "ماسون تست: فقط ۲ بازیکن.",
                show_alert=True,
            )
            return
    elif callback_data.slug == "namayande":
        if callback_data.count not in NAMAYANDEH_PLAYER_COUNTS:
            await callback.answer(
                "نماینده: ۱۰، ۱۱، ۱۲، ۱۳، ۱۴ یا ۱۶ بازیکن.",
                show_alert=True,
            )
            return
    elif callback_data.count not in CREATE_PLAYER_COUNTS:
        await callback.answer("انتخاب نامعتبر است.", show_alert=True)
        return

    game = manager.create_game(
        host_id=uid,
        scenario_name=callback_data.slug,
        max_players=callback_data.count,
        host_full_name=callback.from_user.full_name or "",
        host_username=callback.from_user.username,
    )
    if not game:
        await callback.answer("امکان ساخت اتاق نیست.", show_alert=True)
        return

    if game.scenario_name == "bazpors_salamat_test":
        manager.setup_bazpors_salamat_test_room(game)
        await callback.answer()
        if not callback.message:
            return
        err = await deal_roles_full_pipeline(bot, game)
        if err:
            await callback.message.edit_text(
                f"⚠️ خطا در راه‌اندازی اتاق تست:\n{html.escape(err)}",
                parse_mode="HTML",
            )
            return
        label = manager.scenario_display_name(game.scenario_name)
        roster_plain = role_roster_banner_text(
            game.scenario_name, game.max_players, manager
        )
        roster_html = format_roster_plain_to_html(roster_plain)
        host_label = manager.get_user_display_name(
            uid,
            (callback.from_user.full_name or "").strip() or "—",
        )
        text = (
            f"🧪 <b>اتاق تست شبکه سلامت آماده است</b>\n\n"
            f"🔑 کد اتاق: <code>{html.escape(game.room_code)}</code>\n"
            f"🎭 سناریو: {html.escape(label)}\n"
            f"🎙 گرداننده: {html.escape(host_label)}\n\n"
            f"{roster_html}\n\n"
            f"{_fa_digits(game.max_players)} صندلی با نام ساختگی پر شد و نقش‌ها پخش شد؛ "
            "ربات به صندلی‌ها پیام خصوصی نمی‌فرستد.\n"
            "برای امتحان <b>پنل نیمه‌خودکار گرداننده</b>، پیام بعدی ربات را ببینید.\n\n"
            "⛔ پایان اتاق: مانند همیشه <code>/endgame</code>."
        )
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        return

    await callback.answer()
    if not callback.message:
        return

    bot_username = (await bot.get_me()).username or "YourBot"
    invite_link = f"https://t.me/{bot_username}?start={game.room_code}"
    label = manager.scenario_display_name(game.scenario_name)
    roster_plain = role_roster_banner_text(game.scenario_name, game.max_players, manager)
    roster_html = format_roster_plain_to_html(roster_plain)
    host_label = manager.get_user_display_name(
        uid,
        (callback.from_user.full_name or "").strip() or "—",
    )
    rle = "\u202B"  # RTL embedding
    pdf = "\u202C"
    lri = "\u2066"  # LTR isolate
    pdi = "\u2069"

    def rtl_line(s: str) -> str:
        return f"{rle}{s}{pdf}"

    text = (
        f"{rtl_line('✅ <b>اتاق ساخته شد</b>')}\n\n"
        f"{rtl_line(f'🔑 کد ورود: <b>{html.escape(game.room_code)}</b>')}\n"
        f"{rtl_line(f'🎭 سناریو: {html.escape(label)}')}\n"
        f"{rtl_line(f'👥 ظرفیت: {game.max_players} نفر')}\n"
        f"{rtl_line(f'🎙 گرداننده: {html.escape(host_label)}')}\n\n"
        f"{roster_html}\n\n"
        f"{rtl_line('📥 بازیکنان با کد بالا یا لینک زیر وارد شوند:')}\n"
        f'{rtl_line(f"🔗 <a href=\"{html.escape(invite_link)}\">ورود به اتاق (یک ضربه)</a>")}\n'
        f"{rtl_line(f'همچنین می‌توانند بفرستند: {lri}/join {html.escape(game.room_code)}{pdi}')}"
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )


@router.callback_query(CreatePickHostMode.filter())
async def cb_create_host_mode(
    callback: CallbackQuery,
    callback_data: CreatePickHostMode,
    bot: Bot,
) -> None:
    if not callback.message or callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer("فقط در چت خصوصی با ربات.", show_alert=True)
        return
    if callback_data.slug == "russian_mafia":
        from bot.russian_mafia_flow import accept_russian_host_mode

        await accept_russian_host_mode(callback, bot, callback_data)
        return
    if callback_data.mode not in ("semi_auto", "manual", "no_host"):
        await callback.answer("انتخاب نامعتبر.", show_alert=True)
        return
    uid = callback.from_user.id
    if manager.get_room_for_user(uid) or manager.get_room_for_host(uid):
        await callback.answer(
            "شما همین الان در یک اتاق هستید. اول /leave بزنید.",
            show_alert=True,
        )
        return
    if callback_data.slug == "mozakere":
        if callback_data.count not in MOZAKERE_PLAYER_COUNTS:
            await callback.answer("تعداد بازیکن نامعتبر.", show_alert=True)
            return
        if callback_data.mode != "no_host":
            await callback.answer("ثبت شد.")
            if not callback.message:
                return
            label = manager.scenario_display_name("mozakere")
            n = _fa_digits(callback_data.count)
            await callback.message.edit_text(
                f"🎭 سناریو: <b>{html.escape(label)}</b> · <b>{n}</b> نفر\n\n"
                f"{html.escape(MOZAKERE_HOST_MODE_STUB_HTML)}",
                parse_mode="HTML",
                reply_markup=None,
            )
            return
    elif callback_data.slug == "masoon":
        from bot.mason_create_flow import (
            MASON_HOST_MODE_STUB_HTML,
            build_mason_manual_created_room_html,
            mason_player_count_invalid_alert,
            mason_player_counts,
            present_mason_host_mode_created_room,
        )

        if callback_data.count not in mason_player_counts():
            await callback.answer(mason_player_count_invalid_alert(), show_alert=True)
            return
        if callback_data.mode == "semi_auto":
            await callback.answer("ثبت شد.")
            if not callback.message:
                return
            label = manager.scenario_display_name("masoon")
            n = _fa_digits(callback_data.count)
            await callback.message.edit_text(
                f"🎭 سناریو: <b>{html.escape(label)}</b> · <b>{n}</b> نفر\n\n"
                f"{html.escape(MASON_HOST_MODE_STUB_HTML)}",
                parse_mode="HTML",
                reply_markup=None,
            )
            return
        if callback_data.mode == "manual":
            game = manager.create_game(
                host_id=uid,
                scenario_name="masoon",
                max_players=callback_data.count,
                host_full_name=callback.from_user.full_name or "",
                host_username=callback.from_user.username,
            )
            if not game:
                await callback.answer("امکان ساخت اتاق نیست.", show_alert=True)
                return
            await callback.answer()
            if not callback.message:
                return
            bot_username = (await bot.get_me()).username or "YourBot"
            invite_link = f"https://t.me/{bot_username}?start={game.room_code}"
            label = manager.scenario_display_name(game.scenario_name)
            roster_plain = role_roster_banner_text(
                game.scenario_name, game.max_players, manager
            )
            roster_html = format_roster_plain_to_html(roster_plain)
            host_label = manager.get_user_display_name(
                uid,
                (callback.from_user.full_name or "").strip() or "—",
            )
            text = build_mason_manual_created_room_html(
                game,
                invite_link=invite_link,
                host_label=host_label,
                scenario_label=label,
                roster_html=roster_html,
            )
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                disable_web_page_preview=True,
            )
            return
        if callback_data.mode != "no_host":
            await callback.answer("انتخاب نامعتبر.", show_alert=True)
            return
        game = manager.create_game(
            host_id=uid,
            scenario_name="masoon",
            max_players=callback_data.count,
            host_full_name=callback.from_user.full_name or "",
            host_username=callback.from_user.username,
            bazpors_host_mode="no_host",
        )
        if not game:
            await callback.answer("امکان ساخت اتاق نیست.", show_alert=True)
            return
        await callback.answer()
        creator = Player(
            user_id=uid,
            full_name=(callback.from_user.full_name or "").strip() or "بازیکن",
            username=callback.from_user.username,
        )
        join_err = manager.add_player(game, creator)
        if join_err and join_err != "already_in_room":
            await callback.message.edit_text(
                "اتاق ساخته شد اما ثبت شما به‌عنوان بازیکن ناموفق بود. "
                f"کد: <code>{html.escape(game.room_code)}</code>",
                parse_mode="HTML",
            )
            return
        await present_mason_host_mode_created_room(
            callback,
            bot,
            game,
            mode="no_host",
            host_uid=uid,
            host_full_name=callback.from_user.full_name or "",
            creator_registered=True,
        )
        return
    elif callback_data.slug != "bazpors":
        await callback.answer("فقط برای سناریوی بازپرس.", show_alert=True)
        return
    elif callback_data.count not in BAZPORS_PLAYER_COUNTS:
        await callback.answer("تعداد بازیکن نامعتبر.", show_alert=True)
        return

    game = manager.create_game(
        host_id=uid,
        scenario_name=callback_data.slug,
        max_players=callback_data.count,
        host_full_name=callback.from_user.full_name or "",
        host_username=callback.from_user.username,
        bazpors_host_mode=callback_data.mode,
    )
    if not game:
        await callback.answer("امکان ساخت اتاق نیست.", show_alert=True)
        return

    await callback.answer()
    if not callback.message:
        return
    bot_username = (await bot.get_me()).username or "YourBot"
    invite_link = f"https://t.me/{bot_username}?start={game.room_code}"
    label = manager.scenario_display_name(game.scenario_name)
    roster_plain = role_roster_banner_text(game.scenario_name, game.max_players, manager)
    roster_html = format_roster_plain_to_html(roster_plain)
    host_label = manager.get_user_display_name(
        uid,
        (callback.from_user.full_name or "").strip() or "—",
    )
    creator_registered = False
    if callback_data.mode == "no_host":
        creator = Player(
            user_id=uid,
            full_name=(callback.from_user.full_name or "").strip() or "بازیکن",
            username=callback.from_user.username,
        )
        join_err = manager.add_player(game, creator)
        if join_err and join_err != "already_in_room":
            await callback.message.edit_text(
                "اتاق ساخته شد اما ثبت شما به‌عنوان بازیکن ناموفق بود. "
                f"کد: <code>{html.escape(game.room_code)}</code>",
                parse_mode="HTML",
            )
            return
        creator_registered = True

    text = build_host_mode_created_room_html(
        game,
        mode=callback_data.mode,
        invite_link=invite_link,
        host_label=host_label,
        scenario_label=label,
        roster_html=roster_html,
        creator_registered=creator_registered,
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=(
            semi_auto_lobby_dev_keyboard(game)
            if callback_data.mode in ("semi_auto", "no_host")
            else None
        ),
    )


@router.callback_query(SemiAutoDevLobby.filter())
async def cb_semi_auto_dev_lobby(
    callback: CallbackQuery,
    callback_data: SemiAutoDevLobby,
    bot: Bot,
) -> None:
    if not callback.message or callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer("فقط در چت خصوصی با ربات.", show_alert=True)
        return
    if not callback.from_user:
        return
    game = manager.get_game(callback_data.code)
    if not game or callback.from_user.id != game.host_id:
        await callback.answer("فقط گرداننده همین اتاق.", show_alert=True)
        return
    if not lobby_dev_fill_enabled(game):
        await callback.answer(
            "این دکمه فقط برای بازپرس نیمه‌خودکار یا بدون گرداننده است.",
            show_alert=True,
        )
        return

    if callback_data.act == "wait":
        await callback.answer("منتظر بازیکن‌های واقعی می‌مانید.")
        note = (
            "\n\n<i>⏳ منتظر join بازیکن‌های واقعی — دکمه‌های تست موقت حذف شد.</i>"
        )
        try:
            await callback.message.edit_text(
                (callback.message.html_text or callback.message.text or "") + note,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=None,
            )
        except Exception:
            pass
        return

    if callback_data.act != "fill":
        await callback.answer("دکمه نامعتبر.", show_alert=True)
        return

    if is_no_host_player_room(game):
        err_code = manager.fill_no_host_synthetic_lobby(game)
    elif (
        game.scenario_name == "russian_mafia"
        and game.bazpors_host_mode == "host_helper"
    ):
        err_code = manager.fill_russian_mafia_synthetic_lobby(game)
    else:
        err_code = manager.fill_bazpors_semi_auto_synthetic_lobby(game)
    if err_code == "has_real_players":
        await callback.answer(
            "حداقل یک بازیکن واقعی join کرده؛ پر کردن تصادفی ممکن نیست.",
            show_alert=True,
        )
        return
    if err_code == "creator_not_player":
        await callback.answer(
            "سازندهٔ اتاق در لیست بازیکنان نیست؛ اتاق را دوباره بسازید.",
            show_alert=True,
        )
        return
    if err_code:
        await callback.answer("الان این کار ممکن نیست.", show_alert=True)
        return

    real_n = sum(
        1 for uid in game.players if not is_synthetic_player_uid(uid)
    )
    synth_n = len(game.players) - real_n
    await callback.answer("لابی پر شد.")
    if is_no_host_player_room(game) or (
        game.scenario_name == "russian_mafia"
        and game.bazpors_host_mode == "host_helper"
    ):
        note = (
            f"\n\n<i>🎲 {_fa_digits(real_n)} بازیکن واقعی + "
            f"{_fa_digits(synth_n)} بازیکن تست — "
            f"جمع {_fa_digits(len(game.players))}/{_fa_digits(game.max_players)} نفر.</i>"
        )
    else:
        note = (
            f"\n\n<i>🎲 لابی با {_fa_digits(game.max_players)} بازیکن تست پر شد — "
            "گام بعد را از پیام بعدی بزنید.</i>"
        )
    try:
        await callback.message.edit_text(
            (callback.message.html_text or callback.message.text or "") + note,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=None,
        )
    except Exception:
        pass
    await send_host_lobby_full_prompt(bot, game)


@router.callback_query(NoHostObserverPrompt.filter())
async def cb_no_host_observer_prompt(
    callback: CallbackQuery,
    callback_data: NoHostObserverPrompt,
    bot: Bot,
) -> None:
    if not callback.message or callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer("فقط در چت خصوصی با ربات.", show_alert=True)
        return
    if not callback.from_user:
        return
    game = manager.get_game(callback_data.code)
    if game and game.scenario_name == "russian_mafia" and game.bazpors_host_mode == "host_helper":
        if callback.from_user.id != game.host_id:
            await callback.answer("فقط کمک‌کنندهٔ این اتاق.", show_alert=True)
            return
        if callback_data.act == "skip" and game.observer_user_id is not None:
            await callback.answer("ناظر قبلاً ثبت شده؛ نمی‌توانید لغو کنید.", show_alert=True)
            return
        if callback_data.act == "skip":
            game.observer_prompt_status = "skipped"
            await callback.answer("بدون ناظر ادامه می‌دهید.")
        elif callback_data.act == "code_sent":
            if game.observer_user_id is None:
                game.observer_prompt_status = "code_sent"
            await callback.answer("ثبت شد.")
        else:
            await callback.answer("دکمه نامعتبر.", show_alert=True)
            return
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        from bot.russian_mafia_flow import on_observer_prompt_done

        await on_observer_prompt_done(bot, game)
        return
    if not game or not is_no_host_player_room(game):
        await callback.answer("این دکمه برای این اتاق نیست.", show_alert=True)
        return
    if callback.from_user.id != game.host_id:
        await callback.answer("فقط بازیکن سازندهٔ این اتاق.", show_alert=True)
        return
    if game.host_id not in game.players:
        await callback.answer("سازنده در لیست بازیکنان نیست.", show_alert=True)
        return
    if callback_data.act == "code_sent":
        if game.observer_user_id is None:
            game.observer_prompt_status = "code_sent"
        await callback.answer("ثبت شد.")
        if game.observer_user_id is not None:
            suffix = "\n\n<i>✅ کد برای ناظر ارسال شد — ناظر قبلاً ثبت شده است.</i>"
        else:
            suffix = (
                "\n\n<i>✅ کد برای ناظر ارسال شد — منتظر ثبت با دستور بالا.</i>"
            )
    elif callback_data.act == "skip":
        if game.observer_user_id is not None:
            await callback.answer(
                "ناظر قبلاً ثبت شده؛ نمی‌توانید لغو کنید.",
                show_alert=True,
            )
            return
        game.observer_prompt_status = "skipped"
        await callback.answer("بدون ناظر ادامه می‌دهید.")
        suffix = "\n\n<i>⭕ ثبت ناظر برای این بازی لغو شد.</i>"
    else:
        await callback.answer("دکمه نامعتبر.", show_alert=True)
        return
    try:
        base = callback.message.html_text or callback.message.text or ""
        await callback.message.edit_text(
            base + suffix,
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    await send_no_host_bot_assistant_prompt(bot, game)


@router.callback_query(NoHostBotAssistantPick.filter())
async def cb_no_host_bot_assistant_pick(
    callback: CallbackQuery,
    callback_data: NoHostBotAssistantPick,
    bot: Bot,
) -> None:
    if not callback.message or callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer("فقط در چت خصوصی با ربات.", show_alert=True)
        return
    if not callback.from_user:
        return
    game = manager.get_game(callback_data.code)
    russian_room = bool(game and is_russian_mafia_host_helper_room(game))
    if not game or not (
        no_host_bot_assistant_flow_enabled(game) or russian_room
    ):
        await callback.answer(
            "کمک‌کننده ربات فقط در حالت «گردانندگی بدون گرداننده» فعال است.",
            show_alert=True,
        )
        return
    if callback.from_user.id != game.host_id:
        await callback.answer("فقط بازیکن سازندهٔ این اتاق.", show_alert=True)
        return
    if game.host_id not in game.players:
        await callback.answer("سازنده در لیست بازیکنان نیست.", show_alert=True)
        return
    if game.bot_assistant_user_id is not None:
        await callback.answer("کمک‌کنندهٔ ربات قبلاً انتخاب شده است.", show_alert=True)
        return

    allowed = set(_no_host_bot_assistant_candidate_uids(game))
    random_pick = callback_data.act != "pick"
    if random_pick:
        assistant_uid = pick_random_no_host_bot_assistant(game)
    else:
        assistant_uid = callback_data.tid
        if assistant_uid not in allowed:
            await callback.answer("این بازیکن قابل انتخاب نیست.", show_alert=True)
            return

    if assistant_uid is None:
        await callback.answer(
            "بازیکن واقعی برای انتخاب پیدا نشد.",
            show_alert=True,
        )
        return

    if is_russian_mafia_host_helper_room(game):
        game.bot_assistant_user_id = assistant_uid

    await callback.answer("انتخاب انجام شد.")
    ap = game.players.get(assistant_uid)
    assistant_tag = html.escape(
        manager.format_player_tag(ap) if ap else str(assistant_uid)
    )
    try:
        base = callback.message.html_text or callback.message.text or ""
        await callback.message.edit_text(
            base
            + "\n\n"
            + f"<i>✅ کمک‌کننده ربات: <b>{assistant_tag}</b></i>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    if is_russian_mafia_host_helper_room(game):
        from bot.russian_mafia_flow import finalize_russian_bot_helper

        await finalize_russian_bot_helper(
            bot, game, assistant_uid, random_pick=random_pick
        )
        return
    await finalize_no_host_bot_assistant(
        bot, game, assistant_uid, random_pick=random_pick
    )


@router.message(F.text.regexp(_OBSERVER_CMD_RE))
async def observer_register_cmd(msg: Message, bot: Bot) -> None:
    if not _require_private(msg):
        await msg.answer("فقط در چت خصوصی با ربات.")
        return
    text = (msg.text or "").strip()
    m = _OBSERVER_CMD_RE.match(text)
    if not m:
        return
    await register_observer_via_command(msg, bot, m.group(1))


@router.message(Command("join"))
async def join_cmd(msg: Message, bot: Bot) -> None:
    if not _require_private(msg):
        await msg.answer("فقط در چت خصوصی با ربات.")
        return
    uid = msg.from_user.id
    parts = msg.text.split(maxsplit=1)
    if len(parts) < 2:
        waiting_join_user_ids.add(uid)
        await msg.answer(
            "🔑 کد ورود اتاق (دو رقم، مثلاً ۰۷، 42 یا ۴۲) را بفرستید.\n\n"
            "🚫 لغو انتظار: 0 یا ۰\n"
            "⚡ یک‌خطی: /join 07 یا /join ۰۷"
        )
        return
    code = parts[1].strip()
    if _join_cancel_input(code):
        waiting_join_user_ids.discard(uid)
        await msg.answer("✅ انتظار برای ورود کد لغو شد.")
        return
    if manager.normalize_join_code(code) is None:
        await msg.answer(
            "کد باید یک یا دو رقم باشد (۰۰ تا ۹۹؛ ارقام فارسی هم قبول است). "
            "دوباره امتحان کنید یا /join بزنید."
        )
        return
    waiting_join_user_ids.discard(uid)
    await _do_join(msg, bot, code)


@router.message(
    F.chat.type == ChatType.PRIVATE,
    F.text.regexp(JOIN_CODE_TEXT_RE),
)
async def join_after_prompt(msg: Message, bot: Bot) -> None:
    uid = msg.from_user.id
    if uid not in waiting_join_user_ids:
        return
    code = (msg.text or "").strip()
    if _join_cancel_input(code):
        waiting_join_user_ids.discard(uid)
        await msg.answer("✅ انتظار برای ورود کد لغو شد.")
        return
    result = await _do_join(msg, bot, code)
    if result != JoinFlowResult.RETRY_BAD_CODE:
        waiting_join_user_ids.discard(uid)


@router.message(Command("leave"))
async def leave_cmd(msg: Message, bot: Bot) -> None:
    if not _require_private(msg):
        return
    uid = msg.from_user.id
    cancelled_wait = uid in waiting_join_user_ids
    waiting_join_user_ids.discard(uid)
    if cancelled_wait:
        await msg.answer("حالت انتظار کد ورود لغو شد.")
    room, _, is_host = resolve_game_context(uid)
    if not room:
        if not cancelled_wait:
            await msg.answer("شما در هیچ اتاقی نیستید.")
        return
    game = manager.get_game(room)
    if not game:
        await msg.answer("اتاق پیدا نشد.")
        return
    if is_host:
        manager.host_leave_cancel_game(game)
        await msg.answer("⛔ اتاق لغو شد (گرداننده خارج شد).")
        await broadcast_game(
            bot, game, "⛔ گرداننده اتاق را لغو کرد. بازی تمام شد."
        )
        return
    if game.roles_dealt or game.phase != Phase.LOBBY:
        await msg.answer(LOBBY_LEAVE_BLOCKED_AFTER_ROLES_MSG)
        return
    if msg.from_user.id not in game.players:
        await msg.answer("شما بازیکن این اتاق نیستید.")
        return
    ok = manager.remove_player_from_lobby(game, msg.from_user.id)
    if ok:
        await msg.answer(LOBBY_LEAVE_SUCCESS_MSG)
        game.lobby_status_message_ids.pop(msg.from_user.id, None)
        await refresh_lobby_status_messages(bot, game)
        await broadcast_game(
            bot,
            game,
            LOBBY_LEAVE_BROADCAST_MSG,
            exclude=msg.from_user.id,
        )
    else:
        await msg.answer("در این فاز نمی‌توانید از لابی خارج شوید.")
