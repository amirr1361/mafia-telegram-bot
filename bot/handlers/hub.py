"""Handler router: hub."""

from __future__ import annotations

import html
import logging
import os
import sys
import time
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from bot import db
from bot.app_state import PANIC_PASSWORD_TTL_SEC
from bot.app_state import manager
from bot.app_state import panic_password_pending
from bot.app_state import waiting_join_user_ids
from bot.app_state import waiting_myname_user_ids
from bot.main import (
    AmirHostDoc,
    HostTimerApply,
    HostTimerNavigate,
    HubMenu,
    MedalPick,
    _do_join,
    _myname_waiting_filter,
    _panic_password_wait_filter,
    _panic_trigger_message_filter,
    _persist_host_timer_field,
    _require_private,
    _session_medal_author_id,
    _username_suffix_for_myname_reply,
    build_amir_host_reply_markup,
    build_help_full_text,
    build_host_narrator_panel_html,
    build_host_timer_panel_html,
    dispatch_quick_start_link,
    format_players,
    format_user_scorecard,
    host_timer_picker_keyboard,
    host_timer_root_keyboard,
    hub_root_keyboard,
    prompt_host_next_medal,
    user_is_bazpors_host,
)
from bot.config import get_panic_allowed_user_ids, get_panic_password
from bot.models import Game, Phase, Player, Role
from bot.post_game_flow import resolve_game_context
from bot.text_fa import fa_digits as _fa_digits

logger = logging.getLogger(__name__)
router = Router(name="hub")


def register_hub_handlers(dp) -> None:
    dp.include_router(router)


@router.message(CommandStart(deep_link=True))
async def start_join_deeplink(msg: Message, command: CommandObject, bot: Bot) -> None:
    if not msg.from_user:
        return
    args = (command.args or "").strip()
    if args in QUICK_START_MAP:
        await dispatch_quick_start_link(msg, bot, args)
        return
    if manager.normalize_join_code(args) is None:
        await msg.answer(
            "لینک نامعتبر است. برای ورود به اتاق کد دو رقمی (۰۰–۹۹، "
            "ارقام فارسی هم مجاز) را از گرداننده بگیرید یا از منوی ربات /menu استفاده کنید."
        )
        return
    if msg.from_user:
        waiting_join_user_ids.discard(msg.from_user.id)
    await _do_join(msg, bot, args)


@router.message(Command("start"))
async def start_cmd(msg: Message, bot: Bot) -> None:
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) > 1:
        code = parts[1].strip()
        if code in QUICK_START_MAP:
            await dispatch_quick_start_link(msg, bot, code)
            return
        if manager.normalize_join_code(code) is not None:
            if msg.from_user:
                waiting_join_user_ids.discard(msg.from_user.id)
            await _do_join(msg, bot, code)
            return
    uid = msg.from_user.id if msg.from_user else 0
    show_amir = bool(msg.from_user and user_is_bazpors_host(uid))
    await msg.answer(
        "👋 سلام! همه‌چیز در چت خصوصی با ربات انجام می‌شود.\n\n"
        "🎙 <b>گرداننده:</b> /create — ساخت اتاق\n"
        "🎲 <b>بازیکن:</b> /join — کد دو رقمی اتاق\n"
        "📎 <b>بقیهٔ منو:</b> /menu — بازیکنان، وضعیت، امتیاز، راهنما\n\n"
        "❓ /help — راهنمای کامل متنی",
        parse_mode="HTML",
        reply_markup=hub_root_keyboard(show_amir_mehraban=show_amir),
    )


@router.message(Command("help"))
async def help_cmd(msg: Message) -> None:
    await msg.answer(build_help_full_text())


@router.message(Command("rolehelp"))
async def rolehelp_cmd(msg: Message) -> None:
    if not _require_private(msg) or not msg.from_user:
        await msg.answer("فقط در چت خصوصی با ربات.")
        return
    uid = msg.from_user.id
    room, player, is_host = resolve_game_context(uid)
    if is_host or not room or not player:
        await msg.answer(
            "این دستور فقط برای <b>بازیکن</b> یک اتاق فعال است (نه گرداننده).\n"
            "گرداننده از منو → «امیر مهربان» راهنمای نقش‌ها را می‌بیند.",
            parse_mode="HTML",
        )
        return
    game = manager.get_game(room)
    if not game or game.scenario_name not in ("bazpors", "bazpors_salamat_test"):
        await msg.answer(
            "فقط در سناریوی بازپرس (یا تست شبکه سلامت) و وقتی در اتاق هستید معتبر است."
        )
        return
    if not game.roles_dealt or not player.role:
        await msg.answer("هنوز نقش برای شما پخش نشده است.")
        return
    body = amir_mb.bazpors_rolehelp_html(player.role)
    await msg.answer(body, parse_mode="HTML")


