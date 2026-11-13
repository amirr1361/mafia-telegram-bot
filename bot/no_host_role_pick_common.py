"""اشتراک مکانیک UI انتخاب نقش — فقط no_host (فاز B).

بدون قوانین نقش‌محور؛ منطق نقش در bot/roles/*.py می‌ماند.
"""

from __future__ import annotations

import html
from collections.abc import Callable, Iterable, Mapping
from typing import TYPE_CHECKING

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.game import is_synthetic_player_uid
from bot.models import Game, Player
from bot.observer_delivery import PlayerMirrorCb, no_host_observer_registered, update_mirror_prompt_pair

if TYPE_CHECKING:
    from aiogram import Bot


def panel_style_scheme(game: Game) -> str | None:
    """Scenario-scoped cosmetic button styling scheme (no behaviour change).

    Unified redesign contract for Bazpors and Mozakere (Part C): red
    (danger) for the selected/tentative target, blue (primary) for
    everything unselected, and a green (success) inline confirm button
    visible from the initial panel rendering — confirm commits only.
    Every other scenario: None (buttons left unstyled) unless the call
    site passes an explicit `selected_style` override (the Mason target
    panels pass "danger" — red selected, blue otherwise).
    """
    from bot.room_mode import is_mozakere_scenario

    if game.scenario_name == "bazpors":
        return "bazpors"
    if is_mozakere_scenario(game):
        return "mozakere"
    return None


