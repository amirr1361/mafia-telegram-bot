"""اشتراک مکانیک UI انتخاب نقش — semi_auto / narrator (فاز B).

بدون قوانین نقش‌محور؛ منطق نقش در bot/roles/*.py می‌ماند.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.models import Player

if TYPE_CHECKING:
    from bot.nam10.engine import GameManager


def game_scenario_namayande(code: str) -> bool:
    """Scenario gate for the Namayande button-colour contract.

    The narrator helpers only receive the room code, so resolve the live
    room by code. Non-Namayande rooms keep their previous unstyled output.
    """
    from bot import app_state

    game = app_state.manager.get_game(code)
    return (
        game is not None
        and getattr(game, "scenario_name", None) == "namayande"
    )


def _narr_cb(code: str, act: str, *, tid: int = 0, rid: str = "") -> str:
    from bot.nam10.nmnd_narrator import BazporsNarrCb

    return BazporsNarrCb(code=code, act=act, tid=tid, rid=rid).pack()


def build_narrator_pick_rows(
    code: str,
    act: str,
    players: list[Player],
    gm: "GameManager",
    emoji: str,
    *,
    columns: int = 2,
    label_max_len: int = 14,
) -> list[list[InlineKeyboardButton]]:
    """ردیف‌های انتخاب بازیکن — همان الگوی `_pick_rows` نریتور."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in players:
        lab = gm.format_player_tag(p)[:label_max_len]
        btn = InlineKeyboardButton(
            text=f"{emoji} {lab}",
            callback_data=_narr_cb(code, act, tid=p.user_id),
        )
        # Namayande narrator picks: blue unselected option buttons.
        if game_scenario_namayande(code):
            btn.style = "primary"
        row.append(btn)
        if len(row) >= columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def build_narrator_action_row(
    code: str,
    act: str,
    text: str,
    *,
    tid: int = 0,
    rid: str = "",
) -> list[InlineKeyboardButton]:
    return [
        InlineKeyboardButton(
            text=text,
            callback_data=_narr_cb(code, act, tid=tid, rid=rid),
        )
    ]


def build_narrator_action_keyboard(
    code: str,
    act: str,
    text: str,
    *,
    tid: int = 0,
    rid: str = "",
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[build_narrator_action_row(code, act, text, tid=tid, rid=rid)]
    )


def build_narrator_confirm_back_rows(
    code: str,
    *,
    confirm_act: str,
    confirm_text: str,
    back_act: str,
    back_text: str,
) -> list[list[InlineKeyboardButton]]:
    confirm = InlineKeyboardButton(
        text=confirm_text, callback_data=_narr_cb(code, confirm_act)
    )
    back = InlineKeyboardButton(
        text=back_text, callback_data=_narr_cb(code, back_act)
    )
    # Namayande narrator confirm/back: green confirmation, blue back-nav.
    if game_scenario_namayande(code):
        confirm.style = "success"
        back.style = "primary"
    return [[confirm], [back]]


def build_narrator_labeled_grid_rows(
    code: str,
    act: str,
    items: Iterable[tuple[str, str]],
    *,
    columns: int = 2,
    tid: int = 0,
) -> list[list[InlineKeyboardButton]]:
    """شبکهٔ دکمه با برچسب و rid — مثلاً نقش‌های یاغی."""
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for label, rid in items:
        btn = InlineKeyboardButton(
            text=label,
            callback_data=_narr_cb(code, act, tid=tid, rid=rid),
        )
        if game_scenario_namayande(code):
            btn.style = "primary"
        row.append(btn)
        if len(row) >= columns:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def append_narrator_extra_rows(
    rows: list[list[InlineKeyboardButton]],
    *extra_rows: list[InlineKeyboardButton],
) -> list[list[InlineKeyboardButton]]:
    out = list(rows)
    for extra in extra_rows:
        out.append(extra)
    return out


def build_narrator_pick_keyboard(
    code: str,
    act: str,
    players: list[Player],
    gm: "GameManager",
    emoji: str,
    *extra_rows: list[InlineKeyboardButton],
) -> InlineKeyboardMarkup:
    rows = build_narrator_pick_rows(code, act, players, gm, emoji)
    if extra_rows:
        rows = append_narrator_extra_rows(rows, *extra_rows)
    return InlineKeyboardMarkup(inline_keyboard=rows)