@router.message(Command("menu"))
async def menu_cmd(msg: Message) -> None:
    if not _require_private(msg):
        await msg.answer("فقط در چت خصوصی با ربات.")
        return
    uid = msg.from_user.id
    show_amir = user_is_bazpors_host(uid)
    await msg.answer(
        "📎 <b>منوی بیشتر</b>\n\n"
        "یک گزینه را بزنید یا همان دستور را مستقیم تایپ کنید.",
        parse_mode="HTML",
        reply_markup=hub_root_keyboard(show_amir_mehraban=show_amir),
    )


@router.callback_query(HubMenu.filter())
async def hub_menu_cb(callback: CallbackQuery, callback_data: HubMenu) -> None:
    if not callback.from_user or callback.message is None:
        return
    if callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer("فقط در چت خصوصی.", show_alert=True)
        return
    uid = callback.from_user.id
    act = callback_data.act
    room, _, is_host = resolve_game_context(uid)

    if act == "ply":
        if not room:
            await callback.answer()
            await callback.message.answer("در هیچ اتاقی نیستید. /join")
            return
        await callback.answer()
        await callback.message.answer(format_players(room))
        return

    if act == "sts":
        if not room:
            await callback.answer()
            await callback.message.answer("در هیچ اتاقی نیستید. /join")
            return
        game = manager.get_game(room)
        if not game:
            await callback.answer()
            return
        seat_line = "✅" if game.seats_finalized else "⏳"
        await callback.answer()
        await callback.message.answer(
            f"🎲 اتاق: {game.room_code}\n"
            f"⏳ فاز: {game.phase.value}\n"
            f"🎭 سناریو: {manager.scenario_display_name(game.scenario_name)}\n"
            f"👥 بازیکنان: {len(game.players)}/{game.max_players}\n"
            "✍️ حالت روایت: دستی\n"
            f"🪑 صندلی‌ها ثبت: {seat_line}\n\n"
            + format_players(room)
        )
        return

    if act == "lve":
        await callback.answer()
        await callback.message.answer(
            "🚪 برای ترک لابی یا خروج اضطراری بعد از نقش، دستور /leave را بفرستید."
        )
        return

    if act == "tre":
        await callback.answer()
        await callback.message.answer(
            "🗳 بعد از پخش نقش: /request_end\n"
            "ابتدا خودتان با دکمه تأیید می‌کنید که برای همه پیام رأی برود؛ "
            "بعد همهٔ بازیکنان تا مهلت مشخص تأیید می‌کنند."
        )
        return

    if act == "mnm":
        await callback.answer()
        await callback.message.answer(
            "✏️ نام نمایشی فقط در ربات:\n"
            "مثال: /myname علی رضایی\n"
            "برگشت به نام تلگرام: /myname پیش‌فرض"
        )
        return

    if act == "scr":
        await callback.answer()
        await callback.message.answer(
            format_user_scorecard(uid),
            parse_mode="HTML",
        )
        return

    if act == "nar":
        await callback.answer()
        if is_host and room:
            game_n = manager.get_game(room)
            if (
                game_n
                and game_n.phase == Phase.MANUAL
                and game_n.roles_dealt
            ):
                await callback.message.answer(
                    build_host_narrator_panel_html(
                        post_deal_header=False,
                        after_roles_hint=True,
                        room_code=game_n.room_code,
                        scenario_name=game_n.scenario_name,
                    ),
                    parse_mode="HTML",
                )
            else:
                await callback.message.answer(
                    build_host_narrator_panel_html(),
                    parse_mode="HTML",
                )
        else:
            await callback.message.answer(
                "🎙 گرداننده اتاق را می‌سازد و با دکمه‌های ربات صندلی و نقش را جلو می‌برد.\n"
                "اگر گرداننده هستید: /create و بعد از پر شدن لابی دکمه‌های ربات را ببینید."
            )
        return

    if act == "hlp":
        await callback.answer()
        await callback.message.answer(build_help_full_text())
        return

    if act == "htg":
        await callback.answer()
        uid = callback.from_user.id
        await callback.message.answer(
            build_host_timer_panel_html(uid),
            parse_mode="HTML",
            reply_markup=host_timer_root_keyboard(uid),
        )
        return

    if act == "amr":
        uid = callback.from_user.id
        if not user_is_bazpors_host(uid):
            await callback.answer(
                "فقط گردانندهٔ یک اتاق فعال با سناریوی بازپرس.",
                show_alert=True,
            )
            return
        await callback.answer()
        await callback.message.answer(
            amir_mb.INTRO_FOR_HOST_FA,
            parse_mode="HTML",
            reply_markup=build_amir_host_reply_markup(),
        )
        return

    if act == "jin":
        await callback.answer()
        await callback.message.answer(
            "🎲 برای ورود: /join را بزنید و بعد کد دو رقمی اتاق را بفرستید "
            "(۰۰ تا ۹۹؛ ارقام فارسی مثل ۰۷ هم قبول است)."
        )
        return

    await callback.answer("گزینه نامعتبر.", show_alert=True)


