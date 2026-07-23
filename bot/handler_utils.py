"""ابزارهای مشترک هندلرها."""

from __future__ import annotations

from aiogram.enums import ChatType
from aiogram.types import Message


def require_private(msg: Message) -> bool:
    return msg.chat.type == ChatType.PRIVATE
