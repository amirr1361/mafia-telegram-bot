"""انتخاب شمارهٔ نقش برای مافیای روسی — روی هستهٔ مشترک."""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from bot.models import Game, Role
from bot.player_role_pick_common import (
    RolePickProfile,
    all_real_players_have_selected,
    auto_assign_remaining_numbers_to_non_real as _auto_assign,
    build_role_pick_keyboard as _build_kb,
    dispatch_player_role_pick_panels as _dispatch,
    handle_player_role_pick_callback as _handle_claim,
    handle_player_role_pick_taken_callback as _handle_taken,
    parse_prefixed_role_pick_callback,
    start_player_role_pick as _start,
)
from bot.russian_mafia import russian_roles_for_count

ROLE_PICK_CB_PREFIX = "rrp"
ROLE_PICK_TAKEN_CB_PREFIX = "rrp_taken"


def _assign_russian(gm, game: Game, role_by_player: dict[int, Role]) -> None:
    gm.assign_russian_mafia_roles_by_player(game, role_by_player)


RUSSIAN_ROLE_PICK = RolePickProfile(
    scenario_name="russian_mafia",
    log_label="Russian Mafia",
    cb_prefix=ROLE_PICK_CB_PREFIX,
    taken_cb_prefix=ROLE_PICK_TAKEN_CB_PREFIX,
    state_prefix="russian_mafia",
    roles_for_count=russian_roles_for_count,
    assign_by_player=_assign_russian,
    reveal_via_private_role=True,
)


def parse_role_pick_callback_data(data: str) -> tuple[str, int] | None:
    return parse_prefixed_role_pick_callback(data, prefix=ROLE_PICK_CB_PREFIX)


def parse_role_pick_taken_callback_data(data: str) -> tuple[str, int] | None:
    return parse_prefixed_role_pick_callback(
        data, prefix=ROLE_PICK_TAKEN_CB_PREFIX
    )


def build_role_pick_keyboard(game: Game) -> InlineKeyboardMarkup:
    return _build_kb(RUSSIAN_ROLE_PICK, game)


def auto_assign_remaining_numbers_to_non_real(game: Game) -> bool:
    return _auto_assign(RUSSIAN_ROLE_PICK, game)


def all_real_russian_players_have_selected(game: Game) -> bool:
    return all_real_players_have_selected(RUSSIAN_ROLE_PICK, game)


def start_player_role_pick(game: Game) -> str | None:
    return _start(RUSSIAN_ROLE_PICK, game)


async def dispatch_player_role_pick_panels(bot: Bot, game: Game) -> None:
    await _dispatch(RUSSIAN_ROLE_PICK, bot, game)


async def handle_player_role_pick_taken_callback(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    number: int,
) -> None:
    await _handle_taken(callback, bot, game, number)


async def handle_player_role_pick_callback(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    number: int,
) -> None:
    await _handle_claim(RUSSIAN_ROLE_PICK, callback, bot, game, number)
