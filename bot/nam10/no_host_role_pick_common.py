"""اشتراک مکانیک UI انتخاب نقش — فقط no_host (فاز B).

بدون قوانین نقش‌محور؛ منطق نقش در bot/roles/*.py می‌ماند.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.nam10.engine import is_synthetic_player_uid
from bot.models import Game, Player
from bot.observer_delivery import PlayerMirrorCb, no_host_observer_registered as nam10_observer_registered, update_mirror_prompt_pair

if TYPE_CHECKING:
    from aiogram import Bot


def player_button_name(
    p: Player | None, uid: int, display_name: str | None = None
) -> str:
    """Player label for selection buttons.

    Display-name priority: custom /myname name first (explicit
    ``display_name`` or the singleton-manager lookup), then the Telegram
    full name, then the numeric id.
    """
    if display_name is not None:
        return display_name or str(uid)
    if p is None:
        return str(uid)
    from bot.app_state import custom_display_name

    custom = custom_display_name(uid)
    if custom is not None:
        return custom
    return p.full_name or str(uid)


def sort_players_for_pick(players: list[Player]) -> list[Player]:
    return sorted(
        players,
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    )


def default_pick_label(p: Player, display_name: str | None = None) -> str:
    return html.escape(player_button_name(p, p.user_id, display_name)[:32])


def build_target_button_rows(
    game: Game,
    *,
    as_uid: int,
    pick_act: str,
    players: list[Player],
    label_for_player: Callable[[Player], str] | None = None,
    columns: int = 2,
    selected_uids: Iterable[int] | None = None,
    display_names: Mapping[int, str] | None = None,
) -> list[list[InlineKeyboardButton]]:
    _custom_names = display_names or {}
    if label_for_player is not None:
        label_fn = label_for_player
    else:
        def label_fn(p: Player) -> str:
            # Default label: custom /myname name wins over Telegram name.
            return default_pick_label(p, _custom_names.get(p.user_id))
    # Namayande cosmetic styling: blue unselected picks, red selected uid(s).
    nmnd_style = game.scenario_name == "namayande"
    selected = frozenset(selected_uids) if selected_uids is not None else frozenset()
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in sort_players_for_pick(players):
        cb = PlayerMirrorCb(
            code=game.room_code, act=pick_act, as_uid=as_uid, tid=p.user_id
        ).pack()
        btn = InlineKeyboardButton(text=label_fn(p), callback_data=cb)
        if nmnd_style:
            btn.style = "danger" if p.user_id in selected else "primary"
        row.append(btn)
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
    selected_uids: Iterable[int] | None = None,
    display_names: Mapping[int, str] | None = None,
) -> InlineKeyboardMarkup:
    rows = build_target_button_rows(
        game,
        as_uid=as_uid,
        pick_act=pick_act,
        players=players,
        label_for_player=label_for_player,
        columns=columns,
        selected_uids=selected_uids,
        display_names=display_names,
    )
    if none_act is not None and none_text is not None:
        row = build_none_pick_row(game, as_uid, none_act=none_act, none_text=none_text)
        if game.scenario_name == "namayande":
            for btn in row:
                btn.style = "primary"
        rows.append(row)
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
    kb = InlineKeyboardMarkup(
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
    if game.scenario_name == "namayande":
        # Green (success) final confirmation, blue (primary) back-nav.
        for btn in kb.inline_keyboard[0]:
            btn.style = "success"
        for row in kb.inline_keyboard[1:]:
            for btn in row:
                btn.style = "primary"
    return kb


def build_single_action_keyboard(
    game: Game,
    as_uid: int,
    *,
    act: str,
    text: str,
) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(
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
    if game.scenario_name == "namayande":
        for row in kb.inline_keyboard:
            for btn in row:
                btn.style = "primary"
    return kb


def apply_bazpors_panel_styles(
    game: Game,
    kb: InlineKeyboardMarkup,
    *,
    pick_acts: Iterable[str] = (),
    selected_uids: Iterable[int] = (),
    ok_acts: Iterable[str] = (),
    green_acts: Iterable[str] = (),
) -> InlineKeyboardMarkup:
    """Namayande cosmetic styling for hand-rolled role-panel keyboards.

    Buttons whose callback act is in `pick_acts` become blue (primary); those
    whose PlayerMirrorCb target id is in `selected_uids` become red
    (danger). Acts in `ok_acts` (back/ok/nav) become blue (primary); acts in
    `green_acts` (final confirmations) become green (success). Any other
    button is left untouched. Non-Namayande scenarios are returned unmodified.
    """
    if game.scenario_name != "namayande":
        return kb
    picks = frozenset(pick_acts)
    selected = frozenset(selected_uids)
    oks = frozenset(ok_acts)
    greens = frozenset(green_acts)
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data is None:
                continue
            try:
                cb = PlayerMirrorCb.unpack(btn.callback_data)
            except Exception:
                continue
            if cb.act in picks:
                btn.style = "danger" if (cb.tid and cb.tid in selected) else "primary"
            elif cb.act in greens:
                btn.style = "success"
            elif cb.act in oks:
                btn.style = "primary"
    return kb


def pool_uid_set(players: list[Player]) -> set[int]:
    return {p.user_id for p in players}


def target_in_pool(target_uid: int, players: list[Player]) -> bool:
    return target_uid in pool_uid_set(players)


def actor_may_act_on_role_panel(game: Game, actor_uid: int, role_uid: int) -> bool:
    if actor_uid == role_uid:
        return True
    return bool(
        is_synthetic_player_uid(role_uid)
        and nam10_observer_registered(game)
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
