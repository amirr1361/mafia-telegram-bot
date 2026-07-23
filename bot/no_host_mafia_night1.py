"""شب ۱ — انتخاب عملیات تیم مافیا (حالت بدون گرداننده)."""

from __future__ import annotations

import asyncio
import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.bazpors_narrator import (
    NS_MAFIA_SHOT,
    NS_NATO_ROLE,
    NS_YAKU_SAC,
    _alive,
    _night_title_fa,
    _visually_mafia,
    mafia_shot_allowed,
    nato_can_register,
    push_host_step,
    yakuzai_allowed,
)
from bot.game import is_synthetic_player_uid
from bot.models import Game, Role
from bot.roles.registry import find_alive_role_holder
from bot.no_host_mafia_chooser import (
    _alive_mafia_members,
    _yaku_recruit_panel_fallback,
    maybe_start_shiad_parallel_night_panels,
    resolve_mafia_night1_panel_recipients,
    resolve_mafia_shot_chooser,
    should_start_shiad_direct_shot_menu,
)
from bot.observer_delivery import (
    PlayerMirrorCb,
    apply_mirror_claim_winner,
    deliver_no_host_player_game_copy,
    mirror_ui_claim_key,
    no_host_observer_registered,
    player_should_receive_game_messages,
    publish_mirror_prompt_pair,
    update_mirror_prompt_pair,
)
from bot.room_mode import is_mason_scenario, is_mozakere_scenario
if TYPE_CHECKING:
    from bot.game import GameManager

MAFIA_ACTION_SHOT = "shot"
MAFIA_ACTION_YAKU = "yaku"
MAFIA_ACTION_NATO = "nato"
MAFIA_ACTION_NEGOTIATE = "negotiate"

_ACTION_LABELS: dict[str, str] = {
    MAFIA_ACTION_SHOT: "🔫 شات کردن",
    MAFIA_ACTION_YAKU: "🩸 یاکوزایی کردن",
    MAFIA_ACTION_NATO: "🎭 ناتویی کردن",
    MAFIA_ACTION_NEGOTIATE: "🤝 مذاکره کردن",
}

_MASON_ACTION_LABELS: dict[str, str] = {
    MAFIA_ACTION_SHOT: "🔫 شلیک",
    MAFIA_ACTION_NATO: "🎭 ناتویی",
}


def _action_label(game: Game, action: str) -> str:
    if is_mason_scenario(game):
        return _MASON_ACTION_LABELS.get(action, _ACTION_LABELS.get(action, action))
    return _ACTION_LABELS.get(action, action)


def resolve_mafia_night1_chooser(game: Game):
    """اولین عضو لیست دریافت‌کنندگان پنل (سازگاری با کد قدیمی)."""
    recipients = resolve_mafia_night1_panel_recipients(game)
    return recipients[0] if recipients else None


def _mafia_panel_has_uid(game: Game, mafia_uid: int) -> bool:
    return mafia_uid in game.no_host_mafia_night1_panel_uids


def mafia_night1_expected_panel_uids(game: Game) -> list[int]:
    recipients = resolve_mafia_night1_panel_recipients(game)
    return [
        p.user_id
        for p in recipients
        if player_should_receive_game_messages(game, p.user_id)
    ]


def mafia_night1_panel_delivered(game: Game, mafia_uid: int) -> bool:
    if mafia_uid not in game.no_host_mafia_night1_panel_uids:
        return False
    if mafia_uid in game.no_host_mafia_night1_refs:
        return True
    ui_key = _mafia_night1_ui_key(game, mafia_uid)
    entry = game.mirror_prompt_messages.get(ui_key, {})
    return bool(entry.get("player") or entry.get("observer"))


def _mafia_night1_needs_mason_restart(game: Game) -> bool:
    if not is_mason_scenario(game) or game.no_host_mafia_night1_done:
        return False
    expected = mafia_night1_expected_panel_uids(game)
    if not expected:
        return False
    holder_uid = expected[0]
    if game.no_host_mafia_night1_flow_active:
        chooser = game.no_host_mafia_night1_chooser_uid
        chooser_p = game.players.get(chooser or -1)
        if chooser_p is None or not chooser_p.is_alive:
            return True
        if chooser != holder_uid:
            return True
        return not mafia_night1_panel_delivered(game, holder_uid)
    return game.mason_night_entry_dispatched_night == game.bazpors_narrator_night_count


