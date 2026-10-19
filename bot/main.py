from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import random
import re
import sys
import time
from enum import Enum, auto
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.filters import ExceptionTypeFilter
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ErrorEvent,
    Message,
    ReplyKeyboardRemove,
    User,
)

from bot import amir_mehraban as amir_mb
from bot import db
from bot.post_game_rating import (
    register_post_game_rating_handlers,
    send_rating_invites,
)
from bot.config import (
    get_panic_allowed_user_ids,
    get_panic_password,
    get_panic_trigger_phrase,
    get_token,
)
from bot.async_broadcast import gather_bounded
from bot.text_fa import fa_digits as _fa_digits
from bot.app_state import (
    PANIC_PASSWORD_TTL_SEC,
    PENDING_SESSION_RECAP,
    ROLE_DEAL_IN_PROGRESS_MSG,
    _ROLE_DEAL_LOCKS,
    manager,
    panic_password_pending,
    waiting_join_user_ids,
    waiting_myname_user_ids,
)
from bot.post_game_flow import (
    build_post_session_recap_snapshot,
    endgame_winner_keyboard_for,
    finalize_game_winner,
    resolve_game_context,
)
from bot.room_mode import (
    bazpors_lobby_dev_fill_enabled,
    host_receives_moderator_deal_messages,
    is_bazpors_narrator_room,
    is_bazpors_no_host_room,
    is_bazpors_semi_auto_room,
    is_mason_scenario,
    is_mozakere_scenario,
    is_no_host_player_room,
    is_russian_mafia_host_helper_room,
    narrator_assist_after_roles_dealt,
    no_host_bot_assistant_flow_enabled,
    players_receive_post_deal_hub_message,
)
from bot import bazpors_salamat_rules as bzs_rules
from bot.bazpors_narrator import (
    CHAOS_PHASE_LABEL,
    _alive_faction_counts,
    _seat_fa,
    begin_narrator_assist_after_roles_dealt,
    begin_no_host_day1_defense_pick,
    day_vote_defender_uids,
    day_vote_participation_count,
    day_vote_pick_uids,
    eliminate_player_from_game,
    no_host_day1_after_elim_enter_night,
    no_host_day1_defense_no_votes_enter_night,
    no_host_day1_no_exit_enter_night,
    no_host_skip_day1_vote_enter_night,
    push_host_step,
    set_day_vote_defender_uids,
    set_day_vote_pick_uids,
)
from bot.game import (
    BAZPORS_PLAYER_COUNTS,
    BAZPORS_SALAMAT_TEST_PLAYER_COUNTS,
    DISPLAY_NAME_MAX_LEN,
    HOST_TIMER_BROADCAST_CONFIRM_MAX,
    HOST_TIMER_BROADCAST_CONFIRM_MIN,
    HOST_TIMER_LOBBY_MAX,
    HOST_TIMER_LOBBY_MIN,
    HOST_TIMER_PLAYER_END_APPROVAL_MAX,
    HOST_TIMER_PLAYER_END_APPROVAL_MIN,
    HOST_TIMER_POST_DEAL_MAX_HOURS,
    HOST_TIMER_POST_DEAL_MIN_HOURS,
    LOBBY_FILL_DEADLINE_MINUTES,
    LOBBY_FULL_READY_FOR_ROLES_MSG,
    LOBBY_LEAVE_BLOCKED_AFTER_ROLES_MSG,
    LOBBY_LEAVE_BROADCAST_MSG,
    LOBBY_LEAVE_SUCCESS_MSG,
    LOBBY_NOT_FULL_FOR_ROLES_MSG,
    MASOON2_PLAYER_COUNTS,
    MASOON_PLAYER_COUNTS,
    NAMAYANDEH_PLAYER_COUNTS,
    MOZAKERE_PLAYER_COUNTS,
    PLAYER_END_APPROVAL_MINUTES,
    PLAYER_END_BROADCAST_CONFIRM_MINUTES,
    POST_DEAL_TIMEOUT_HOURS,
    TAKAVAR_PLAYER_COUNTS,
    GameManager,
    is_mafia_team,
    is_synthetic_player_uid,
    join_code_to_ascii_digits,
    normalize_host_timer_settings,
    role_label_fa,
    role_roster_banner_text,
    scenario_role_label_fa,
)
from bot.models import Game, Phase, Player, Role
from bot.observer_delivery import (
    PlayerMirrorCb,
    broadcast_to_players,
    game_observer_mirror_active,
    mirror_ui_claim_key,
    mirrored_emergency_leave_keyboard,
    mirrored_endgame_winner_keyboard,
    apply_mirror_claim_winner,
    close_mirror_prompt_keyboards,
    broadcast_to_alive_players,
    deliver_no_host_player_game_copy,
    mirror_per_player_to_observer,
    player_should_receive_game_messages,
    mirrored_day1_vote_choice_keyboard,
    mirrored_intro_night_start_keyboard,
    mirrored_intro_night_confirm_keyboard,
    mirrored_player_end_broadcast_confirm_keyboard,
    mirrored_player_end_keyboard,
    no_host_observer_registered,
    observer_player_copy_prefix,
    flush_elimination_notifications,
    promote_mirror_prompt_to_panel,
    register_mirror_prompt_pair,
    unpack_player_mirror_cb,
    send_to_player,
    send_observer_players_roster,
    try_claim_mirror_ui,
    update_mirror_prompt_pair,
)
from bot.no_host_phase import no_host_run_day1_end_vote_flow
from bot.no_host_night1 import on_no_host_entered_night1
from bot.tg_send import (
    safe_callback_answer,
    safe_message_answer,
    safe_send_message,
    safe_send_message_return,
)

logger = logging.getLogger(__name__)


def _username_suffix_for_myname_reply(user: User) -> str:
    """اگر کاربر @username دارد، در تأیید /myname کنار نام نمایشی نشان داده شود."""
    if user.username:
        return f"\n📎 آیدی تلگرام: @{user.username}"
    return ""


# حداقل طول متن داخل <tg-spoiler> نقش خصوصی تا پهنای نوار مخفی از بیرون حدس‌پذیر نباشد
PRIVATE_ROLE_SPOILER_MIN_CHARS = 15

dp = Dispatcher()
register_post_game_rating_handlers(dp, manager)


@dp.error(ExceptionTypeFilter(TelegramForbiddenError))
async def _handle_telegram_forbidden(event: ErrorEvent) -> bool:
    """کاربر ربات را بلاک کرده — بدون traceback در لاگ."""
    logger.info(
        "TelegramForbiddenError (bot blocked): update_id=%s",
        event.update.update_id if event.update else "?",
    )
    return True


@dp.error(ExceptionTypeFilter(TelegramBadRequest))
async def _handle_telegram_bad_request(event: ErrorEvent) -> bool:
    """برای callbackهای منقضی‌شده (بعد از ری‌استارت/تاخیر)، traceback چاپ نکن."""
    ex = event.exception
    msg = str(ex).lower() if ex is not None else ""
    if "query is too old" in msg or "query id is invalid" in msg:
        logger.info(
            "Ignored stale callback query: update_id=%s",
            event.update.update_id if event.update else "?",
        )
        return True
    return False


def build_help_full_text() -> str:
    return (
        "📖 همه دستورها در چت خصوصی:\n\n"
        f"⏱ اگر تا مهلت لابی (پیش‌فرض ربات: {LOBBY_FILL_DEADLINE_MINUTES} دقیقه؛ از منوی "
        "«⏱ مهلت‌های گرداننده» قابل تغییر برای اتاق‌های خودتان) لابی به حد نصاب نرسد، "
        "اتاق منحل می‌شود و کد آزاد می‌گردد.\n\n"
        "🎙 /create — ساخت اتاق\n"
        "🎲 /join — ورود با کد دو رقمی\n"
        "📎 /menu — بقیهٔ ابزارها (بازیکنان، وضعیت، ⏱ مهلت‌های گرداننده، امتیاز، راهنما)\n"
        "✏️ /myname — نام نمایشی در ربات (مثلاً /myname علی رضایی؛ بازگشت: /myname پیش‌فرض)\n"
        "📖 /rolehelp — توضیح نقش شما در سناریوی بازپرس بعد از پخش نقش (نسخهٔ «امیر مهربان»)\n"
        "🚫 در انتظار /join با 0 یا ۰ (تک نویسه) لغو می‌شود\n"
        "👋 /leave — ترک لابی\n"
        "📋 /players — لیست بازیکنان\n"
        "📊 /status — وضعیت\n\n"
        "▶️ گرداننده — شروع بازی:\n"
        "وقتی لابی پر شد ربات برای شما دکمه می‌فرستد؛ یا دستورها:\n"
        "🔀 /shuffle و ✅ /confirmshuffle — صندلی‌ها\n"
        "🎭 /dealroles — پخش نقش‌های تصادفی\n\n"
        "📝 روایت همیشه دستی است و پیشبرد فاز با ربات انجام نمی‌شود.\n"
        "⛔ /endgame — پایان (فقط گرداننده)\n"
        f"🗳 /request_end — پایان با رأی بازیکنان (ابتدا تأیید خود درخواست‌دهنده، سپس رأی همه تا مهلت اتاق؛ "
        f"پیش‌فرض ربات {PLAYER_END_APPROVAL_MINUTES} دقیقه) "
        "(گرداننده رأی نمی‌دهد)\n"
        f"⏱ بعد از پخش نقش، اگر تا مهلت اتاق (پیش‌فرض ربات {POST_DEAL_TIMEOUT_HOURS} ساعت) بازی رسمی تمام نشود، اتاق خودکار بسته می‌شود.\n"
        "🚪 /leave — در لابی: ترک؛ بعد از نقش: خروج اضطراری با هشدار و تأیید دوباره."
    )


def format_user_scorecard(user_id: int) -> str:
    avg, n = db.narrator_aggregate_for_host(user_id)
    mc = db.medal_counts_for_recipient(user_id)
    given = db.ratings_given_count(user_id)
    lines: list[str] = ["⭐️ <b>امتیاز و مدال‌های شما</b>\n"]
    if n and avg is not None:
        lines.append(
            f"🎙 به‌عنوان گرداننده: میانگین <b>{avg:.2f}</b> از ۵ ستاره "
            f"({n} بازخورد ناشناس در بایگانی)\n"
        )
    else:
        lines.append("🎙 به‌عنوان گرداننده: هنوز بازخورد ستاره‌ای ثبت نشده.\n")
    lines.append(
        "🏅 مدال‌های دریافتی از گرداننده‌ها در بازی‌های تمام‌شده:\n"
        f"🥇 طلا: {_fa_digits(mc['gold'])}  "
        f"🥈 نقره: {_fa_digits(mc['silver'])}  "
        f"🥉 برنز: {_fa_digits(mc['bronze'])}\n"
        f"🏅 افتخار (دو جایزه): {_fa_digits(mc['honor1'] + mc['honor2'])}\n"
    )
    lines.append(
        f"📤 تعداد امتیازهایی که شما به گرداننده‌ها داده‌اید: {_fa_digits(given)}"
    )
    return "".join(lines)

# بعد از /join بدون کد، تا وارد کردن کد دو رقمی (۰۰–۹۹؛ ارقام فارسی/عربی هم)
JOIN_CODE_TEXT_RE = re.compile(
    r"^[\d\u06f0-\u06f9\u0660-\u0669]{1,2}$"
)


def _join_cancel_input(code: str) -> bool:
    """لغو انتظار کد: 0 یا ۰ (تک نویسه)."""
    s = join_code_to_ascii_digits(code)
    return len(s) == 1 and s == "0"

# لینک t.me/bot?start=... — باید با کد اتاق (فقط رقم) تداخل نداشته باشد.
QUICK_START_MAP: dict[str, str] = {
    "q_pl": "players",
    "q_st": "status",
    "q_mn": "menu",
    "q_lv": "leave",
    "q_re": "request_end",
    "q_my": "myname",
    "q_hp": "help",
}


def format_roster_plain_to_html(roster_plain: str) -> str:
    """رول‌کال بدون بلوک کد؛ خط اول عنوان به‌صورت پررنگ."""
    out: list[str] = []
    title_done = False
    for line in roster_plain.split("\n"):
        if not line.strip():
            out.append("")
            continue
        if not title_done:
            out.append(f"<b>{html.escape(line)}</b>")
            title_done = True
        else:
            out.append(html.escape(line))
    return "\n".join(out)


def build_start_action_links_html(bot_username: str) -> str:
    """هایپرلینک‌های t.me که با باز کردن چت، همان /start با payload اجرا می‌شود."""
    base = f"https://t.me/{bot_username}"
    items: list[tuple[str, str]] = [
        ("q_pl", "فهرست بازیکنان"),
        ("q_st", "وضعیت اتاق و فاز"),
        ("q_mn", "منوی بیشتر (دکمه‌ها)"),
        ("q_lv", "ترک لابی یا خروج اضطراری"),
        ("q_re", "پایان دست با رأی بازیکنان"),
        ("q_my", "نام نمایشی در ربات"),
        ("q_hp", "راهنمای کامل"),
    ]
    lines = ["<b>دستورهای سریع (یک ضربه):</b>"]
    for token, label in items:
        url = f"{base}?start={token}"
        lines.append(f"• <a href=\"{html.escape(url)}\">{html.escape(label)}</a>")
    return "\n".join(lines)


async def dispatch_quick_start_link(msg: Message, bot: Bot, token: str) -> None:
    if not msg.from_user:
        return
    kind = QUICK_START_MAP.get(token)
    if not kind:
        return
    if kind == "players":
        await players_cmd(msg)
    elif kind == "status":
        await status_cmd(msg)
    elif kind == "menu":
        await menu_cmd(msg)
    elif kind == "leave":
        await leave_cmd(msg, bot)
    elif kind == "request_end":
        await request_end_cmd(msg, bot)
    elif kind == "myname":
        await myname_cmd(msg)
    elif kind == "help":
        await help_cmd(msg)


class JoinFlowResult(Enum):
    SUCCESS = auto()
    RETRY_BAD_CODE = auto()
    ABORT = auto()

# --- /create flow: scenario menu → player count (only after host runs /create) ---
CREATE_PLAYER_COUNTS = frozenset({10, 11, 12, 13, 15})


class JoinConfirmCb(CallbackData, prefix="jcf"):
    """تأیید ورود به اتاق — code + uid برای امنیت."""

    code: str
    uid: int
    act: str


class CreatePickScenario(CallbackData, prefix="crs"):
    slug: str


class CreatePickPlayers(CallbackData, prefix="crp"):
    slug: str
    count: int


class CreatePickHostMode(CallbackData, prefix="crh"):
    slug: str
    count: int
    mode: str


class SemiAutoDevLobby(CallbackData, prefix="sad"):
    """موقت: پر کردن لابی با بازیکن ساختگی یا انتظار برای join واقعی."""

    code: str
    act: str


class NoHostObserverPrompt(CallbackData, prefix="nho"):
    """ثبت ناظر — فقط سازندهٔ اتاق no_host (بازیکن)."""

    code: str
    act: str


class NoHostBotAssistantPick(CallbackData, prefix="nhb"):
    """انتخاب کمک‌کننده ربات — فقط سازندهٔ اتاق no_host (دستی یا تصادفی)."""

    code: str
    act: str = "random"
    tid: int = 0


class NoHostIntroNightStart(CallbackData, prefix="nhi"):
    """شروع شب معارفه — فقط کمک‌کننده ربات (بدون ناظر فعال)."""

    code: str
    act: str = "go"


class NoHostDay1DefenseCb(CallbackData, prefix="nhd"):
    """پنل دفاعیهٔ روز اول — کمک‌کننده (بدون ناظر فعال)."""

    code: str
    act: str
    tid: int = 0


def _defense_toggle_target_uid(act: str, tid: int) -> int | None:
    if act in ("d1dt", "tog") and tid:
        return tid
    for prefix in ("d1dt-", "d1dt:", "tog-", "tog:"):
        if act.startswith(prefix):
            raw = act[len(prefix) :]
            if raw.lstrip("-").isdigit():
                return int(raw)
    return None


class HostPanel(CallbackData, prefix="hp"):
    """دکمه‌های گرداننده: fs شافل، fd/dr پخش نقش، sy/sr تأیید/شافل مجدد."""

    code: str
    act: str


class EmergencyLeaveConfirm(CallbackData, prefix="elc"):
    code: str


class PlayerEndApprove(CallbackData, prefix="pea"):
    code: str


class PlayerEndDismiss(CallbackData, prefix="pex"):
    code: str


class PlayerEndBroadcastConfirm(CallbackData, prefix="pbc"):
    code: str
    ok: int


class EmergencyLeaveCancel(CallbackData, prefix="elx"):
    code: str


class HubMenu(CallbackData, prefix="hub"):
    """زیرمنو: ply sts lve tre mnm scr nar hlp jin htg amr"""

    act: str


class HostTimerNavigate(CallbackData, prefix="htn"):
    """root = پنل اصلی؛ lb/pd/pe/bc = انتخاب مقدار؛ x = بستن."""

    where: str


class HostTimerApply(CallbackData, prefix="hta"):
    field: str
    value: int


class AmirHostDoc(CallbackData, prefix="amh"):
    """راهنمای نقش امیر مهربان؛ key=close برای بستن پنل."""

    key: str


class SalamatHostPanel(CallbackData, prefix="slt"):
    """پنل نیمه‌خودکار گرداننده برای اتاق تست شبکه سلامت."""

    code: str
    act: str


class MedalPick(CallbackData, prefix="mdl"):
    sid: int
    slot: str
    pid: int


def scenario_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🕵️ بازپرس",
                    callback_data=CreatePickScenario(slug="bazpors").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🏛 نماینده",
                    callback_data=CreatePickScenario(slug="namayande").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎖 تکاور",
                    callback_data=CreatePickScenario(slug="takavar").pack(),
                ),
                InlineKeyboardButton(
                    text="🤝 ماسون",
                    callback_data=CreatePickScenario(slug="masoon").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="💬 مذاکره",
                    callback_data=CreatePickScenario(slug="mozakere").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🕶 مافیای روسی",
                    callback_data=CreatePickScenario(slug="russian_mafia").pack(),
                ),
            ],
        ]
    )


def player_count_keyboard(slug: str) -> InlineKeyboardMarkup:
    if slug == "russian_mafia":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{n} بازیکن",
                        callback_data=CreatePickPlayers(slug=slug, count=n).pack(),
                    )
                    for n in (8, 9)
                ]
            ]
        )
    if slug == "bazpors_salamat_test":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🧪 ۱۲ صندلی ساختگی (تست پنل گرداننده)",
                        callback_data=CreatePickPlayers(
                            slug=slug, count=12
                        ).pack(),
                    ),
                ],
            ]
        )
    if slug == "masoon2":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🧪 ۲ بازیکن (۱ مافیا + ۱ شهروند)",
                        callback_data=CreatePickPlayers(slug=slug, count=2).pack(),
                    ),
                ],
            ]
        )
    if slug == "masoon":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{n} بازیکن",
                        callback_data=CreatePickPlayers(slug=slug, count=n).pack(),
                    )
                    for n in (12, 13, 14)
                ],
                [
                    InlineKeyboardButton(
                        text=f"{n} بازیکن",
                        callback_data=CreatePickPlayers(slug=slug, count=n).pack(),
                    )
                    for n in (15, 16, 17)
                ],
                [
                    InlineKeyboardButton(
                        text="۱۸ بازیکن",
                        callback_data=CreatePickPlayers(slug=slug, count=18).pack(),
                    ),
                ],
            ]
        )
    if slug == "bazpors":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{n} بازیکن",
                        callback_data=CreatePickPlayers(slug=slug, count=n).pack(),
                    )
                    for n in (10, 11, 12, 13)
                ],
            ]
        )
    if slug == "mozakere":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{n} بازیکن",
                        callback_data=CreatePickPlayers(slug=slug, count=n).pack(),
                    )
                    for n in (10, 11, 12, 13)
                ],
                [
                    InlineKeyboardButton(
                        text="۱۵ بازیکن",
                        callback_data=CreatePickPlayers(slug=slug, count=15).pack(),
                    ),
                ],
            ]
        )
    if slug == "takavar":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{n} بازیکن",
                        callback_data=CreatePickPlayers(slug=slug, count=n).pack(),
                    )
                    for n in (10, 11, 12, 13)
                ],
                [
                    InlineKeyboardButton(
                        text="۱۵ بازیکن",
                        callback_data=CreatePickPlayers(slug=slug, count=15).pack(),
                    ),
                ],
            ]
        )
    if slug == "namayande":
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=f"{n} بازیکن",
                        callback_data=CreatePickPlayers(slug=slug, count=n).pack(),
                    )
                    for n in (10, 11, 12)
                ],
                [
                    InlineKeyboardButton(
                        text=f"{n} بازیکن",
                        callback_data=CreatePickPlayers(slug=slug, count=n).pack(),
                    )
                    for n in (13, 14)
                ],
                [
                    InlineKeyboardButton(
                        text="۱۶ بازیکن",
                        callback_data=CreatePickPlayers(slug=slug, count=16).pack(),
                    ),
                ],
            ]
        )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{n} بازیکن",
                    callback_data=CreatePickPlayers(slug=slug, count=n).pack(),
                )
                for n in (10, 11, 12)
            ],
            [
                InlineKeyboardButton(
                    text=f"{n} بازیکن",
                    callback_data=CreatePickPlayers(slug=slug, count=n).pack(),
                )
                for n in (13, 15)
            ],
        ]
    )


MOZAKERE_HOST_MODE_STUB_HTML = (
    "سناریوی مذاکره فعلاً فقط تا مرحله انتخاب نوع گردانندگی آماده شده است. "
    "نقش‌ها و اجرای بازی بعداً اضافه می‌شود."
)

MOZAKERE_DEAL_ROLES_STUB_HTML = (
    "پخش نقش‌های تصادفی برای سناریوی مذاکره در مرحله بعد اضافه می‌شود."
)


