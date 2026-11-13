"""یادآور زندهٔ اکت‌های شب برای کمک‌کننده — فقط سناریوی ماسون."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from bot.game import is_synthetic_player_uid, synthetic_player_base_name
from bot.models import Game, Phase, Player, Role
from bot.room_mode import is_mason_scenario
from bot.tg_send import safe_send_message_return

if TYPE_CHECKING:
    from bot.game import GameManager

logger = logging.getLogger(__name__)

REMINDER_DELAY_SEC = 120.0

# پنل شمارندهٔ زندهٔ ماسون — عمومی، بدون نام بازیکن/نقش/صندلی (متن ماسون
# بدون هشدارهای سرباز/اسنایپر است؛ آن‌ها فقط ویژهٔ نماینده ۱۲/۱۳ هستند).
_MASON_REMINDER_HEADER = "🌙 قابلیت اتمام شب"
_MASON_REMINDER_COUNT_LINE = (
    "به دلیل اینکه هنوز {count} اقدام شبانه تکمیل نشده است، "
    "فاز شب همچنان ادامه دارد."
)
_MASON_REMINDER_ASK_LINE = (
    "لطفاً از بازیکنان بخواهید اقدامات شبانه خود را تکمیل و تأیید کنند."
)
_MASON_REMINDER_BUTTON_LINE = (
    "در صورت نیاز، می‌توانید با انتخاب گزینه «اتمام شب»، "
    "شب جاری را به پایان برسانید."
)
_MASON_REMINDER_TAIL_LINE = (
    "در این حالت، اقدامات تأییدشده محاسبه می‌شوند و اقدامات ناتمام "
    "مطابق قوانین سناریو تعیین تکلیف خواهند شد."
)
_DONE_MARK = " (انجام داد)"

# room_code -> in-flight timer task (never persisted)
_REMINDER_TASKS: dict[str, asyncio.Task] = {}
_REMINDER_LOCKS: dict[str, asyncio.Lock] = {}


def _lock_for(room_code: str) -> asyncio.Lock:
    return _REMINDER_LOCKS.setdefault(room_code, asyncio.Lock())


def cancel_mason_night_reminder_task(room_code: str) -> None:
    task = _REMINDER_TASKS.pop(room_code, None)
    if task is not None and not task.done():
        task.cancel()


def clear_mason_night_reminder_state(game: Game) -> None:
    """پاک‌سازی متادیتای سریال‌شونده — بدون حذف پیام تلگرام."""
    game.mason_night_reminder_chat_id = None
    game.mason_night_reminder_message_id = None
    game.mason_night_reminder_initial_pending_uids = []
    game.mason_night_reminder_night_count = None
    game.mason_night_reminder_last_text = None
    game.mason_night_reminder_created_at_iso = None


def mason_reminder_display_name(player: Player) -> str:
    from bot.app_state import custom_display_name

    name = (custom_display_name(player.user_id) or (player.full_name or "")).strip()
    if not name:
        return str(player.user_id)
    if is_synthetic_player_uid(player.user_id):
        from bot.mason_synthetic_names import MASON_SYNTHETIC_NAME_SEP

        base = synthetic_player_base_name(name)
        if base != name:
            return base
        if MASON_SYNTHETIC_NAME_SEP in name:
            return name.split(MASON_SYNTHETIC_NAME_SEP, 1)[0].strip()
        return base
    return name


def collect_mason_night_pending_holder_uids(
    game: Game, gm: "GameManager"
) -> list[int]:
    """uid بازیکنان زنده با مسئولیت شبانهٔ ناتمام — منبع حقیقت responsibilities."""
    if not is_mason_scenario(game):
        return []
    from bot.mason_responsibilities import collect_mason_night_responsibilities

    pending: list[int] = []
    seen: set[int] = set()
    for resp in collect_mason_night_responsibilities(game, gm):
        if not resp.required or resp.done:
            continue
        uid = resp.holder_uid
        if uid is None or uid in seen:
            continue
        player = game.players.get(uid)
        if player is None or not player.is_alive:
            continue
        if player.role == Role.OBSERVER:
            continue
        seen.add(uid)
        pending.append(uid)
    pending.sort(
        key=lambda u: (
            game.players[u].seat if game.players[u].seat is not None else 999,
            u,
        )
    )
    return pending


def collect_mason_night_outstanding_count(game: Game, gm: "GameManager") -> int:
    """شمارندهٔ authoritative اقدامات ناتمام — الزامات، نه نفرات یکتا.

    هر الزامِ required و انجام‌نشده یک واحد شمرده می‌شود (بازیکنی با دو
    اقدام الزامی، دو واحد شمرده می‌شود). موارد بی‌دارنده/مرده و
    مسئولیت‌های ناظر (خارج از پنل یادآور) شمرده نمی‌شوند — همان فیلترهای
    برچسب‌گذاری قدیمی."""
    if not is_mason_scenario(game):
        return 0
    from bot.mason_responsibilities import collect_mason_night_responsibilities

    count = 0
    for resp in collect_mason_night_responsibilities(game, gm):
        if not resp.required or resp.done:
            continue
        uid = resp.holder_uid
        player = game.players.get(uid) if uid is not None else None
        if player is None or not player.is_alive:
            continue
        if player.role == Role.OBSERVER:
            continue
        count += 1
    return count


def build_mason_night_reminder_text(game: Game, count: int) -> str:
    """متن عمومی یادآور با شمارندهٔ زنده — هیچ نام یا نقشی نمایش داده نمی‌شود."""
    from bot.text_fa import fa_digits

    del game
    body = "\n\n".join(
        (
            _MASON_REMINDER_COUNT_LINE.format(
                count=fa_digits(max(0, count))
            ),
            _MASON_REMINDER_ASK_LINE,
            _MASON_REMINDER_BUTTON_LINE,
            _MASON_REMINDER_TAIL_LINE,
        )
    )
    return f"{_MASON_REMINDER_HEADER}\n\n{body}"


def _reminder_still_valid(
    game: Game,
    *,
    generation: int,
    night_count: int,
    created_at_iso: str,
) -> bool:
    if not is_mason_scenario(game):
        return False
    if game.phase == Phase.ENDED:
        return False
    if game.mason_night_reminder_generation != generation:
        return False
    if game.bazpors_narrator_night_count != night_count:
        return False
    if game.mason_night_reminder_created_at_iso != created_at_iso:
        return False
    from bot.no_host_night_ready import no_host_parallel_night_collect_active

    if not no_host_parallel_night_collect_active(game):
        return False
    return True


async def _delete_reminder_message(bot: Bot, game: Game) -> None:
    chat_id = game.mason_night_reminder_chat_id
    message_id = game.mason_night_reminder_message_id
    clear_mason_night_reminder_state(game)
    if chat_id is None or message_id is None:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramBadRequest:
        pass
    except TelegramForbiddenError:
        pass
    except Exception:
        logger.exception(
            "mason night reminder delete failed room=%s", game.room_code
        )


async def cleanup_mason_night_helper_reminder(
    bot: Bot, game: Game, *, cancel_timer: bool = True
) -> None:
    """حذف پیام و باطل‌سازی تایمر — خطا بازی را متوقف نمی‌کند."""
    if not is_mason_scenario(game):
        return
    if cancel_timer:
        cancel_mason_night_reminder_task(game.room_code)
    async with _lock_for(game.room_code):
        try:
            await _delete_reminder_message(bot, game)
        except Exception:
            logger.exception(
                "mason night reminder cleanup failed room=%s", game.room_code
            )
            clear_mason_night_reminder_state(game)


async def refresh_mason_night_helper_reminder(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """به‌روزرسانی زندهٔ شمارنده روی همان پیام — بدون پیام جدید و بدون تایمر جدید."""
    if not is_mason_scenario(game):
        return
    if game.mason_night_reminder_message_id is None:
        return
    async with _lock_for(game.room_code):
        if game.mason_night_reminder_message_id is None:
            return
        try:
            from bot.mason_night_ready import all_mason_parallel_night_ready
            from bot.no_host_night_ready import no_host_parallel_night_collect_active

            if (
                game.phase == Phase.ENDED
                or not no_host_parallel_night_collect_active(game)
                or all_mason_parallel_night_ready(game)
            ):
                await _delete_reminder_message(bot, game)
                return
            count = collect_mason_night_outstanding_count(game, gm)
            if count <= 0:
                await _delete_reminder_message(bot, game)
                return
            text = build_mason_night_reminder_text(game, count)
            if game.mason_night_reminder_last_text == text:
                return
            chat_id = (
                game.mason_night_reminder_chat_id
                or game.bot_assistant_user_id
            )
            message_id = game.mason_night_reminder_message_id
            if chat_id is None or message_id is None:
                return
            try:
                from bot.mason_force_finish_night import (
                    mason_force_finish_button_keyboard,
                )

                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                    reply_markup=mason_force_finish_button_keyboard(game),
                )
                game.mason_night_reminder_last_text = text
            except TelegramBadRequest:
                # message not modified / too old — the counter stays
                # authoritative for the next refresh tick.
                game.mason_night_reminder_last_text = text
        except Exception:
            logger.exception(
                "mason night reminder refresh failed room=%s", game.room_code
            )


async def _send_reminder_if_needed(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    generation: int,
    night_count: int,
    created_at_iso: str,
) -> None:
    async with _lock_for(game.room_code):
        if not _reminder_still_valid(
            game,
            generation=generation,
            night_count=night_count,
            created_at_iso=created_at_iso,
        ):
            return
        from bot.mason_night_ready import all_mason_parallel_night_ready

        if all_mason_parallel_night_ready(game):
            return
        if game.mason_night_reminder_message_id is not None:
            # already sent for this night
            return

        assistant_uid = game.bot_assistant_user_id
        if assistant_uid is None:
            return

        count = collect_mason_night_outstanding_count(game, gm)
        if count <= 0:
            return

        text = build_mason_night_reminder_text(game, count)
        from bot.mason_force_finish_night import mason_force_finish_button_keyboard

        msg = await safe_send_message_return(
            bot,
            assistant_uid,
            text,
            reply_markup=mason_force_finish_button_keyboard(game),
        )
        if msg is None:
            return
        game.mason_night_reminder_chat_id = assistant_uid
        game.mason_night_reminder_message_id = msg.message_id
        game.mason_night_reminder_initial_pending_uids = []
        game.mason_night_reminder_night_count = night_count
        game.mason_night_reminder_last_text = text
        game.mason_night_reminder_created_at_iso = created_at_iso


async def _reminder_timer_job(
    bot: Bot,
    room_code: str,
    *,
    generation: int,
    night_count: int,
    created_at_iso: str,
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
            created_at_iso=created_at_iso,
        )
    except asyncio.CancelledError:
        return
    except Exception:
        logger.exception(
            "mason night reminder timer failed room=%s gen=%s",
            room_code,
            generation,
        )
    finally:
        task = _REMINDER_TASKS.get(room_code)
        current = asyncio.current_task()
        if task is current:
            _REMINDER_TASKS.pop(room_code, None)


def schedule_mason_night_helper_reminder(
    bot: Bot,
    game: Game,
    *,
    delay_sec: float = REMINDER_DELAY_SEC,
) -> None:
    """پس از اتمام ارسال پنل‌های شب — تایمر ۱۲۰ثانیه‌ای برای کمک‌کننده."""
    if not is_mason_scenario(game):
        return
    if game.bot_assistant_user_id is None:
        return

    cancel_mason_night_reminder_task(game.room_code)
    # نسل جدید؛ پیام شب قبل نباید بماند
    game.mason_night_reminder_generation = int(
        game.mason_night_reminder_generation or 0
    ) + 1
    clear_mason_night_reminder_state(game)

    generation = game.mason_night_reminder_generation
    night_count = int(game.bazpors_narrator_night_count)
    created_at_iso = game.created_at.isoformat()
    game.mason_night_reminder_created_at_iso = created_at_iso
    game.mason_night_reminder_night_count = night_count

    task = asyncio.create_task(
        _reminder_timer_job(
            bot,
            game.room_code,
            generation=generation,
            night_count=night_count,
            created_at_iso=created_at_iso,
            delay_sec=delay_sec,
        ),
        name=f"mason_night_reminder:{game.room_code}:{generation}",
    )
    _REMINDER_TASKS[game.room_code] = task


def invalidate_mason_night_reminders_on_restore() -> None:
    """پس از ریستارت سرویس — تایمرهای حافظه از بین رفته‌اند؛ از ارسال کهنه جلوگیری کن."""
    for room in list(_REMINDER_TASKS):
        cancel_mason_night_reminder_task(room)
