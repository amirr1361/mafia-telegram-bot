"""اشتراک مکانیک UI انتخاب نقش — فقط no_host (فاز B).

بدون قوانین نقش‌محور؛ منطق نقش در bot/roles/*.py می‌ماند.
"""

from __future__ import annotations

import html
from collections.abc import Callable
from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.game import is_synthetic_player_uid
from bot.models import Game, Player
from bot.observer_delivery import PlayerMirrorCb, no_host_observer_registered, update_mirror_prompt_pair

if TYPE_CHECKING:
    from aiogram import Bot


def player_button_name(p: Player | None, uid: int) -> str:
    if p is None:
        return str(uid)
    return p.full_name or str(uid)


def sort_players_for_pick(players: list[Player]) -> list[Player]:
    return sorted(
        players,
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    )


def default_pick_label(p: Player) -> str:
    return html.escape(player_button_name(p, p.user_id)[:32])


def build_target_button_rows(
    game: Game,
    *,
    as_uid: int,
    pick_act: str,
    players: list[Player],
    label_for_player: Callable[[Player], str] | None = None,
    columns: int = 2,
) -> list[list[InlineKeyboardButton]]:
    label_fn = label_for_player or default_pick_label
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in sort_players_for_pick(players):
        cb = PlayerMirrorCb(
            code=game.room_code, act=pick_act, as_uid=as_uid, tid=p.user_id
        ).pack()
        row.append(InlineKeyboardButton(text=label_fn(p), callback_data=cb))
        if len(row) >= columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def build_none_pick_row(
    game: Game,
    as_uid: int,
    *,
    none_act: str,
    none_text: str,
) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(
            text=none_text,
            callback_data=PlayerMirrorCb(
                code=game.room_code, act=none_act, as_uid=as_uid
            ).pack(),
        )
    ]


def build_pick_keyboard(
    game: Game,
    as_uid: int,
    *,
    pick_act: str,
    players: list[Player],
    none_act: str | None = None,
    none_text: str | None = None,
    label_for_player: Callable[[Player], str] | None = None,
    columns: int = 2,
) -> InlineKeyboardMarkup:
    rows = build_target_button_rows(
        game,
        as_uid=as_uid,
        pick_act=pick_act,
        players=players,
        label_for_player=label_for_player,
        columns=columns,
    )
    if none_act is not None and none_text is not None:
        rows.append(build_none_pick_row(game, as_uid, none_act=none_act, none_text=none_text))
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_confirm_cancel_keyboard(
    game: Game,
    as_uid: int,
    *,
    confirm_act: str,
    back_act: str,
    confirm_text: str,
    back_text: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=confirm_text,
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act=confirm_act, as_uid=as_uid
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text=back_text,
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act=back_act, as_uid=as_uid
                    ).pack(),
                )
            ],
        ]
    )


def build_single_action_keyboard(
    game: Game,
    as_uid: int,
    *,
    act: str,
    text: str,
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=text,
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act=act, as_uid=as_uid
                    ).pack(),
                )
            ]
        ]
    )


def pool_uid_set(players: list[Player]) -> set[int]:
    return {p.user_id for p in players}


def target_in_pool(target_uid: int, players: list[Player]) -> bool:
    return target_uid in pool_uid_set(players)


def actor_may_act_on_role_panel(game: Game, actor_uid: int, role_uid: int) -> bool:
    if actor_uid == role_uid:
        return True
    return bool(
        is_synthetic_player_uid(role_uid)
        and no_host_observer_registered(game)
        and game.observer_user_id == actor_uid
    )


async def sync_role_mirror_panel(
    bot: Bot,
    game: Game,
    ui_key: str,
    role_uid: int,
    text: str,
    kb: InlineKeyboardMarkup | None,
) -> None:
    await update_mirror_prompt_pair(
        bot,
        game,
        ui_key,
        text,
        kb,
        assistant_uid=role_uid,
        parse_mode="HTML",
    )
