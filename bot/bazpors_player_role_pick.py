"""Bazpors player-selected role-number distribution — thin scenario adapter."""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from bot.game import bazpors_roles_for_count
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
    is_real_player_uid,
    non_real_player_uids,
    parse_prefixed_role_pick_callback,
    real_player_uids,
    role_pick_callback_data as _cb_data,
    role_pick_taken_callback_data as _taken_cb_data,
    start_player_role_pick as _start,
)

ROLE_PICK_CB_PREFIX = "brp"
ROLE_PICK_TAKEN_CB_PREFIX = "brp_taken"


def _assign_bazpors(gm, game: Game, role_by_player: dict[int, Role]) -> None:
    gm.assign_bazpors_roles_by_player(game, role_by_player)


BAZPORS_ROLE_PICK = RolePickProfile(
    scenario_name="bazpors",
    log_label="Bazpors",
    cb_prefix=ROLE_PICK_CB_PREFIX,
    taken_cb_prefix=ROLE_PICK_TAKEN_CB_PREFIX,
    state_prefix="bazpors",
    roles_for_count=bazpors_roles_for_count,
    assign_by_player=_assign_bazpors,
    reveal_via_private_role=False,
)


def is_real_bazpors_player_uid(user_id: int) -> bool:
    return is_real_player_uid(user_id)


def real_bazpors_player_uids(game: Game) -> list[int]:
    return real_player_uids(game)


def non_real_bazpors_player_uids(game: Game) -> list[int]:
    return non_real_player_uids(game)


def all_real_bazpors_players_have_selected(game: Game) -> bool:
    return all_real_players_have_selected(BAZPORS_ROLE_PICK, game)


def role_pick_callback_data(room_code: str, number: int) -> str:
    return _cb_data(BAZPORS_ROLE_PICK, room_code, number)


def role_pick_taken_callback_data(room_code: str, number: int) -> str:
    return _taken_cb_data(BAZPORS_ROLE_PICK, room_code, number)


def parse_role_pick_callback_data(data: str) -> tuple[str, int] | None:
    return parse_prefixed_role_pick_callback(data, prefix=ROLE_PICK_CB_PREFIX)


def parse_role_pick_taken_callback_data(data: str) -> tuple[str, int] | None:
    return parse_prefixed_role_pick_callback(
        data, prefix=ROLE_PICK_TAKEN_CB_PREFIX
    )


def build_role_pick_keyboard(game: Game) -> InlineKeyboardMarkup:
    return _build_kb(BAZPORS_ROLE_PICK, game)


def auto_assign_remaining_numbers_to_non_real(game: Game) -> bool:
    return _auto_assign(BAZPORS_ROLE_PICK, game)


def start_player_role_pick(game: Game) -> str | None:
    return _start(BAZPORS_ROLE_PICK, game)


async def dispatch_player_role_pick_panels(bot: Bot, game: Game) -> None:
    await _dispatch(BAZPORS_ROLE_PICK, bot, game)


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
    await _handle_claim(BAZPORS_ROLE_PICK, callback, bot, game, number)