def build_host_mode_created_room_html(
    game: Game,
    *,
    mode: str,
    invite_link: str,
    host_label: str,
    scenario_label: str,
    roster_html: str,
    creator_registered: bool = False,
) -> str:
    """متن پنل اتاق پس از انتخاب نوع گردانندگی (بازپرس و مذاکره)."""
    rle = "\u202B"
    pdf = "\u202C"
    lri = "\u2066"
    pdi = "\u2069"

    def rtl_line(s: str) -> str:
        return f"{rle}{s}{pdf}"

    if mode == "semi_auto":
        mode_line = rtl_line(
            "🎙 <b>گردانندگی خودکار مستقل</b> — بعد از پر شدن لابی و پخش نقش، "
            "پنل گردانندگی فعال می‌شود؛ بازیکنان فقط نقش خود را می‌گیرند و تا پایان دست "
            "پیام دیگری از ربات نمی‌بینند."
        )
    elif mode == "no_host":
        mode_line = rtl_line(
            "👤 <b>بازیکن گرداننده</b> — یکی از بازیکنان ربات را راهنمایی می‌کند؛ "
            "شما به‌عنوان بازیکن در صندلی هستید و نقش‌ها برای شما مخفی می‌ماند."
        )
    else:
        mode_line = rtl_line(
            "✋ <b>گردانندگی دستی</b> — شافل صندلی، پخش نقش و روایت بدون پنل ربات."
        )

    host_line = (
        rtl_line(
            "👤 <b>بازیکن گرداننده</b> — کمک‌کنندهٔ ربات پس از ورود به اتاق انتخاب می‌شود"
        )
        if mode == "no_host"
        else rtl_line(f"🎙 گرداننده: {html.escape(host_label)}")
    )
    text = (
        f"{rtl_line('✅ <b>اتاق ساخته شد</b>')}\n\n"
        f"{mode_line}\n\n"
        f"{rtl_line(f'🔑 کد ورود: <b>{html.escape(game.room_code)}</b>')}\n"
        f"{rtl_line(f'🎭 سناریو: {html.escape(scenario_label)}')}\n"
        f"{rtl_line(f'👥 ظرفیت: {game.max_players} نفر')}\n"
        f"{host_line}\n\n"
        f"{roster_html}\n\n"
        f"{rtl_line('📥 بازیکنان با کد بالا یا لینک زیر وارد شوند:')}\n"
        f'{rtl_line(f"🔗 <a href=\"{html.escape(invite_link)}\">ورود به اتاق (یک ضربه)</a>")}\n'
        f"{rtl_line(f'همچنین می‌توانند بفرستند: {lri}/join {html.escape(game.room_code)}{pdi}')}"
    )
    if creator_registered:
        text += (
            "\n\n"
            f"{rtl_line('✅ شما به‌عنوان <b>بازیکن</b> در این اتاق ثبت شدید.')}"
        )
    if mode in ("semi_auto", "no_host"):
        dev_hint = (
            "برای پر کردن بقیهٔ جای خالی با بازیکن تست، دکمهٔ پر کردن تصادفی را بزنید؛ "
            "در غیر این صورت منتظر join بازیکن‌های واقعی بمانید."
            if mode == "no_host"
            else "اگر می‌خواهید صندلی‌ها بدون join واقعی پر شوند، دکمهٔ پر کردن تصادفی را بزنید؛ "
            "در غیر این صورت منتظر بازیکن‌های واقعی بمانید."
        )
        dev_label = (
            "🎲 <b>لابی</b>"
            if mode == "no_host"
            else "🧪 <b>فقط برای تست (موقت)</b>"
        )
        text += (
            "\n\n"
            f"{rtl_line(dev_label)}\n"
            f"{rtl_line(dev_hint)}"
        )
    return text


def bazpors_host_mode_prompt_html(label: str, count: int) -> str:
    n = _fa_digits(count)
    return (
        f"🎭 سناریو: <b>{html.escape(label)}</b> · <b>{n}</b> نفر\n\n"
        "نوع گردانندگی را از لیست زیر انتخاب کنید:\n\n"
        "<b>۱- گردانندگی خودکار مستقل</b>\n"
        "در این حالت، گرداننده اکت‌های بازیکنان را دریافت کرده و در ربات ثبت می‌کند.\n"
        "ربات قوانین بازی را بررسی می‌کند، گرداننده را در طول بازی راهنمایی می‌کند "
        "و گزارش‌های لازم را ارائه می‌دهد.\n\n"
        "<b>۲- بازیکن‌گرداننده</b>\n"
        "در این حالت، یکی از بازیکنان نقش گرداننده را هم بر عهده دارد و ربات را "
        "برای اجرای کامل بازی راهنمایی می‌کند.\n"
        "بازیکن‌گرداننده در هیچ مرحله‌ای از بازی نقش سایر بازیکنان را نمی‌داند.\n"
        "ربات اتفاقات بازی را به‌صورت خلاصه گزارش می‌دهد.\n\n"
        "پس از خروج یک یا چند بازیکن از بازی، امکان انتقال گردانندگی به یکی از "
        "بازیکنان خارج‌شده وجود دارد.\n"
        "در این صورت، ادامه بازی می‌تواند به حالت گردانندگی خودکار مستقل تغییر کند.\n\n"
        "<b>۳- گردانندگی دستی</b>\n"
        "در این حالت، ربات فقط اتاق بازی را ایجاد می‌کند. پس از ورود بازیکنان، "
        "شافل نقش‌ها و ارسال نقش‌ها به بازیکنان انجام می‌شود.\n"
        "از این مرحله به بعد، گرداننده باید بدون کمک ربات و بر اساس قوانین سناریو، "
        "بازی را مدیریت کند."
    )


def bazpors_host_mode_keyboard(slug: str, count: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="گردانندگی خودکار مستقل",
                    callback_data=CreatePickHostMode(
                        slug=slug, count=count, mode="semi_auto"
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="بازیکن گرداننده",
                    callback_data=CreatePickHostMode(
                        slug=slug, count=count, mode="no_host"
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="گردانندگی دستی",
                    callback_data=CreatePickHostMode(
                        slug=slug, count=count, mode="manual"
                    ).pack(),
                ),
            ],
        ]
    )


def find_player_in_game(user_id: int) -> tuple[str | None, Player | None]:
    room = manager.get_room_for_user(user_id)
    if not room:
        return None, None
    game = manager.get_game(room)
    if not game:
        return None, None
    player = game.players.get(user_id)
    if not player:
        return None, None
    return room, player


def user_is_bazpors_host(user_id: int) -> bool:
    room = manager.get_room_for_host(user_id)
    if not room:
        return False
    game = manager.get_game(room)
    return bool(
        game and game.scenario_name in ("bazpors", "bazpors_salamat_test")
    )


def build_amir_host_reply_markup() -> InlineKeyboardMarkup:
    rows_out: list[list[InlineKeyboardButton]] = []
    for row in amir_mb.amir_host_keyboard():
        rows_out.append(
            [
                InlineKeyboardButton(
                    text=lbl,
                    callback_data=AmirHostDoc(key=k).pack(),
                )
                for k, lbl in row
            ]
        )
    rows_out.append(
        [
            InlineKeyboardButton(
                text="✖️ بستن پنل",
                callback_data=AmirHostDoc(key="close").pack(),
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows_out)


def _players_sorted_for_display(game: Game) -> list[Player]:
    return sorted(
        game.players.values(),
        key=lambda p: (p.seat is None, p.seat or 0, p.user_id),
    )


_HOST_TIMER_FIELD_TITLES: dict[str, str] = {
    "lb": "مهلت لابی تا حد نصاب (دقیقه)",
    "pd": "بعد از پخش نقش بدون پایان رسمی (ساعت)",
    "pe": "رأی پایان جمعی /request_end (دقیقه)",
    "bc": "تأیید دوم درخواست‌دهنده قبل از پخش رأی (دقیقه)",
}


def _host_timer_summary_dict(user_id: int) -> dict[str, int]:
    row = db.get_host_timer_settings_row(user_id)
    if not row:
        return normalize_host_timer_settings()
    return normalize_host_timer_settings(
        lobby=row["lobby_fill_deadline_minutes"],
        post=row["post_deal_timeout_hours"],
        appr=row["player_end_approval_minutes"],
        brdc=row["player_end_broadcast_confirm_minutes"],
    )


def _host_timer_value_choices(field: str) -> list[int]:
    if field == "lb":
        return list(range(HOST_TIMER_LOBBY_MIN, HOST_TIMER_LOBBY_MAX + 1, 5))
    if field == "pd":
        return [
            h
            for h in (6, 8, 10, 12, 16, 18, 24, 36, 48)
            if HOST_TIMER_POST_DEAL_MIN_HOURS <= h <= HOST_TIMER_POST_DEAL_MAX_HOURS
        ]
    if field == "pe":
        return list(
            range(
                HOST_TIMER_PLAYER_END_APPROVAL_MIN,
                HOST_TIMER_PLAYER_END_APPROVAL_MAX + 1,
                5,
            )
        )
    if field == "bc":
        return list(
            range(
                HOST_TIMER_BROADCAST_CONFIRM_MIN,
                HOST_TIMER_BROADCAST_CONFIRM_MAX + 1,
                5,
            )
        )
    return []


def _persist_host_timer_field(user_id: int, field: str, value: int) -> dict[str, int]:
    s = _host_timer_summary_dict(user_id)
    if field == "lb":
        out = normalize_host_timer_settings(
            lobby=value,
            post=s["post_deal_timeout_hours"],
            appr=s["player_end_approval_minutes"],
            brdc=s["player_end_broadcast_confirm_minutes"],
        )
    elif field == "pd":
        out = normalize_host_timer_settings(
            lobby=s["lobby_fill_deadline_minutes"],
            post=value,
            appr=s["player_end_approval_minutes"],
            brdc=s["player_end_broadcast_confirm_minutes"],
        )
    elif field == "pe":
        out = normalize_host_timer_settings(
            lobby=s["lobby_fill_deadline_minutes"],
            post=s["post_deal_timeout_hours"],
            appr=value,
            brdc=s["player_end_broadcast_confirm_minutes"],
        )
    elif field == "bc":
        out = normalize_host_timer_settings(
            lobby=s["lobby_fill_deadline_minutes"],
            post=s["post_deal_timeout_hours"],
            appr=s["player_end_approval_minutes"],
            brdc=value,
        )
    else:
        raise ValueError(field)
    db.upsert_host_timer_settings_row(user_id, out)
    return out


def build_host_timer_panel_html(user_id: int) -> str:
    m = _host_timer_summary_dict(user_id)
    return (
        "⏱ <b>مهلت‌های اتاق‌های شما</b>\n\n"
        "برای هر اتاقی که <b>از این به بعد بسازید</b> همین اعداد هنگام ایجاد اتاق ثبت می‌شود؛ "
        "اتاق‌های در جریان عوض نمی‌شوند.\n\n"
        f"• لابی: <b>{_fa_digits(m['lobby_fill_deadline_minutes'])}</b> دقیقه\n"
        f"• بعد از پخش نقش (بدون /endgame): <b>{_fa_digits(m['post_deal_timeout_hours'])}</b> ساعت\n"
        f"• رأی پایان جمعی: <b>{_fa_digits(m['player_end_approval_minutes'])}</b> دقیقه\n"
        f"• تأیید دوم درخواست‌دهنده: <b>{_fa_digits(m['player_end_broadcast_confirm_minutes'])}</b> دقیقه"
    )


def host_timer_root_keyboard(user_id: int) -> InlineKeyboardMarkup:
    m = _host_timer_summary_dict(user_id)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"لابی ({_fa_digits(m['lobby_fill_deadline_minutes'])})",
                    callback_data=HostTimerNavigate(where="lb").pack(),
                ),
                InlineKeyboardButton(
                    text=f"پس‌ازنقش ({_fa_digits(m['post_deal_timeout_hours'])})",
                    callback_data=HostTimerNavigate(where="pd").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text=f"رأی جمعی ({_fa_digits(m['player_end_approval_minutes'])})",
                    callback_data=HostTimerNavigate(where="pe").pack(),
                ),
                InlineKeyboardButton(
                    text=f"تأیید دوم ({_fa_digits(m['player_end_broadcast_confirm_minutes'])})",
                    callback_data=HostTimerNavigate(where="bc").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✖️ بستن پنل",
                    callback_data=HostTimerNavigate(where="x").pack(),
                ),
            ],
        ]
    )


def host_timer_picker_keyboard(field: str) -> InlineKeyboardMarkup:
    choices = _host_timer_value_choices(field)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for v in choices:
        row.append(
            InlineKeyboardButton(
                text=_fa_digits(v),
                callback_data=HostTimerApply(field=field, value=v).pack(),
            )
        )
        if len(row) >= 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text="◀️ بازگشت",
                callback_data=HostTimerNavigate(where="root").pack(),
            ),
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _host_tag_plain(game: Game) -> str:
    return manager.format_user_tag(
        game.host_id,
        game.host_full_name or "گرداننده",
        game.host_username,
    )


def _host_narrator_rating_line_html(host_id: int) -> str:
    avg, n = db.narrator_aggregate_for_host(host_id)
    if not n or avg is None:
        return "امتیاز گردانندگی در ربات تا الان: <i>هنوز بازخوردی ثبت نشده</i>"
    return (
        f"امتیاز گردانندگی در ربات الان: میانگین <b>{avg:.2f}</b> از ۵ ستاره "
        f"({_fa_digits(n)} بازخورد)"
    )


def _players_in_lobby_join_order(game: Game) -> list[Player]:
    """ترتیب پیوستن به لابی (نه مرتب‌سازی بر اساس user_id)."""
    return list(game.players.values())


def build_join_preview_html(game: Game) -> str:
    sc = html.escape(manager.scenario_display_name(game.scenario_name))
    room_no = html.escape(_fa_digits(int(game.room_code)))
    cap = html.escape(_fa_digits(game.max_players))
    roles = manager.intended_roles_for_room(game.scenario_name, game.max_players)
    mafia_roles = [r for r in roles if is_mafia_team(r)]
    town_roles = [r for r in roles if not is_mafia_team(r)]
    lines = [
        f"🏠 اتاق شماره: {room_no} | 📖 سناریو: {sc} | "
        f"👥 تعداد بازیکنان: {cap} نفر",
        "",
        "🎭 لیست نقش‌ها",
        "",
        "🟥 نقش‌های مافیا:",
    ]
    for r in mafia_roles:
        lines.append(f"- {html.escape(role_label_fa(r))}")
    lines.extend(["", "🟦 نقش‌های شهروندی:"])
    for r in town_roles:
        lines.append(f"- {html.escape(role_label_fa(r))}")
    lines.extend(["", "👤 لیست بازیکنان کنونی:"])
    players = _players_in_lobby_join_order(game)
    if not players:
        lines.append("<i>هنوز بازیکنی در اتاق نیست.</i>")
    else:
        for idx, p in enumerate(players, start=1):
            lines.append(
                f"{_fa_digits(idx)}. "
                f"{html.escape(manager.format_player_tag(p))}"
            )
    lines.extend(["", "❓ آیا تمایل دارید در این اتاق بازی کنید؟"])
    return "\n".join(lines)


def join_confirm_keyboard(room_code: str, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ بله  ",
                    callback_data=JoinConfirmCb(
                        code=room_code, uid=user_id, act="yes"
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ خیر",
                    callback_data=JoinConfirmCb(
                        code=room_code, uid=user_id, act="no"
                    ).pack(),
                ),
            ],
        ]
    )


async def _show_join_preview(
    msg: Message, bot: Bot, room_code: str, game: Game
) -> None:
    uid = msg.from_user.id if msg.from_user else 0
    await msg.answer(
        build_join_preview_html(game),
        parse_mode="HTML",
        reply_markup=join_confirm_keyboard(room_code, uid),
    )


def _join_confirm_error_message(
    user_id: int,
    room_code: str,
) -> str | None:
    """اعتبارسنجی ورود پس از تأیید؛ None = مجاز به add_player."""
    game = manager.get_game(room_code)
    if not game:
        return "این کد اتاق فعالی نیست.\nدوباره از گرداننده کد دو رقمی بگیرید."
    if user_id == game.host_id:
        return "شما گرداننده این اتاق هستید؛ خودتان با کد وارد نمی‌شوید. بازیکنان /join بزنند."
    hosting = manager.get_room_for_host(user_id)
    if hosting:
        return (
            "شما یک اتاق دیگر را می‌گیرید. اول آن را با /leave (لغو گرداننده) تمام کنید."
        )
    other = manager.get_room_for_user(user_id)
    if other and other != room_code:
        return f"شما در اتاق دیگری ({other}) هستید. اول /leave بزنید."
    if user_id in game.players:
        return f"شما همین الان در این اتاق هستید. کد: {game.room_code}"
    if len(game.players) >= game.max_players:
        return "ظرفیت اتاق پر است."
    if game.phase != Phase.LOBBY:
        return "این بازی دیگر در حالت لابی نیست."
    return None


async def _execute_confirmed_join(
    bot: Bot,
    user_id: int,
    full_name: str,
    username: str | None,
    room_code: str,
) -> str | None:
    """ورود پس از تأیید؛ None = موفق، وگرنه پیام خطای فارسی."""
    err = _join_confirm_error_message(user_id, room_code)
    if err:
        return err
    game = manager.get_game(room_code)
    if game is None:
        return "این کد اتاق فعالی نیست.\nدوباره از گرداننده کد دو رقمی بگیرید."
    player = Player(
        user_id=user_id,
        full_name=full_name,
        username=username,
    )
    add_err = manager.add_player(game, player)
    if add_err == "full":
        return "ظرفیت اتاق پر است."
    if add_err == "not_lobby":
        return "این بازی دیگر در حالت لابی نیست."
    if add_err == "already_in_room":
        return f"شما همین الان در این اتاق هستید. کد: {game.room_code}"
    await refresh_lobby_status_messages(bot, game)
    ready, _ = manager.lobby_ready_for_deal(game)
    if ready:
        await send_host_lobby_full_prompt(bot, game)
    return None


def build_game_final_report_header_html(
    room_code: str, scenario_name: str, max_players: int
) -> str:
    sc = html.escape(manager.scenario_display_name(scenario_name))
    room_no = html.escape(_fa_digits(int(room_code)))
    cap = html.escape(_fa_digits(max_players))
    return (
        f"🏠 اتاق شماره: {room_no} | 📖 سناریو: {sc} | "
        f"👥 تعداد بازیکنان: {cap} نفر"
    )


def _bazpors_auto_host_final_report_header(game: Game) -> bool:
    """گزارش نهایی no_host و semi_auto — سربرگ اتاق در ابتدای پیام."""
    from bot.room_mode import is_mason_no_host_room, is_mozakere_no_host_room

    if game.scenario_name == "mozakere":
        return is_mozakere_no_host_room(game)
    if game.scenario_name == "masoon":
        return is_mason_no_host_room(game)
    return game.scenario_name in ("bazpors", "bazpors_salamat_test") and (
        is_bazpors_no_host_room(game) or is_bazpors_semi_auto_room(game)
    )


LOBBY_JOIN_LEAVE_HINT = (
    "⚠️ تا پیش از تقسیم و ارسال نقش‌ها توسط گرداننده، "
    "می‌توانید با دستور /leave از اتاق خارج شوید. "
    "پس از تخصیص نقش‌ها، امکان خروج از اتاق وجود نخواهد داشت."
)


def build_lobby_join_status_text(game: Game) -> str:
    """پیام ورود به لابی؛ با هر پیوست جدید برای همه ویرایش می‌شود."""
    sc_label = manager.scenario_display_name(game.scenario_name)
    lines = [
        f"🎲 اتاق: {game.room_code} | 🎭 سناریو: {sc_label} | "
        f"👥 {len(game.players)}/{game.max_players}",
        "",
        "📋 بازیکن‌ها:",
    ]
    for p in _players_in_lobby_join_order(game):
        lines.append(f"\u200f{manager.format_player_tag(p)}")
    lines.extend(["", LOBBY_JOIN_LEAVE_HINT])
    return "\n".join(lines)


async def refresh_lobby_status_messages(bot: Bot, game: Game) -> None:
    if game.phase != Phase.LOBBY:
        return
    text = build_lobby_join_status_text(game)
    for uid in list(game.players.keys()):
        mid = game.lobby_status_message_ids.get(uid)
        if mid is not None:
            try:
                await bot.edit_message_text(chat_id=uid, message_id=mid, text=text)
            except TelegramBadRequest as err:
                if "message is not modified" in str(err).lower():
                    continue
                msg = await safe_send_message_return(bot, uid, text)
                if msg is not None:
                    game.lobby_status_message_ids[uid] = msg.message_id
        else:
            msg = await safe_send_message_return(bot, uid, text)
            if msg is not None:
                game.lobby_status_message_ids[uid] = msg.message_id


def format_players(game_room_code: str) -> str:
    game = manager.get_game(game_room_code)
    if not game or not game.players:
        return "بازیکنی وجود ندارد."
    if game.phase == Phase.LOBBY:
        return build_lobby_join_status_text(game)
    sc_label = manager.scenario_display_name(game.scenario_name)
    lines = [
        f"🎲 اتاق: {game.room_code} | 🎭 سناریو: {sc_label} | "
        f"👥 {len(game.players)}/{game.max_players}",
        "",
        "📋 بازیکن‌ها:",
    ]
    for idx, p in enumerate(_players_sorted_for_display(game), start=1):
        # 🟢/🔴 = زنده / حذف‌شده (ربطی به نقش مافیا یا شهروند ندارد)، فقط بعد از شروع بازی.
        if game.phase == Phase.LOBBY:
            mark = "👤"
        else:
            mark = "🟢" if p.is_alive else "🔴"
        seat_no = p.seat if p.seat is not None else idx
        # RLM برای راست‌به‌چپ پایدار وقتی username لاتین وجود دارد.
        lines.append(
            f"\u200f{_fa_digits(seat_no)}- {manager.format_player_tag(p)} {mark}"
        )
    return "\n".join(lines)


def _private_role_spoiler_html(text: str, *, min_chars: int = 0) -> str:
    escaped = html.escape(text)
    if min_chars and len(text) < min_chars:
        escaped = escaped + (" " * (min_chars - len(text)))
    return f"<tg-spoiler>{escaped}</tg-spoiler>"