def _reset_mafia_night1_flow_for_mason_retry(game: Game) -> None:
    game.no_host_mafia_night1_flow_active = False
    game.no_host_mafia_night1_pending_action = None
    game.no_host_mafia_night1_refs.clear()
    game.no_host_mafia_night1_panel_uids = []
    game.no_host_mafia_night1_chooser_uid = None


def _mafia_night1_ui_key(game: Game, mafia_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "night1_mafia", mafia_uid)


_MAFIA_ACTIONS_WITH_SUBFLOW = frozenset(
    {MAFIA_ACTION_SHOT, MAFIA_ACTION_YAKU, MAFIA_ACTION_NATO, MAFIA_ACTION_NEGOTIATE}
)


async def sync_mafia_mirror_panel(
    bot: Bot,
    game: Game,
    mafia_uid: int,
    text: str,
    kb: InlineKeyboardMarkup | None,
) -> None:
    """به‌روزرسانی پنل مافیا برای بازیکن و ناظر؛ در صورت نبود ref، ارسال مجدد."""
    ui_key = _mafia_night1_ui_key(game, mafia_uid)
    await publish_mirror_prompt_pair(
        bot,
        game,
        mafia_uid,
        ui_key,
        text,
        kb,
        fresh_observer_copy=False,
        send_player=(
            player_should_receive_game_messages(game, mafia_uid)
            and not is_synthetic_player_uid(mafia_uid)
        ),
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )
    _sync_mafia_ref_from_mirror(game, mafia_uid)


def _mafia_team_notification_recipients(game: Game) -> list[Player]:
    members = _alive_mafia_members(game)
    if is_mason_scenario(game):
        from bot.roles.mason_apache import mason_receives_mafia_private_message

        return [p for p in members if mason_receives_mafia_private_message(game, p)]
    return members


async def notify_all_alive_mafia_team(
    bot: Bot,
    game: Game,
    text: str,
) -> None:
    """پیام بدون دکمه به همهٔ مافیاهای زنده؛ برای صندلی تست، آینه به ناظر."""
    for p in _mafia_team_notification_recipients(game):
        uid = p.user_id
        ui_key = _mafia_night1_ui_key(game, uid)
        entry = game.mirror_prompt_messages.get(ui_key, {})
        has_panel = (
            uid in game.no_host_mafia_night1_refs
            or entry.get("player")
            or entry.get("observer")
        )
        if has_panel:
            await sync_mafia_mirror_panel(bot, game, uid, text, None)
            continue
        await deliver_no_host_player_game_copy(
            bot,
            game,
            uid,
            text,
            is_synthetic_uid=is_synthetic_player_uid,
            parse_mode="HTML",
        )


def _mafia_confirm_claim_key(game: Game) -> str:
    return mirror_ui_claim_key(game.room_code, "night1_mafia_confirm", 0)


def _mafia_night_header(game: Game) -> str:
    return _night_title_fa(max(1, game.bazpors_narrator_night_count))


def build_mozakere_mafia_operation_menu_html(game: Game) -> str:
    night_lbl = _mafia_night_header(game)
    return (
        f"🌙 <b>{night_lbl} — انتخاب عملیات تیم مافیا</b>\n\n"
        "امشب تیم مافیا می‌تواند یکی از این دو کار را انجام دهد:\n\n"
        "🔫 شات کردن\n"
        "🤝 مذاکره کردن\n\n"
        "لطفاً انتخاب کنید:"
    )


def build_mason_mafia_operation_menu_html() -> str:
    return (
        "🌙 <b>عملیات تیم مافیا</b>\n\n"
        "یکی از گزینه‌های زیر را انتخاب کنید:"
    )


def build_no_host_mafia_night1_menu_html(game: Game) -> str:
    if is_mozakere_scenario(game):
        return build_mozakere_mafia_operation_menu_html(game)
    if is_mason_scenario(game):
        return build_mason_mafia_operation_menu_html()
    return (
        f"🌙 <b>{_mafia_night_header(game)} — ثبت انتخاب تیم مافیا</b>\n\n"
        "🎯 برای فاز شب، کدام عملیات را می‌خواهید انجام دهید؟"
    )


def build_no_host_mafia_night1_confirm_html(game: Game, action: str) -> str:
    label = _action_label(game, action)
    return (
        f"🌙 <b>{_mafia_night_header(game)} — ثبت انتخاب تیم مافیا</b>\n\n"
        f"❓ آیا از انجام عملیات «<b>{html.escape(label)}</b>» مطمئن هستید؟"
    )


