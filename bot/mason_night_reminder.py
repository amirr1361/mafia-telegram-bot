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
from bot.text_fa import fa_digits
from bot.tg_send import safe_send_message_return

if TYPE_CHECKING:
    from bot.game import GameManager

logger = logging.getLogger(__name__)

REMINDER_DELAY_SEC = 60.0

_REMINDER_HEADER = "بازیکن‌های زیر هنوز اکت خودشان را انجام نداده‌اند:\n\n"
_REMINDER_FOOTER = (
    "\n\nبه بازیکن‌های بالا گوشزد کنید که تا زمانی که اکت خودشان را انجام ندهند، "
    "ربات پایان شب را اعلام نمی‌کند."
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
    name = (player.full_name or "").strip()
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


def build_mason_night_reminder_text(
    game: Game,
    initial_uids: list[int],
    *,
    pending_uids: set[int],
) -> str:
    lines: list[str] = []
    for idx, uid in enumerate(initial_uids, start=1):
        player = game.players.get(uid)
        if player is None:
            name = str(uid)
        else:
            name = mason_reminder_display_name(player)
        mark = _DONE_MARK if uid not in pending_uids else ""
        lines.append(f"{fa_digits(idx)}- {name}{mark}")
    return _REMINDER_HEADER + "\n".join(lines) + _REMINDER_FOOTER


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
    """پس از تأیید اکت — ویرایش/حذف یادآور (event-driven)."""
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

            initial = list(game.mason_night_reminder_initial_pending_uids)
            if not initial:
                await _delete_reminder_message(bot, game)
                return

            pending = set(collect_mason_night_pending_holder_uids(game, gm))
            if not any(uid in pending for uid in initial):
                await _delete_reminder_message(bot, game)
                return

            text = build_mason_night_reminder_text(
                game, initial, pending_uids=pending
            )
            if text == game.mason_night_reminder_last_text:
                return
            chat_id = game.mason_night_reminder_chat_id
            message_id = game.mason_night_reminder_message_id
            if chat_id is None or message_id is None:
                return
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=text,
                )
                game.mason_night_reminder_last_text = text
            except TelegramBadRequest as exc:
                # پیام حذف‌شده یا بدون تغییر
                msg = str(exc).lower()
                if "message is not modified" in msg:
                    game.mason_night_reminder_last_text = text
                    return
                if "message to edit not found" in msg or "message can't be edited" in msg:
                    clear_mason_night_reminder_state(game)
                    return
                logger.info(
                    "mason night reminder edit ignored room=%s err=%s",
                    game.room_code,
                    exc,
                )
            except TelegramForbiddenError:
                clear_mason_night_reminder_state(game)
            except Exception:
                logger.exception(
                    "mason night reminder edit failed room=%s", game.room_code
                )
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

        pending = collect_mason_night_pending_holder_uids(game, gm)
        if not pending:
            return

        text = build_mason_night_reminder_text(
            game, pending, pending_uids=set(pending)
        )
        msg = await safe_send_message_return(bot, assistant_uid, text)
        if msg is None:
            return
        game.mason_night_reminder_chat_id = assistant_uid
        game.mason_night_reminder_message_id = msg.message_id
        game.mason_night_reminder_initial_pending_uids = list(pending)
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
    """پس از اتمام ارسال پنل‌های شب — تایمر ۶۰ثانیه‌ای برای کمک‌کننده."""
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
