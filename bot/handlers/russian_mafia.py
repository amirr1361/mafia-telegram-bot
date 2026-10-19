"""Callbackهای مافیای روسی — جدا از روتر سناریوهای دیگر."""

from __future__ import annotations

from aiogram import Bot, Router
from aiogram.types import CallbackQuery

from bot.app_state import manager
from bot.russian_mafia_flow import handle_host_action, handle_player_action
from bot.russian_mafia_player_role_pick import (
    ROLE_PICK_CB_PREFIX,
    ROLE_PICK_TAKEN_CB_PREFIX,
    handle_player_role_pick_callback,
    handle_player_role_pick_taken_callback,
    parse_role_pick_callback_data,
    parse_role_pick_taken_callback_data,
)
from bot.tg_send import safe_callback_answer

router = Router(name="russian_mafia")


def register_russian_mafia_handlers(dp) -> None:
    dp.include_router(router)


@router.callback_query(
    lambda c: c.data is not None and c.data.startswith(f"{ROLE_PICK_TAKEN_CB_PREFIX}:")
)
async def cb_russian_role_pick_taken(callback: CallbackQuery, bot: Bot) -> None:
    packed = parse_role_pick_taken_callback_data(callback.data or "")
    if packed is None:
        await safe_callback_answer(callback, "دکمه نامعتبر.", show_alert=True)
        return
    room, number = packed
    game = manager.get_game(room)
    if not game or game.scenario_name != "russian_mafia":
        await safe_callback_answer(callback, "این دکمه برای این اتاق نیست.", show_alert=True)
        return
    await handle_player_role_pick_taken_callback(callback, bot, game, number)


@router.callback_query(
    lambda c: c.data is not None and c.data.startswith(f"{ROLE_PICK_CB_PREFIX}:")
)
async def cb_russian_role_pick(callback: CallbackQuery, bot: Bot) -> None:
    packed = parse_role_pick_callback_data(callback.data or "")
    if packed is None:
        await safe_callback_answer(callback, "دکمه نامعتبر.", show_alert=True)
        return
    room, number = packed
    game = manager.get_game(room)
    if not game or game.scenario_name != "russian_mafia":
        await safe_callback_answer(callback, "این دکمه برای این اتاق نیست.", show_alert=True)
        return
    await handle_player_role_pick_callback(callback, bot, game, number)


@router.callback_query(lambda c: c.data is not None and c.data.startswith("rmf:"))
async def cb_russian_player_action(callback: CallbackQuery, bot: Bot) -> None:
    if not callback.data:
        return
    room = callback.data.split(":")[1] if callback.data.count(":") >= 2 else ""
    game = manager.get_game(room)
    if not game or game.scenario_name != "russian_mafia":
        await safe_callback_answer(callback, "این دکمه برای این اتاق نیست.", show_alert=True)
        return
    await handle_player_action(callback, bot, game)


@router.callback_query(lambda c: c.data is not None and c.data.startswith("rmh:"))
async def cb_russian_host_action(callback: CallbackQuery, bot: Bot) -> None:
    if not callback.data:
        return
    room = callback.data.split(":")[1] if callback.data.count(":") >= 2 else ""
    game = manager.get_game(room)
    if not game or game.scenario_name != "russian_mafia":
        await safe_callback_answer(callback, "این دکمه برای این اتاق نیست.", show_alert=True)
        return
    await handle_host_action(callback, bot, game)