def build_no_host_mafia_night1_waiting_html(game: Game, action: str) -> str:
    label = _action_label(game, action)
    return (
        f"🌙 <b>{_mafia_night_header(game)} — ثبت انتخاب تیم مافیا</b>\n\n"
        f"✅ عملیات «<b>{html.escape(label)}</b>» ثبت شد.\n\n"
        "<i>تا پایان فاز شب منتظر بمانید.</i>"
    )


def _yaku_option_visible(game: Game, gm: "GameManager") -> bool:
    """همان شرط پنل semi_auto — فدا، هدف و رئیس زنده."""
    return yakuzai_allowed(game, gm)


def _mozakere_available_mafia_actions(game: Game) -> list[str]:
    from bot.roles.mozakere_negotiator import negotiation_allowed

    out: list[str] = []
    if negotiation_allowed(game):
        if mafia_shot_allowed(game):
            out.append(MAFIA_ACTION_SHOT)
        out.append(MAFIA_ACTION_NEGOTIATE)
    elif mafia_shot_allowed(game):
        out.append(MAFIA_ACTION_SHOT)
    return out


def _mason_available_mafia_actions(game: Game) -> list[str]:
    from bot.roles.mason_godfather import mason_nato_can_register

    out: list[str] = []
    if mafia_shot_allowed(game):
        out.append(MAFIA_ACTION_SHOT)
    if mason_nato_can_register(game):
        out.append(MAFIA_ACTION_NATO)
    return out


def _available_mafia_actions(game: Game, gm: "GameManager") -> list[str]:
    """شب ۱ و شب‌های بعد — شات / یاکوزایی / ناتویی مثل منوی گرداننده."""
    if is_mozakere_scenario(game):
        return _mozakere_available_mafia_actions(game)
    if is_mason_scenario(game):
        return _mason_available_mafia_actions(game)
    out: list[str] = []
    if mafia_shot_allowed(game):
        out.append(MAFIA_ACTION_SHOT)
    if _yaku_option_visible(game, gm):
        out.append(MAFIA_ACTION_YAKU)
    if nato_can_register(game):
        out.append(MAFIA_ACTION_NATO)
    return out


def _mozakere_mafia_menu_keyboard(
    game: Game, mafia_uid: int
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for action, cb_act in (
        (MAFIA_ACTION_SHOT, "nms"),
        (MAFIA_ACTION_NEGOTIATE, "nmg"),
    ):
        if action not in _mozakere_available_mafia_actions(game):
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=_ACTION_LABELS[action],
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act=cb_act, as_uid=mafia_uid
                    ).pack(),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _mafia_menu_keyboard(game: Game, mafia_uid: int, gm: "GameManager") -> InlineKeyboardMarkup:
    if is_mozakere_scenario(game):
        return _mozakere_mafia_menu_keyboard(game, mafia_uid)
    rows: list[list[InlineKeyboardButton]] = []
    act_map = {
        MAFIA_ACTION_SHOT: "nms",
        MAFIA_ACTION_YAKU: "nmy",
        MAFIA_ACTION_NATO: "nmn",
    }
    for action in _available_mafia_actions(game, gm):
        cb_act = act_map[action]
        rows.append(
            [
                InlineKeyboardButton(
                    text=_action_label(game, action),
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act=cb_act, as_uid=mafia_uid
                    ).pack(),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _mafia_confirm_keyboard(game: Game, mafia_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="nmc", as_uid=mafia_uid
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ انصراف و بازگشت به مرحله قبل",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="nmb", as_uid=mafia_uid
                    ).pack(),
                )
            ],
        ]
    )


def _store_mafia_ref(
    game: Game, mafia_uid: int, chat_id: int, message_id: int, text: str
) -> None:
    game.no_host_mafia_night1_refs[mafia_uid] = (chat_id, message_id, text)


def _sync_mafia_ref_from_mirror(game: Game, mafia_uid: int) -> None:
    ui_key = _mafia_night1_ui_key(game, mafia_uid)
    entry = game.mirror_prompt_messages.get(ui_key, {})
    player_ref = entry.get("player")
    if isinstance(player_ref, tuple) and len(player_ref) == 2:
        chat_id, message_id = int(player_ref[0]), int(player_ref[1])
        _store_mafia_ref(
            game, mafia_uid, chat_id, message_id, str(entry.get("text") or "")
        )