def build_private_role_message_html(
    game: Game | None, role: Role, *, with_role_card: bool = False
) -> str:
    if game is not None and game.scenario_name == "russian_mafia":
        from bot.russian_mafia import russian_role_description_fa, russian_role_label_fa

        label = russian_role_label_fa(role)
        return (
            "🎭 نقش شما: <b>" + html.escape(label) + "</b>\n"
            + html.escape(russian_role_description_fa(role, game))
        )
    if game is not None and is_mozakere_scenario(game):
        from bot.mozakere_role_descriptions import mozakere_role_description_fa

        label = scenario_role_label_fa(game, role)
        role_html = f"<b>{_private_role_spoiler_html(label, min_chars=PRIVATE_ROLE_SPOILER_MIN_CHARS)}</b>"
        desc = mozakere_role_description_fa(role)
        desc_html = _private_role_spoiler_html(desc)
        if game is not None and is_no_host_player_room(game):
            mode_line = "بازی بدون گرداننده برگزار می‌شود."
        else:
            mode_line = "📝 روایت دستی است؛ روند شب و روز با گرداننده انجام می‌شود."
        return (
            f"🎭 نقش شما: {role_html}\n"
            f"{mode_line}\n"
            f"درباره نقش شما: {desc_html}"
        )

    if game is not None and is_mason_scenario(game):
        from bot.mason_role_descriptions import build_mason_private_role_message_html

        return build_mason_private_role_message_html(role)

    if game is not None:
        label = html.escape(scenario_role_label_fa(game, role))
    else:
        label = html.escape(role_label_fa(role))
    if len(label) < PRIVATE_ROLE_SPOILER_MIN_CHARS:
        label = label + (" " * (PRIVATE_ROLE_SPOILER_MIN_CHARS - len(label)))
    role_html = f"<b><tg-spoiler>{label}</tg-spoiler></b>"
    if with_role_card:
        hint = (
            "<i>برای دیدن کارت نقش روی تصویر محو بزنید؛ "
            "برای دیدن نام نقش روی نوار خاکستری زیر بزنید.</i>"
        )
    else:
        hint = "<i>برای دیدن نقش روی نوار خاکستری بزنید.</i>"
    if game is not None and is_no_host_player_room(game):
        return (
            f"🎭 نقش شما: {role_html}\n"
            "بازی بدون گرداننده برگزار می‌شود.\n"
            f"{hint}"
        )
    return (
        f"🎭 نقش شما: {role_html}\n"
        "📝 روایت دستی است؛ روند شب و روز با گرداننده انجام می‌شود.\n"
        f"{hint}"
    )


async def send_private_role(
    bot: Bot, user_id: int, role: Role, *, game: Game | None = None
) -> bool:
    """ارسال نقش خصوصی؛ False اگر DM به بازیکن واقعی نرسد."""
    from aiogram.types import FSInputFile

    from bot.role_cards import role_card_image_path
    from bot.tg_send import safe_send_photo_return

    if game is not None and user_id in game.private_role_card_delivered_uids:
        return True
    if game is not None and is_synthetic_player_uid(user_id):
        return True

    card_path = (
        None
        if game is not None
        and (
            is_mozakere_scenario(game)
            or is_mason_scenario(game)
            or game.scenario_name == "russian_mafia"
        )
        else role_card_image_path(role)
    )
    msg = build_private_role_message_html(
        game, role, with_role_card=card_path is not None
    )
    if card_path is not None:
        sent = await safe_send_photo_return(
            bot,
            user_id,
            FSInputFile(card_path),
            caption=msg,
            parse_mode="HTML",
            reply_markup=ReplyKeyboardRemove(),
            has_spoiler=True,
        )
        ok = sent is not None
    else:
        ok = await safe_send_message(
            bot, user_id, msg, parse_mode="HTML", reply_markup=ReplyKeyboardRemove()
        )
    if ok and game is not None:
        game.private_role_card_delivered_uids.add(user_id)
        from bot.observer_delivery import (
            mirror_per_player_to_observer,
            no_host_observer_registered,
        )

        if no_host_observer_registered(game):
            await mirror_per_player_to_observer(
                bot, game, user_id, msg, parse_mode="HTML"
            )
    return ok


async def ensure_private_role_card_delivered(
    bot: Bot, game: Game, user_id: int
) -> None:
    """اگر پیام نقش هنوز نرسیده، دوباره ارسال می‌کند (مثلاً کمک‌کننده ربات)."""
    if user_id in game.private_role_card_delivered_uids:
        return
    if is_synthetic_player_uid(user_id):
        return
    player = game.players.get(user_id)
    if player is None or player.role is None:
        return
    await send_private_role(bot, user_id, player.role, game=game)


def no_host_observer_prompt_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔹 کد برای ناظر بازی فرستاده شد",
                    callback_data=NoHostObserverPrompt(
                        code=game.room_code, act="code_sent"
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔹 ناظر بازی لازم نیست",
                    callback_data=NoHostObserverPrompt(
                        code=game.room_code, act="skip"
                    ).pack(),
                )
            ],
        ]
    )


def build_no_host_observer_prompt_html(game: Game) -> str:
    obs_code = manager.ensure_observer_code(game)
    code_fa = _fa_digits(obs_code)
    return (
        "🎮 برای ثبت ناظر بازی، از شخص موردنظر بخواهید با کد "
        f"<b>{code_fa}</b> و دستور "
        f"<code>/observer_{obs_code}</code> "
        "نام خود را به‌عنوان ناظر بازی ثبت کند."
    )


async def send_no_host_observer_prompt(bot: Bot, game: Game) -> None:
    """فقط به بازیکنِ سازندهٔ اتاق no_host (بازپرس یا مذاکره)."""
    if not is_no_host_player_room(game):
        return
    creator_id = game.host_id
    if creator_id not in game.players or is_synthetic_player_uid(creator_id):
        return
    game.observer_prompt_status = game.observer_prompt_status or "pending"
    await safe_send_message(
        bot,
        creator_id,
        build_no_host_observer_prompt_html(game),
        parse_mode="HTML",
        reply_markup=no_host_observer_prompt_keyboard(game),
    )


def no_host_bot_assistant_pick_keyboard(game: Game) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in sorted(
        [
            pl
            for pl in game.players.values()
            if not is_synthetic_player_uid(pl.user_id)
        ],
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    ):
        lab = manager.format_player_tag(p)[:40]
        row.append(
            InlineKeyboardButton(
                text=lab,
                callback_data=NoHostBotAssistantPick(
                    code=game.room_code, act="pick", tid=p.user_id
                ).pack(),
            )
        )
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text="🎲 انتخاب تصادفی",
                callback_data=NoHostBotAssistantPick(
                    code=game.room_code, act="random", tid=0
                ).pack(),
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_no_host_bot_assistant_prompt_html() -> str:
    return (
        "🤖 برای این بازی باید یک نفر به‌عنوان «کمک‌کننده ربات» انتخاب شود.\n\n"
        "چه کسی را انتخاب می‌کنید؟ از لیست زیر یکی را بزنید "
        "یا «انتخاب تصادفی»."
    )


def _assistant_pick_room(game: Game) -> bool:
    return no_host_bot_assistant_flow_enabled(game) or is_russian_mafia_host_helper_room(
        game
    )


def _no_host_bot_assistant_candidate_uids(game: Game) -> list[int]:
    if not _assistant_pick_room(game):
        return []
    observer_id = game.observer_user_id
    return [
        uid
        for uid in game.players
        if not is_synthetic_player_uid(uid) and uid != observer_id
    ]


def pick_random_no_host_bot_assistant(game: Game) -> int | None:
    if not _assistant_pick_room(game):
        return None
    candidates = _no_host_bot_assistant_candidate_uids(game)
    if not candidates:
        return None
    return random.choice(candidates)


def build_no_host_bot_assistant_private_html(*, random_pick: bool) -> str:
    if random_pick:
        lead = "شما به‌صورت تصادفی به‌عنوان «کمک‌کننده ربات» انتخاب شدید."
    else:
        lead = "شما به‌عنوان «کمک‌کننده ربات» انتخاب شدید."
    return f"🤖 {lead}\n📌 هر زمان لازم باشد، از شما کمک خواهم گرفت."


def build_no_host_assistant_announcement_html(game: Game, assistant_uid: int) -> str:
    ap = game.players.get(assistant_uid)
    assistant_tag = html.escape(
        manager.format_player_tag(ap) if ap else str(assistant_uid)
    )
    lines = [
        f"🤖 <b>{assistant_tag}</b> به‌عنوان کمک‌کننده ربات در این بازی انتخاب شد.",
        "",
    ]
    if no_host_observer_registered(game):
        obs_tag = html.escape(
            manager.format_user_tag(
                game.observer_user_id,
                game.observer_full_name,
                game.observer_username,
            )
        )
        lines.extend(
            [
                f"👁️ <b>{obs_tag}</b> به‌عنوان ناظر بازی انتخاب شد.",
                "",
                "📩 ناظر بازی تمامی پیام‌های خصوصی‌ای که ربات برای بازیکنان "
                "ارسال می‌کند را مشاهده خواهد کرد.",
            ]
        )
    return "\n".join(lines)


async def send_no_host_bot_assistant_prompt(bot: Bot, game: Game) -> None:
    """مرحلهٔ بعد از تأیید/رد ناظر — فقط اتاق no_host و فقط به سازنده."""
    if not no_host_bot_assistant_flow_enabled(game):
        return
    creator_id = game.host_id
    if creator_id not in game.players or is_synthetic_player_uid(creator_id):
        return
    if game.bot_assistant_user_id is not None:
        return
    await safe_send_message(
        bot,
        creator_id,
        build_no_host_bot_assistant_prompt_html(),
        parse_mode="HTML",
        reply_markup=no_host_bot_assistant_pick_keyboard(game),
    )


async def finalize_no_host_bot_assistant(
    bot: Bot, game: Game, assistant_uid: int, *, random_pick: bool = True
) -> None:
    if not no_host_bot_assistant_flow_enabled(game):
        return
    game.bot_assistant_user_id = assistant_uid
    game.no_host_assistant_narrator_active = True
    game.no_host_observer_only_narrator_mirror = True
    await ensure_private_role_card_delivered(bot, game, assistant_uid)
    await send_to_player(
        bot,
        game,
        assistant_uid,
        build_no_host_bot_assistant_private_html(random_pick=random_pick),
        parse_mode="HTML",
    )
    announce = build_no_host_assistant_announcement_html(game, assistant_uid)
    await broadcast_to_players(
        bot,
        game,
        announce,
        exclude=assistant_uid,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.bot_assistant_picked",
            assistant_uid=assistant_uid,
            observer_uid=game.observer_user_id,
            random_pick=random_pick,
        )
    except Exception:
        pass
    await send_no_host_intro_night_start_prompt(bot, game)


def build_no_host_intro_night_start_html() -> str:
    return (
        "🌙 <b>شروع شب معارفه</b>\n\n"
        "با فشردن دکمه زیر، شب معارفه آغاز خواهد شد.\n\n"
        "⚠️ <b>توجه:</b>\n"
        "پس از فشردن این دکمه، پیامی برای تمامی اعضای تیم مافیا ارسال می‌شود "
        "که در آن هم‌تیمی‌هایشان معرفی خواهند شد.\n\n"
        "❗ لطفاً فقط زمانی این دکمه را بزنید که روز معارفه به‌طور کامل "
        "به پایان رسیده باشد."
    )


def build_no_host_intro_night_confirm_html() -> str:
    return (
        "🌙 <b>تأیید شروع شب معارفه</b>\n\n"
        "شما در آستانه شروع شب معارفه هستید.\n\n"
        "📨 با ادامه این فرایند، پیامی حاوی معرفی تمامی اعضای تیم مافیا "
        "برای اعضای این تیم ارسال خواهد شد.\n\n"
        "❓ آیا از ادامه این عملیات اطمینان دارید؟"
    )


def intro_night_start_keyboard_for(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    if game_observer_mirror_active(game):
        return mirrored_intro_night_start_keyboard(game, assistant_uid)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌙 شروع شب معارفه",
                    callback_data=NoHostIntroNightStart(
                        code=game.room_code, act="go"
                    ).pack(),
                ),
            ],
        ]
    )


def intro_night_confirm_keyboard_for(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    if game_observer_mirror_active(game):
        return mirrored_intro_night_confirm_keyboard(game, assistant_uid)
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ ادامه",
                    callback_data=NoHostIntroNightStart(
                        code=game.room_code, act="ok"
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="↩️ بازگشت",
                    callback_data=NoHostIntroNightStart(
                        code=game.room_code, act="back"
                    ).pack(),
                ),
            ],
        ]
    )


def build_no_host_intro_night_civilian_html() -> str:
    return (
        "🌙 <b>شب معارفه آغاز شد</b>\n"
        "اعضای تیم مافیا از طریق پیام ارسالی، هم‌تیمی‌های خود را شناسایی کردند.\n"
        "😴 لطفاً چشم‌های خود را ببندید و بخوابید تا اعضای تیم مافیا "
        "فرصت بیشتری برای آشنایی با یکدیگر داشته باشند."
    )


def _no_host_alive_mafia_for_intro(game: Game) -> list[Player]:
    mafs = [
        p
        for p in game.players.values()
        if p.is_alive and p.role and is_mafia_team(p.role)
    ]

    def _sort_key(p: Player) -> tuple[int, int, int]:
        if p.role == Role.MAFIA_BOSS:
            return (0, p.seat if p.seat is not None else 999, p.user_id)
        return (1, p.seat if p.seat is not None else 999, p.user_id)

    mafs.sort(key=_sort_key)
    return mafs


def build_no_host_intro_night_mafia_dm_html(game: Game) -> str:
    lines = [
        "🌙 <b>شب معارفه آغاز شد.</b>",
        "شما عضو تیم مافیا هستید. اعضای تیم شما عبارت‌اند از:",
        "📋 <b>اعضای تیم مافیا:</b>",
    ]
    for p in _no_host_alive_mafia_for_intro(game):
        tag = html.escape(manager.format_player_tag(p))
        role_txt = html.escape(scenario_role_label_fa(game, p.role))
        lines.append(f"• {tag} — <b>{role_txt}</b>")
    return "\n".join(lines)


async def deliver_no_host_intro_night_started_messages(
    bot: Bot, game: Game
) -> None:
    """پس از تأیید شب معارفه — پیام جدا برای شهروندان زنده و تیم مافیا."""
    civilian_text = build_no_host_intro_night_civilian_html()
    mafia_text = build_no_host_intro_night_mafia_dm_html(game)
    for uid, p in game.players.items():
        if not p.is_alive or is_synthetic_player_uid(uid):
            continue
        if p.role and is_mafia_team(p.role):
            text = mafia_text
        else:
            text = civilian_text
        await safe_send_message(bot, uid, text, parse_mode="HTML")
    if no_host_observer_registered(game):
        obs_id = game.observer_user_id
        if obs_id is not None:
            await safe_send_message(
                bot, obs_id, civilian_text, parse_mode="HTML"
            )


async def send_no_host_intro_night_start_prompt(
    bot: Bot,
    game: Game,
    *,
    observer_only: bool = False,
) -> None:
    """فقط کمک‌کننده ربات؛ اگر ناظر ثبت شده همان پیام بدون پیش‌وند آینه."""
    if not no_host_bot_assistant_flow_enabled(game):
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None or game.no_host_intro_night_started:
        return
    text = build_no_host_intro_night_start_html()
    kb = intro_night_start_keyboard_for(game, assistant_uid)
    ui_key = mirror_ui_claim_key(
        game.room_code, "intro_night_start", assistant_uid
    )
    await register_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        ui_key,
        text,
        kb,
        send_player=not observer_only,
        send_observer=no_host_observer_registered(game),
        observer_same_text=True,
        parse_mode="HTML",
    )
    # ناظر دیرتر ثبت شده: پیام کمک‌کننده هنوز دکمهٔ قدیمی (nhi) دارد — کیبورد آینه را هم‌گام کن.
    if observer_only and game_observer_mirror_active(game):
        entry = game.mirror_prompt_messages.get(ui_key, {})
        if entry.get("player"):
            await update_mirror_prompt_pair(
                bot,
                game,
                ui_key,
                text,
                kb,
                assistant_uid=assistant_uid,
                parse_mode="HTML",
            )


async def _refresh_intro_night_prompt_panel(
    bot: Bot,
    game: Game,
    assistant_uid: int,
    *,
    phase: str,
    callback_message: Message | None = None,
) -> None:
    if phase == "confirm":
        text = build_no_host_intro_night_confirm_html()
        kb = intro_night_confirm_keyboard_for(game, assistant_uid)
    else:
        text = build_no_host_intro_night_start_html()
        kb = intro_night_start_keyboard_for(game, assistant_uid)
    ui_key = mirror_ui_claim_key(
        game.room_code, "intro_night_start", assistant_uid
    )
    entry = game.mirror_prompt_messages.get(ui_key) or {}
    if entry.get("player") or entry.get("observer"):
        await update_mirror_prompt_pair(
            bot,
            game,
            ui_key,
            text,
            kb,
            assistant_uid=assistant_uid,
            parse_mode="HTML",
        )
    elif callback_message is not None:
        try:
            await callback_message.edit_text(
                text, parse_mode="HTML", reply_markup=kb
            )
        except TelegramBadRequest:
            pass


async def _handle_no_host_intro_night_action(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
    act: str,
) -> None:
    if callback.message is None:
        return
    if not no_host_bot_assistant_flow_enabled(game):
        await callback.answer("این مرحله برای این اتاق نیست.", show_alert=True)
        return
    if game.bot_assistant_user_id != assistant_uid:
        await callback.answer("فقط کمک‌کننده ربات.", show_alert=True)
        return
    if game.no_host_intro_night_started:
        await callback.answer("شب معارفه قبلاً شروع شده است.", show_alert=True)
        return
    if act == "go":
        await callback.answer()
        await _refresh_intro_night_prompt_panel(
            bot,
            game,
            assistant_uid,
            phase="confirm",
            callback_message=callback.message,
        )
        return
    if act == "back":
        await callback.answer()
        await _refresh_intro_night_prompt_panel(
            bot,
            game,
            assistant_uid,
            phase="start",
            callback_message=callback.message,
        )
        return
    if act != "ok":
        await callback.answer("نامعتبر.", show_alert=True)
        return
    await _execute_no_host_intro_night_start(
        callback, bot, game, assistant_uid, actor_uid
    )


