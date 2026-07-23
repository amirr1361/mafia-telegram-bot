"""ارسال امن به تلگرام — وقتی کاربر ربات را بلاک کرده خطا ندهد."""

from __future__ import annotations

import logging
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)


async def safe_send_message_return(
    bot: Bot, chat_id: int, text: str, **kwargs: Any
) -> Message | None:
    """پیام خصوصی؛ در موفقیت شیء Message برمی‌گرداند."""
    delete_after_sec = kwargs.pop("delete_after_sec", None)
    try:
        msg = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
    except TelegramForbiddenError:
        logger.info("send_message forbidden chat_id=%s (user blocked bot)", chat_id)
        return None
    except TelegramBadRequest:
        return None
    if msg is not None and delete_after_sec:
        from bot.no_host_ephemeral import schedule_no_host_ephemeral_delete

        schedule_no_host_ephemeral_delete(
            bot, chat_id, msg.message_id, delay_sec=float(delete_after_sec)
        )
    return msg


async def safe_send_message(bot: Bot, chat_id: int, text: str, **kwargs: Any) -> bool:
    """پیام خصوصی؛ اگر کاربر ربات را بلاک کرده False برمی‌گرداند."""
    return (await safe_send_message_return(bot, chat_id, text, **kwargs)) is not None


async def safe_send_photo_return(
    bot: Bot,
    chat_id: int,
    photo: Any,
    *,
    caption: str | None = None,
    **kwargs: Any,
) -> Message | None:
    """ارسال عکس؛ در موفقیت Message برمی‌گرداند."""
    try:
        return await bot.send_photo(
            chat_id=chat_id, photo=photo, caption=caption, **kwargs
        )
    except TelegramForbiddenError:
        logger.info("send_photo forbidden chat_id=%s (user blocked bot)", chat_id)
        return None
    except TelegramBadRequest:
        return None


async def safe_send_photo(
    bot: Bot,
    chat_id: int,
    photo: Any,
    *,
    caption: str | None = None,
    **kwargs: Any,
) -> bool:
    return (
        await safe_send_photo_return(
            bot, chat_id, photo, caption=caption, **kwargs
        )
    ) is not None


async def safe_message_answer(msg: Message, text: str, **kwargs: Any) -> bool:
    """پاسخ به پیام کاربر؛ بلاک را بدون کرش نادیده می‌گیرد."""
    try:
        await msg.answer(text, **kwargs)
        return True
    except TelegramForbiddenError:
        uid = msg.from_user.id if msg.from_user else "?"
        logger.info("message.answer forbidden user_id=%s (user blocked bot)", uid)
        return False
    except TelegramBadRequest:
        return False


async def safe_callback_answer(
    callback: CallbackQuery,
    text: str | None = None,
    *,
    show_alert: bool = False,
) -> bool:
    """پاسخ به callback؛ اگر query منقضی شده بود خطا ندهد (مثلاً بعد از عمل طولانی)."""
    try:
        await callback.answer(text=text, show_alert=show_alert)
        return True
    except TelegramBadRequest as err:
        low = str(err).lower()
        if (
            "query is too old" in low
            or "response timeout expired" in low
            or "query id is invalid" in low
        ):
            return False
        raise