async def _send_mafia_prompt(
    bot: Bot,
    game: Game,
    mafia_uid: int,
    text: str,
    kb: InlineKeyboardMarkup,
    gm: "GameManager",
) -> None:
    ui_key = _mafia_night1_ui_key(game, mafia_uid)
    await publish_mirror_prompt_pair(
        bot,
        game,
        mafia_uid,
        ui_key,
        text,
        kb,
        fresh_observer_copy=True,
        send_player=(
            player_should_receive_game_messages(game, mafia_uid)
            and not is_synthetic_player_uid(mafia_uid)
        ),
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )
    _sync_mafia_ref_from_mirror(game, mafia_uid)


async def _edit_mafia_prompt(
    bot: Bot,
    game: Game,
    mafia_uid: int,
    text: str,
    kb: InlineKeyboardMarkup | None,
) -> None:
    ui_key = _mafia_night1_ui_key(game, mafia_uid)
    await update_mirror_prompt_pair(
        bot,
        game,
        ui_key,
        text,
        kb,
        assistant_uid=mafia_uid,
        parse_mode="HTML",
    )
    _sync_mafia_ref_from_mirror(game, mafia_uid)


async def _close_other_mafia_prompts(
    bot: Bot,
    game: Game,
    *,
    winner_mafia_uid: int,
    actor_uid: int,
    notice: str = "\n\n<i>✅ یکی از اعضای تیم مافیا این عملیات را تأیید کرد.</i>",
) -> None:
    for uid in list(game.no_host_mafia_night1_refs.keys()):
        if uid == winner_mafia_uid:
            continue
        ref = game.no_host_mafia_night1_refs.get(uid)
        if not ref:
            continue
        chat_id, message_id, base = ref
        ui_key = _mafia_night1_ui_key(game, uid)
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=base + notice,
                parse_mode="HTML",
                reply_markup=None,
            )
        except TelegramBadRequest:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=chat_id, message_id=message_id, reply_markup=None
                )
            except TelegramBadRequest:
                pass
        if (
            no_host_observer_registered(game)
            and actor_uid == game.observer_user_id
            and actor_uid != uid
        ):
            await apply_mirror_claim_winner(bot, game, ui_key, actor_uid, uid)


def _apply_mafia_action_to_game(game: Game, action: str) -> None:
    if action == MAFIA_ACTION_SHOT:
        game.bazpors_night_substep = NS_MAFIA_SHOT
    elif action == MAFIA_ACTION_YAKU:
        game.bazpors_night_substep = NS_YAKU_SAC
    elif action == MAFIA_ACTION_NATO:
        game.bazpors_night_substep = NS_NATO_ROLE


async def _start_mozakere_direct_shot(
    bot: Bot, game: Game, gm: "GameManager", *, mafia_uid: int, actor_uid: int
) -> None:
    from bot.no_host_mafia_shot import (
        _shot_pick_keyboard,
        _sync_mafia_shot_mirror_panel,
        build_no_host_mafia_shot_pick_html,
    )

    game.no_host_mafia_night1_flow_active = False
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_pending_action = None
    game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
    game.no_host_mafia_night1_actor_uid = actor_uid
    game.no_host_mafia_night1_panel_uids = [mafia_uid]
    game.no_host_mafia_night1_chooser_uid = mafia_uid
    _apply_mafia_action_to_game(game, MAFIA_ACTION_SHOT)

    pick_text = build_no_host_mafia_shot_pick_html(game)
    pick_kb = _shot_pick_keyboard(game, mafia_uid, gm)
    if is_mason_scenario(game):
        from bot.mason_responsibilities import mason_mafia_shot_uses_dedicated_panel

        if mason_mafia_shot_uses_dedicated_panel(game, mafia_uid):
            await _sync_mafia_shot_mirror_panel(
                bot, game, mafia_uid, pick_text, pick_kb
            )
        else:
            await _send_mafia_prompt(bot, game, mafia_uid, pick_text, pick_kb, gm)
    else:
        await _send_mafia_prompt(bot, game, mafia_uid, pick_text, pick_kb, gm)
    game.no_host_mafia_shot_flow_active = True
    game.no_host_mafia_shot_pending_uid = None
    game.no_host_mafia_shot_awaiting_confirm = False
    await maybe_start_shiad_parallel_night_panels(bot, game, gm)