@router.callback_query(HostTimerNavigate.filter())
async def host_timer_nav_cb(
    callback: CallbackQuery, callback_data: HostTimerNavigate
) -> None:
    if not callback.from_user or callback.message is None:
        return
    if callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer("فقط در چت خصوصی.", show_alert=True)
        return
    uid = callback.from_user.id
    where = callback_data.where
    if where == "x":
        await callback.answer()
        try:
            await callback.message.edit_text("باشه.", reply_markup=None)
        except Exception:
            pass
        return
    if where == "root":
        await callback.answer()
        try:
            await callback.message.edit_text(
                build_host_timer_panel_html(uid),
                parse_mode="HTML",
                reply_markup=host_timer_root_keyboard(uid),
            )
        except Exception:
            pass
        return
    if where not in _HOST_TIMER_FIELD_TITLES:
        await callback.answer("نامعتبر.", show_alert=True)
        return
    title = html.escape(_HOST_TIMER_FIELD_TITLES[where])
    await callback.answer()
    try:
        await callback.message.edit_text(
            f"<b>{title}</b>\n\nیک مقدار را بزنید:",
            parse_mode="HTML",
            reply_markup=host_timer_picker_keyboard(where),
        )
    except Exception:
        pass


@router.callback_query(HostTimerApply.filter())
async def host_timer_apply_cb(
    callback: CallbackQuery, callback_data: HostTimerApply
) -> None:
    if not callback.from_user or callback.message is None:
        return
    if callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer("فقط در چت خصوصی.", show_alert=True)
        return
    uid = callback.from_user.id
    field = callback_data.field
    if field not in _HOST_TIMER_FIELD_TITLES:
        await callback.answer("نامعتبر.", show_alert=True)
        return
    _persist_host_timer_field(uid, field, callback_data.value)
    await callback.answer("ثبت شد.")
    try:
        await callback.message.edit_text(
            build_host_timer_panel_html(uid),
            parse_mode="HTML",
            reply_markup=host_timer_root_keyboard(uid),
        )
    except Exception:
        pass


@router.callback_query(AmirHostDoc.filter())
async def amir_host_doc_cb(
    callback: CallbackQuery, callback_data: AmirHostDoc
) -> None:
    if not callback.from_user or callback.message is None:
        return
    if callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer("فقط در چت خصوصی.", show_alert=True)
        return
    uid = callback.from_user.id
    key = callback_data.key
    if key == "close":
        await callback.answer()
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        return
    if not user_is_bazpors_host(uid):
        await callback.answer(
            "فقط گردانندهٔ یک اتاق فعال با سناریوی بازپرس.",
            show_alert=True,
        )
        return
    doc = amir_mb.amir_host_doc_get(key)
    if not doc:
        await callback.answer("نامعتبر.", show_alert=True)
        return
    await callback.answer()
    await callback.message.answer(doc, parse_mode="HTML")