async def _execute_no_host_intro_night_start(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if callback.message is None:
        return
    game.no_host_intro_night_started = True
    from bot.bazpors_narrator import _mark_day_start_alive_snapshot

    game.bazpors_narrator_host_day = max(1, game.bazpors_narrator_host_day)
    _mark_day_start_alive_snapshot(game)
    ui_key = mirror_ui_claim_key(
        game.room_code, "intro_night_start", assistant_uid
    )
    await apply_mirror_claim_winner(
        bot, game, ui_key, actor_uid, assistant_uid
    )
    await callback.answer("شب معارفه شروع شد.")
    try:
        base = callback.message.html_text or callback.message.text or ""
        await callback.message.edit_text(
            base + "\n\n<i>✅ شب معارفه آغاز شد.</i>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
    if is_mason_scenario(game):
        from bot.mason_intro_flow import mason_after_intro_night_started

        await mason_after_intro_night_started(bot, game, manager)
    else:
        await deliver_no_host_intro_night_started_messages(bot, game)
        try:
            from bot.game_audit_log import log_event

            log_event(
                game,
                "no_host.intro_night_started",
                assistant_uid=assistant_uid,
                observer_uid=game.observer_user_id,
                observer_prompt_status=game.observer_prompt_status,
                observer_mirror_active=no_host_observer_registered(game),
                per_seat_broadcast_targets=len(game.players) - 1,
            )
        except Exception:
            pass
        await no_host_run_day1_end_vote_flow(bot, game)
        return
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.intro_night_started",
            assistant_uid=assistant_uid,
            observer_uid=game.observer_user_id,
            observer_prompt_status=game.observer_prompt_status,
            observer_mirror_active=no_host_observer_registered(game),
            per_seat_broadcast_targets=len(game.players) - 1,
        )
    except Exception:
        pass


def day1_vote_choice_keyboard_for(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    from bot.no_host_day_vote import day_vote_choice_keyboard_for as _kb

    return _kb(game, assistant_uid)


async def send_no_host_day1_vote_prompt(bot: Bot, game: Game) -> None:
    from bot.no_host_day_vote import send_no_host_day_vote_prompt

    await send_no_host_day_vote_prompt(bot, game)


def build_no_host_day1_defense_no_exit_broadcast_html(
    game: Game, assistant_uid: int
) -> str:
    from bot.no_host_day_vote import (
        no_host_day_ordinal_fa,
        no_host_upcoming_night_ordinal_fa,
    )

    ap = game.players.get(assistant_uid)
    tag = html.escape(
        manager.format_player_tag(ap) if ap else str(assistant_uid)
    )
    day_w = no_host_day_ordinal_fa(game.bazpors_narrator_host_day)
    night_w = no_host_upcoming_night_ordinal_fa(game)
    return (
        f"🌙 <b>پایان روز {day_w}</b>\n\n"
        f"<b>{tag}</b> تأیید کرد که پس از دفاعیه، "
        "هیچ بازیکنی با اجماع رأی از بازی خارج نشد؛ "
        f"بنابراین وارد فاز شب {night_w} می‌شویم.\n\n"
        "😴 لطفاً برای چند لحظه بخوابید تا گروه مافیا بیدار شده و "
        "درباره تصمیم امشب خود مشورت کند.\n\n"
        f"پس از پایان مشورت و با تأیید <b>{tag}</b>، انتخاب تمام بازیکنان "
        "از طریق پیام خصوصی دریافت و ثبت خواهد شد.\n\n"
        "📩 همه بازیکنان باید یکی از گزینه‌هایی را که ربات برایشان "
        "ارسال می‌کند انتخاب کنند.\n\n"
        f"✅ وقتی همه بازیکنان انتخاب خود را انجام دادند، "
        f"<b>{tag}</b> می‌تواند تأیید کند تا نتیجه شب {night_w} برای همه ارسال شود."
    )


def build_no_host_day1_no_defense_votes_broadcast_html(
    game: Game, assistant_uid: int
) -> str:
    from bot.no_host_day_vote import (
        no_host_day_ordinal_fa,
        no_host_upcoming_night_ordinal_fa,
    )

    ap = game.players.get(assistant_uid)
    tag = html.escape(
        manager.format_player_tag(ap) if ap else str(assistant_uid)
    )
    day_w = no_host_day_ordinal_fa(game.bazpors_narrator_host_day)
    night_w = no_host_upcoming_night_ordinal_fa(game)
    return (
        f"🌙 <b>پایان روز {day_w}</b>\n\n"
        f"<b>{tag}</b> تأیید کرد که در پایان روز و پس از رأی‌گیری، "
        "هیچ بازیکنی آرای لازم برای دفاعیه را کسب نکرده است؛ "
        f"بنابراین وارد فاز شب {night_w} می‌شویم.\n\n"
        "😴 لطفاً برای چند لحظه بخوابید تا گروه مافیا بیدار شده و "
        "درباره تصمیم امشب خود مشورت کند.\n\n"
        f"پس از پایان مشورت و با تأیید <b>{tag}</b>، انتخاب تمام بازیکنان "
        "از طریق پیام خصوصی دریافت و ثبت خواهد شد.\n\n"
        "📩 همه بازیکنان باید یکی از گزینه‌هایی را که ربات برایشان "
        "ارسال می‌کند انتخاب کنند.\n\n"
        f"✅ وقتی همه بازیکنان انتخاب خود را انجام دادند، "
        f"<b>{tag}</b> می‌تواند تأیید کند تا نتیجه شب {night_w} برای همه ارسال شود."
    )


def build_no_host_day1_skip_vote_broadcast_html(
    game: Game, assistant_uid: int
) -> str:
    ap = game.players.get(assistant_uid)
    tag = html.escape(
        manager.format_player_tag(ap) if ap else str(assistant_uid)
    )
    return (
        f"🌙 <b>{tag}</b> تأیید کرد که رأی‌گیری در این روز لازم نیست.\n\n"
        "😴 لطفاً همه بازیکنان بخوابند تا گروه مافیا بتوانند با هم مشورت کنند."
    )


async def _process_no_host_day1_skip_night(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.no_host_day1_vote_resolved:
        await callback.answer("این انتخاب قبلاً ثبت شده است.", show_alert=True)
        return
    from bot.no_host_day_vote import no_host_day_vote_choice_ui_key

    ui_key = no_host_day_vote_choice_ui_key(game, assistant_uid)
    await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
    await callback.answer("ثبت شد.")
    try:
        if callback.message:
            base = callback.message.html_text or callback.message.text or ""
            await callback.message.edit_text(
                base + "\n\n<i>✅ به فاز شب می‌رویم (بدون رأی روز).</i>",
                parse_mode="HTML",
                reply_markup=None,
            )
    except Exception:
        pass
    broadcast = build_no_host_day1_skip_vote_broadcast_html(game, assistant_uid)
    await broadcast_to_alive_players(
        bot,
        game,
        broadcast,
        exclude=assistant_uid,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    no_host_skip_day1_vote_enter_night(game)
    await on_no_host_entered_night1(bot, game, manager)
    game.no_host_day1_vote_resolved = True
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_vote_skipped",
            assistant_uid=assistant_uid,
            actor_uid=actor_uid,
        )
    except Exception:
        pass


async def _process_no_host_day1_show_vote_panel(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.no_host_day1_vote_resolved:
        await callback.answer("این انتخاب قبلاً ثبت شده است.", show_alert=True)
        return
    from bot.no_host_day_vote import no_host_day_vote_choice_ui_key

    ui_key = no_host_day_vote_choice_ui_key(game, assistant_uid)
    if game_observer_mirror_active(game):
        err = try_claim_mirror_ui(game, ui_key, actor_uid, assistant_uid)
        if err == "already_claimed":
            await callback.answer("این انتخاب قبلاً ثبت شده است.", show_alert=True)
            return
        if err not in (None, "dup_self") and await _answer_mirror_claim(
            callback, err
        ):
            return
    await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
    await callback.answer("پنل رأی‌گیری فعال شد.")
    begin_no_host_day1_defense_pick(game)
    text = build_no_host_day1_defense_pick_html(game)
    kb = day1_defense_pick_keyboard_for(game, assistant_uid)
    pick_key = _no_host_day1_defense_pick_ui_key(game, assistant_uid)
    from bot.observer_delivery import promote_mirror_prompt_to_panel

    promoted = await promote_mirror_prompt_to_panel(
        bot,
        game,
        from_ui_key=ui_key,
        to_ui_key=pick_key,
        assistant_uid=assistant_uid,
        text=text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    if not promoted:
        await send_no_host_day1_defense_pick_panel(bot, game)
    game.no_host_day1_vote_resolved = True
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_vote_panel_opened",
            assistant_uid=assistant_uid,
            actor_uid=actor_uid,
        )
    except Exception:
        pass


def _no_host_day1_defense_pick_ui_key(game: Game, assistant_uid: int) -> str:
    d = max(1, game.bazpors_narrator_host_day)
    kind = "day1_defense_pick" if d == 1 else f"day_defense_pick_{d}"
    return mirror_ui_claim_key(game.room_code, kind, assistant_uid)


def _no_host_day1_defense_outcome_ui_key(game: Game, assistant_uid: int) -> str:
    d = max(1, game.bazpors_narrator_host_day)
    kind = "day1_defense_outcome" if d == 1 else f"day_defense_outcome_{d}"
    return mirror_ui_claim_key(game.room_code, kind, assistant_uid)


def _no_host_day1_pick_elim_ui_key(game: Game, assistant_uid: int) -> str:
    d = max(1, game.bazpors_narrator_host_day)
    kind = "day1_defense_pick_elim" if d == 1 else f"day_defense_pick_elim_{d}"
    return mirror_ui_claim_key(game.room_code, kind, assistant_uid)


def _no_host_day1_confirm_elim_ui_key(game: Game, assistant_uid: int) -> str:
    d = max(1, game.bazpors_narrator_host_day)
    kind = (
        "day1_defense_confirm_elim"
        if d == 1
        else f"day_defense_confirm_elim_{d}"
    )
    return mirror_ui_claim_key(game.room_code, kind, assistant_uid)


def _day1_defense_pool_players(game: Game) -> list[Player]:
    pool: list[Player] = []
    for uid in sorted(day_vote_defender_uids(game)):
        p = game.players.get(uid)
        if p is not None and p.is_alive:
            pool.append(p)
    return pool


def _alive_players_sorted(game: Game) -> list[Player]:
    alive = [p for p in game.players.values() if p.is_alive]
    return sorted(alive, key=lambda p: (p.seat if p.seat is not None else 999, p.user_id))


def _no_host_day1_defense_actor_may_act(
    game: Game, actor_uid: int, assistant_uid: int
) -> bool:
    if actor_uid == assistant_uid:
        return True
    return (
        game_observer_mirror_active(game)
        and game.observer_user_id == actor_uid
    )


def build_no_host_day1_defense_pick_html(game: Game) -> str:
    picked = day_vote_pick_uids(game)
    n = len(picked)
    sel = f"\n<i>انتخاب‌شده: {_fa_digits(n)} نفر</i>\n" if n else "\n"
    return (
        "🌅 روز شروع شد.\n"
        "از لیست زیر، بازیکنانی را انتخاب کنید که در پایان روز "
        "با رأی اکثریت برای دفاع انتخاب شده‌اند. 🗳️⚖️\n"
        "سپس دکمه «برو به مرحله بعد» را بزنید. ⏭️\n"
        "اگر هیچ بازیکنی وارد مرحله دفاعیه نشده است، "
        "دکمه «دفاعیه نداریم» را بزنید تا بازی وارد شب شود. 🌙"
        f"{sel}"
    )


def _no_host_day1_defense_pick_keyboard(
    game: Game, assistant_uid: int, *, mirror: bool
) -> InlineKeyboardMarkup:
    picked = day_vote_pick_uids(game)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in _alive_players_sorted(game):
        tick = "✅" if p.user_id in picked else "☐"
        name = html.escape(manager.format_player_tag(p)[:24])
        if mirror:
            cb = PlayerMirrorCb(
                code=game.room_code,
                act="d1dt",
                as_uid=assistant_uid,
                tid=p.user_id,
            ).pack()
        else:
            cb = NoHostDay1DefenseCb(
                code=game.room_code, act="tog", tid=p.user_id
            ).pack()
        row.append(InlineKeyboardButton(text=f"{tick} {name}", callback_data=cb))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if mirror:
        confirm_cb = PlayerMirrorCb(
            code=game.room_code, act="d1dc", as_uid=assistant_uid
        ).pack()
        none_cb = PlayerMirrorCb(
            code=game.room_code, act="d1dn", as_uid=assistant_uid
        ).pack()
    else:
        confirm_cb = NoHostDay1DefenseCb(
            code=game.room_code, act="confirm"
        ).pack()
        none_cb = NoHostDay1DefenseCb(code=game.room_code, act="none").pack()
    rows.append(
        [
            InlineKeyboardButton(
                text="⏭️ برو به مرحله بعد",
                callback_data=confirm_cb,
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                text="🌙 دفاعیه نداریم",
                callback_data=none_cb,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def day1_defense_pick_keyboard_for(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    mirror = game_observer_mirror_active(game)
    return _no_host_day1_defense_pick_keyboard(game, assistant_uid, mirror=mirror)


async def send_no_host_day1_defense_pick_panel(bot: Bot, game: Game) -> None:
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None or not game.no_host_day1_defense_active:
        return
    text = build_no_host_day1_defense_pick_html(game)
    kb = day1_defense_pick_keyboard_for(game, assistant_uid)
    pick_key = _no_host_day1_defense_pick_ui_key(game, assistant_uid)
    from bot.observer_delivery import publish_mirror_prompt_pair

    await publish_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        pick_key,
        text,
        kb,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        fresh_observer_copy=True,
        parse_mode="HTML",
    )


async def refresh_no_host_day1_defense_pick_panel(bot: Bot, game: Game) -> None:
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None or game.no_host_day1_defense_phase != "pick":
        return
    text = build_no_host_day1_defense_pick_html(game)
    kb = day1_defense_pick_keyboard_for(game, assistant_uid)
    ui_key = _no_host_day1_defense_pick_ui_key(game, assistant_uid)
    await update_mirror_prompt_pair(
        bot, game, ui_key, text, kb, assistant_uid=assistant_uid, parse_mode="HTML"
    )


def build_no_host_day1_defense_outcome_html(game: Game) -> str:
    if is_mason_scenario(game):
        from bot.mason_day_defense import build_mason_defense_candidates_announcement_html

        return build_mason_defense_candidates_announcement_html(game)
    uids = sorted(day_vote_defender_uids(game))
    lines: list[str] = []
    for uid in uids:
        p = game.players.get(uid)
        if not p:
            continue
        tag = html.escape(manager.format_player_tag(p))
        prev = day_vote_participation_count(game, uid)
        lines.append(
            f"👤 {tag} 🗳️ سابقه حضور در رأی‌گیری‌های قبلی: {_fa_digits(prev)}"
        )
    body = "\n".join(lines) if lines else "<i>هیچ بازیکنی انتخاب نشده است.</i>"
    return (
        "بازیکن(های) زیر برای دفاعیه انتخاب شده‌اند:\n\n"
        f"{body}"
    )


def build_no_host_day1_pick_elim_html(game: Game) -> str:
    n = len(_day1_defense_pool_players(game))
    return (
        "💀 <b>خروجی دفاعیه — انتخاب بازیکن خارج‌شده</b>\n\n"
        f"📋 از بین <b>{n}</b> بازیکن دفاعیه، کسی را که با اجماع رأی "
        "از بازی خارج شد انتخاب کنید."
    )


def build_no_host_day1_confirm_elim_html(game: Game, target_uid: int) -> str:
    p = game.players.get(target_uid)
    tag = html.escape(
        manager.format_player_tag(p) if p else str(target_uid)
    )
    return (
        "⚠️ <b>تأیید حذف</b>\n\n"
        f"آیا مطمئن هستید که <b>{tag}</b> با اجماع رأی‌گیری "
        "از بازی خارج شد؟"
    )


def build_no_host_day1_elim_broadcast_html(
    game: Game, assistant_uid: int, eliminated_uid: int
) -> str:
    from bot.bazpors_narrator import hunter_vote_elim_names_html_block

    ap = game.players.get(assistant_uid)
    assistant_tag = html.escape(
        manager.format_player_tag(ap) if ap else str(assistant_uid)
    )
    from bot.no_host_day_vote import (
        no_host_day_ordinal_fa,
        no_host_upcoming_night_ordinal_fa,
    )

    names_block = hunter_vote_elim_names_html_block(
        game, manager, eliminated_uid
    )
    day_w = no_host_day_ordinal_fa(game.bazpors_narrator_host_day)
    night_w = no_host_upcoming_night_ordinal_fa(game)
    elim_intro = (
        "بازیکنان زیر با اجماع رأی‌گیری از بازی خارج شدند"
        if "\n" in names_block
        else "بازیکن زیر با اجماع رأی‌گیری از بازی خارج شد"
    )
    return (
        f"🌙 <b>پایان روز {day_w}</b>\n\n"
        f"طبق تأیید <b>{assistant_tag}</b>، {elim_intro}:\n\n"
        f"{names_block}\n\n"
        "🌑 فاز شب آغاز می‌شود.\n\n"
        "😴 لطفاً برای چند لحظه بخوابید تا گروه مافیا بیدار شده و "
        "درباره تصمیم امشب خود مشورت کند.\n\n"
        f"پس از پایان مشورت و با تأیید <b>{assistant_tag}</b>، انتخاب تمام "
        "بازیکنان از طریق پیام خصوصی دریافت و ثبت خواهد شد.\n\n"
        "📩 همه بازیکنان باید یکی از گزینه‌هایی را که ربات برایشان "
        "ارسال می‌کند انتخاب کنند.\n\n"
        f"✅ وقتی همه بازیکنان انتخاب خود را انجام دادند، "
        f"<b>{assistant_tag}</b> می‌تواند تأیید کند تا نتیجه شب {night_w} "
        "برای همه ارسال شود."
    )


def _no_host_day1_defense_outcome_keyboard(
    game: Game, assistant_uid: int, *, mirror: bool
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in _day1_defense_pool_players(game):
        name = html.escape(manager.format_player_tag(p)[:28])
        if mirror:
            cb = PlayerMirrorCb(
                code=game.room_code,
                act="d1el",
                as_uid=assistant_uid,
                tid=p.user_id,
            ).pack()
        else:
            cb = NoHostDay1DefenseCb(
                code=game.room_code, act="d1el", tid=p.user_id
            ).pack()
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"خروج ({name})",
                    callback_data=cb,
                )
            ]
        )
    if mirror:
        no_cb = PlayerMirrorCb(
            code=game.room_code, act="d1d0", as_uid=assistant_uid
        ).pack()
    else:
        no_cb = NoHostDay1DefenseCb(
            code=game.room_code, act="no_exit"
        ).pack()
    rows.append(
        [
            InlineKeyboardButton(
                text="خروجی نداشتیم. شب کن",
                callback_data=no_cb,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _no_host_day1_pick_elim_keyboard(
    game: Game, assistant_uid: int, *, mirror: bool
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in _day1_defense_pool_players(game):
        name = html.escape(manager.format_player_tag(p)[:28])
        if mirror:
            cb = PlayerMirrorCb(
                code=game.room_code, act="d1el", as_uid=assistant_uid, tid=p.user_id
            ).pack()
        else:
            cb = NoHostDay1DefenseCb(
                code=game.room_code, act="d1el", tid=p.user_id
            ).pack()
        row.append(InlineKeyboardButton(text=name, callback_data=cb))
        if len(row) >= 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if mirror:
        back_cb = PlayerMirrorCb(
            code=game.room_code, act="d1d0", as_uid=assistant_uid
        ).pack()
    else:
        back_cb = NoHostDay1DefenseCb(code=game.room_code, act="no_exit").pack()
    rows.append(
        [
            InlineKeyboardButton(
                text="↩️ خروجی نداشتیم",
                callback_data=back_cb,
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _no_host_day1_confirm_elim_keyboard(
    game: Game, assistant_uid: int, *, mirror: bool
) -> InlineKeyboardMarkup:
    if mirror:
        yes_cb = PlayerMirrorCb(
            code=game.room_code, act="d1ey", as_uid=assistant_uid
        ).pack()
        no_cb = PlayerMirrorCb(
            code=game.room_code, act="d1en", as_uid=assistant_uid
        ).pack()
    else:
        yes_cb = NoHostDay1DefenseCb(code=game.room_code, act="elim_yes").pack()
        no_cb = NoHostDay1DefenseCb(code=game.room_code, act="elim_no").pack()
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔹 بله، تأیید و حذف از بازی",
                    callback_data=yes_cb,
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔹 خیر، بازگشت به انتخاب",
                    callback_data=no_cb,
                )
            ],
        ]
    )


async def send_no_host_day1_pick_elim_panel(bot: Bot, game: Game) -> None:
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return
    text = build_no_host_day1_pick_elim_html(game)
    kb = _no_host_day1_pick_elim_keyboard(
        game, assistant_uid, mirror=game_observer_mirror_active(game)
    )
    pick_key = _no_host_day1_pick_elim_ui_key(game, assistant_uid)
    confirm_key = _no_host_day1_confirm_elim_ui_key(game, assistant_uid)
    outcome_key = _no_host_day1_defense_outcome_ui_key(game, assistant_uid)
    promoted = False
    for from_key in (pick_key, confirm_key, outcome_key):
        if await promote_mirror_prompt_to_panel(
            bot,
            game,
            from_ui_key=from_key,
            to_ui_key=pick_key,
            assistant_uid=assistant_uid,
            text=text,
            reply_markup=kb,
        ):
            promoted = True
            break
    if not promoted:
        await register_mirror_prompt_pair(
            bot,
            game,
            assistant_uid,
            pick_key,
            text,
            kb,
            send_observer=no_host_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )


async def send_no_host_day1_confirm_elim_panel(
    bot: Bot, game: Game, target_uid: int
) -> None:
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return
    text = build_no_host_day1_confirm_elim_html(game, target_uid)
    kb = _no_host_day1_confirm_elim_keyboard(
        game, assistant_uid, mirror=game_observer_mirror_active(game)
    )
    confirm_key = _no_host_day1_confirm_elim_ui_key(game, assistant_uid)
    pick_key = _no_host_day1_pick_elim_ui_key(game, assistant_uid)
    outcome_key = _no_host_day1_defense_outcome_ui_key(game, assistant_uid)
    promoted = False
    for from_key in (outcome_key, pick_key):
        if await promote_mirror_prompt_to_panel(
            bot,
            game,
            from_ui_key=from_key,
            to_ui_key=confirm_key,
            assistant_uid=assistant_uid,
            text=text,
            reply_markup=kb,
        ):
            promoted = True
            break
    if not promoted:
        await register_mirror_prompt_pair(
            bot,
            game,
            assistant_uid,
            confirm_key,
            text,
            kb,
            send_observer=no_host_observer_registered(game),
            observer_same_text=False,
            parse_mode="HTML",
        )
        await close_mirror_prompt_keyboards(bot, game, outcome_key)
        await close_mirror_prompt_keyboards(bot, game, pick_key)


async def send_no_host_day1_defense_outcome_panel(bot: Bot, game: Game) -> None:
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        return
    text = build_no_host_day1_defense_outcome_html(game)
    kb = _no_host_day1_defense_outcome_keyboard(
        game, assistant_uid, mirror=game_observer_mirror_active(game)
    )
    ui_key = _no_host_day1_defense_outcome_ui_key(game, assistant_uid)
    await register_mirror_prompt_pair(
        bot,
        game,
        assistant_uid,
        ui_key,
        text,
        kb,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )


async def send_no_host_day1_defense_outcome_prompt(bot: Bot, game: Game) -> None:
    await send_no_host_day1_defense_outcome_panel(bot, game)


async def _no_host_day1_defense_toggle(
    bot: Bot, game: Game, assistant_uid: int, target_uid: int
) -> str | None:
    if game.no_host_day1_defense_phase != "pick":
        return "این مرحله دیگر فعال نیست."
    if target_uid not in game.players or not game.players[target_uid].is_alive:
        return "بازیکن زنده نیست."
    picked = day_vote_pick_uids(game)
    if target_uid in picked:
        picked.discard(target_uid)
    else:
        picked.add(target_uid)
    set_day_vote_pick_uids(game, picked)
    await refresh_no_host_day1_defense_pick_panel(bot, game)
    return None


async def _no_host_day1_defense_confirm(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.no_host_day1_defense_phase != "pick":
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    ui_key = _no_host_day1_defense_pick_ui_key(game, assistant_uid)
    if game_observer_mirror_active(game):
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor_uid, assistant_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
    picked = {
        u
        for u in day_vote_pick_uids(game)
        if u in game.players and game.players[u].is_alive
    }
    set_day_vote_defender_uids(game, picked)
    set_day_vote_pick_uids(game, set())
    from bot.russian_mafia_flow import note_russian_defense_candidates

    note_russian_defense_candidates(game, picked)
    game.no_host_day1_defense_phase = "outcome"
    await callback.answer("ثبت شد.")
    pick_key = _no_host_day1_defense_pick_ui_key(game, assistant_uid)
    outcome_key = _no_host_day1_defense_outcome_ui_key(game, assistant_uid)
    text = build_no_host_day1_defense_outcome_html(game)
    kb = _no_host_day1_defense_outcome_keyboard(
        game, assistant_uid, mirror=game_observer_mirror_active(game)
    )
    promoted = await promote_mirror_prompt_to_panel(
        bot,
        game,
        from_ui_key=pick_key,
        to_ui_key=outcome_key,
        assistant_uid=assistant_uid,
        text=text,
        reply_markup=kb,
        parse_mode="HTML",
    )
    if not promoted:
        try:
            if callback.message:
                base = callback.message.html_text or callback.message.text or ""
                await callback.message.edit_text(
                    base + "\n\n<i>✅ انتخاب‌ها ثبت شد.</i>",
                    parse_mode="HTML",
                    reply_markup=None,
                )
        except Exception:
            pass
        await send_no_host_day1_defense_outcome_panel(bot, game)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_defense_confirmed",
            assistant_uid=assistant_uid,
            actor_uid=actor_uid,
            defender_uids=sorted(picked),
        )
    except Exception:
        pass


async def _no_host_day1_defense_no_votes(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.no_host_day1_defense_phase != "pick":
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    ui_key = _no_host_day1_defense_pick_ui_key(game, assistant_uid)
    if game_observer_mirror_active(game):
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor_uid, assistant_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
    set_day_vote_pick_uids(game, set())
    set_day_vote_defender_uids(game, set())
    await callback.answer("ثبت شد.")
    try:
        if callback.message:
            base = callback.message.html_text or callback.message.text or ""
            await callback.message.edit_text(
                base + "\n\n<i>✅ پیام پایان روز برای بازیکنان ارسال شد؛ وارد شب یک می‌شویم.</i>",
                parse_mode="HTML",
                reply_markup=None,
            )
    except Exception:
        pass
    broadcast = build_no_host_day1_no_defense_votes_broadcast_html(
        game, assistant_uid
    )
    await broadcast_to_alive_players(
        bot,
        game,
        broadcast,
        exclude=assistant_uid,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    from bot.russian_mafia_flow import apply_russian_day_result

    if await apply_russian_day_result(
        bot, game, eliminated_uid=None, reason="none"
    ):
        return
    no_host_day1_defense_no_votes_enter_night(game)
    await on_no_host_entered_night1(bot, game, manager)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_defense_no_votes",
            assistant_uid=assistant_uid,
            actor_uid=actor_uid,
        )
    except Exception:
        pass


async def _no_host_day1_defense_outcome_no_exit(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.no_host_day1_defense_phase not in ("outcome", "pick_elim"):
        try:
            from bot.game_audit_log import log_no_host_day1_defense_callback

            log_no_host_day1_defense_callback(
                game,
                act="no_exit",
                actor_uid=actor_uid,
                assistant_uid=assistant_uid,
                source="dispatch",
                outcome="rejected",
                reject_reason="wrong_phase",
            )
        except Exception:
            pass
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    ui_key = _no_host_day1_defense_outcome_ui_key(game, assistant_uid)
    if game_observer_mirror_active(game):
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor_uid, assistant_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
    game.no_host_day1_pending_elim_uid = None
    await callback.answer("ثبت شد.")
    try:
        if callback.message:
            base = callback.message.html_text or callback.message.text or ""
            await callback.message.edit_text(
                base + "\n\n<i>✅ خروجی نداشتیم — وارد شب یک می‌شویم.</i>",
                parse_mode="HTML",
                reply_markup=None,
            )
    except Exception:
        pass
    broadcast = build_no_host_day1_defense_no_exit_broadcast_html(
        game, assistant_uid
    )
    await broadcast_to_alive_players(
        bot,
        game,
        broadcast,
        exclude=assistant_uid,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    from bot.russian_mafia_flow import apply_russian_day_result

    if await apply_russian_day_result(
        bot, game, eliminated_uid=None, reason="no_exit"
    ):
        return
    no_host_day1_no_exit_enter_night(game)
    await on_no_host_entered_night1(bot, game, manager)
    try:
        from bot.game_audit_log import (
            log_event,
            log_no_host_day1_defense_callback,
        )

        log_no_host_day1_defense_callback(
            game,
            act="no_exit",
            actor_uid=actor_uid,
            assistant_uid=assistant_uid,
            source="dispatch",
            outcome="completed",
        )
        log_event(
            game,
            "no_host.day1_defense_outcome",
            assistant_uid=assistant_uid,
            actor_uid=actor_uid,
            had_exit=False,
        )
    except Exception:
        pass


async def _no_host_day1_defense_outcome_has_exit(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.no_host_day1_defense_phase != "outcome":
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    pool = _day1_defense_pool_players(game)
    if not pool:
        await callback.answer(
            "لیست دفاعیه خالی است؛ ابتدا بازیکنان دفاعیه را ثبت کنید.",
            show_alert=True,
        )
        return
    ui_key = _no_host_day1_defense_outcome_ui_key(game, assistant_uid)
    if game_observer_mirror_active(game):
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor_uid, assistant_uid),
        ):
            return
        game.mirror_action_claims[ui_key] = actor_uid
    game.no_host_day1_defense_phase = "pick_elim"
    game.no_host_day1_pending_elim_uid = None
    await callback.answer("بازیکن خارج‌شده را انتخاب کنید.")
    await send_no_host_day1_pick_elim_panel(bot, game)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_defense_pick_elim_opened",
            assistant_uid=assistant_uid,
            actor_uid=actor_uid,
        )
    except Exception:
        pass


async def _no_host_day1_defense_pick_elim(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
    target_uid: int,
) -> None:
    if game.no_host_day1_defense_phase not in ("pick_elim", "outcome"):
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    allowed = {p.user_id for p in _day1_defense_pool_players(game)}
    if target_uid not in allowed:
        await callback.answer(
            "فقط بازیکنان ثبت‌شده در دفاعیه قابل انتخاب هستند.",
            show_alert=True,
        )
        return
    game.no_host_day1_pending_elim_uid = target_uid
    game.no_host_day1_defense_phase = "confirm_elim"
    await callback.answer("تأیید کنید.")
    await send_no_host_day1_confirm_elim_panel(bot, game, target_uid)


async def _no_host_day1_defense_confirm_elim_yes(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.no_host_day1_defense_phase != "confirm_elim":
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    target_uid = game.no_host_day1_pending_elim_uid
    if target_uid is None or target_uid not in game.players:
        await callback.answer("بازیکن انتخاب نشده.", show_alert=True)
        return
    if not game.players[target_uid].is_alive:
        await callback.answer("این بازیکن قبلاً خارج شده است.", show_alert=True)
        return
    ui_key = _no_host_day1_confirm_elim_ui_key(game, assistant_uid)
    if game_observer_mirror_active(game):
        if await _answer_mirror_claim(
            callback,
            try_claim_mirror_ui(game, ui_key, actor_uid, assistant_uid),
        ):
            return
        await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, assistant_uid)
    from bot.russian_mafia_flow import finish_russian_confirmed_elimination

    if await finish_russian_confirmed_elimination(
        callback, bot, game, assistant_uid, target_uid
    ):
        return
    from bot.bazpors_narrator import hunter_chain_confirm_alert_text

    chain_alert = hunter_chain_confirm_alert_text(
        game, manager, target_uid, public=True
    )
    eliminate_player_from_game(
        game, manager, target_uid, elim_source="day_vote"
    )
    armor_saved = game.players[target_uid].is_alive
    if not armor_saved:
        from bot.room_mode import is_mason_scenario

        if is_mason_scenario(game):
            from bot.mason_day_ability import (
                dismiss_mason_day_ability_panel_for_eliminated,
            )

            await dismiss_mason_day_ability_panel_for_eliminated(
                bot, game, target_uid
            )
    if not armor_saved:
        await flush_elimination_notifications(bot, game)
    if armor_saved:
        await callback.answer("زره مصرف شد؛ بازیکن در بازی ماند.", show_alert=True)
    elif chain_alert:
        await callback.answer(chain_alert, show_alert=True)
    else:
        await callback.answer("حذف ثبت شد.")
    try:
        if callback.message:
            base = callback.message.html_text or callback.message.text or ""
            suffix = (
                "\n\n<i>✅ زره مصرف شد؛ بازیکن در بازی ماند.</i>"
                if armor_saved
                else "\n\n<i>✅ حذف بازیکن تأیید و ثبت شد.</i>"
            )
            await callback.message.edit_text(
                base + suffix,
                parse_mode="HTML",
                reply_markup=None,
            )
    except Exception:
        pass
    skip_mid = (
        frozenset({callback.message.message_id})
        if callback.message
        else frozenset()
    )
    await close_mirror_prompt_keyboards(
        bot,
        game,
        _no_host_day1_defense_outcome_ui_key(game, assistant_uid),
        skip_message_ids=skip_mid,
    )
    await close_mirror_prompt_keyboards(
        bot,
        game,
        _no_host_day1_pick_elim_ui_key(game, assistant_uid),
        skip_message_ids=skip_mid,
    )
    if armor_saved:
        from bot.roles.mozakere_armored import day_vote_armor_consumed_announce_line

        broadcast = (
            "<b>📢 اعلام رأی روز</b>\n\n"
            f"{html.escape(day_vote_armor_consumed_announce_line(game, manager, target_uid))}"
        )
    else:
        broadcast = build_no_host_day1_elim_broadcast_html(
            game, assistant_uid, target_uid
        )
    await broadcast_to_alive_players(
        bot,
        game,
        broadcast,
        exclude=assistant_uid,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    from bot.no_host_mafia_win import no_host_maybe_end_on_faction_win

    if not armor_saved and await no_host_maybe_end_on_faction_win(
        bot,
        game,
        manager,
        elim_source="day_vote",
        elim_uid=target_uid,
    ):
        return
    from bot.no_host_handoff import offer_handoff_day1_after_elim

    if offer_handoff_day1_after_elim(game):
        await push_host_step(bot, game, manager)
    else:
        no_host_day1_after_elim_enter_night(game)
        await on_no_host_entered_night1(bot, game, manager)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.day1_defense_elim_confirmed",
            assistant_uid=assistant_uid,
            actor_uid=actor_uid,
            eliminated_uid=target_uid,
            host_day=game.bazpors_narrator_host_day,
            night_count=game.bazpors_narrator_night_count,
        )
    except Exception:
        pass


async def _no_host_day1_defense_confirm_elim_no(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
) -> None:
    if game.no_host_day1_defense_phase != "confirm_elim":
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    game.no_host_day1_pending_elim_uid = None
    game.no_host_day1_defense_phase = "outcome"
    await callback.answer("بازگشت به انتخاب.")
    await send_no_host_day1_defense_outcome_panel(bot, game)


async def _dispatch_no_host_day1_defense_act(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    assistant_uid: int,
    actor_uid: int,
    act: str,
    *,
    tid: int = 0,
    source: str = "nhd",
) -> None:
    try:
        from bot.game_audit_log import log_no_host_day1_defense_callback

        log_no_host_day1_defense_callback(
            game,
            act=act,
            actor_uid=actor_uid,
            assistant_uid=assistant_uid,
            source=source,
            target_uid=tid or None,
            outcome="received",
        )
    except Exception:
        pass
    if not _no_host_day1_defense_actor_may_act(game, actor_uid, assistant_uid):
        try:
            from bot.game_audit_log import log_no_host_day1_defense_callback

            log_no_host_day1_defense_callback(
                game,
                act=act,
                actor_uid=actor_uid,
                assistant_uid=assistant_uid,
                source=source,
                target_uid=tid or None,
                outcome="rejected",
                reject_reason="forbidden_actor",
            )
        except Exception:
            pass
        await callback.answer("شما مجاز به این عمل نیستید.", show_alert=True)
        return
    target_uid = _defense_toggle_target_uid(act, tid)
    if target_uid is not None:
        err = await _no_host_day1_defense_toggle(
            bot, game, assistant_uid, target_uid
        )
        if err:
            await callback.answer(err, show_alert=True)
            return
        await callback.answer("به‌روز شد.")
        return
    if act in ("confirm", "d1dc"):
        await _no_host_day1_defense_confirm(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    if act in ("none", "d1dn"):
        await _no_host_day1_defense_no_votes(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    if act in ("no_exit", "d1d0"):
        await _no_host_day1_defense_outcome_no_exit(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    if act in ("has_exit", "d1d1"):
        await _no_host_day1_defense_outcome_has_exit(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    if act == "d1el" and tid:
        await _no_host_day1_defense_pick_elim(
            callback, bot, game, assistant_uid, actor_uid, tid
        )
        return
    if act in ("elim_yes", "d1ey"):
        await _no_host_day1_defense_confirm_elim_yes(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    if act in ("elim_no", "d1en"):
        await _no_host_day1_defense_confirm_elim_no(
            callback, bot, game, assistant_uid, actor_uid
        )
        return
    try:
        from bot.game_audit_log import log_no_host_day1_defense_callback

        log_no_host_day1_defense_callback(
            game,
            act=act,
            actor_uid=actor_uid,
            assistant_uid=assistant_uid,
            source=source,
            target_uid=tid or None,
            outcome="rejected",
            reject_reason="unknown_act",
        )
    except Exception:
        pass
    await callback.answer("عمل نامعتبر.", show_alert=True)


_OBSERVER_REGISTER_ERRORS_FA: dict[str, str] = {
    "invalid_code": "کد ناظر نامعتبر است.",
    "not_no_host": "این اتاق حالت بدون گرداننده ندارد.",
    "skipped": "سازندهٔ بازی ثبت ناظر را لغو کرده است.",
    "already_registered": "برای این بازی قبلاً ناظر ثبت شده است.",
    "creator_is_player": "سازندهٔ اتاق خودش بازیکن است و نمی‌تواند ناظر شود.",
    "is_player": "بازیکنان این صندلی نمی‌توانند ناظر شوند.",
    "in_other_room": "اول از اتاق دیگری که در آن بازیکن هستید خارج شوید.",
    "hosts_other_room": "شما گردانندهٔ اتاق دیگری هستید؛ نمی‌توانید ناظر شوید.",
    "observer_elsewhere": "شما در حال حاضر ناظر اتاق دیگری هستید.",
}


async def register_observer_via_command(
    msg: Message, bot: Bot, observer_code: str
) -> None:
    if not msg.from_user:
        return
    code = join_code_to_ascii_digits(observer_code)
    if code is None or len(code) != 4:
        await msg.answer(_OBSERVER_REGISTER_ERRORS_FA["invalid_code"])
        return
    game = manager.find_no_host_game_by_observer_code(code)
    if not game:
        await msg.answer(
            "اتاق فعالی با این کد ناظر پیدا نشد. کد را از بازیکن سازندهٔ بازی بگیرید."
        )
        return
    err = manager.register_game_observer(
        game,
        msg.from_user.id,
        full_name=msg.from_user.full_name or "",
        username=msg.from_user.username,
    )
    if err == "already_registered":
        if game.observer_user_id == msg.from_user.id:
            from bot.no_host_night_entry import resync_observer_night_entry_panels
            from bot.no_host_night_sage_quote import resync_observer_night_sage_quotes

            await send_observer_players_roster(bot, game, manager)
            if game.bazpors_host_mode == "no_host":
                await resync_observer_night_sage_quotes(bot, game)
                await resync_observer_night_entry_panels(bot, game, manager)
            room = html.escape(game.room_code)
            await msg.answer(
                f"شما قبلاً ناظر اتاق <code>{room}</code> بودید.\n"
                "پنل‌های باز (از جمله نقش‌های شب) دوباره برای شما ارسال شد.",
                parse_mode="HTML",
            )
            return
        await msg.answer(_OBSERVER_REGISTER_ERRORS_FA["already_registered"])
        return
    if err:
        await msg.answer(
            _OBSERVER_REGISTER_ERRORS_FA.get(err, "ثبت ناظر ممکن نیست.")
        )
        return
    tag = html.escape(
        manager.format_user_tag(
            msg.from_user.id,
            game.observer_full_name,
            game.observer_username,
        )
    )
    room = html.escape(game.room_code)
    await msg.answer(
        f"✅ شما به‌عنوان <b>ناظر بازی</b> اتاق <code>{room}</code> ثبت شدید.\n"
        f"نقش شما: <b>{html.escape(role_label_fa(Role.OBSERVER))}</b>\n\n"
        "از این پس هر پیامی که برای بازیکنان این دست فرستاده شود، "
        "همین‌جا هم برای شما می‌آید.\n"
        "اگر دکمهٔ انتخاب داشته باشد، هر کس زودتر بزند (شما یا همان بازیکن) "
        "همان انتخاب ثبت می‌شود.",
        parse_mode="HTML",
    )
    await send_observer_players_roster(bot, game, manager)
    if game.bazpors_host_mode == "no_host":
        from bot.no_host_night_entry import resync_observer_night_entry_panels
        from bot.no_host_night_sage_quote import resync_observer_night_sage_quotes

        await resync_observer_night_sage_quotes(bot, game)
        await resync_observer_night_entry_panels(bot, game, manager)
    try:
        await bot.send_message(
            game.host_id,
            f"✅ <b>{tag}</b> با دستور <code>/observer_{html.escape(code)}</code> "
            "به‌عنوان ناظر بازی ثبت شد.",
            parse_mode="HTML",
        )
    except Exception:
        pass
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "observer.registered",
            uid=msg.from_user.id,
            name=game.observer_full_name,
        )
    except Exception:
        pass
    if no_host_bot_assistant_flow_enabled(game) and game.bot_assistant_user_id is not None:
        if game.no_host_intro_night_started:
            if is_mason_scenario(game):
                from bot.mason_intro_flow import deliver_mason_intro_night_started_messages

                await deliver_mason_intro_night_started_messages(bot, game)
            else:
                await deliver_no_host_intro_night_started_messages(bot, game)
        else:
            await send_no_host_intro_night_start_prompt(bot, game, observer_only=True)


async def broadcast_game(bot: Bot, game: Game, text: str, *, exclude: int | None = None) -> None:
    await broadcast_to_players(
        bot,
        game,
        text,
        exclude=exclude,
        is_synthetic_uid=is_synthetic_player_uid,
    )


async def broadcast_post_session_html(
    bot: Bot,
    session_id: int,
    text: str,
    *,
    observer_user_id: int | None = None,
) -> bool:
    """بعد از پایان اتاق؛ به بازیکنان جلسه + گرداننده (+ ناظر اگر ثبت شده)."""
    row = db.get_session(session_id)
    if not row:
        return False
    host_id = int(row["host_id"])
    targets = db.session_player_ids(session_id) | {host_id}
    if observer_user_id is not None:
        targets.add(int(observer_user_id))
    sent = False

    async def _send(uid: int) -> None:
        nonlocal sent
        if await safe_send_message(bot, uid, text, parse_mode="HTML"):
            sent = True

    await gather_bounded(list(targets), _send)
    return sent



# ایموجی سطر مدال در پیام جمع‌بندی پایان دست (بدون جدول)
SESSION_RECAP_MEDAL_EMOJI: dict[str, str] = {
    "gold": "🥇",
    "silver": "🥈",
    "bronze": "🥉",
    "honor1": "🎖",
    "honor2": "🎗",
}


def _role_from_snap_value(val: object) -> Role | None:
    if not isinstance(val, str):
        return None
    try:
        return Role(val)
    except ValueError:
        return None


def _recap_roster_mafia_tier(role: Role | None) -> int:
    if role == Role.MAFIA_BOSS:
        return 0
    if role == Role.MAFIA_BASIC:
        return 2
    return 1


def _recap_roster_citizen_tier(role: Role | None) -> int:
    if role is None or role == Role.CITIZEN:
        return 1
    return 0


def _fa_number_text(n: float | int) -> str:
    """نمایش عدد با ارقام فارسی (برای امتیاز گزارش پایان دست)."""
    if isinstance(n, int) or n == int(n):
        return _fa_digits(int(n))
    s = f"{n:.1f}".rstrip("0").rstrip(".")
    return s.translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _format_recap_rating_line(avg: float | None, n_ratings: int) -> str:
    if not n_ratings or avg is None:
        return "⭐️ <b>امتیاز:</b> <i>ثبت نشده</i>"
    return (
        f"⭐️ <b>امتیاز:</b> {_fa_number_text(avg)}/۵ "
        f"از {_fa_digits(n_ratings)} بازخورد"
    )


def _recap_medal_emoji_by_uid(medals_map: dict[str, int]) -> dict[int, str]:
    """هر بازیکن حداکثر یک مدال — برای نمایش کنار نام در فهرست پایان دست."""
    out: dict[int, str] = {}
    for slot in db.MEDAL_SLOTS:
        rid = medals_map.get(slot)
        if rid is None:
            continue
        out[int(rid)] = SESSION_RECAP_MEDAL_EMOJI.get(slot, "🏅")
    return out


def _recap_row_counts_as_mafia(row: dict[str, object]) -> bool:
    if bool(row.get("yakuza_converted")):
        return True
    if bool(row.get("mozakere_converted_by_negotiation")):
        return True
    return is_mafia_team(_role_from_snap_value(row.get("role")))


def _recap_scenario_role_label(scenario_name: str, role: Role | None) -> str:
    if role is None:
        return "نامشخص"
    if scenario_name == "mozakere":
        from bot.game import mozakere_role_label_fa

        return mozakere_role_label_fa(role)
    return role_label_fa(role)


def _recap_roster_name_and_role(
    row: dict[str, object], *, scenario_name: str = "bazpors"
) -> tuple[str, str]:
    tag = str(row.get("tag") or "بازیکن نامشخص")
    role = _role_from_snap_value(row.get("role"))
    if bool(row.get("yakuza_converted")):
        show_role = _role_from_snap_value(row.get("original_role")) or role
        role_txt = _recap_scenario_role_label(scenario_name, show_role)
        return f"{tag} (یاکوزایی شده)", role_txt
    if bool(row.get("mozakere_converted_by_negotiation")):
        show_role = _role_from_snap_value(row.get("mozakere_original_role")) or role
        role_txt = _recap_scenario_role_label(scenario_name, show_role)
        return f"{tag} (مذاکره)", role_txt
    role_txt = _recap_scenario_role_label(scenario_name, role)
    return tag, role_txt


def _build_session_recap_roster_lines(
    rows: list[dict[str, object]],
    *,
    medal_by_uid: dict[int, str] | None = None,
    scenario_name: str = "bazpors",
) -> list[str]:
    """فهرست پایان دست: مافیا (نقش‌دار → ساده) سپس شهروند (نقش‌دار → ساده)."""
    medals = medal_by_uid or {}
    parsed: list[tuple[dict[str, object], Role | None, int, int]] = []
    for row in rows:
        try:
            uid = int(row["user_id"])
            seat = int(row["seat"])
        except (KeyError, ValueError, TypeError):
            continue
        role = _role_from_snap_value(row.get("role"))
        parsed.append((row, role, seat, uid))

    mafia = [x for x in parsed if _recap_row_counts_as_mafia(x[0])]
    citizens = [x for x in parsed if not _recap_row_counts_as_mafia(x[0])]
    mafia.sort(
        key=lambda x: (_recap_roster_mafia_tier(x[1]), x[2], x[3])
    )
    citizens.sort(
        key=lambda x: (_recap_roster_citizen_tier(x[1]), x[2], x[3])
    )

    lines: list[str] = []
    for row, _role, seat, uid in mafia:
        name_txt, role_txt = _recap_roster_name_and_role(
            row, scenario_name=scenario_name
        )
        medal = f" {medals[uid]}" if uid in medals else ""
        lines.append(
            f"🔴 <b>{_fa_digits(seat)}</b>- {html.escape(name_txt)} — "
            f"{html.escape(role_txt)}{medal}"
        )
    for row, _role, seat, uid in citizens:
        name_txt, role_txt = _recap_roster_name_and_role(
            row, scenario_name=scenario_name
        )
        medal = f" {medals[uid]}" if uid in medals else ""
        lines.append(
            f"🟢 <b>{_fa_digits(seat)}</b>- {html.escape(name_txt)} — "
            f"{html.escape(role_txt)}{medal}"
        )
    return lines


def _load_audit_records_for_recap(snap: dict[str, object]) -> list[dict[str, object]]:
    raw = snap.get("audit_log_path")
    if not isinstance(raw, str) or not raw.strip():
        return []
    path = Path(raw)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    rows: list[dict[str, object]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(rec, dict):
            rows.append(rec)
    return rows


def _timeline_day_for_elimination(bz: dict[str, object]) -> int:
    """روز نمایشی در جمع‌بندی — بازپرسی روز بعد از شب N است (نه host_day خام)."""
    step = str(bz.get("narrator_step") or "")
    try:
        host_day = int(bz.get("host_day") or 1)
    except (ValueError, TypeError):
        host_day = 1
    try:
        night_count = int(bz.get("night_count") or 0)
    except (ValueError, TypeError):
        night_count = 0
    if step == "no_host_interrog_day":
        return max(1, night_count + 1)
    if step in (
        "confirm_interrog_vote_elim",
        "pick_interrog_vote_elim",
    ):
        return max(1, night_count + 1)
    if not step and night_count == 0:
        return max(1, host_day)
    return max(1, host_day)


def _timeline_yaku_line_from_bazpors(
    bz: dict[str, object],
    tag_for_uid,
    *,
    records: list[dict[str, object]] | None = None,
    night_no: int | None = None,
) -> str | None:
    """یک خط یاکوزایی برای تایم‌لاین — از اسنپ‌شات یا آخرین yc در لاگ."""
    if not bz.get("yakuzai_used"):
        return None
    civ_uid = bz.get("yaku_night_civilian_uid")
    sac_uid = bz.get("yaku_sac_elim_uid") or bz.get("yaku_sac_uid")
    success = bz.get("yaku_night_success")
    if civ_uid is None and records and night_no is not None:
        recruits_raw = bz.get("mafia_recruit_ids")
        recruits: set[int] = set()
        if isinstance(recruits_raw, list):
            for x in recruits_raw:
                try:
                    recruits.add(int(x))
                except (TypeError, ValueError):
                    pass
        for rec in reversed(records):
            if str(rec.get("event") or "") != "narrator.callback":
                continue
            if str(rec.get("act") or "") != "yc":
                continue
            rbz = rec.get("bazpors")
            if not isinstance(rbz, dict):
                continue
            try:
                rec_night = int(rbz.get("night_count") or 0)
            except (TypeError, ValueError):
                rec_night = 0
            if rec_night != night_no:
                continue
            try:
                civ_uid = int(rec["tid"])
            except (KeyError, TypeError, ValueError):
                continue
            if success is None:
                success = civ_uid in recruits
            break
    if civ_uid is None or sac_uid is None:
        return None
    try:
        civ_i = int(civ_uid)
        sac_i = int(sac_uid)
    except (TypeError, ValueError):
        return None
    if success:
        label = "یاکوزایی موفق"
    elif success is False:
        label = "یاکوزایی ناموفق"
    else:
        return None
    return (
        f"🤝 {label} با ({tag_for_uid(civ_i)} - مافیای فدا شده: {tag_for_uid(sac_i)})"
    )


def _timeline_night_lines_from_bazpors(
    bz: dict[str, object],
    tag_for_uid,
    *,
    records: list[dict[str, object]] | None = None,
    night_no: int | None = None,
) -> list[str]:
    """اقدامات ثبت‌شدهٔ یک شب ناتمام — وقتی night.resolved ثبت نشده."""
    lines: list[str] = []
    try:
        hunter_link = int(bz["hunter_link_uid"])
    except (KeyError, TypeError, ValueError):
        hunter_link = None
    if hunter_link is not None and bz.get("hunter_linked_this_night"):
        lines.append(f"🏹 هانتر: {tag_for_uid(hunter_link)}")
    try:
        shot_t = int(bz["mafia_target"])
    except (KeyError, TypeError, ValueError):
        shot_t = None
    if bz.get("mafia_shot_registered") and shot_t is not None:
        lines.append(f"🔴 شات مافیا: {tag_for_uid(shot_t)}")
    yaku = _timeline_yaku_line_from_bazpors(
        bz, tag_for_uid, records=records, night_no=night_no
    )
    if yaku:
        lines.append(yaku)
    try:
        shiad_t = int(bz["shiad_target_uid"])
    except (KeyError, TypeError, ValueError):
        shiad_t = None
    if shiad_t is not None:
        lines.append(f"🎭 شیاد: {tag_for_uid(shiad_t)}")
    if not bz.get("det_no_inquiry"):
        try:
            det_t = int(bz["detective_check"])
        except (KeyError, TypeError, ValueError):
            det_t = None
        if det_t is not None:
            from bot.bazpors_detective_inquiry import (
                load_detective_inquiry_label_from_snapshot,
            )

            res = load_detective_inquiry_label_from_snapshot(bz)
            if res is not None:
                lines.append(f"🕵️ استعلام کارآگاه: {tag_for_uid(det_t)} — {res}")
    u1, u2 = bz.get("interrog_first_uid"), bz.get("interrog_second_uid")
    if bz.get("interrog_night_finished") and u1 is not None and u2 is not None:
        try:
            lines.append(
                "⚖️ بازپرس: "
                f"{tag_for_uid(int(u1))} و {tag_for_uid(int(u2))}"
            )
        except (TypeError, ValueError):
            pass
    try:
        sn_t = int(bz["sniper_night_target_uid"])
    except (KeyError, TypeError, ValueError):
        sn_t = None
    if sn_t is not None:
        lines.append(f"🎯 تک‌تیرانداز: {tag_for_uid(sn_t)}")
    return lines


def _night_lines_from_report_html(report_html: str) -> list[str]:
    """خطوط خلاصهٔ اقدامات شب — فقط بلوک «گزارش کامل شب گذشته»."""
    if not report_html.strip():
        return []
    out: list[str] = []
    in_full_report = False
    for raw in report_html.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "گزارش کامل شب گذشته" in line:
            in_full_report = True
            continue
        if not in_full_report:
            continue
        if "════════" in line:
            continue
        out.append(line.replace("میز ", "صندلی "))
    return out


def _timeline_infer_chaos_host_day(records: list[dict[str, object]]) -> int:
    """روز فاز آشوب از لاگ no_host.day_started_after_night یا game.ended."""
    for rec in records:
        if str(rec.get("event") or "") != "no_host.day_started_after_night":
            continue
        if not rec.get("ki_as_today"):
            continue
        try:
            day = int(rec.get("host_day") or 0)
        except (TypeError, ValueError):
            continue
        if day > 0:
            return day
    for rec in records:
        if str(rec.get("event") or "") != "chaos_handshake.resolved":
            continue
        try:
            day = int(rec.get("host_day") or 0)
        except (TypeError, ValueError):
            continue
        if day > 0:
            return day
    for rec in reversed(records):
        if str(rec.get("event") or "") != "game.ended":
            continue
        bz = rec.get("bazpors")
        if not isinstance(bz, dict):
            continue
        if str(bz.get("narrator_step") or "") != "chaos_day_handshake":
            continue
        try:
            return int(bz.get("host_day") or 0)
        except (TypeError, ValueError):
            continue
    return 0


def _timeline_short_name_from_tag(tag: str) -> str:
    """نام کوتاه برای تایم‌لاین — بخش قبل از خط تیره در تگ صندلی."""
    if "-" in tag:
        return tag.split("-", 1)[0].strip()
    return tag.strip()


def _timeline_chaos_compact_lines(
    rec: dict[str, object], tag_for_uid
) -> list[str]:
    """خلاصهٔ فاز آشوب در گزارش پایان بازی (بدون جزئیات هر انتخاب)."""
    lines: list[str] = []
    winner = str(rec.get("winner") or "")
    pair = rec.get("pair")
    pair_txt = ""
    if isinstance(pair, (list, tuple)) and len(pair) == 2:
        try:
            a, b = int(pair[0]), int(pair[1])
            na = html.escape(_timeline_short_name_from_tag(tag_for_uid(a)))
            nb = html.escape(_timeline_short_name_from_tag(tag_for_uid(b)))
            pair_txt = f"{na} ↔ {nb}"
        except (TypeError, ValueError):
            pair_txt = ""
    if pair_txt:
        lines.append(f"دست نهایی: {pair_txt}")
    elif winner == "no_valid_handshake":
        lines.append("دست نهایی: بدون جفت متقابل")
    if winner == "mafia":
        lines.append("برنده: مافیا 🖤")
    elif winner == "citizens":
        lines.append("برنده: شهروند 🤍")
    elif winner == "no_valid_handshake":
        lines.append("برنده: نامشخص")
    return lines


def _mason_day_ability_elim_keys(
    records: list[dict[str, object]],
) -> set[tuple[int, int]]:
    """(روز، uid) — حذف‌شدگان آپاچی/کابوی/تفنگ روز؛ بدون خط رأی."""
    out: set[tuple[int, int]] = set()
    for rec in records:
        event = str(rec.get("event") or "")
        try:
            day_no = int(rec.get("host_day") or 1)
        except (TypeError, ValueError):
            day_no = 1
        if event == "no_host.mason_apache_day":
            target_uid = rec.get("target_uid")
            if target_uid is not None:
                try:
                    out.add((day_no, int(target_uid)))
                except (TypeError, ValueError):
                    pass
            apache_uid = rec.get("apache_uid")
            if apache_uid is not None:
                try:
                    out.add((day_no, int(apache_uid)))
                except (TypeError, ValueError):
                    pass
        elif event == "no_host.mason_cowboy_day":
            target_uid = rec.get("target_uid")
            if target_uid is not None:
                try:
                    out.add((day_no, int(target_uid)))
                except (TypeError, ValueError):
                    pass
            cowboy_uid = rec.get("cowboy_uid")
            if cowboy_uid is not None:
                try:
                    out.add((day_no, int(cowboy_uid)))
                except (TypeError, ValueError):
                    pass
        elif event == "no_host.mason_day_gun_shot":
            target_uid = rec.get("target_uid")
            if target_uid is not None:
                try:
                    out.add((day_no, int(target_uid)))
                except (TypeError, ValueError):
                    pass
    return out


def _build_bazpors_timeline_html(snap: dict[str, object]) -> str:
    scenario = str(snap.get("scenario_name") or "")
    if scenario not in ("bazpors", "bazpors_salamat_test", "mozakere", "masoon"):
        return ""
    rows_raw = snap.get("rows")
    rows: list[dict[str, object]] = rows_raw if isinstance(rows_raw, list) else []
    uid_to_tag: dict[int, str] = {}
    for row in rows:
        try:
            uid = int(row["user_id"])
        except (KeyError, ValueError, TypeError):
            continue
        uid_to_tag[uid] = html.escape(str(row.get("tag") or "بازیکن نامشخص"))

    def tag_for_uid(uid: int | None) -> str:
        if uid is None:
            return "بازیکن نامشخص"
        raw = uid_to_tag.get(uid, f"بازیکن {uid}")
        return raw.replace("میز ", "صندلی ")

    day_events: dict[int, list[str]] = {}
    night_events: dict[int, list[str]] = {}
    logged_day_elims: set[tuple[int, int, str]] = set()

    def append_day_event(day_no: int, line: str) -> None:
        if day_no <= 0:
            day_no = 1
        bucket = day_events.setdefault(day_no, [])
        if line not in bucket:
            bucket.append(line)

    def append_day_elim(
        day_no: int, uid: int, line: str, *, kind: str
    ) -> None:
        if scenario == "masoon" and (day_no, uid) in mason_day_elims:
            return
        key = (day_no, uid, kind)
        if key in logged_day_elims:
            return
        logged_day_elims.add(key)
        append_day_event(day_no, line)

    def append_night_event(night_no: int, line: str) -> None:
        if night_no <= 0:
            night_no = 1
        bucket = night_events.setdefault(night_no, [])
        if line not in bucket:
            bucket.append(line)

    records = _load_audit_records_for_recap(snap)
    mason_day_elims = (
        _mason_day_ability_elim_keys(records) if scenario == "masoon" else set()
    )
    chaos_day = _timeline_infer_chaos_host_day(records)
    chaos_day_compact: dict[int, list[str]] = {}

    def _timeline_winner_line(winner: str) -> str:
        if winner == "mafia":
            return "🏁 پایان بازی: <b>مافیا</b> برنده شد."
        if winner == "citizen":
            return "🏁 پایان بازی: <b>شهروند</b> برنده شد."
        if winner == "aborted":
            return "⛔ بازی بدون نتیجهٔ رسمی متوقف شد."
        return "🏁 پایان بازی ثبت شد."

    elim_day_by_uid: dict[int, int] = {}
    for rec in records:
        if rec.get("event") != "player.eliminated":
            continue
        bz = rec.get("bazpors")
        if not isinstance(bz, dict):
            continue
        step = str(bz.get("narrator_step") or "")
        if str(rec.get("source") or "") == "night_resolve" or step == "night_actions":
            continue
        try:
            elim_day_by_uid[int(rec["uid"])] = _timeline_day_for_elimination(bz)
        except (KeyError, ValueError, TypeError):
            continue

    for rec in records:
        event = str(rec.get("event") or "")
        if event == "no_host.day_started_after_night":
            continue
        if event == "no_host.mozakere_negotiation_committed":
            try:
                night_no = int(rec.get("night_count") or 0)
            except (TypeError, ValueError):
                night_no = 0
            target_uid = rec.get("target_uid")
            if night_no <= 0 or target_uid is None:
                continue
            try:
                target_i = int(target_uid)
            except (TypeError, ValueError):
                continue
            success = rec.get("success")
            target_name = tag_for_uid(target_i)
            if success is True:
                line = f"🤝 مذاکره موفق با ({target_name})"
            elif success is False:
                line = f"🤝 مذاکره ناموفق با ({target_name})"
            else:
                line = f"🤝 مذاکره با ({target_name})"
            append_night_event(night_no, line)
            continue
        if event == "no_host.journalist_pick_confirmed":
            try:
                night_no = int(rec.get("night_count") or 0)
            except (TypeError, ValueError):
                night_no = 0
            target_uid = rec.get("target_uid")
            if night_no <= 0 or target_uid is None:
                continue
            try:
                target_i = int(target_uid)
            except (TypeError, ValueError):
                continue
            positive = rec.get("journalist_positive")
            if positive is None:
                positive = rec.get("is_positive")
            label = "مثبت" if positive else "منفی"
            append_night_event(
                night_no,
                f"📰 استعلام خبرنگار: {tag_for_uid(target_i)} — {label}",
            )
            continue
        if event == "no_host.mason_apache_day":
            try:
                day_no = int(rec.get("host_day") or 1)
            except (TypeError, ValueError):
                day_no = 1
            target_uid = rec.get("target_uid")
            if target_uid is None:
                continue
            try:
                target_i = int(target_uid)
            except (TypeError, ValueError):
                continue
            append_day_event(day_no, f"🏹 آپاچی: {tag_for_uid(target_i)}")
            continue
        if event == "no_host.mason_cowboy_day":
            try:
                day_no = int(rec.get("host_day") or 1)
            except (TypeError, ValueError):
                day_no = 1
            target_uid = rec.get("target_uid")
            if target_uid is None:
                continue
            try:
                target_i = int(target_uid)
            except (TypeError, ValueError):
                continue
            append_day_event(day_no, f"🤠 کابوی: {tag_for_uid(target_i)}")
            continue
        if event == "no_host.mason_day_gun_shot":
            try:
                day_no = int(rec.get("host_day") or 1)
            except (TypeError, ValueError):
                day_no = 1
            target_uid = rec.get("target_uid")
            if target_uid is None:
                continue
            try:
                target_i = int(target_uid)
            except (TypeError, ValueError):
                continue
            if rec.get("sabotaged"):
                append_day_event(
                    day_no,
                    f"🔫 شلیک با تفنگ (خرابکاری): {tag_for_uid(target_i)}",
                )
            else:
                append_day_event(day_no, f"🔫 شلیک با تفنگ: {tag_for_uid(target_i)}")
            continue
        if event.startswith("chaos_handshake.") and chaos_day > 0:
            if event == "chaos_handshake.resolved":
                compact = _timeline_chaos_compact_lines(rec, tag_for_uid)
                if compact:
                    chaos_day_compact[chaos_day] = compact
                    day_events.pop(chaos_day, None)
            continue
        if event == "no_host.day1_defense_elim_confirmed":
            try:
                uid = int(rec["eliminated_uid"])
            except (KeyError, ValueError, TypeError):
                continue
            if rec.get("host_day") is not None:
                try:
                    day_no = int(rec["host_day"])
                except (ValueError, TypeError):
                    day_no = elim_day_by_uid.get(uid, 1)
            else:
                day_no = elim_day_by_uid.get(uid, 1)
            who = tag_for_uid(uid)
            append_day_elim(
                day_no,
                uid,
                f"{who} به اتفاق آرا از بازی خارج شد.",
                kind="day_vote",
            )
            continue
        if event == "player.eliminated":
            try:
                uid = int(rec["uid"])
            except (KeyError, ValueError, TypeError):
                continue
            bz = rec.get("bazpors")
            if not isinstance(bz, dict):
                continue
            step = str(bz.get("narrator_step") or "")
            source = str(rec.get("source") or "")
            who = tag_for_uid(uid)
            if source == "night_resolve" or step == "night_actions":
                continue
            day_no = _timeline_day_for_elimination(bz)
            if step in (
                "confirm_day_elim",
                "day_discuss",
            ) or (not step and int(bz.get("night_count") or 0) == 0):
                append_day_elim(
                    day_no,
                    uid,
                    f"{who} به اتفاق آرا از بازی خارج شد.",
                    kind="day_vote",
                )
            elif step in (
                "confirm_interrog_vote_elim",
                "no_host_interrog_day",
            ):
                append_day_elim(
                    day_no,
                    uid,
                    f"{who} به اتفاق آرا در رای بازپرسی از بازی خارج شد.",
                    kind="interrog",
                )
            elif not step:
                # no_host: حذف رأی روز در no_host.day1_defense_elim_confirmed ثبت می‌شود
                continue
            companion_note = rec.get("companion_note")
            if isinstance(companion_note, str) and companion_note.strip():
                note_plain = re.sub(r"<[^>]+>", "", companion_note).strip()
                if note_plain:
                    append_day_event(day_no, note_plain)
            continue
        if event == "night.resolved":
            bz = rec.get("bazpors")
            if isinstance(bz, dict):
                try:
                    night_no = int(bz.get("night_count") or 0)
                except (ValueError, TypeError):
                    night_no = 0
            else:
                night_no = 0
            if night_no <= 0:
                night_no = len(night_events) + 1
            report_html = str(rec.get("night_report_html") or "")
            lines = _night_lines_from_report_html(report_html)
            if scenario == "masoon":
                from bot.mason_final_outcome import (
                    append_mason_outcome_to_timeline_lines,
                )

                outcome = rec.get("mason_final_outcome")
                if isinstance(outcome, dict):
                    lines = append_mason_outcome_to_timeline_lines(
                        lines, outcome, tag_for_uid
                    )
            if lines:
                night_events[night_no] = lines
            continue
        if event == "game.ended":
            bz_end = rec.get("bazpors")
            if not isinstance(bz_end, dict):
                continue
            try:
                end_night = int(bz_end.get("night_count") or 0)
            except (TypeError, ValueError):
                end_night = 0
            if end_night > 0 and end_night not in night_events:
                raw_lines = rec.get("night_timeline_lines")
                if isinstance(raw_lines, list) and raw_lines:
                    end_lines = [str(x) for x in raw_lines if str(x).strip()]
                else:
                    end_lines = _timeline_night_lines_from_bazpors(
                        bz_end,
                        tag_for_uid,
                        records=records,
                        night_no=end_night,
                    )
                if end_lines:
                    night_events[end_night] = end_lines
            try:
                end_day = int(bz_end.get("host_day") or 0)
            except (TypeError, ValueError):
                end_day = 0
            if end_day > 0:
                winner = str(rec.get("winner") or "")
                if winner:
                    append_day_event(end_day, _timeline_winner_line(winner))
            continue
        if event != "narrator.callback":
            continue
        if rec.get("error"):
            continue
        act = str(rec.get("act") or "")
        bz_cb = rec.get("bazpors")
        if isinstance(bz_cb, dict) and act == "nx_no":
            after = rec.get("after")
            if isinstance(after, dict) and str(after.get("step") or "") == "day_discuss":
                if bz_cb.get("ki_as_today"):
                    try:
                        chaos_day = int(bz_cb.get("host_day") or 0)
                    except (TypeError, ValueError):
                        chaos_day = 0
                    if chaos_day > 0:
                        append_day_event(
                            chaos_day,
                            f"🔔 <b>{CHAOS_PHASE_LABEL}</b> برگزار شد — "
                            "بدون رأی‌گیری روز؛ نتیجهٔ دست در پایان روز ثبت شد.",
                        )
        if act in ("ki_as_mafia_win", "ki_as_citizen_win"):
            if isinstance(bz_cb, dict):
                try:
                    chaos_day = int(bz_cb.get("host_day") or 0)
                except (TypeError, ValueError):
                    chaos_day = 0
                if chaos_day > 0:
                    append_day_event(
                        chaos_day,
                        f"🔔 <b>{CHAOS_PHASE_LABEL}</b> برگزار شد — "
                        "بدون رأی‌گیری روز؛ نتیجهٔ دست در پایان روز ثبت شد.",
                    )
                    append_day_event(
                        chaos_day,
                        _timeline_winner_line(
                            "mafia" if act == "ki_as_mafia_win" else "citizen"
                        ),
                    )
            continue
        if act not in ("confirm_day_yes", "confirm_intr_vote_yes"):
            continue
        bz = rec.get("bazpors")
        if not isinstance(bz, dict):
            continue
        day_no = _timeline_day_for_elimination(bz)
        before = rec.get("before")
        pending_uid: int | None = None
        if isinstance(before, dict):
            try:
                pending_uid = int(before.get("pending_uid"))
            except (ValueError, TypeError):
                pending_uid = None
        if pending_uid is None:
            continue
        who = tag_for_uid(pending_uid)
        if act == "confirm_day_yes":
            append_day_elim(
                day_no,
                pending_uid,
                f"{who} به اتفاق آرا از بازی خارج شد.",
                kind="day_vote",
            )
        else:
            append_day_elim(
                day_no,
                pending_uid,
                f"{who} به اتفاق آرا در رای بازپرسی از بازی خارج شد.",
                kind="interrog",
            )

    if not day_events and not night_events and not chaos_day_compact:
        return ""
    end_game_day = 0
    for rec in records:
        if str(rec.get("event") or "") != "game.ended":
            continue
        bz_end = rec.get("bazpors")
        if not isinstance(bz_end, dict):
            continue
        try:
            end_game_day = max(end_game_day, int(bz_end.get("host_day") or 0))
        except (TypeError, ValueError):
            pass
    max_day = max(
        max(day_events.keys(), default=0),
        max(night_events.keys(), default=0),
        max(chaos_day_compact.keys(), default=0),
        chaos_day,
        end_game_day,
    )
    if max_day <= 0:
        return ""
    lines: list[str] = ["🧭 <b>اتفاقات در طول بازی</b>", ""]
    _no_events = "بدون اتفاق"
    for day in range(1, max_day + 1):
        compact = chaos_day_compact.get(day)
        day_ev = day_events.get(day)
        if compact is not None:
            lines.append(f"☀️ <b>روز {_fa_digits(day)}</b> — فاز آشوب")
            lines.extend(compact)
        elif day_ev:
            lines.append(f"☀️ <b>روز {_fa_digits(day)}</b>")
            lines.extend(day_ev)
        else:
            lines.append(f"☀️ <b>روز {_fa_digits(day)}</b> - {_no_events}")
        night_ev = night_events.get(day)
        if night_ev:
            lines.append(f"🌙 <b>شب {_fa_digits(day)}</b>")
            lines.extend(night_ev)
        else:
            lines.append(f"🌙 <b>شب {_fa_digits(day)}</b> - {_no_events}")
        if day != max_day:
            lines.append("")
    return "\n".join(lines)


def build_session_recap_html(session_id: int, snap: dict[str, object]) -> str:
    """پیام جمع‌بندی پایان دست: گرداننده + امتیاز + برنده + فهرست نقش‌ها + مدال‌ها."""
    winner = str(snap["winner"])
    scenario_key = str(snap["scenario_name"])
    room_code = str(snap["room_code"])
    host_id = int(snap["host_id"])
    host_fn = str(snap.get("host_full_name") or "")
    rows_raw = snap.get("rows")
    rows: list[dict[str, object]] = rows_raw if isinstance(rows_raw, list) else []

    sc = html.escape(manager.scenario_display_name(scenario_key))
    host_name = html.escape(host_fn or "گرداننده")
    avg, n_ratings = db.narrator_aggregate_for_host(host_id)
    n_sessions = db.host_game_sessions_count(host_id)

    parts: list[str] = []
    host_mode = snap.get("bazpors_host_mode")
    max_players = snap.get("max_players")
    if (
        (
            scenario_key in ("bazpors", "bazpors_salamat_test")
            or scenario_key in ("mozakere", "masoon")
        )
        and host_mode in ("no_host", "semi_auto")
        and isinstance(max_players, int)
    ):
        parts.extend(
            [
                build_game_final_report_header_html(
                    room_code, scenario_key, max_players
                ),
                "",
            ]
        )

    header = (
        f"🎭 <b>سناریو:</b> {sc}\n"
        f"🎲 <b>اتاق:</b> <code>{html.escape(room_code)}</code>\n"
        f"🎙 <b>گرداننده:</b> {host_name}\n"
        f"{_format_recap_rating_line(avg, n_ratings)}\n"
        f"📚 <b>گردانندگی‌ها:</b> {_fa_digits(n_sessions)}"
    )

    if winner == "mafia":
        winner_html = "🔴 <b>برندهٔ بازی:</b> تیم مافیا! تبریک 🎉"
    else:
        winner_html = "🟢 <b>برندهٔ بازی:</b> تیم شهروند! تبریک 🎉"

    medals_map = db.get_session_medals(session_id)
    scenario_name = str(snap.get("scenario_name") or "bazpors")
    roster_block = "\n".join(
        _build_session_recap_roster_lines(
            rows,
            medal_by_uid=_recap_medal_emoji_by_uid(medals_map),
            scenario_name=scenario_name,
        )
    )

    nl = "\n"
    parts.extend(
        [
            header,
            "",
            "────────────",
            "",
            winner_html,
            "",
            "📋 <b>بازیکنان و نقش‌ها</b>",
            roster_block,
        ]
    )
    timeline_html = _build_bazpors_timeline_html(snap)
    if timeline_html:
        parts.extend(["", "────────────", "", timeline_html])
    return nl.join(parts)


def _build_bazpors_game_end_winner_html(game: Game, winner: str) -> str:
    if winner == "mafia":
        if game.bazpors_mafia_win_via_chaos:
            balance = "برد مافیا در فاز آشوب"
        else:
            _, mafia_n, citizen_n = _alive_faction_counts(game, manager)
            if mafia_n == citizen_n:
                balance = (
                    f"تعداد مافیا و شهروند <b>برابر شد</b> "
                    f"({_seat_fa(mafia_n)} مافیا، {_seat_fa(citizen_n)} شهروند)."
                )
            elif mafia_n > citizen_n:
                balance = (
                    f"تعداد مافیا ({_seat_fa(mafia_n)}) "
                    f"<b>بیشتر از</b> شهروند ({_seat_fa(citizen_n)}) است."
                )
            else:
                balance = "برد مافیا در فاز آشوب"
        return (
            "🏁 <b>پایان بازی — برد مافیا</b>\n\n"
            f"{balance}\n\n"
            "طبق قانون این سناریو، <b>تیم مافیا برنده است.</b>"
        )
    _, _mafia_n, citizen_n = _alive_faction_counts(game, manager)
    return (
        "🏁 <b>پایان بازی — برد شهروند</b>\n\n"
        "مافیا (و اعضای تیم مافیا) دیگر در بازی <b>نیستند</b>.\n"
        f"({_seat_fa(citizen_n)} شهروند زنده در صندلی است.)\n"
        "طبق قانون این سناریو، <b>تیم شهروند برنده است.</b>"
    )


def build_bazpors_game_end_broadcast_html(game: Game, winner: str) -> str:
    """پیام پایان بازی برای بازیکنان — برنده، نقش‌ها، اتفاقات شب و روز."""
    if winner not in ("mafia", "citizen"):
        winner = "citizen"
    snap = build_post_session_recap_snapshot(game, winner)
    rows_raw = snap.get("rows")
    rows: list[dict[str, object]] = rows_raw if isinstance(rows_raw, list) else []
    scenario_name = str(snap.get("scenario_name") or game.scenario_name or "bazpors")
    roster_block = "\n".join(
        _build_session_recap_roster_lines(rows, scenario_name=scenario_name)
    )
    timeline_html = _build_bazpors_timeline_html(snap)
    parts: list[str] = []
    if _bazpors_auto_host_final_report_header(game):
        parts.extend(
            [
                build_game_final_report_header_html(
                    game.room_code, game.scenario_name, game.max_players
                ),
                "",
            ]
        )
    parts.extend(
        [
            _build_bazpors_game_end_winner_html(game, winner),
            "",
            "────────────",
            "",
            "📋 <b>بازیکنان و نقش‌ها</b>",
            roster_block,
        ]
    )
    if timeline_html:
        parts.extend(["", "────────────", "", timeline_html])
    return "\n".join(parts)



async def finalize_pending_session_recap(bot: Bot, session_id: int) -> bool:
    if db.session_recap_already_broadcasted(session_id):
        return True
    snap = PENDING_SESSION_RECAP.pop(session_id, None)
    if not snap:
        snap = db.get_session_recap_snapshot(session_id)
    if not snap:
        return False
    text = build_session_recap_html(session_id, snap)
    obs = snap.get("observer_user_id")
    observer_uid = int(obs) if isinstance(obs, int) else None
    if not await broadcast_post_session_html(
        bot, session_id, text, observer_user_id=observer_uid
    ):
        PENDING_SESSION_RECAP[session_id] = snap
        return False
    db.mark_session_recap_broadcasted(session_id)
    return True


async def safe_edit_text(message: Message, text: str, **kwargs) -> bool:
    """Avoid crash when Telegram says message is not modified."""
    try:
        await message.edit_text(text, **kwargs)
        return True
    except TelegramBadRequest as err:
        if "message is not modified" in str(err).lower():
            return False
        raise


def host_deal_roles_keyboard(game: Game) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="🎭 پخش نقش‌های تصادفی",
                callback_data=HostPanel(code=game.room_code, act="dr").pack(),
            ),
        ]
    ]
    if game.scenario_name in ("bazpors", "mozakere", "masoon", "russian_mafia"):
        rows.append(
            [
                InlineKeyboardButton(
                    text="انتخاب نقش‌ها توسط بازیکنان",
                    callback_data=HostPanel(code=game.room_code, act="pr").pack(),
                ),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def host_seat_confirm_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تایید می‌کنم",
                    callback_data=HostPanel(code=game.room_code, act="sy").pack(),
                ),
                InlineKeyboardButton(
                    text="🔁 شافل دوباره",
                    callback_data=HostPanel(code=game.room_code, act="sr").pack(),
                ),
            ]
        ]
    )


def _host_shuffle_hides_player_names(game: Game) -> bool:
    if is_russian_mafia_host_helper_room(game):
        return True
    return is_no_host_player_room(game) or is_bazpors_semi_auto_room(game)


def bump_seat_shuffle_count(game: Game) -> int:
    game.bazpors_seat_shuffle_count += 1
    return game.bazpors_seat_shuffle_count


def build_seat_assignment_player_message(game: Game) -> str:
    """پیام پس از تأیید شافل صندلی — یکسان برای همه بازیکنان."""
    pending = game.pending_seat_order
    if not pending:
        return ""
    sc_label = manager.scenario_display_name(game.scenario_name)
    room_no = _fa_digits(int(game.room_code))
    cap = _fa_digits(game.max_players)
    lines = [
        f"🏠 اتاق {room_no} | 🎭 سناریو: {sc_label} | 👥 تعداد: {cap} نفر",
        "",
        "لیست بازیکنها به ترتیب شماره صندلی",
        "",
    ]
    for seat_idx, uid in enumerate(pending, start=1):
        p = game.players.get(uid)
        if p is None:
            continue
        lines.append(
            f"{_fa_digits(seat_idx)}. \u200f{manager.format_player_tag(p)}"
        )
    lines.extend(["", "⏳ منتظر دریافت نقش خود باشید"])
    return "\n".join(lines)


def build_shuffle_confirm_prompt_html(
    game: Game, rows: list[tuple[int, Player]]
) -> str:
    """پیش‌نمایش شافل صندلی — در نیمه‌خودکار/بدون گرداننده نام بازیکن دیده نمی‌شود."""
    if _host_shuffle_hides_player_names(game):
        n = max(1, game.bazpors_seat_shuffle_count)
        return (
            f"🔀 شماره صندلی‌ها <b>{_fa_digits(n)} بار</b> شافل شد.\n\n"
            "آیا مایل به <b>تایید</b> هستید؟"
        )
    lines = [
        f"🪑 صندلی {s}: {html.escape(manager.format_player_tag(p))}"
        for s, p in rows
    ]
    return (
        "🔀 شافل شماره صندلی بازیکن‌ها انجام شد.\n\n"
        + "\n".join(lines)
        + "\n\nآیا مایل به <b>تایید</b> هستید؟"
    )


def semi_auto_lobby_dev_keyboard(game: Game) -> InlineKeyboardMarkup:
    """موقت — فقط هنگام انتظار برای join در بازپرس نیمه‌خودکار."""
    code = game.room_code
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🎲 پر کردن تصادفی بازیکن‌ها",
                    callback_data=SemiAutoDevLobby(code=code, act="fill").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⏳ منتظر بازیکن‌های واقعی می‌مانم",
                    callback_data=SemiAutoDevLobby(code=code, act="wait").pack(),
                ),
            ],
        ]
    )


async def send_host_lobby_full_prompt(bot: Bot, game: Game) -> None:
    ready, _ = manager.lobby_ready_for_deal(game)
    if (
        not ready
        or game.lobby_full_notice_sent
        or game.phase != Phase.LOBBY
        or game.seats_finalized
        or game.roles_dealt
    ):
        return
    game.lobby_full_notice_sent = True
    if _host_shuffle_hides_player_names(game):
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔀 شافل شماره صندلی‌ها",
                        callback_data=HostPanel(
                            code=game.room_code, act="fs"
                        ).pack(),
                    ),
                ]
            ]
        )
        body = (
            f"{LOBBY_FULL_READY_FOR_ROLES_MSG}\n\n"
            "برای شروع، شماره صندلی‌ها را شافل کنید."
        )
    else:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔀 شافل شماره صندلی",
                        callback_data=HostPanel(
                            code=game.room_code, act="fs"
                        ).pack(),
                    ),
                    InlineKeyboardButton(
                        text="🎭 پخش نقش‌ها",
                        callback_data=HostPanel(
                            code=game.room_code, act="fd"
                        ).pack(),
                    ),
                ]
            ]
        )
        body = (
            f"{LOBBY_FULL_READY_FOR_ROLES_MSG}\n\n"
            "گام بعد را انتخاب کنید. برای پخش نقش، ابتدا باید شماره صندلی‌ها را شافل و "
            "<b>تأیید</b> کنید."
        )
    await bot.send_message(
        game.host_id,
        body,
        reply_markup=kb,
        parse_mode="HTML",
    )