async def _finalize_mozakere_negotiate_action(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    mafia_uid: int,
    actor_uid: int,
) -> None:
    from bot.no_host_mozakere_negotiation import (
        broadcast_mozakere_negotiation_started,
        mark_mozakere_negotiation_tonight,
        start_no_host_mozakere_negotiator_flow,
    )

    game.no_host_mafia_night1_flow_active = False
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_pending_action = None
    game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_NEGOTIATE
    game.no_host_mafia_night1_actor_uid = actor_uid
    _apply_mafia_action_to_game(game, MAFIA_ACTION_NEGOTIATE)

    await _close_other_mafia_prompts(
        bot, game, winner_mafia_uid=mafia_uid, actor_uid=actor_uid
    )

    mark_mozakere_negotiation_tonight(game)
    game.no_host_mafia_shot_done = True

    await _edit_mafia_prompt(
        bot,
        game,
        mafia_uid,
        "✅ <b>مذاکره کردن</b> انتخاب شد.\n"
        "<i>مذاکره‌کننده پنل انتخاب را دریافت می‌کند.</i>",
        None,
    )
    await broadcast_mozakere_negotiation_started(bot, game)
    await start_no_host_mozakere_negotiator_flow(bot, game, gm)

    from bot.no_host_night_ready import maybe_finish_no_host_parallel_night

    await maybe_finish_no_host_parallel_night(bot, game, gm)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.mozakere_mafia_negotiate_chosen",
            mafia_uid=mafia_uid,
            actor_uid=actor_uid,
        )
    except Exception:
        pass