@router.callback_query(MedalPick.filter())
async def medal_pick_cb(callback: CallbackQuery, callback_data: MedalPick, bot: Bot) -> None:
    if not callback.from_user or callback.message is None:
        return
    sid = callback_data.sid
    slot = callback_data.slot
    pid = callback_data.pid
    row = db.get_session(sid)
    if not row:
        await callback.answer("جلسه پیدا نشد.", show_alert=True)
        return
    author_id = _session_medal_author_id(row)
    if callback.from_user.id != author_id:
        await callback.answer(
            "فقط گرداننده، یا اگر بازی با رأی بازیکنان تمام شده همان کسی که برنده را ثبت کرده، "
            "می‌تواند مدال بدهد.",
            show_alert=True,
        )
        return
    if slot not in db.MEDAL_SLOTS:
        await callback.answer("نامعتبر.", show_alert=True)
        return
    need = db.next_medal_slot(sid)
    if need != slot:
        await callback.answer("ترتیب مدال‌ها رعایت نشده. از پیام جدید انتخاب کنید.", show_alert=True)
        return
    allowed = db.session_player_ids(sid)
    if pid not in allowed:
        await callback.answer("این فرد در این دست نبود.", show_alert=True)
        return
    already_medaled = db.session_medal_recipient_ids(sid)
    if pid in already_medaled:
        await callback.answer(
            "این بازیکن قبلاً در این دست مدال گرفته است.",
            show_alert=True,
        )
        return
    if slot == "honor2":
        medals = db.get_session_medals(sid)
        h1 = medals.get("honor1")
        if h1 is not None and h1 == pid:
            await callback.answer(
                "مدال افتخار دوم باید به نفر دیگری داده شود.",
                show_alert=True,
            )
            return
    db.save_session_medal(sid, slot, pid)
    await callback.answer("ثبت شد.")
    try:
        await callback.message.edit_text(
            f"✅ {html.escape(db.MEDAL_LABEL_FA.get(slot, slot))} ثبت شد.",
            reply_markup=None,
        )
    except Exception:
        pass
    await prompt_host_next_medal(bot, sid)


@router.message(Command("players"))
async def players_cmd(msg: Message) -> None:
    if not _require_private(msg):
        return
    room, _, _ = resolve_game_context(msg.from_user.id)
    if not room:
        await msg.answer("شما در بازی نیستید. /join یا /create")
        return
    await msg.answer(format_players(room))


@router.message(Command("narrator"))
async def narrator_cmd(msg: Message) -> None:
    if not _require_private(msg):
        return
    room, _, is_host = resolve_game_context(msg.from_user.id)
    if not room and not is_host:
        await msg.answer(
            "🎙 پنل گرداننده\n\n"
            "🆕 ساخت اتاق: /create\n"
            "بعد از ساخت اتاق، بقیه ابزار گردانندگی همین‌جا نمایش داده می‌شود."
        )
        return
    if not is_host:
        await msg.answer("فقط گرداننده.")
        return
    game = manager.get_game(room)
    if not game:
        return
    if game.phase == Phase.MANUAL and game.roles_dealt:
        await msg.answer(
            build_host_narrator_panel_html(
                post_deal_header=False,
                after_roles_hint=True,
                room_code=game.room_code,
                scenario_name=game.scenario_name,
            ),
            parse_mode="HTML",
        )
        return
    await msg.answer(
        build_host_narrator_panel_html(),
        parse_mode="HTML",
    )


@router.message(Command("weblogin"))
async def weblogin_cmd(msg: Message) -> None:
    await msg.answer("🌐 نسخه فعلی بدون وب است.")


@router.message(Command("myname"))
async def myname_cmd(msg: Message) -> None:
    if not _require_private(msg):
        await msg.answer("فقط در چت خصوصی با ربات.")
        return
    if not msg.from_user:
        return
    parts = (msg.text or "").split(maxsplit=1)
    if len(parts) < 2:
        waiting_myname_user_ids.add(msg.from_user.id)
        await msg.answer(
            "✏️ <b>تغییر نام نمایشی</b>\n"
            "<i>این نام فقط در پیام‌های همین ربات نمایش داده می‌شود.</i>\n\n"
            "لطفاً نام جدید را در یک پیام بفرستید.\n"
            f"(حداکثر {DISPLAY_NAME_MAX_LEN} نویسه)\n\n"
            "🔙 بازگشت به نام تلگرام: بنویسید <code>پیش‌فرض</code>\n"
            "🚫 لغو: 0",
            parse_mode="HTML",
        )
        return
    raw = parts[1]
    try:
        manager.set_user_display_name(msg.from_user.id, raw)
    except ValueError as err:
        await msg.answer(f"⚠️ {err}")
        return
    if msg.from_user.id not in manager.user_display_names:
        await msg.answer("✅ نام نمایشی پاک شد؛ از این به بعد نام تلگرام نمایش داده می‌شود.")
    else:
        saved = manager.user_display_names[msg.from_user.id]
        await msg.answer(
            "✅ نام نمایشی ذخیره شد:\n👤 "
            f"{saved}"
            f"{_username_suffix_for_myname_reply(msg.from_user)}"
        )


def panic_restart_directory() -> Path:
    """ریشهٔ مخزن (حاوی بستهٔ bot)، نه خود پوشهٔ bot."""
    return Path(__file__).resolve().parents[2]


