"""Mason (masoon) player-selected role-number distribution."""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from bot.mason_roles import masoon_roles_for_count
from bot.models import Game, Role
from bot.player_role_pick_common import (
    CLAIM_SOURCE_AUTOMATIC_NON_REAL,
    CLAIM_SOURCE_PLAYER,
    RolePickProfile,
    all_real_players_have_selected,
    auto_assign_remaining_numbers_to_non_real as _auto_assign,
    available_number_button_text,
    build_role_pick_keyboard as _build_kb,
    claimed_number_button_text,
    dispatch_player_role_pick_panels as _dispatch,
    handle_player_role_pick_callback as _handle_claim,
    handle_player_role_pick_taken_callback as _handle_taken,
    inline_button_supports_style,
    parse_prefixed_role_pick_callback,
    real_player_uids,
    non_real_player_uids,
    start_player_role_pick as _start,
)

ROLE_PICK_CB_PREFIX = "msrp"
ROLE_PICK_TAKEN_CB_PREFIX = "msrp_taken"


def _assign_mason(gm, game: Game, role_by_player: dict[int, Role]) -> None:
    gm.assign_mason_roles_by_player(game, role_by_player)


MASON_ROLE_PICK = RolePickProfile(
    scenario_name="masoon",
    log_label="Mason",
    cb_prefix=ROLE_PICK_CB_PREFIX,
    taken_cb_prefix=ROLE_PICK_TAKEN_CB_PREFIX,
    state_prefix="mason",
    roles_for_count=masoon_roles_for_count,
    assign_by_player=_assign_mason,
    reveal_via_private_role=True,
)


def all_real_mason_players_have_selected(game: Game) -> bool:
    return all_real_players_have_selected(MASON_ROLE_PICK, game)


def parse_role_pick_callback_data(data: str) -> tuple[str, int] | None:
    return parse_prefixed_role_pick_callback(data, prefix=ROLE_PICK_CB_PREFIX)


def parse_role_pick_taken_callback_data(data: str) -> tuple[str, int] | None:
    return parse_prefixed_role_pick_callback(
        data, prefix=ROLE_PICK_TAKEN_CB_PREFIX
    )


def build_role_pick_keyboard(game: Game) -> InlineKeyboardMarkup:
    return _build_kb(MASON_ROLE_PICK, game)


def auto_assign_remaining_numbers_to_non_real(game: Game) -> bool:
    return _auto_assign(MASON_ROLE_PICK, game)


def start_player_role_pick(game: Game) -> str | None:
    return _start(MASON_ROLE_PICK, game)


async def dispatch_player_role_pick_panels(bot: Bot, game: Game) -> None:
    await _dispatch(MASON_ROLE_PICK, bot, game)


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
    await _handle_claim(MASON_ROLE_PICK, callback, bot, game, number)
