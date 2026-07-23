"""هندلرهای /endgame و callback انتخاب برنده."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.app_state import manager
from bot.post_game_flow import (
    ENDGAME_ABORT_CONFIRM_HTML,
    EndGameAbortConfirm,
    EndGameDismiss,
    EndGamePick,
    abort_game_without_result,
    endgame_abort_confirm_keyboard,
    endgame_winner_keyboard,
    finalize_game_winner,
    host_endgame_needs_abort_confirm,
    resolve_game_context,
    user_may_act_as_game_host,
)
from bot.observer_delivery import game_observer_mirror_active

logger = logging.getLogger(__name__)

router = Router(name="post_game")


def _require_private(msg: Message) -> bool:
    return msg.chat.type == ChatType.PRIVATE


def register_post_game_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)


@router.message(Command("endgame"))
async def end_cmd(msg: Message, bot: Bot) -> None:
    if not _require_private(msg):
        return
    if not msg.from_user:
        return
    room, _, is_host = resolve_game_context(msg.from_user.id)
    if not room or not is_host:
        await msg.answer("فقط گرداننده می‌تواند پایان دهد.")
        return
    game = manager.get_game(room)
    if not game:
        return
    if host_endgame_needs_abort_confirm(game):
        await msg.answer(
            ENDGAME_ABORT_CONFIRM_HTML,
            parse_mode="HTML",
            reply_markup=endgame_abort_confirm_keyboard(game),
        )
        return
    if not game.host_may_pick_winner:
        game.host_may_pick_winner = True
    await msg.answer(
        "پایان بازی ثبت شود.\n"
        "لطفاً مشخص کنید کدام تیم برنده شد:",
        reply_markup=endgame_winner_keyboard(game),
    )


@router.callback_query(EndGameAbortConfirm.filter())
async def endgame_abort_confirm_cb(
    callback: CallbackQuery,
    callback_data: EndGameAbortConfirm,
    bot: Bot,
) -> None:
    if not callback.from_user or callback.message is None:
        return
    game = manager.get_game(callback_data.code)
    if not game:
        await callback.answer("اتاق دیگر فعال نیست.", show_alert=True)
        return
    uid = callback.from_user.id
    if not user_may_act_as_game_host(game, uid):
        await callback.answer("فقط گرداننده می‌تواند تأیید کند.", show_alert=True)
        return
    if callback_data.ok != 1:
        await callback.answer("لغو شد.")
        try:
            await callback.message.edit_text(
                "پایان بدون نتیجه لغو شد.",
                reply_markup=None,
            )
        except Exception:
            logger.debug("endgame abort dismiss edit failed", exc_info=True)
        return
    await callback.answer("اتاق بسته شد.")
    try:
        await callback.message.edit_text(
            "✅ بازی بدون نتیجه پایان یافت؛ اتاق بسته شد.",
            reply_markup=None,
        )
    except Exception:
        logger.debug("endgame abort confirm edit failed", exc_info=True)
    await abort_game_without_result(bot, game, actor_uid=uid)


@router.callback_query(EndGamePick.filter())
async def endgame_pick_cb(
    callback: CallbackQuery,
    callback_data: EndGamePick,
    bot: Bot,
) -> None:
    if not callback.from_user:
        return
    game = manager.get_game(callback_data.code)
    if not game:
        await callback.answer("اتاق دیگر فعال نیست.", show_alert=True)
        return
    if game_observer_mirror_active(game) and game.player_end_winner_picker_id:
        await callback.answer(
            "از دکمهٔ همان پیام خودتان استفاده کنید.",
            show_alert=True,
        )
        return
    uid = callback.from_user.id
    if user_may_act_as_game_host(game, uid):
        if not game.host_may_pick_winner:
            await callback.answer(
                "ابتدا دستور /endgame را بزنید؛ بعد می‌توانید با دکمه نتیجه را ثبت کنید.",
                show_alert=True,
            )
            return
    elif uid != (game.player_end_winner_picker_id or -1):
        await callback.answer(
            "فقط گرداننده یا همان بازیکنی که همه برای پایان به او رأی داده‌اند می‌تواند برنده را ثبت کند.",
            show_alert=True,
        )
        return
    winner = callback_data.winner
    if winner not in ("mafia", "citizen"):
        await callback.answer("گزینه نامعتبر.", show_alert=True)
        return
    await finalize_game_winner(bot, game, winner, uid)
    await callback.answer("نتیجه ثبت شد.")


@router.callback_query(EndGameDismiss.filter())
async def endgame_dismiss_cb(
    callback: CallbackQuery,
    callback_data: EndGameDismiss,
) -> None:
    if not callback.from_user or callback.message is None:
        return
    game = manager.get_game(callback_data.code)
    if not game:
        await callback.answer("اتاق دیگر فعال نیست.", show_alert=True)
        return
    uid = callback.from_user.id
    if uid != game.host_id and uid != (game.player_end_winner_picker_id or -1):
        await callback.answer("فقط کسی که باید برنده را ثبت کند.", show_alert=True)
        return
    await callback.answer("ثبت نتیجه لغو شد.")
    if uid == game.host_id:
        game.host_may_pick_winner = False
    try:
        await callback.message.edit_text(
            "✖️ انتخاب برنده لغو شد. هر زمان آماده بودید دوباره /endgame بزنید "
            "یا همان پیام قبلی را باز کنید.",
            reply_markup=None,
        )
    except Exception:
        logger.debug("endgame dismiss edit failed", exc_info=True)
