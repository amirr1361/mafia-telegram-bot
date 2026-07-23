"""پنل انتخاب چندتایی شب — فقط سناریوی ماسون."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.models import Game, Player
from bot.no_host_role_pick_common import (
    build_none_pick_row,
    build_target_button_rows,
)
from bot.observer_delivery import PlayerMirrorCb

if TYPE_CHECKING:
    from bot.game import GameManager

_ORDINALS_FA = ("اول", "دوم", "سوم", "چهارم", "پنجم", "ششم")


def mason_selection_ordinal_fa(index_1based: int) -> str:
    if 1 <= index_1based <= len(_ORDINALS_FA):
        return _ORDINALS_FA[index_1based - 1]
    return str(index_1based)


def build_mason_multi_select_progress_text(
    selected_count: int, max_allowed: int
) -> str:
    return f"انتخاب‌های مجاز شما: {selected_count} از {max_allowed}"


def mason_multi_select_no_more_button_label(next_step_1based: int) -> str:
    ord_fa = mason_selection_ordinal_fa(next_step_1based)
    return f"انتخاب {ord_fa} ندارم"


def mason_multi_select_none_button_label(
    selected_count: int,
    *,
    first_step_label: str,
) -> str:
    """برچسب دکمهٔ «بدون انتخاب بیشتر» برای گام فعلی."""
    if selected_count == 0:
        return first_step_label
    return mason_multi_select_no_more_button_label(selected_count + 1)


def build_mason_selected_players_lines(
    game: Game,
    gm: "GameManager",
    selected_uids: list[int],
    *,
    line_prefix: str = "انتخاب",
) -> str:
    if not selected_uids:
        return ""
    lines: list[str] = []
    for i, uid in enumerate(selected_uids, 1):
        p = game.players.get(uid)
        name = html.escape(gm.format_player_tag(p) if p else str(uid))
        ord_fa = mason_selection_ordinal_fa(i)
        lines.append(f"{line_prefix} {ord_fa}: {name}")
    return "\n".join(lines)


def build_mason_multi_select_panel_text(
    header: str,
    game: Game,
    gm: "GameManager",
    selected_uids: list[int],
    max_allowed: int,
    *,
    line_prefix: str = "انتخاب",
) -> str:
    progress = build_mason_multi_select_progress_text(
        len(selected_uids), max_allowed
    )
    selection_lines = build_mason_selected_players_lines(
        game, gm, selected_uids, line_prefix=line_prefix
    )
    parts = [header, "", progress]
    if selection_lines:
        parts.extend(["", selection_lines])
    return "\n".join(parts)


def append_mason_selection_lines(header: str, selection_lines: str) -> str:
    if not selection_lines:
        return header
    return f"{header}\n\n{selection_lines}"


def filter_player_pool(
    players: list[Player], exclude_uids: set[int] | list[int]
) -> list[Player]:
    excluded = set(exclude_uids)
    return [p for p in players if p.user_id not in excluded]


def build_mason_multi_select_keyboard(
    game: Game,
    as_uid: int,
    *,
    pick_act: str,
    players: list[Player],
    none_act: str | None = None,
    none_text: str | None = None,
    done_act: str | None = None,
    done_text: str | None = None,
) -> InlineKeyboardMarkup:
    rows = build_target_button_rows(
        game,
        as_uid=as_uid,
        pick_act=pick_act,
        players=players,
    )
    if none_act is not None and none_text is not None:
        rows.append(build_none_pick_row(game, as_uid, none_act=none_act, none_text=none_text))
    if done_act is not None and done_text is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text=done_text,
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act=done_act, as_uid=as_uid
                    ).pack(),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)
