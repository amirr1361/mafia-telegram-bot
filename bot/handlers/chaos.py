"""Handler router: chaos."""

from __future__ import annotations

import logging

from aiogram import Bot, Router
from aiogram.types import CallbackQuery

from bot.app_state import manager
from bot.chaos_handshake import ChaosHandshakeCb, handle_chaos_handshake_pick
from bot.tg_send import safe_callback_answer

logger = logging.getLogger(__name__)
router = Router(name="chaos")


def register_chaos_handlers(dp) -> None:
    dp.include_router(router)


@router.callback_query(ChaosHandshakeCb.filter())
async def chaos_handshake_player_cb(
    callback: CallbackQuery,
    callback_data: ChaosHandshakeCb,
    bot: Bot,
) -> None:
    if not callback.from_user or not callback.message:
        return
    game = manager.get_game(callback_data.code)
    if not game:
        await safe_callback_answer(callback, "اتاق دیگر فعال نیست.", show_alert=True)
        return
    await handle_chaos_handshake_pick(
        bot,
        game,
        manager,
        chooser_uid=callback_data.ch,
        target_uid=callback_data.tgt,
        round_no=callback_data.rnd,
        actor_uid=callback.from_user.id,
        callback=callback,
    )