async def deliver_seat_assignments(bot: Bot, game: Game) -> list[str]:
    failed: list[str] = []
    pending = game.pending_seat_order
    if not pending:
        return failed
    seat_text = build_seat_assignment_player_message(game)
    if not seat_text:
        return failed
    observer_once = no_host_observer_registered(game)
    obs_id = game.observer_user_id if observer_once else None
    for uid in pending:
        if is_synthetic_player_uid(uid):
            continue
        p = game.players.get(uid)
        if p is None:
            continue
        try:
            if is_russian_mafia_host_helper_room(game):
                ok = await safe_send_message(bot, uid, seat_text)
            elif observer_once:
                ok = (
                    await safe_send_message_return(bot, p.user_id, seat_text)
                ) is not None
            else:
                ok = await send_to_player(bot, game, p.user_id, seat_text)
            if not ok:
                failed.append(manager.format_player_tag(p))
        except Exception:
            failed.append(manager.format_player_tag(p))
    if observer_once and obs_id is not None and not failed:
        await safe_send_message(bot, obs_id, seat_text)
    return failed


async def send_host_secret_role_roster(bot: Bot, game: Game) -> None:
    lines = [
        "🔐 <b>لیست نقش همه بازیکنان</b>\n"
        "<i>فقط شما این پیام را می‌بینید.</i>\n",
        f"🎲 اتاق <code>{html.escape(game.room_code)}</code>\n",
    ]
    for p in _players_sorted_for_display(game):
        r = p.role
        rtxt = scenario_role_label_fa(game, r) if r else "—"
        seat_txt = str(p.seat) if p.seat is not None else "—"
        mark = "🔴" if is_mafia_team(r) else "🟢"
        lines.append(
            f"{seat_txt}. {mark} "
            f"{html.escape(manager.format_player_tag(p))}"
            f" → <b>{html.escape(rtxt)}</b>"
        )
    await bot.send_message(
        game.host_id,
        "\n".join(lines),
        parse_mode="HTML",
    )


