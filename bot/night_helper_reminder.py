"""یادآور عمومی پایان نیافتن اقدامات شبانه — فقط کمک‌کنندهٔ ربات.

فقط سناریوهای غیر ماسون (ماسون ماژول مستقل خودش را دارد):
- مذاکره (mozakere, no_host) — همراه دکمه «اتمام شب»
- نماینده (namayande, nam10 fork همهٔ نفرات) — همراه دکمه «اتمام شب»
- بازپرس (bazpors, no_host) — همراه دکمه «اتمام شب»
- مافیا روسی (russian_mafia, host_helper) — بدون دکمه

متن یادآور عمومی است: بدون نام بازیکن، بدون نام نقش، بدون شماره صندلی.

پنل شمارندهٔ زنده (مذاکره/نماینده/ماسون): عنوان «قابلیت اتمام شب» با شمارندهٔ
اقدامات ناتمام که با هر تأیید روی همان پیام ویرایش می‌شود. مافیا روسی
متن قدیمی و ثابت را حفظ می‌کند.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot.models import Game, Phase, Role
from bot.tg_send import safe_send_message_return

if TYPE_CHECKING:
    from bot.game import GameManager

logger = logging.getLogger(__name__)

REMINDER_DELAY_SEC = 120.0

REMINDER_HEADER = "🌙 اقدامات شبانه هنوز تکمیل نشده‌اند"
REMINDER_GENERIC_LINE = "برخی از بازیکنان هنوز اقدامات شبانه خود را تکمیل نکرده‌اند."
REMINDER_BUTTON_PARAGRAPH = (
    "در صورت تمایل، کمک‌کننده ربات می‌تواند با استفاده از دکمه «اتمام شب»، "
    "فاز شب را به پایان برساند.\n\n"
    "در این حالت، ربات فقط اقدامات تأییدشده را محاسبه می‌کند و اقداماتی را که "
    "هنوز تأیید نشده‌اند، انجام‌نشده در نظر می‌گیرد."
)
REMINDER_PLAIN_PARAGRAPH = (
    "تا زمان تکمیل اقدامات ضروری، ربات به‌صورت عادی پایان شب را اعلام نمی‌کند."
)

# پنل جدید شمارنده‌دار (مذاکره/نماینده/ماسون) — بدون نام/نقش/صندلی.
NIGHT_FINISH_HEADER = "🌙 قابلیت اتمام شب"
NIGHT_FINISH_COUNT_LINE = (
    "به دلیل اینکه هنوز {count} اقدام شبانه تکمیل نشده است، "
    "فاز شب همچنان ادامه دارد."
)

# بازپرس: شمارندهٔ بولد مطابق مشخصات (فقط در جریان HTML).
NIGHT_FINISH_COUNT_LINE_BAZPORS_HTML = (
    "به دلیل اینکه هنوز <b>{count} اقدام شبانه</b> تکمیل نشده است، "
    "فاز شب همچنان ادامه دارد."
)
NIGHT_FINISH_ASK_LINE = (
    "لطفاً از بازیکنان بخواهید اقدامات شبانه خود را تکمیل و تأیید کنند."
)
NIGHT_FINISH_BUTTON_LINE = (
    "در صورت نیاز، می‌توانید با انتخاب گزینه «اتمام شب»، "
    "شب جاری را به پایان برسانید."
)
NIGHT_FINISH_TAIL_LINE = (
    "در این حالت، اقدامات تأییدشده محاسبه می‌شوند و اقدامات ناتمام "
    "مطابق قوانین سناریو تعیین تکلیف خواهند شد."
)

# مذاکره: پنل با سربرگ بولد HTML — نماینده متن ساده نگه داشته می‌شود.
NIGHT_FINISH_HEADER_HTML = "🌙 <b>قابلیت اتمام شب</b>"

# وقتی حذف پیام ممکن نبود (مذاکره): دکمه برداشته و پیام بسته می‌شود.
NIGHT_REMINDER_CLOSED_FALLBACK_TEXT = "این یادآور بسته شد."

# هشدارهای مخصوص نمایندهٔ ۱۲/۱۳ (فقط وقتی سرباز در ترکیب هست) — بدون نام
# بازیکن، بدون افشای اینکه اکنون چه کسی این نقش‌ها را دارد یا چه کسی
# اقدامش ناتمام است.
NAM10_FORCE_FINISH_WARNINGS = (
    "⚠️ قوانین مهم اتمام اجباری شب در سناریوی نماینده\n\n"
    "🪖 سرباز:\n"
    "اگر سرباز هنوز بازیکنی را برای دریافت قابلیت اسنایپر انتخاب و تأیید "
    "نکرده است، باید پیش از اتمام شب اقدام خود را تکمیل کند.\n\n"
    "در غیر این صورت، با انتخاب گزینه «اتمام شب»، سرباز در پایان همان شب "
    "از بازی خارج خواهد شد.\n\n"
    "🎯 اسنایپر موقت:\n"
    "اگر بازیکنی قابلیت اسنایپر موقت دریافت کرده است، باید حتماً یک بازیکن "
    "را برای شلیک انتخاب و تأیید کند.\n\n"
    "اگر اسنایپر موقت تا زمان اتمام اجباری شب شلیک خود را تأیید نکند، "
    "خودش در پایان همان شب از بازی خارج خواهد شد."
)

FORCE_FINISH_BUTTON_TEXT = "🌙 اتمام شب"

# room_code -> in-flight timer task (never persisted)
_REMINDER_TASKS: dict[str, asyncio.Task] = {}
_REMINDER_LOCKS: dict[str, asyncio.Lock] = {}


def _lock_for(room_code: str) -> asyncio.Lock:
    return _REMINDER_LOCKS.setdefault(room_code, asyncio.Lock())


def _mode(game: Game) -> str | None:
    """Scenario support mode; None = not applicable (mason has its own module)."""
    from bot.room_mode import (
        is_bazpors_no_host_room,
        is_mason_scenario,
        is_mozakere_no_host_room,
        is_namayande10_no_host_room,
        is_russian_mafia_host_helper_room,
    )

    if is_mason_scenario(game):
        return None
    if is_mozakere_no_host_room(game):
        return "no_host_collect"
    if is_bazpors_no_host_room(game):
        return "no_host_collect"
    if is_namayande10_no_host_room(game):
        return "nam10"
    if is_russian_mafia_host_helper_room(game):
        return "russian"
    return None


def night_reminder_uses_force_finish(game: Game) -> bool:
    """«اتمام شب» برای مذاکره/بازپرس(no_host)/نماینده — ماسون ماژول خودش را دارد."""
    from bot.room_mode import (
        is_bazpors_no_host_room,
        is_mozakere_scenario,
        is_namayande10_no_host_room,
    )

    if is_mozakere_scenario(game):
        return True
    if is_bazpors_no_host_room(game):
        return True
    if is_namayande10_no_host_room(game):
        return True
    return False


def build_generic_night_reminder_text(game: Game) -> str:
    if night_reminder_uses_force_finish(game):
        tail = REMINDER_BUTTON_PARAGRAPH
    else:
        tail = REMINDER_PLAIN_PARAGRAPH
    return f"{REMINDER_HEADER}\n\n{REMINDER_GENERIC_LINE}\n\n{tail}"


def night_reminder_uses_counted_text(game: Game) -> bool:
    """پنل شمارندهٔ زنده فقط برای مذاکره/نماینده (بازپرس/روسی متن قدیمی)."""
    return night_reminder_uses_force_finish(game)


def counted_night_reminder_header_and_parse_mode(
    game: Game,
) -> tuple[str, str | None]:
    """سربرگ و حالت پارس پنل شمارنده‌دار — مذاکره/بازپرس: HTML بولد.

    نماینده متن ساده بدون parse_mode نگه داشته می‌شود (بدون تغییر رابط کاربری).
    """
    from bot.room_mode import is_bazpors_no_host_room, is_mozakere_scenario

    if is_mozakere_scenario(game) or is_bazpors_no_host_room(game):
        return NIGHT_FINISH_HEADER_HTML, "HTML"
    return NIGHT_FINISH_HEADER, None


def night_reminder_outstanding_count(game: Game) -> int:
    """شمارندهٔ authoritative اقدامات ناتمام — فقط تعداد، بدون هیچ هویتی.

    مذاکره: آمادگی‌های شب موازی (برچسب‌های ناتمام). نماینده: کلیدهای
    الزامی night2_required_keys (هر اقدام الزامی یک کلید).
    """
    mode = _mode(game)
    if mode == "nam10":
        from bot.nam10.night2 import night2_required_keys

        return len(night2_required_keys(game))
    if mode == "no_host_collect":
        from bot.room_mode import is_bazpors_no_host_room, is_mozakere_scenario

        if is_mozakere_scenario(game) or is_bazpors_no_host_room(game):
            from bot.no_host_night_ready import (
                pending_no_host_night_actor_labels,
            )

            return len(pending_no_host_night_actor_labels(game))
    return 0


def nam10_force_finish_warnings_active(game: Game) -> bool:
    """هشدارهای سرباز/اسنایپر موقت فقط برای ترکیب‌های دارای سرباز (۱۲/۱۳)."""
    if _mode(game) != "nam10":
        return False
    try:
        from bot.nam10.night2 import _holder

        return _holder(game, Role.SOLDIER) is not None
    except Exception:
        return False


def build_counted_night_reminder_text(game: Game, count: int) -> str:
    """پنل «قابلیت اتمام شب» با شمارندهٔ زندهٔ اقدامات ناتمام."""
    from bot.text_fa import fa_digits

    from bot.room_mode import is_bazpors_no_host_room

    if is_bazpors_no_host_room(game):
        count_line = NIGHT_FINISH_COUNT_LINE_BAZPORS_HTML.format(
            count=fa_digits(max(0, count))
        )
    else:
        count_line = NIGHT_FINISH_COUNT_LINE.format(count=fa_digits(max(0, count)))
    body = "\n\n".join(
        (
            count_line,
            NIGHT_FINISH_ASK_LINE,
            NIGHT_FINISH_BUTTON_LINE,
            NIGHT_FINISH_TAIL_LINE,
        )
    )
    if night_reminder_uses_force_finish(game) and nam10_force_finish_warnings_active(game):
        body = f"{body}\n\n{NAM10_FORCE_FINISH_WARNINGS}"
    header, _parse_mode = counted_night_reminder_header_and_parse_mode(game)
    return f"{header}\n\n{body}"


def night_reminder_collect_active(game: Game) -> bool:
    mode = _mode(game)
    if mode == "no_host_collect":
        from bot.no_host_night_ready import no_host_parallel_night_collect_active

        return no_host_parallel_night_collect_active(game)
    if mode == "nam10":
        from bot.nam10.night2 import PENDING_COLLECTING, nam10_night2_mode

        return bool(
            nam10_night2_mode(game)
            and game.nmnd_night2_phase == PENDING_COLLECTING
        )
    if mode == "russian":
        return game.phase == Phase.NIGHT
    return False


def night_reminder_all_ready(game: Game) -> bool:
    mode = _mode(game)
    if mode == "no_host_collect":
        from bot.no_host_night_ready import all_no_host_parallel_night_ready

        return all_no_host_parallel_night_ready(game)
    if mode == "nam10":
        from bot.nam10.night2 import night2_required_keys

        return not night2_required_keys(game)
    if mode == "russian":
        from bot.russian_mafia import night_ready_to_resolve

        return night_ready_to_resolve(game)
    return True


def night_reminder_night_stamp(game: Game) -> int:
    mode = _mode(game)
    if mode == "nam10":
        return int(
            game.nmnd_night2_night_count
            or game.nmnd_narrator_night_count
            or 0
        )
    if mode == "russian":
        return int(game.russian_mafia_night_index or 0)
    return int(game.bazpors_narrator_night_count or 0)


def _force_finish_keyboard_for(game: Game):
    from bot.room_mode import (
        is_bazpors_no_host_room,
        is_mozakere_scenario,
        is_namayande10_no_host_room,
    )

    if is_mozakere_scenario(game):
        try:
            from bot.mozakere_force_finish_night import (
                mozakere_force_finish_button_keyboard,
            )

            return mozakere_force_finish_button_keyboard(game)
        except Exception:
            logger.exception("mozakere force finish keyboard build failed")
            return None
    if is_bazpors_no_host_room(game):
        try:
            from bot.bazpors_force_finish_night import (
                bazpors_force_finish_button_keyboard,
            )

            return bazpors_force_finish_button_keyboard(game)
        except Exception:
            logger.exception("bazpors force finish keyboard build failed")
            return None
    if is_namayande10_no_host_room(game):
        try:
            from bot.nam10.night_force_finish import (
                nam10_force_finish_button_keyboard,
            )

            return nam10_force_finish_button_keyboard(game)
        except Exception:
            logger.exception("nam10 force finish keyboard build failed")
            return None
    return None


def _reminder_still_valid(
    game: Game,
    *,
    generation: int,
    night_count: int,
) -> bool:
    if _mode(game) is None:
        return False
    if game.phase == Phase.ENDED:
        return False
    if game.night_helper_reminder_generation != generation:
        return False
    if night_reminder_night_stamp(game) != night_count:
        return False
    if not night_reminder_collect_active(game):
        return False
    return True


async def _delete_reminder_message(bot: Bot, game: Game) -> None:
    chat_id = game.night_helper_reminder_chat_id
    message_id = game.night_helper_reminder_message_id
    clear_night_helper_reminder_state(game)
    if chat_id is None or message_id is None:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramBadRequest:
        await _fallback_close_reminder(bot, game, chat_id, message_id)
    except TelegramForbiddenError:
        await _fallback_close_reminder(bot, game, chat_id, message_id)
    except Exception:
        logger.exception(
            "night helper reminder delete failed room=%s", game.room_code
        )
        await _fallback_close_reminder(bot, game, chat_id, message_id)


async def _fallback_close_reminder(
    bot: Bot, game: Game, chat_id: int, message_id: int
) -> None:
    """حذف ممکن نشد → مذاکره/بازپرس: دکمه برداشته و پیام بسته می‌شود."""
    from bot.room_mode import is_bazpors_no_host_room, is_mozakere_scenario

    if not (is_mozakere_scenario(game) or is_bazpors_no_host_room(game)):
        return
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=NIGHT_REMINDER_CLOSED_FALLBACK_TEXT,
            reply_markup=None,
        )
    except Exception:
        logger.info(
            "night helper reminder fallback close failed room=%s msg=%s",
            game.room_code,
            message_id,
        )


def clear_night_helper_reminder_state(game: Game) -> None:
    """پاک‌سازی متادیتای سریال‌شونده — بدون حذف پیام تلگرام."""
    game.night_helper_reminder_chat_id = None
    game.night_helper_reminder_message_id = None
    game.night_helper_reminder_night_count = None
    game.night_helper_reminder_last_count = None
    game.night_helper_reminder_scheduled_at = 0.0
    game.night_helper_reminder_force_confirm_open = False


def cancel_night_helper_reminder_task(room_code: str) -> None:
    task = _REMINDER_TASKS.pop(room_code, None)
    if task is not None and not task.done():
        task.cancel()


async def cleanup_night_helper_reminder(
    bot: Bot, game: Game, *, cancel_timer: bool = True
) -> None:
    """حذف پیام و باطل‌سازی تایمر — خطا بازی را متوقف نمی‌کند."""
    if _mode(game) is None:
        return
    if cancel_timer:
        cancel_night_helper_reminder_task(game.room_code)
    if (
        game.night_helper_reminder_chat_id is None
        and game.night_helper_reminder_message_id is None
    ):
        return
    async with _lock_for(game.room_code):
        try:
            await _delete_reminder_message(bot, game)
        except Exception:
            logger.exception(
                "night helper reminder cleanup failed room=%s", game.room_code
            )
            clear_night_helper_reminder_state(game)


async def _send_reminder_if_needed(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    generation: int,
    night_count: int,
) -> None:
    async with _lock_for(game.room_code):
        if not _reminder_still_valid(
            game,
            generation=generation,
            night_count=night_count,
        ):
            return
        if night_reminder_all_ready(game):
            return
        if game.night_helper_reminder_message_id is not None:
            # already sent for this night
            return
        assistant_uid = game.bot_assistant_user_id
        if assistant_uid is None:
            return
        if night_reminder_uses_counted_text(game):
            count = night_reminder_outstanding_count(game)
            if count <= 0:
                return
            text = build_counted_night_reminder_text(game, count)
        else:
            count = None
            text = build_generic_night_reminder_text(game)
        send_kwargs: dict = {}
        if night_reminder_uses_counted_text(game):
            _header, send_parse_mode = (
                counted_night_reminder_header_and_parse_mode(game)
            )
            if send_parse_mode:
                send_kwargs["parse_mode"] = send_parse_mode
        msg = await safe_send_message_return(
            bot,
            assistant_uid,
            text,
            reply_markup=_force_finish_keyboard_for(game),
            **send_kwargs,
        )
        if msg is None:
            return
        game.night_helper_reminder_chat_id = assistant_uid
        game.night_helper_reminder_message_id = msg.message_id
        game.night_helper_reminder_night_count = night_count
        game.night_helper_reminder_last_count = count


async def refresh_night_helper_reminder(bot: Bot, game: Game) -> None:
    """به‌روزرسانی زندهٔ شمارنده روی همان پیام — بدون پیام جدید و بدون تایمر جدید.

    - شمارنده تغییر کرده → edit همان پیام (دکمهٔ «اتمام شب» حفظ می‌شود).
    - شمارنده صفر یا فاز دیگر → حذف پیام (callback دیررس باطل می‌شود؛
      هیچ اتمام اجباری و هیچ جریمه‌ای اجرا نمی‌شود).
    - شمارنده بدون تغییر → بدون edit (بدون ارسال مجدد).
    """
    if _mode(game) is None:
        return
    if not night_reminder_uses_counted_text(game):
        return
    if game.night_helper_reminder_message_id is None:
        return
    async with _lock_for(game.room_code):
        if game.night_helper_reminder_message_id is None:
            return
        try:
            if (
                game.phase == Phase.ENDED
                or not night_reminder_collect_active(game)
                or night_reminder_all_ready(game)
            ):
                await _delete_reminder_message(bot, game)
                return
            count = night_reminder_outstanding_count(game)
            if count <= 0:
                await _delete_reminder_message(bot, game)
                return
            if game.night_helper_reminder_force_confirm_open:
                # The force-finish confirm panel is open on the SAME
                # message — the live counter must not overwrite it;
                # the count is recalculated on cancel-restore.
                return
            if game.night_helper_reminder_last_count == count:
                return
            chat_id = (
                game.night_helper_reminder_chat_id
                or game.bot_assistant_user_id
            )
            message_id = game.night_helper_reminder_message_id
            if chat_id is None or message_id is None:
                return
            try:
                _header, edit_parse_mode = (
                    counted_night_reminder_header_and_parse_mode(game)
                )
                edit_kwargs: dict = {}
                if edit_parse_mode:
                    edit_kwargs["parse_mode"] = edit_parse_mode
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=build_counted_night_reminder_text(game, count),
                    reply_markup=_force_finish_keyboard_for(game),
                    **edit_kwargs,
                )
                game.night_helper_reminder_last_count = count
            except TelegramBadRequest:
                # message not modified / too old — counter state is
                # still authoritative for the next refresh tick.
                game.night_helper_reminder_last_count = count
        except Exception:
            logger.exception(
                "night helper reminder refresh failed room=%s",
                game.room_code,
            )


async def restore_night_helper_reminder_after_cancel(bot: Bot, game: Game) -> None:
    """Restore the SAME message from the force-finish confirm state to the
    counted reminder panel.

    Cancel path for «اتمام شب»: no new message, no new timer. The counter
    is recalculated from live state so a stale count is never shown.
    """
    if _mode(game) is None:
        return
    game.night_helper_reminder_force_confirm_open = False
    chat_id = game.night_helper_reminder_chat_id or game.bot_assistant_user_id
    message_id = game.night_helper_reminder_message_id
    if chat_id is None or message_id is None:
        return
    async with _lock_for(game.room_code):
        try:
            if (
                game.phase == Phase.ENDED
                or not night_reminder_collect_active(game)
                or night_reminder_all_ready(game)
            ):
                # نزدیک به بسته‌شدن — cleanup زودتر اجرا خواهد شد.
                return
            count = max(0, night_reminder_outstanding_count(game))
            _header, parse_mode = counted_night_reminder_header_and_parse_mode(
                game
            )
            edit_kwargs: dict = {}
            if parse_mode:
                edit_kwargs["parse_mode"] = parse_mode
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=build_counted_night_reminder_text(game, count),
                reply_markup=_force_finish_keyboard_for(game),
                **edit_kwargs,
            )
            game.night_helper_reminder_last_count = count
        except TelegramBadRequest:
            # already in the requested state / too old — counter state
            # stays authoritative for the next refresh tick.
            game.night_helper_reminder_last_count = (
                night_reminder_outstanding_count(game)
            )
        except Exception:
            logger.exception(
                "night helper reminder cancel-restore failed room=%s",
                game.room_code,
            )


async def _reminder_timer_job(
    bot: Bot,
    room_code: str,
    *,
    generation: int,
    night_count: int,
    delay_sec: float,
) -> None:
    try:
        await asyncio.sleep(delay_sec)
    except asyncio.CancelledError:
        return
    try:
        from bot.app_state import manager

        game = manager.get_game(room_code)
        if game is None:
            return
        await _send_reminder_if_needed(
            bot,
            game,
            manager,
            generation=generation,
            night_count=night_count,
        )
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception(
            "night helper reminder timer failed room=%s gen=%s",
            room_code,
            generation,
        )
    finally:
        task = _REMINDER_TASKS.get(room_code)
        current = asyncio.current_task()
        if task is current:
            _REMINDER_TASKS.pop(room_code, None)


def schedule_night_helper_reminder(
    bot: Bot,
    game: Game,
    *,
    delay_sec: float = REMINDER_DELAY_SEC,
) -> None:
    """پس از اتمام ارسال پنل‌های شب — تایمر ۱۲۰ثانیه‌ای برای کمک‌کننده."""
    if _mode(game) is None:
        return
    if game.bot_assistant_user_id is None:
        return
    if not night_reminder_collect_active(game):
        return

    cancel_night_helper_reminder_task(game.room_code)
    # نسل جدید؛ پیام شب قبل نباید بماند
    game.night_helper_reminder_generation = int(
        game.night_helper_reminder_generation or 0
    ) + 1
    clear_night_helper_reminder_state(game)

    generation = game.night_helper_reminder_generation
    night_count = night_reminder_night_stamp(game)
    game.night_helper_reminder_night_count = night_count
    game.night_helper_reminder_scheduled_at = time.time()

    task = asyncio.create_task(
        _reminder_timer_job(
            bot,
            game.room_code,
            generation=generation,
            night_count=night_count,
            delay_sec=delay_sec,
        ),
        name=f"night_helper_reminder:{game.room_code}:{generation}",
    )
    _REMINDER_TASKS[game.room_code] = task


def invalidate_night_helper_reminders_on_restore() -> None:
    """پس از ریستارت سرویس — تایمرهای حافظه از بین رفته‌اند؛ از ارسال کهنه جلوگیری کن."""
    for room in list(_REMINDER_TASKS):
        cancel_night_helper_reminder_task(room)



def _create_reminder_timer_task(
    bot: "Bot",
    room_code: str,
    *,
    generation: int,
    night_count: int,
    delay_sec: float,
) -> "asyncio.Task":
    task = asyncio.create_task(
        _reminder_timer_job(
            bot,
            room_code,
            generation=generation,
            night_count=night_count,
            delay_sec=delay_sec,
        ),
        name=f"night_helper_reminder:{room_code}:{generation}",
    )
    _REMINDER_TASKS[room_code] = task
    return task


async def recover_night_helper_reminders_after_restart(bot: "Bot") -> None:
    """بازیابی یادآور بعد از ری‌استارت سرویس — ادامهٔ چرخهٔ حیات همان پیام.

    - پیام و متادیتای ارسال‌شده با snapshot مانده → هیچ ارسال تازه‌ای انجام
      نمی‌شود؛ refresh/cleanup روی همان پیام continue می‌کنند.
    - پیام این شب هنوز ارسال نشده (تایمر با ری‌استارت از بین رفته) → تایمر
      با تاخیر باقی‌مانده دوباره ساخته می‌شود؛ اگر زمان اصلی گذشته باشد
      فقط یک بار بلافاصه ارسال می‌شود.
    """
    from bot.app_state import manager

    for room_code in list(manager.games.keys()):
        game = manager.get_game(room_code)
        if game is None or _mode(game) is None:
            continue
        if game.bot_assistant_user_id is None:
            continue
        if not night_reminder_collect_active(game):
            continue
        sched = float(game.night_helper_reminder_scheduled_at or 0.0)
        if sched <= 0.0:
            continue
        if game.night_helper_reminder_message_id is not None:
            # پیام و binding پابرجاست — چرخهٔ edit/حذف ادامه می‌یابد.
            continue
        night_count = night_reminder_night_stamp(game)
        if game.night_helper_reminder_night_count != night_count:
            # برای این شب زمان‌بندی نشده است — چیزی از خود نمی‌سازیم.
            continue
        _REMINDER_TASKS.pop(room_code, None)
        game.night_helper_reminder_generation = int(
            game.night_helper_reminder_generation or 0
        ) + 1
        generation = game.night_helper_reminder_generation
        remaining = REMINDER_DELAY_SEC - (time.time() - sched)
        if remaining > 0.5:
            _create_reminder_timer_task(
                bot,
                room_code,
                generation=generation,
                night_count=night_count,
                delay_sec=remaining,
            )
        else:
            await _send_reminder_if_needed(
                bot,
                game,
                manager,
                generation=generation,
                night_count=night_count,
            )