async def start_no_host_night1_mafia_flow(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    if game.bazpors_host_mode != "no_host":
        return
    if game.no_host_mafia_night1_done:
        return
    if game.no_host_mafia_night1_flow_active:
        if is_mason_scenario(game) and _mafia_night1_needs_mason_restart(game):
            _reset_mafia_night1_flow_for_mason_retry(game)
        else:
            return

    mafia_members = _alive_mafia_members(game)
    if not mafia_members:
        mafia_members = _yaku_recruit_panel_fallback(game)
    if not mafia_members:
        game.no_host_mafia_night1_done = True
        return

    actions = _available_mafia_actions(game, gm)
    if not actions:
        game.no_host_mafia_night1_done = True
        return

    if is_mozakere_scenario(game) and len(actions) == 1 and actions[0] == MAFIA_ACTION_SHOT:
        chooser = resolve_mafia_shot_chooser(game)
        if chooser is not None:
            uid = chooser.user_id
            game.no_host_mafia_night1_panel_uids = [uid]
            game.no_host_mafia_night1_chooser_uid = uid
            game.no_host_mafia_night1_refs.clear()
            await _start_mozakere_direct_shot(
                bot, game, gm, mafia_uid=uid, actor_uid=uid
            )
            return

    if is_mason_scenario(game) and len(actions) == 1 and actions[0] == MAFIA_ACTION_SHOT:
        chooser = resolve_mafia_shot_chooser(game)
        if chooser is not None:
            uid = chooser.user_id
            game.no_host_mafia_night1_panel_uids = [uid]
            game.no_host_mafia_night1_chooser_uid = uid
            game.no_host_mafia_night1_refs.clear()
            await _start_mozakere_direct_shot(
                bot, game, gm, mafia_uid=uid, actor_uid=uid
            )
            return

    if should_start_shiad_direct_shot_menu(game) and mafia_shot_allowed(game):
        from bot.no_host_phase import no_host_run_mafia_shot_operation

        chooser = resolve_mafia_shot_chooser(game)
        if chooser is not None:
            uid = chooser.user_id
            game.no_host_mafia_night1_done = True
            game.no_host_mafia_night1_chosen_action = MAFIA_ACTION_SHOT
            game.no_host_mafia_night1_chooser_uid = uid
            game.no_host_mafia_night1_panel_uids = [uid]
            _apply_mafia_action_to_game(game, MAFIA_ACTION_SHOT)
            await no_host_run_mafia_shot_operation(bot, game, gm)
            await maybe_start_shiad_parallel_night_panels(bot, game, gm)
        return

    recipients = resolve_mafia_night1_panel_recipients(game)
    panel_uids = [
        p.user_id
        for p in recipients
        if player_should_receive_game_messages(game, p.user_id)
    ]
    if not panel_uids:
        game.no_host_mafia_night1_done = True
        return

    game.no_host_mafia_night1_pending_action = None
    game.no_host_mafia_night1_panel_uids = list(panel_uids)
    game.no_host_mafia_night1_chooser_uid = panel_uids[0]
    game.no_host_mafia_night1_refs.clear()

    text = build_no_host_mafia_night1_menu_html(game)
    for mafia_uid in panel_uids:
        kb = _mafia_menu_keyboard(game, mafia_uid, gm)
        await _send_mafia_prompt(bot, game, mafia_uid, text, kb, gm)
    game.no_host_mafia_night1_flow_active = True


async def _finalize_mafia_night1(
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    mafia_uid: int,
    actor_uid: int,
    action: str,
) -> None:
    from bot.no_host_phase import (
        no_host_run_mafia_nato_operation,
        no_host_run_mafia_shot_operation,
        no_host_run_mafia_yaku_operation,
    )

    game.no_host_mafia_night1_flow_active = False
    game.no_host_mafia_night1_done = True
    game.no_host_mafia_night1_pending_action = None
    game.no_host_mafia_night1_chosen_action = action
    game.no_host_mafia_night1_actor_uid = actor_uid
    _apply_mafia_action_to_game(game, action)

    boss = find_alive_role_holder(game, Role.MAFIA_BOSS)
    if boss is not None and boss.user_id not in game.no_host_mafia_night1_panel_uids:
        game.no_host_mafia_night1_panel_uids.append(boss.user_id)

    await _close_other_mafia_prompts(
        bot, game, winner_mafia_uid=mafia_uid, actor_uid=actor_uid
    )

    label = html.escape(_action_label(game, action))
    if not (is_mason_scenario(game) and action == MAFIA_ACTION_NATO):
        await notify_all_alive_mafia_team(
            bot,
            game,
            f"🌙 تیم مافیا: <b>{label}</b> انتخاب شد.\n"
            "<i>تا پایان فاز شب منتظر بمانید.</i>",
        )

    if action == MAFIA_ACTION_SHOT:
        from bot.no_host_mafia_shot import (
            _shot_confirm_keyboard,
            _shot_pick_keyboard,
            _sync_mafia_shot_mirror_panel,
            build_no_host_mafia_shot_pick_html,
        )

        game.no_host_mafia_night1_panel_uids = [mafia_uid]
        game.no_host_mafia_night1_chooser_uid = mafia_uid
        pick_text = build_no_host_mafia_shot_pick_html(game)
        pick_kb = _shot_pick_keyboard(game, mafia_uid, gm)
        if is_mason_scenario(game):
            from bot.mason_responsibilities import mason_mafia_shot_uses_dedicated_panel

            if mason_mafia_shot_uses_dedicated_panel(game, mafia_uid):
                await _sync_mafia_shot_mirror_panel(
                    bot, game, mafia_uid, pick_text, pick_kb
                )
            else:
                await _edit_mafia_prompt(bot, game, mafia_uid, pick_text, pick_kb)
        else:
            await _edit_mafia_prompt(bot, game, mafia_uid, pick_text, pick_kb)
        game.no_host_mafia_shot_flow_active = True
        game.no_host_mafia_shot_pending_uid = None
        game.no_host_mafia_shot_awaiting_confirm = False
        await maybe_start_shiad_parallel_night_panels(bot, game, gm)
    elif action == MAFIA_ACTION_YAKU:
        if yakuzai_allowed(game, gm):
            await no_host_run_mafia_yaku_operation(bot, game, gm)
        else:
            from bot.no_host_mafia_yaku import (
                _yaku_denied_keyboard,
                build_no_host_yaku_denied_html,
            )

            await _edit_mafia_prompt(
                bot,
                game,
                mafia_uid,
                build_no_host_yaku_denied_html(),
                _yaku_denied_keyboard(game, mafia_uid),
            )
    elif action == MAFIA_ACTION_NATO:
        if is_mason_scenario(game):
            from bot.roles.mason_nato import mark_mason_nato_selected_tonight

            mark_mason_nato_selected_tonight(game)
            game.no_host_mafia_shot_done = True
            await _edit_mafia_prompt(
                bot,
                game,
                mafia_uid,
                f"✅ عملیات «{label}» ثبت شد.\n"
                "<i>ناتو پنل نقش ناتویی را دریافت می‌کند.</i>",
                None,
            )
            await no_host_run_mafia_nato_operation(bot, game, gm)
        else:
            await _edit_mafia_prompt(
                bot,
                game,
                mafia_uid,
                f"✅ عملیات «{label}» ثبت شد.\n"
                "<i>ناتو پنل نقش ناتویی را دریافت می‌کند.</i>",
                None,
            )
            await no_host_run_mafia_nato_operation(bot, game, gm)
    elif action == MAFIA_ACTION_NEGOTIATE:
        from bot.no_host_mozakere_negotiation import (
            broadcast_mozakere_negotiation_started,
            mark_mozakere_negotiation_tonight,
            start_no_host_mozakere_negotiator_flow,
        )

        mark_mozakere_negotiation_tonight(game)
        game.no_host_mafia_shot_done = True
        await _edit_mafia_prompt(
            bot,
            game,
            mafia_uid,
            "✅ <b>مذاکره کردن</b> انتخاب شد.\n"
            "<i>مذاکره‌کننده پنل انتخاب را دریافت می‌کند.</i>",
            None,
        )
        await broadcast_mozakere_negotiation_started(bot, game)
        await start_no_host_mozakere_negotiator_flow(bot, game, gm)
    else:
        wait_text = build_no_host_mafia_night1_waiting_html(game, action)
        await _edit_mafia_prompt(bot, game, mafia_uid, wait_text, None)

    from bot.no_host_night_ready import (
        maybe_finish_no_host_parallel_night,
        no_host_parallel_night_collect_active,
    )

    if no_host_parallel_night_collect_active(game):
        await maybe_finish_no_host_parallel_night(bot, game, gm)
    else:
        from bot.no_host_phase import no_host_maybe_continue_after_night1_assistant

        await no_host_maybe_continue_after_night1_assistant(bot, game, gm)
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.night1_mafia_done",
            action=action,
            mafia_uid=mafia_uid,
            actor_uid=actor_uid,
        )
    except Exception:
        pass