@router.message(_panic_trigger_message_filter)
async def mafia_panic_trigger(msg: Message) -> None:
    assert msg.from_user is not None
    uid = msg.from_user.id
    allowed = get_panic_allowed_user_ids()
    if allowed and uid not in allowed:
        await msg.answer("⛔️ دسترسی ندارید.")
        return
    panic_password_pending[uid] = time.time()
    await msg.answer(
        "🔐 <b>پسورد را بفرستید.</b>\n"
        f"تا <b>{_fa_digits(PANIC_PASSWORD_TTL_SEC)}</b> ثانیه مهلت دارید "
        "(فقط متن پسورد، بدون اسلش).",
        parse_mode="HTML",
    )


@router.message(_panic_password_wait_filter)
async def mafia_panic_password(msg: Message, bot: Bot) -> None:
    assert msg.from_user is not None
    uid = msg.from_user.id
    allowed = get_panic_allowed_user_ids()
    text = (msg.text or "").strip()
    pwd = get_panic_password()
    if text != pwd:
        panic_password_pending.pop(uid, None)
        await msg.answer("پسورد نادرست. درخواست لغو شد.")
        return
    panic_password_pending.pop(uid, None)
    if allowed and uid not in allowed:
        await msg.answer("⛔️ دسترسی ندارید.")
        return
    n = manager.reset_all_games()
    waiting_join_user_ids.clear()
    waiting_myname_user_ids.clear()
    logging.warning(
        "mafia panic reset by uid=%s, rooms_closed=%s; execv restart",
        uid,
        n,
    )
    await msg.answer(
        f"✅ <b>{_fa_digits(n)}</b> اتاق از حافظه بسته شد. "
        "فرایند ربات دوباره اجرا می‌شود…",
        parse_mode="HTML",
    )
    # cwd باید ریشهٔ مخزن باشد. parent.parent این فایل پوشهٔ بستهٔ bot است و
    # `python -m bot.main` از آنجا ModuleNotFoundError می‌دهد. systemd فقط در
    # شروع اولیه WorkingDirectory را اعمال می‌کند؛ execv همان cwd فرایند را نگه می‌دارد.
    repo_root = panic_restart_directory()
    os.chdir(repo_root)
    env = os.environ.copy()
    previous = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        str(repo_root) if not previous else str(repo_root) + os.pathsep + previous
    )
    os.execve(sys.executable, [sys.executable, "-m", "bot.main"], env)


@router.message(_myname_waiting_filter)
async def myname_after_prompt(msg: Message) -> None:
    if not msg.from_user or not msg.text:
        return
    uid = msg.from_user.id
    raw = msg.text.strip()
    if raw == "0":
        waiting_myname_user_ids.discard(uid)
        await msg.answer("✅ تغییر نام لغو شد.")
        return
    try:
        manager.set_user_display_name(uid, raw)
    except ValueError as err:
        await msg.answer(f"⚠️ {err}\n\nدوباره نام را بفرستید یا 0")
        return
    waiting_myname_user_ids.discard(uid)
    if uid not in manager.user_display_names:
        await msg.answer("✅ نام نمایشی پاک شد؛ از این به بعد نام تلگرام نمایش داده می‌شود.")
    else:
        un = _username_suffix_for_myname_reply(msg.from_user)
        await msg.answer(
            "✅ نام نمایشی ذخیره شد:\n👤 "
            f"{manager.user_display_names[uid]}"
            f"{un}"
        )


@router.message(
    F.text == "اتمام شب",
    F.chat.type == ChatType.PRIVATE,
)
async def mason_force_finish_night_message(msg: Message, bot: Bot) -> None:
    if not msg.from_user:
        return
    from bot.mason_force_finish_night import handle_mason_force_finish_text

    await handle_mason_force_finish_text(msg, bot, msg.from_user.id)


@router.message(Command("status"))
async def status_cmd(msg: Message) -> None:
    if not _require_private(msg):
        return
    room, _, _ = resolve_game_context(msg.from_user.id)
    if not room:
        await msg.answer("در بازی نیستید.")
        return
    game = manager.get_game(room)
    if not game:
        return
    seat_line = "✅" if game.seats_finalized else "⏳"
    await msg.answer(
        f"🎲 اتاق: {game.room_code}\n"
        f"⏳ فاز: {game.phase.value}\n"
        f"🎭 سناریو: {manager.scenario_display_name(game.scenario_name)}\n"
        f"👥 بازیکنان: {len(game.players)}/{game.max_players}\n"
        "✍️ حالت روایت: دستی\n"
        f"🪑 صندلی‌ها ثبت: {seat_line}\n\n"
        + format_players(room)
    )