def _panel_selected_style(game: Game) -> str | None:
    scheme = panel_style_scheme(game)
    if scheme == "bazpors":
        return "danger"
    if scheme == "mozakere":
        return "danger"
    return None


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
    selected_style: str | None = None,
    scenario_styles: bool = True,
    display_names: Mapping[int, str] | None = None,
) -> list[list[InlineKeyboardButton]]:
    _custom_names = display_names or {}
    if label_for_player is not None:
        label_fn = label_for_player
    else:
        def label_fn(p: Player) -> str:
            # Default label: custom /myname name wins over Telegram name.
            return default_pick_label(p, _custom_names.get(p.user_id))
    # Scenario-scoped cosmetic styling: blue unselected player buttons and
    # red for the selected/tentative target (Bazpors + Mozakere). Mason call
    # sites pass `selected_style="danger"` explicitly (red selected).
    # scenario_styles=False → panels outside the mozakere redesign keep
    # their previous unstyled buttons completely unchanged.
    selected_style = selected_style or (
        _panel_selected_style(game) if scenario_styles else None
    )
    selected = frozenset(selected_uids) if selected_uids is not None else frozenset()
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for p in sort_players_for_pick(players):
        cb = PlayerMirrorCb(
            code=game.room_code, act=pick_act, as_uid=as_uid, tid=p.user_id
        ).pack()
        btn = InlineKeyboardButton(text=label_fn(p), callback_data=cb)
        if selected_style is not None:
            btn.style = selected_style if p.user_id in selected else "primary"
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
    none_selected: bool = False,
    scenario_styles: bool = True,
    display_names: Mapping[int, str] | None = None,
) -> InlineKeyboardMarkup:
    # scenario_styles=False → پنل‌هایی که بازطراحی مذاکره ندارند (مثل
    # پنل شکارچی) کاملاً بدون استایل قبلی می‌مانند؛ قرارداد بازپرس حفظ می‌شود.
    rows = build_target_button_rows(
        game,
        as_uid=as_uid,
        pick_act=pick_act,
        players=players,
        label_for_player=label_for_player,
        columns=columns,
        selected_uids=selected_uids,
        scenario_styles=scenario_styles,
        display_names=display_names,
    )
    if none_act is not None and none_text is not None:
        row = build_none_pick_row(game, as_uid, none_act=none_act, none_text=none_text)
        if game.scenario_name == "bazpors":
            # «انتخابی ندارم» هم یک گزینهٔ عادی است: آبی، و قرمز وقتی
            # انتخاب موقتِ هیچ (tentative none) فعال است.
            for btn in row:
                btn.style = (
                    _panel_selected_style(game) if none_selected else "primary"
                )
        elif scenario_styles:
            scheme = panel_style_scheme(game)
            if scheme is not None:
                style = (
                    _panel_selected_style(game)
                    if none_selected
                    else "primary"
                )
                for btn in row:
                    btn.style = style
        rows.append(row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


MOZAKERE_CONFIRM_LABEL = "✅ تأیید انتخاب"


def mozakere_confirm_label(game: Game) -> str:
    from bot.room_mode import is_mozakere_scenario

    if is_mozakere_scenario(game) or game.scenario_name == "bazpors":
        return MOZAKERE_CONFIRM_LABEL
    return "✅ تأیید"


def append_pending_selection_line(base_html: str, lines: list[str]) -> str:
    if not lines:
        return base_html
    return base_html + "\n\n" + "\n".join(lines)


def with_inline_confirm_row(
    game: Game,
    as_uid: int,
    base_kb: InlineKeyboardMarkup,
    *,
    confirm_act: str,
    confirm_text: str | None = None,
    style: str | None = None,
) -> InlineKeyboardMarkup:
    """پنل انتخاب با ردیف تأیید در همان صفحه (مذاکره + بازپرس).

    Inline green confirm visible from the initial panel rendering for
    Bazpors (style="success"); Mozakere keeps its blue primary confirm.
    `style=None` → scenario default: green for Bazpors, blue otherwise.
    """
    rows = [list(row) for row in base_kb.inline_keyboard]
    rows.append(
        [
            InlineKeyboardButton(
                text=confirm_text or mozakere_confirm_label(game),
                callback_data=PlayerMirrorCb(
                    code=game.room_code, act=confirm_act, as_uid=as_uid
                ).pack(),
            )
        ]
    )
    kb = InlineKeyboardMarkup(inline_keyboard=rows)
    if style is None:
        style = "success" if game.scenario_name == "bazpors" else "primary"
    for btn in kb.inline_keyboard[-1]:
        btn.style = style
    return kb


def build_confirm_cancel_keyboard(    game: Game,
    as_uid: int,
    *,
    confirm_act: str,
    back_act: str,
    confirm_text: str,
    back_text: str,
    scenario_styles: bool = True,
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
    if game.scenario_name == "bazpors":
        for row in kb.inline_keyboard:
            for btn in row:
                btn.style = "primary"
    elif scenario_styles and panel_style_scheme(game) is not None:
        for row in kb.inline_keyboard:
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
    if game.scenario_name == "bazpors":
        # قرارداد قدیمی بازپرس — آبی. سناریوهای دیگر (از جمله پنل‌های
        # اوکی یک‌ضرب مذاکره) بدون استایل قبلی می‌مانند.
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
    selected_style: str | None = None,
    selected_acts: Iterable[str] = (),
) -> InlineKeyboardMarkup:
    """Scenario-scoped cosmetic styling for hand-rolled role-panel keyboards.

    Unified redesign contract: selected targets red (danger), others blue
    (primary) — for Bazpors, Mozakere and Mason (masoon). Buttons whose
    callback act is in `pick_acts` are player-target buttons; those whose
    PlayerMirrorCb target id is in `selected_uids` are the selected ones.
    Acts in `selected_acts` are action/choice toggles (no target id) whose
    buttons are shown red when their act is the pending selection (e.g.
    mafia menu actions, NATO role choices). Acts in `ok_acts`
    (confirm/back/ok/nav) become blue. Any other button is left untouched.
    Every other scenario is returned unmodified.
    """
    from bot.room_mode import is_mozakere_scenario

    if (
        game.scenario_name != "bazpors"
        and not is_mozakere_scenario(game)
        and selected_style is None
    ):
        return kb
    if selected_style is None:
        selected_style = "danger"
    picks = frozenset(pick_acts)
    selected = frozenset(selected_uids)
    oks = frozenset(ok_acts)
    act_selected = frozenset(selected_acts)
    for row in kb.inline_keyboard:
        for btn in row:
            if btn.callback_data is None:
                continue
            try:
                cb = PlayerMirrorCb.unpack(btn.callback_data)
            except Exception:
                continue
            if cb.act in picks:
                btn.style = (
                    selected_style if (cb.tid and cb.tid in selected) else "primary"
                )
            elif cb.act in act_selected:
                btn.style = selected_style if cb.act in act_selected else "primary"
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


def mirror_panel_superseded(
    game: Game, ui_key: str, message_id: int | None
) -> bool:
    """True when a tracked panel exists for ui_key but the pressed
    message is not the currently tracked one (a superseded/stale panel).

    When no refs are tracked at all the check passes (previous behavior
    is preserved for edge delivery paths).
    """
    if message_id is None:
        return False
    entry = game.mirror_prompt_messages.get(ui_key)
    if not isinstance(entry, dict):
        return False
    live_ids: list[int] = []
    for role in ("player", "observer"):
        ref = entry.get(role)
        if isinstance(ref, tuple) and len(ref) >= 2:
            live_ids.append(int(ref[1]))
    if not live_ids:
        return False
    return message_id not in live_ids


async def close_mirror_panel_refs(bot: "Bot", game: Game, ui_key: str) -> int:
    """Close (delete, or strip the keyboard when deletion fails) the
    tracked player/observer panel messages of ui_key BEFORE it is
    replaced, so old refs are never silently overwritten and no stale
    actionable keyboard survives. Returns the number of messages closed.
    """
    from bot.bazpors_night_panel_purge import _try_delete_panel_message

    entry = game.mirror_prompt_messages.pop(ui_key, None)
    if not isinstance(entry, dict):
        return 0
    closed = 0
    for role in ("player", "observer"):
        ref = entry.get(role)
        if not (isinstance(ref, tuple) and len(ref) >= 2):
            continue
        chat_id, message_id = int(ref[0]), int(ref[1])
        try:
            if await _try_delete_panel_message(bot, chat_id, message_id):
                closed += 1
        except Exception:
            pass
    return closed