def mafia_night1_act_active(game: Game, act: str) -> bool:
    return act in ("nms", "nmy", "nmn", "nmc", "nmb", "nmg")


def _actor_may_use_mafia_copy(
    game: Game, actor_uid: int, mafia_uid: int
) -> bool:
    chooser = game.no_host_mafia_night1_chooser_uid
    if chooser is not None and mafia_uid != chooser:
        return False
    if not _mafia_panel_has_uid(game, mafia_uid):
        return False
    if actor_uid == mafia_uid:
        return True
    return bool(
        is_synthetic_player_uid(mafia_uid)
        and no_host_observer_registered(game)
        and game.observer_user_id == actor_uid
    )


async def dispatch_no_host_mafia_night1(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    mafia_uid: int,
    actor_uid: int,
    act: str,
) -> None:
    from bot.mason_force_finish_night import reject_mason_night_callback_if_closed

    if await reject_mason_night_callback_if_closed(callback, game):
        return
    if game.no_host_mafia_night1_done:
        await callback.answer("این انتخاب قبلاً ثبت شده است.", show_alert=True)
        return
    if not game.no_host_mafia_night1_flow_active:
        await callback.answer("این مرحله فعال نیست.", show_alert=True)
        return
    if not _actor_may_use_mafia_copy(game, actor_uid, mafia_uid):
        await callback.answer("شما مجاز به این عمل نیستید.", show_alert=True)
        return

    if not _mafia_panel_has_uid(game, mafia_uid):
        await callback.answer("شما پنل انتخاب ندارید.", show_alert=True)
        return

    act_map = {"nms": MAFIA_ACTION_SHOT, "nmy": MAFIA_ACTION_YAKU, "nmn": MAFIA_ACTION_NATO, "nmg": MAFIA_ACTION_NEGOTIATE}
    if act in act_map:
        action = act_map[act]
        if is_mozakere_scenario(game) and act in ("nms", "nmg"):
            allowed = _available_mafia_actions(game, gm)
            if action not in allowed:
                await callback.answer("این عملیات الان مجاز نیست.", show_alert=True)
                return
            if act == "nms":
                await callback.answer("شات انتخاب شد.")
                await _start_mozakere_direct_shot(
                    bot, game, gm, mafia_uid=mafia_uid, actor_uid=actor_uid
                )
                return
            await callback.answer("مذاکره انتخاب شد.")
            await _finalize_mozakere_negotiate_action(
                bot, game, gm, mafia_uid=mafia_uid, actor_uid=actor_uid
            )
            return
        if action == MAFIA_ACTION_YAKU:
            if not _yaku_option_visible(game, gm):
                await callback.answer("یاکوزایی مقدور نمی‌باشد.", show_alert=True)
                return
            if not yakuzai_allowed(game, gm):
                from bot.no_host_mafia_yaku import (
                    build_no_host_yaku_denied_html,
                    _yaku_denied_keyboard,
                )

                await callback.answer("یاکوزایی مقدور نمی‌باشد.", show_alert=True)
                denied_text = build_no_host_yaku_denied_html()
                denied_kb = _yaku_denied_keyboard(game, mafia_uid)
                await _edit_mafia_prompt(
                    bot, game, mafia_uid, denied_text, denied_kb
                )
                return
        elif action == MAFIA_ACTION_NATO:
            from bot.bazpors_narrator import nato_denied_message
            from bot.no_host_mafia_nato import (
                _nato_denied_keyboard,
                build_no_host_nato_denied_html,
                no_host_nato_allowed,
            )

            if not no_host_nato_allowed(game):
                denied_msg = nato_denied_message(game)
                await callback.answer(denied_msg, show_alert=True)
                denied_kb = _nato_denied_keyboard(game, mafia_uid)
                await _edit_mafia_prompt(
                    bot,
                    game,
                    mafia_uid,
                    build_no_host_nato_denied_html(game),
                    denied_kb,
                )
                return
        else:
            allowed = _available_mafia_actions(game, gm)
            if action not in allowed:
                await callback.answer("این عملیات الان مجاز نیست.", show_alert=True)
                return
        game.no_host_mafia_night1_pending_action = action
        await callback.answer("تأیید کنید.")
        confirm_text = build_no_host_mafia_night1_confirm_html(game, action)
        confirm_kb = _mafia_confirm_keyboard(game, mafia_uid)
        await _edit_mafia_prompt(bot, game, mafia_uid, confirm_text, confirm_kb)
        return

    if act == "nmb":
        game.no_host_mafia_night1_pending_action = None
        await callback.answer("بازگشت.")
        menu_text = build_no_host_mafia_night1_menu_html(game)
        menu_kb = _mafia_menu_keyboard(game, mafia_uid, gm)
        await _edit_mafia_prompt(bot, game, mafia_uid, menu_text, menu_kb)
        return

    if act == "nmc":
        pending = game.no_host_mafia_night1_pending_action
        if not pending:
            await callback.answer("ابتدا یک عملیات انتخاب کنید.", show_alert=True)
            return
        if pending == MAFIA_ACTION_YAKU and not yakuzai_allowed(game, gm):
            await callback.answer("یاکوزایی مقدور نمی‌باشد.", show_alert=True)
            return
        if pending == MAFIA_ACTION_NATO:
            if is_mason_scenario(game):
                from bot.roles.mason_godfather import mason_nato_can_register

                if not mason_nato_can_register(game):
                    await callback.answer(
                        "ناتویی در حال حاضر مجاز نیست.", show_alert=True
                    )
                    return
            else:
                from bot.bazpors_narrator import nato_denied_message

                if not nato_can_register(game):
                    await callback.answer(nato_denied_message(game), show_alert=True)
                    return
        claim_key = _mafia_confirm_claim_key(game)
        existing = game.mirror_action_claims.get(claim_key)
        if existing is not None and existing != actor_uid:
            await callback.answer(
                "یکی از اعضای تیم مافیا قبلاً انتخاب کرده است.",
                show_alert=True,
            )
            return
        if not _actor_may_use_mafia_copy(game, actor_uid, mafia_uid):
            await callback.answer("شما مجاز به این عمل نیستید.", show_alert=True)
            return
        if existing is None:
            game.mirror_action_claims[claim_key] = actor_uid
            if (
                no_host_observer_registered(game)
                and pending not in _MAFIA_ACTIONS_WITH_SUBFLOW
            ):
                await apply_mirror_claim_winner(
                    bot,
                    game,
                    _mafia_night1_ui_key(game, mafia_uid),
                    actor_uid,
                    mafia_uid,
                )
        if game.no_host_mafia_night1_done:
            await callback.answer("این انتخاب قبلاً ثبت شده است.", show_alert=True)
            return
        await callback.answer("ثبت شد.")
        await _finalize_mafia_night1(
            bot,
            game,
            gm,
            mafia_uid=mafia_uid,
            actor_uid=actor_uid,
            action=pending,
        )
        return

    await callback.answer("عمل نامعتبر.", show_alert=True)