def emergency_leave_keyboard_for(game: Game, as_uid: int) -> InlineKeyboardMarkup:
    if game_observer_mirror_active(game):
        return mirrored_emergency_leave_keyboard(game, as_uid)
    return emergency_leave_keyboard(game.room_code)


def emergency_leave_keyboard(room_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ بله، مطمئنم؛ از بازی خارج می‌شوم",
                    callback_data=EmergencyLeaveConfirm(code=room_code).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✖️ انصراف",
                    callback_data=EmergencyLeaveCancel(code=room_code).pack(),
                ),
            ],
        ]
    )


def player_end_approve_keyboard_for(game: Game, as_uid: int) -> InlineKeyboardMarkup:
    if game_observer_mirror_active(game):
        return mirrored_player_end_keyboard(game, as_uid)
    return player_end_approve_keyboard(game.room_code)


def player_end_approve_keyboard(room_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید پایان این دست (بدون گرداننده)",
                    callback_data=PlayerEndApprove(code=room_code).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✖️ انصراف (بدون تأیید)",
                    callback_data=PlayerEndDismiss(code=room_code).pack(),
                ),
            ],
        ]
    )


def player_end_broadcast_confirm_keyboard_for(
    game: Game, as_uid: int
) -> InlineKeyboardMarkup:
    if game_observer_mirror_active(game):
        return mirrored_player_end_broadcast_confirm_keyboard(game, as_uid)
    return player_end_broadcast_confirm_keyboard(game.room_code)


