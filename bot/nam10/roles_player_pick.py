"""Namayande-10 fork: player-selected role-number distribution (thin adapter).

Mirrors the per-scenario adapters (Bazpors / Mozakere / Mason) on top of the
shared RolePickProfile machinery. Pick state lives on Game fields prefixed
nam10_ so classic Namayande rooms and other scenarios stay untouched.
Callbacks use the fork-exclusive nrp / nrp_taken prefixes.
"""

from __future__ import annotations

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from bot.models import Game, Role
from bot.nam10.lobby import (
    assign_roles_by_player_namayande10,
    roles_for_count,
    sync_synthetic_player_display_names_nam10,
)
from bot.player_role_pick_common import (
    RolePickProfile,
    auto_assign_remaining_numbers_to_non_real as _auto_assign,
    build_role_pick_keyboard as _build_kb,
    dispatch_player_role_pick_panels as _dispatch,
    handle_player_role_pick_callback as _handle_claim,
    handle_player_role_pick_taken_callback as _handle_taken,
    parse_prefixed_role_pick_callback,
    role_pick_active as _profile_active,
    role_pick_callback_data as _cb_data,
    role_pick_taken_callback_data as _taken_cb_data,
    start_player_role_pick as _start,
)

ROLE_PICK_CB_PREFIX = "nrp"
ROLE_PICK_TAKEN_CB_PREFIX = "nrp_taken"


def _assign_nam10(gm, game: Game, role_by_player: dict[int, Role]) -> None:
    assign_roles_by_player_namayande10(game, role_by_player)
    sync_synthetic_player_display_names_nam10(game)


NAM10_ROLE_PICK = RolePickProfile(
    scenario_name="namayande",
    log_label="Namayande10",
    cb_prefix=ROLE_PICK_CB_PREFIX,
    taken_cb_prefix=ROLE_PICK_TAKEN_CB_PREFIX,
    state_prefix="nam10",
    roles_for_count=roles_for_count,
    assign_by_player=_assign_nam10,
    reveal_via_private_role=True,
)


def role_pick_active(game: Game) -> bool:
    return _profile_active(NAM10_ROLE_PICK, game)


def role_pick_callback_data(room_code: str, number: int) -> str:
    return _cb_data(NAM10_ROLE_PICK, room_code, number)


def role_pick_taken_callback_data(room_code: str, number: int) -> str:
    return _taken_cb_data(NAM10_ROLE_PICK, room_code, number)


def parse_role_pick_callback_data(data: str) -> tuple[str, int] | None:
    return parse_prefixed_role_pick_callback(data, prefix=ROLE_PICK_CB_PREFIX)


def parse_role_pick_taken_callback_data(data: str) -> tuple[str, int] | None:
    return parse_prefixed_role_pick_callback(
        data, prefix=ROLE_PICK_TAKEN_CB_PREFIX
    )


def build_role_pick_keyboard(game: Game) -> InlineKeyboardMarkup:
    return _build_kb(NAM10_ROLE_PICK, game)


def auto_assign_remaining_numbers_to_non_real(game: Game) -> bool:
    return _auto_assign(NAM10_ROLE_PICK, game)


def start_player_role_pick(game: Game) -> str | None:
    return _start(NAM10_ROLE_PICK, game)


async def dispatch_player_role_pick_panels(bot: Bot, game: Game) -> None:
    await _dispatch(NAM10_ROLE_PICK, bot, game)


async def handle_player_role_pick_taken_callback(
    callback: CallbackQuery, bot: Bot, game: Game, number: int
) -> None:
    await _handle_taken(callback, bot, game, number)


async def handle_player_role_pick_callback(
    callback: CallbackQuery, bot: Bot, game: Game, number: int
) -> None:
    await _handle_claim(NAM10_ROLE_PICK, callback, bot, game, number)