def player_end_broadcast_confirm_keyboard(room_code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ بله، برای همه پیام رأی بفرست",
                    callback_data=PlayerEndBroadcastConfirm(code=room_code, ok=1).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✖️ خیر، منصرف شدم",
                    callback_data=PlayerEndBroadcastConfirm(code=room_code, ok=0).pack(),
                ),
            ],
        ]
    )


def hub_root_keyboard(*, show_amir_mehraban: bool = False) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
            [
                InlineKeyboardButton(
                    text="📋 بازیکنان",
                    callback_data=HubMenu(act="ply").pack(),
                ),
                InlineKeyboardButton(
                    text="📊 وضعیت اتاق",
                    callback_data=HubMenu(act="sts").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🚪 ترک / خروج",
                    callback_data=HubMenu(act="lve").pack(),
                ),
                InlineKeyboardButton(
                    text="🗳 پایان جمعی",
                    callback_data=HubMenu(act="tre").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✏️ نام نمایشی",
                    callback_data=HubMenu(act="mnm").pack(),
                ),
                InlineKeyboardButton(
                    text="⭐ امتیاز من",
                    callback_data=HubMenu(act="scr").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎙 راهنمای گرداننده",
                    callback_data=HubMenu(act="nar").pack(),
                ),
                InlineKeyboardButton(
                    text="❓ راهنمای کامل",
                    callback_data=HubMenu(act="hlp").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="⏱ مهلت‌های گرداننده",
                    callback_data=HubMenu(act="htg").pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎲 ورود با کد (یادآوری)",
                    callback_data=HubMenu(act="jin").pack(),
                ),
            ],
    ]
    if show_amir_mehraban:
        rows.insert(
            -1,
            [
                InlineKeyboardButton(
                    text=f"💬 {amir_mb.FEATURE_TITLE_FA} (بازپرس)",
                    callback_data=HubMenu(act="amr").pack(),
                ),
            ],
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def begin_post_game_session(
    bot: Bot,
    *,
    session_id: int,
    host_id: int,
    players: list[dict[str, object]],
    host_full_name: str = "",
    host_username: str | None = None,
) -> None:
    """بعد از پایان رسمی: دعوت امتیاز ناشناس + شروع اعطای مدال برای گرداننده."""
    await send_rating_invites(
        bot,
        manager,
        session_id=session_id,
        host_id=host_id,
        players=players,
        host_full_name=host_full_name,
        host_username=host_username,
    )
    await prompt_host_next_medal(bot, session_id)


def medal_pick_keyboard(
    session_id: int, slot: str, players: list[dict[str, object]]
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for p in players:
        uid = int(p["id"])
        fn = str(p.get("fn") or "")
        un = p.get("un")
        label = manager.get_user_display_name(uid, fn)
        if un:
            label = f"{label}"
        rows.append(
            [
                InlineKeyboardButton(
                    text=label[:40],
                    callback_data=MedalPick(sid=session_id, slot=slot, pid=uid).pack(),
                ),
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _session_medal_author_id(row: dict[str, object]) -> int:
    """اگر پایان با رأی بازیکنان باشد، مدال‌ها را نمایندهٔ پایان می‌دهد؛ وگرنه گرداننده."""
    mg = row.get("medal_giver_id")
    if mg is None:
        return int(row["host_id"])
    return int(mg)


async def finalize_post_game_room_closure(
    bot: Bot,
    session_id: int,
    *,
    recap_snap: dict[str, object] | None = None,
) -> None:
    """پس از مدال‌ها: آزادسازی نگاشت‌ها و اطلاع بسته شدن اتاق."""
    row = db.get_session(session_id)
    if not row:
        return
    room_code = str(row["room_code"])
    host_id = int(row["host_id"])
    player_ids = db.session_player_ids(session_id)
    snap = recap_snap
    if snap is None:
        snap = db.get_session_recap_snapshot(session_id)
    observer_uid: int | None = None
    if isinstance(snap, dict):
        obs = snap.get("observer_user_id")
        if isinstance(obs, int):
            observer_uid = obs
    manager.force_release_ended_session(
        room_code,
        host_id,
        player_ids,
        observer_user_id=observer_uid,
    )
    room_no = html.escape(room_code)
    host_notice = (
        f"🔒 اتاق <code>{room_no}</code> بسته شد و همه آزاد شدند.\n\n"
        "✅ می‌توانید با <code>/create</code> اتاق جدید بسازید."
    )
    player_notice = (
        f"🔒 اتاق <code>{room_no}</code> بسته شد.\n"
        "این دست به‌طور کامل پایان یافت."
    )
    await safe_send_message(bot, host_id, host_notice, parse_mode="HTML")
    for pid in sorted(player_ids):
        if pid == host_id or is_synthetic_player_uid(pid):
            continue
        await safe_send_message(bot, pid, player_notice, parse_mode="HTML")
    if observer_uid is not None and observer_uid != host_id:
        await safe_send_message(bot, observer_uid, player_notice, parse_mode="HTML")


async def prompt_host_next_medal(bot: Bot, session_id: int) -> None:
    row = db.get_session(session_id)
    if not row:
        return
    author_id = _session_medal_author_id(row)
    slot = db.next_medal_slot(session_id)
    if slot is None:
        snap_for_closure = PENDING_SESSION_RECAP.get(
            session_id
        ) or db.get_session_recap_snapshot(session_id)
        recap_sent = await finalize_pending_session_recap(bot, session_id)
        await finalize_post_game_room_closure(
            bot, session_id, recap_snap=snap_for_closure
        )
        try:
            if recap_sent:
                await bot.send_message(
                    author_id,
                    "✅ همهٔ مدال‌ها برای این دست ثبت شدند.\n\n"
                    "📣 پیام جمع‌بندی بازی (نقش‌ها و مدال‌ها) برای همهٔ بازیکنان و شما فرستاده شد.",
                )
            else:
                await bot.send_message(
                    author_id,
                    "✅ همهٔ مدال‌ها برای این دست ثبت شدند.\n\n"
                    "⚠️ پیام جمع‌بندی بازی (نقش‌ها و مدال‌ها) ارسال نشد؛ "
                    "اگر باز هم نرسید، به پشتیبانی بگویید.",
                )
        except Exception:
            pass
        return
    players = db.session_players_available_for_medal(session_id)
    label = db.MEDAL_LABEL_FA.get(slot, slot)
    try:
        body = (
            f"🏆 <b>اعطای مدال به بازیکنان این دست</b>\n\n"
            f"یک نفر را برای <b>{html.escape(label)}</b> انتخاب کنید:"
        )
        if not players:
            body += (
                "\n\n<i>همهٔ بازیکنان این دست قبلاً مدال گرفته‌اند؛ "
                "برای ادامه از پیام بعدی مدال بعدی استفاده کنید.</i>"
            )
        await bot.send_message(
            author_id,
            body,
            parse_mode="HTML",
            reply_markup=(
                medal_pick_keyboard(session_id, slot, players) if players else None
            ),
        )
    except Exception:
        pass


async def broadcast_player_end_vote_started(bot: Bot, game: Game) -> None:
    init_id = game.player_end_initiator_id
    if init_id is None or init_id not in game.players:
        return
    init_p = game.players[init_id]
    init_tag = manager.format_player_tag(init_p)
    body = (
        f"📛 <b>{html.escape(init_tag)}</b> درخواست "
        "<b>پایان بازی بدون گرداننده</b> داد.\n\n"
        f"تا <b>{_fa_digits(game.player_end_approval_minutes)}</b> دقیقه همهٔ بازیکنانی که نقش دارند "
        "باید در ربات دکمهٔ تأیید را بزنند.\n"
        "گرداننده در این رأی شرکت نمی‌کند و حق وتو ندارد."
    )
    for uid in game.players:
        if is_synthetic_player_uid(uid):
            continue
        kb = player_end_approve_keyboard_for(game, uid)
        try:
            ui_key = mirror_ui_claim_key(game.room_code, "player_end_vote", uid)
            await send_to_player(
                bot,
                game,
                uid,
                body,
                parse_mode="HTML",
                reply_markup=kb,
                mirror_reply_markup=kb,
                mirror_ui_key=ui_key,
            )
        except Exception:
            pass
    try:
        await bot.send_message(
            chat_id=game.host_id,
            text=body + "\n\n<i>شما فقط مطلع می‌شوید؛ نیازی به تأیید ندارید.</i>",
            parse_mode="HTML",
        )
    except Exception:
        pass



def build_host_narrator_panel_html(
    *,
    post_deal_header: bool = False,
    after_roles_hint: bool = False,
    room_code: str | None = None,
    scenario_name: str | None = None,
) -> str:
    """متن پنل گرداننده (مثل پیام راهنما)؛ دستورها برای لینک خودکار تلگرام."""
    parts: list[str] = []
    if post_deal_header:
        parts.extend(
            [
                "✅ <b>نقش‌ها برای بازیکنان در پیام خصوصی فرستاده شد.</b>",
                "🔐 لیست کامل نقش‌ها در <b>پیام قبلی</b> است <i>(فقط شما)</i>.",
                "",
            ]
        )
    if room_code is not None:
        sc = (
            html.escape(manager.scenario_display_name(scenario_name or "namayande"))
            if scenario_name is not None
            else None
        )
        line = f"🎲 اتاق <code>{html.escape(room_code)}</code>"
        if sc is not None:
            line += f" · <b>{sc}</b>"
        parts.append(line)
        parts.append("")
        if (scenario_name or "").strip().lower() == "bazpors":
            parts.append(
                f"💬 <b>{amir_mb.FEATURE_TITLE_FA}</b> — بازیکنان با <code>/rolehelp</code> "
                "توضیح نقش می‌گیرند؛ شما از /menu همان پنل راهنمای نقش‌ها را دارید."
            )
            parts.append("")
        elif (scenario_name or "").strip().lower() == "bazpors_salamat_test":
            parts.append(
                "🧪 <b>اتاق تست شبکه سلامت:</b> متن قوانین و چک‌لیست گردانندگی را از دکمه‌های "
                "پیام «پنل نیمه‌خودکار» بگیرید. بازیکنان صندلی ساختگی‌اند و به آن‌ها پیام خصوصی نمی‌رود."
            )
            parts.append("")
    parts.extend(
        [
            "🎙 <b>پنل گرداننده</b>",
            "",
            "وقتی لابی پر شد، شافل صندلی و پخش نقش از <b>دکمه‌های پیام ربات</b> است.",
            "✍️ روایت همیشه دستی است.",
            "",
            "🆕 /create · 📎 /menu (شامل ⏱ مهلت‌های گرداننده) · 👋 /leave · 📊 /status · ⛔ /endgame · 🗳 /request_end",
        ]
    )
    if post_deal_header or after_roles_hint:
        parts.extend(
            [
                "",
                "⛔ برای ثبت پایان رسمی و تعیین برنده، <b>ابتدا /endgame</b> را بزنید؛ "
                "بعد دکمهٔ انتخاب تیم برنده برای شما باز می‌شود.",
            ]
        )
    return "\n".join(parts)


async def send_host_post_deal_panel(bot: Bot, game: Game) -> None:
    """بلافاصله پس از پخش موفق نقش‌ها: پنل متنی گرداننده (بدون دکمهٔ برد/باخت)."""
    text = build_host_narrator_panel_html(
        post_deal_header=True,
        room_code=game.room_code,
        scenario_name=game.scenario_name,
    )
    await bot.send_message(
        game.host_id,
        text,
        parse_mode="HTML",
    )


async def notify_initiator_winner_keyboard(
    bot: Bot, room_code: str, picker_id: int
) -> None:
    g2 = manager.get_game(room_code)
    if not g2:
        return
    picker_text = (
        "همهٔ بازیکنان پایان این دست را تأیید کردند.\n"
        "لطفاً برنده را انتخاب کنید (همان گزینه‌های گرداننده):"
    )
    picker_kb = endgame_winner_keyboard_for(g2, picker_id)
    ui_key = mirror_ui_claim_key(g2.room_code, "endgame_pick", picker_id)
    await send_to_player(
        bot,
        g2,
        picker_id,
        picker_text,
        reply_markup=picker_kb,
        mirror_reply_markup=picker_kb,
        mirror_ui_key=ui_key,
    )
    await broadcast_game(
        bot,
        g2,
        "✅ همه بازیکنان پایان دست را تأیید کردند؛ نتیجه را همان کسی که درخواست داده ثبت می‌کند.",
    )


async def notify_players_after_roles_dealt(bot: Bot, game: Game) -> None:
    """بعد از پخش موفق نقش: میز+نام بدون نقش + لینک‌های سریع (بدون کیبورد پایین صفحه)."""
    if not players_receive_post_deal_hub_message(game):
        return
    if game.phase != Phase.MANUAL or not game.players:
        return
    me = await bot.get_me()
    bot_username = (me.username or "").strip()
    sc = html.escape(manager.scenario_display_name(game.scenario_name))
    body_lines: list[str] = [
        "✅ <b>نقش شما در پیام قبلی فرستاده شد.</b>",
        "",
        f"🎭 اتاق <b>{html.escape(game.room_code)}</b> · <b>{sc}</b>",
        "",
        "<b>بازیکن‌ها به ترتیب شماره صندلی:</b>",
    ]
    for idx, p in enumerate(_players_sorted_for_display(game), start=1):
        seat_no = p.seat if p.seat is not None else idx
        name = html.escape(manager.get_user_display_name(p.user_id, p.full_name))
        body_lines.append(f"\u200f{_fa_digits(seat_no)}. {name}")
    body_lines.append("")
    body_lines.append(f"🎙 <b>گرداننده</b>: {html.escape(_host_tag_plain(game))}")
    body_lines.append(_host_narrator_rating_line_html(game.host_id))
    if bot_username:
        body_lines.append("")
        body_lines.append(build_start_action_links_html(bot_username))
        body_lines.append("")
        body_lines.append(
            "<i>دستورها را خودتان تایپ کنید یا از /menu استفاده کنید.</i>"
        )
    else:
        body_lines.append(
            "<b>دستورها:</b> /players · /status · /menu · /leave · /request_end · /myname · /help"
        )
    text = "\n".join(body_lines)
    uids = [
        uid for uid in game.players if not is_synthetic_player_uid(uid)
    ]

    async def _send_hub(uid: int) -> None:
        try:
            await bot.send_message(
                chat_id=uid,
                text=text,
                parse_mode="HTML",
                reply_markup=ReplyKeyboardRemove(),
            )
        except Exception:
            logger.debug(
                "notify_players_after_roles_dealt failed uid=%s room=%s",
                uid,
                game.room_code,
                exc_info=True,
            )

    await gather_bounded(uids, _send_hub)


async def deal_roles_full_pipeline(bot: Bot, game: Game) -> str | None:
    lock = _ROLE_DEAL_LOCKS.setdefault(game.room_code, asyncio.Lock())
    if lock.locked():
        return ROLE_DEAL_IN_PROGRESS_MSG
    async with lock:
        if game.roles_dealt:
            return "نقش‌ها قبلاً پخش شده‌اند."
        try:
            manager.assert_can_deal_roles(game)
        except ValueError as err:
            return str(err)
        try:
            manager.assign_roles(game)
        except ValueError as err:
            return str(err)
        failed: list[str] = []
        for player in game.players.values():
            role = player.role
            if role is None:
                failed.append(manager.format_player_tag(player))
                continue
            if is_synthetic_player_uid(player.user_id):
                continue
            try:
                sent = await send_private_role(bot, player.user_id, role, game=game)
            except Exception:
                failed.append(manager.format_player_tag(player))
                continue
            if not sent:
                failed.append(manager.format_player_tag(player))

        if failed:
            manager.end_game(game.room_code)
            return (
                "⚠️ ارسال نقش برای بعضی بازیکنان نشد:\n"
                + ", ".join(failed)
                + "\nهمه باید یک‌بار /start بزنند. بازی لغو شد."
            )

        await finalize_roles_deal_pipeline(bot, game)
        return None


async def finalize_roles_deal_pipeline(bot: Bot, game: Game) -> None:
    """مرحلهٔ مشترک پس از نهایی‌شدن نقش‌ها (تصادفی یا انتخابی)."""
    manager.finalize_deal_roles_phase(game)
    if host_receives_moderator_deal_messages(game):
        await send_host_secret_role_roster(bot, game)
    if narrator_assist_after_roles_dealt(game):
        await begin_narrator_assist_after_roles_dealt(bot, game, manager)
    elif host_receives_moderator_deal_messages(game):
        await send_host_post_deal_panel(bot, game)
    await notify_players_after_roles_dealt(bot, game)
    if is_no_host_player_room(game):
        await send_no_host_observer_prompt(bot, game)
    elif game.scenario_name == "russian_mafia":
        from bot.russian_mafia_flow import begin_after_roles

        await begin_after_roles(bot, game)


async def _do_join(msg: Message, bot: Bot, code: str) -> JoinFlowResult:
    if not msg.from_user:
        return JoinFlowResult.ABORT
    key = manager.normalize_join_code(code)
    if key is None:
        await msg.answer(
            "کد نامعتبر است. یک یا دو رقم بفرستید "
            "(مثلاً ۰۷، 7، ٠٧). دوباره امتحان کنید."
        )
        return JoinFlowResult.RETRY_BAD_CODE
    game = manager.get_game(key)
    if not game:
        await msg.answer("این کد اتاق فعالی نیست.\nدوباره از گرداننده کد دو رقمی بگیرید.")
        return JoinFlowResult.RETRY_BAD_CODE
    if msg.from_user.id == game.host_id:
        await msg.answer(
            "شما گرداننده این اتاق هستید؛ خودتان با کد وارد نمی‌شوید. بازیکنان /join بزنند."
        )
        return JoinFlowResult.ABORT
    hosting = manager.get_room_for_host(msg.from_user.id)
    if hosting:
        await msg.answer(
            "شما یک اتاق دیگر را می‌گیرید. اول آن را با /leave (لغو گرداننده) تمام کنید."
        )
        return JoinFlowResult.ABORT
    other = manager.get_room_for_user(msg.from_user.id)
    if other and other != key:
        await msg.answer(f"شما در اتاق دیگری ({other}) هستید. اول /leave بزنید.")
        return JoinFlowResult.ABORT
    if msg.from_user.id in game.players:
        await msg.answer(f"شما همین الان در این اتاق هستید. کد: {game.room_code}")
        return JoinFlowResult.SUCCESS

    await _show_join_preview(msg, bot, key, game)
    return JoinFlowResult.SUCCESS














def _require_private(msg: Message) -> bool:
    return msg.chat.type == ChatType.PRIVATE




















_OBSERVER_CMD_RE = re.compile(r"^/observer_(\d{4})\s*$")
















async def _player_end_dismiss_message(callback: CallbackQuery) -> None:
    if callback.message is None:
        return
    await callback.answer()
    try:
        await callback.message.edit_text(
            "✖️ بدون تأیید بستید. اگر بخواهید بعداً می‌توانید دوباره درخواست دهنده را دنبال کنید.",
            reply_markup=None,
        )
    except Exception:
        pass


async def _answer_mirror_claim(callback: CallbackQuery, err: str | None) -> bool:
    if err is None:
        return False
    if err == "already_claimed":
        await callback.answer("این انتخاب قبلاً ثبت شده است.", show_alert=True)
    elif err == "forbidden":
        await callback.answer("شما مجاز به این عمل نیستید.", show_alert=True)
    elif err == "dup_self":
        await callback.answer("قبلاً ثبت شده.")
    else:
        await callback.answer("خطا.", show_alert=True)
    return True


async def _process_player_end_approve(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    as_player_uid: int,
) -> None:
    if callback.message is None:
        return
    err = manager.approve_player_end_vote(game, as_player_uid)
    if err == "dup":
        await callback.answer("قبلاً تأیید کرده‌اید.")
        return
    if err == "host":
        await callback.answer("گرداننده در این رأی شرکت نمی‌کند.", show_alert=True)
        return
    if err:
        msg = {
            "inactive": "درخواست فعالی نیست یا مهلتش تمام شده.",
            "not_voter": "شما در فهرست این رأی نیستید.",
        }.get(err, "خطا.")
        await callback.answer(msg, show_alert=True)
        return
    await callback.answer("تأیید ثبت شد.")
    try:
        base = callback.message.text or ""
        await callback.message.edit_text(
            base + "\n\n✅ <b>تأیید شما ثبت شد.</b>",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        pass
    picker_id = manager.try_finalize_player_end_vote(game)
    if not picker_id:
        return
    await notify_initiator_winner_keyboard(bot, game.room_code, picker_id)





























def _panic_trigger_message_filter(msg: Message) -> bool:
    if msg.chat.type != ChatType.PRIVATE or not msg.from_user or not msg.text:
        return False
    phrase = get_panic_trigger_phrase()
    return bool(phrase) and msg.text.strip() == phrase


def _panic_password_wait_filter(msg: Message) -> bool:
    if msg.chat.type != ChatType.PRIVATE or not msg.from_user or msg.text is None:
        return False
    uid = msg.from_user.id
    if uid not in panic_password_pending:
        return False
    if time.time() - panic_password_pending[uid] > PANIC_PASSWORD_TTL_SEC:
        panic_password_pending.pop(uid, None)
        return False
    return True






def _myname_waiting_filter(msg: Message) -> bool:
    if msg.chat.type != ChatType.PRIVATE or not msg.from_user or not msg.text:
        return False
    if (msg.text or "").startswith("/"):
        return False
    return msg.from_user.id in waiting_myname_user_ids






















async def game_deadlines_watcher(bot: Bot) -> None:
    """لابی نیمه‌پر، تایم‌اوت ۱۲ ساعت بعد از پخش نقش، انقضای رأی پایان جمعی."""
    tick = 0
    while True:
        await asyncio.sleep(60)
        tick += 1
        if tick % 5 == 0:
            for g in list(manager.games.values()):
                if g.phase != Phase.ENDED:
                    manager.persist_snapshot(g, reason="periodic")
        for stale in manager.collect_stale_unfilled_lobbies():
            code = stale.room_code
            game = manager.get_game(code)
            if game is None:
                continue
            if not manager.is_lobby_past_fill_deadline(game):
                continue
            notice = (
                f"⏱ اتاق {code} چون در {_fa_digits(game.lobby_fill_deadline_minutes)} دقیقه "
                "به حد نصاب نرسید منحل شد.\n"
                "🔓 کد آزاد است؛ می‌توانید دوباره /create بزنید."
            )
            await broadcast_game(bot, game, notice)
            manager.end_game(code)

        for g in manager.collect_post_deal_timeout_games():
            code = g.room_code
            game = manager.get_game(code)
            if game is None:
                continue
            if not manager.is_post_deal_past_timeout(game):
                continue
            notice = (
                f"⏱ از پخش نقش در اتاق {code} بیش از {_fa_digits(game.post_deal_timeout_hours)} ساعت گذشت "
                "و بازی بدون پایان رسمی بسته شد."
            )
            await broadcast_game(bot, game, notice)
            manager.end_game(code)

        for g in manager.collect_expired_player_end_broadcast_pending():
            target_uid = g.player_end_broadcast_pending_uid
            manager.clear_player_end_broadcast_pending(g)
            if target_uid:
                try:
                    await bot.send_message(
                        target_uid,
                        f"⌛ مهلت {_fa_digits(g.player_end_broadcast_confirm_minutes)} دقیقه‌ای تأیید اولیهٔ "
                        "/request_end تمام شد؛ در صورت نیاز دوباره همان دستور را بزنید.",
                    )
                except Exception:
                    pass

        for g in manager.collect_expired_player_end_votes():
            code = g.room_code
            game = manager.get_game(code)
            if game is None:
                continue
            if not manager.player_end_vote_expired(game):
                continue
            if manager.player_end_all_approved(game):
                continue
            manager.clear_player_end_vote(game)
            notice = (
                f"⌛ درخواست پایان بدون گرداننده در اتاق {code} چون تا "
                f"{_fa_digits(game.player_end_approval_minutes)} دقیقه همه تأیید نکردند منقضی شد."
            )
            await broadcast_game(bot, game, notice)


def build_bot_menu_commands() -> list[BotCommand]:
    """حداکثر چند دستور اصلی؛ بقیه از /menu و دکمه‌ها."""
    return [
        BotCommand(command="start", description="شروع و منوی اصلی"),
        BotCommand(command="create", description="ساخت اتاق جدید"),
        BotCommand(command="join", description="ورود با کد دو رقمی اتاق"),
        BotCommand(command="menu", description="بقیه: اتاق، امتیاز، راهنما"),
    ]


def _wire_handlers() -> None:
    from bot.handlers import register_all_handlers

    register_all_handlers(dp)


async def main() -> None:
    _wire_handlers()
    db.init_db()
    manager.load_user_display_names_from_db()
    restored = manager.restore_active_games_from_db()
    try:
        from bot.mason_night_reminder import (
            invalidate_mason_night_reminders_on_restore,
            clear_mason_night_reminder_state,
        )
        from bot.room_mode import is_mason_scenario

        invalidate_mason_night_reminders_on_restore()
        for code in restored:
            g = manager.get_game(code)
            if g is None or not is_mason_scenario(g):
                continue
            g.mason_night_reminder_generation = (
                int(g.mason_night_reminder_generation or 0) + 1
            )
            clear_mason_night_reminder_state(g)
    except Exception:
        logger.exception("mason night reminder restore invalidate failed")
    if restored:
        logger.info(
            "Restored %d active game(s) from snapshot: %s",
            len(restored),
            ", ".join(restored),
        )
    bot = Bot(token=get_token())
    if restored:
        from bot.russian_mafia_flow import reissue_open_russian_action_panels

        for code in list(restored):
            restored_game = manager.get_game(code)
            if restored_game is None:
                continue
            try:
                await reissue_open_russian_action_panels(bot, restored_game)
            except Exception:
                logger.exception(
                    "Russian panel reissue failed room=%s", code
                )
    await bot.set_my_commands(
        build_bot_menu_commands(),
        scope=BotCommandScopeAllPrivateChats(),
    )
    asyncio.create_task(game_deadlines_watcher(bot))
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
