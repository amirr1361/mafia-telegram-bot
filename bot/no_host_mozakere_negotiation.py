"""شب — پنل مذاکره‌کننده (فقط سناریوی مذاکره، no_host)."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from bot.game import is_synthetic_player_uid
from bot.models import Game, Player
from bot.no_host_role_pick_common import (
    actor_may_act_on_role_panel,
    build_confirm_cancel_keyboard,
    build_pick_keyboard,
    player_button_name,
    sync_role_mirror_panel,
    target_in_pool,
)
from bot.observer_delivery import (
    broadcast_to_alive_players,
    deliver_no_host_player_game_copy,
    mirror_ui_claim_key,
    no_host_observer_registered,
    register_mirror_prompt_pair,
)
from bot.room_mode import is_mozakere_scenario
from bot.roles.mozakere_negotiator import (
    commit_mozakere_negotiation,
    find_alive_negotiator,
    negotiation_panel_target_pool,
)
from bot.roles.night_state import mozakere_negotiation_night_state

MOZAKERE_NEGOTIATION_RECRUIT_SUCCESS_TEXT = (
    "مذاکره با شما موفقیت‌آمیز بود؛ از این پس عضو تیم مافیا هستید "
    "و از شب بعد همراه آن‌ها بیدار می‌شوید."
)
MOZAKERE_NEGOTIATION_EXISTING_MAFIA_SUCCESS_TEXT = (
    "در صورت موفقیت‌آمیز بودن مذاکره، فرد انتخابی از شب بعد "
    "همراه شما بیدار خواهد شد."
)

if TYPE_CHECKING:
    from bot.game import GameManager


def _negotiator_ui_key(game: Game, neg_uid: int) -> str:
    return mirror_ui_claim_key(game.room_code, "no_host_negotiator", neg_uid)


def _player_button_name(p: Player | None, uid: int) -> str:
    return player_button_name(p, uid)


def build_mozakere_negotiation_broadcast_html() -> str:
    return "تیم مافیا در حال مذاکره"


def build_no_host_negotiator_pick_html() -> str:
    return (
        "🤝 <b>مذاکره</b>\n\n"
        "چه بازیکنی را برای مذاکره انتخاب می‌کنید؟"
    )


def build_no_host_negotiator_confirm_html(target_uid: int, game: Game) -> str:
    p = game.players.get(target_uid)
    name = html.escape(_player_button_name(p, target_uid))
    return (
        "🤝 <b>مذاکره</b>\n\n"
        f"انتخاب شما:\n<b>{name}</b>\n\n"
        "آیا این انتخاب را تأیید می‌کنید؟"
    )


def build_no_host_negotiator_waiting_html(target_uid: int, game: Game) -> str:
    p = game.players.get(target_uid)
    name = html.escape(_player_button_name(p, target_uid))
    return (
        "🤝 <b>مذاکره</b>\n\n"
        f"✅ انتخاب <b>{name}</b> ثبت شد.\n\n"
        "<i>تا پایان فاز شب منتظر بمانید.</i>"
    )


def _pick_keyboard(game: Game, neg_uid: int) -> InlineKeyboardMarkup:
    return build_pick_keyboard(
        game,
        neg_uid,
        pick_act="negp",
        players=negotiation_panel_target_pool(game),
    )


def _confirm_keyboard(game: Game, neg_uid: int) -> InlineKeyboardMarkup:
    return build_confirm_cancel_keyboard(
        game,
        neg_uid,
        confirm_act="negc",
        back_act="negb",
        confirm_text="✅ تأیید",
        back_text="↩️ بازگشت",
    )


async def send_mozakere_negotiation_commit_notifications(
    bot: Bot, game: Game, *, target_uid: int, succeeded: bool
) -> None:
    """پس از تأیید هدف مذاکره — پیام عمومی برای مافیا؛ پیام جذب فقط در موفقیت."""
    if not is_mozakere_scenario(game):
        return
    state = mozakere_negotiation_night_state(game)
    if not state.tonight:
        return

    from bot.game import is_mafia_team

    for uid, p in sorted(game.players.items()):
        if uid == target_uid:
            continue
        if not p.is_alive or p.role is None or not is_mafia_team(p.role):
            continue
        await deliver_no_host_player_game_copy(
            bot,
            game,
            uid,
            MOZAKERE_NEGOTIATION_EXISTING_MAFIA_SUCCESS_TEXT,
            is_synthetic_uid=is_synthetic_player_uid,
        )

    if not succeeded:
        return
    if target_uid not in game.mozakere_mafia_recruit_ids:
        return
    await deliver_no_host_player_game_copy(
        bot,
        game,
        target_uid,
        MOZAKERE_NEGOTIATION_RECRUIT_SUCCESS_TEXT,
        is_synthetic_uid=is_synthetic_player_uid,
    )


async def broadcast_mozakere_negotiation_started(bot: Bot, game: Game) -> None:
    text = build_mozakere_negotiation_broadcast_html()
    await broadcast_to_alive_players(
        bot,
        game,
        text,
        is_synthetic_uid=is_synthetic_player_uid,
    )
    if no_host_observer_registered(game) and game.observer_user_id is not None:
        await deliver_no_host_player_game_copy(
            bot,
            game,
            game.observer_user_id,
            text,
            is_synthetic_uid=is_synthetic_player_uid,
        )


def mark_mozakere_negotiation_tonight(game: Game) -> None:
    mozakere_negotiation_night_state(game).tonight = True


async def start_no_host_mozakere_negotiator_flow(
    bot: Bot, game: Game, gm: "GameManager"
) -> bool:
    del gm
    if not is_mozakere_scenario(game):
        return False
    if game.no_host_negotiator_pick_confirmed:
        return False
    neg = find_alive_negotiator(game)
    if neg is None:
        return False

    game.no_host_negotiator_flow_active = True
    game.no_host_negotiator_pending_tid = None
    text = build_no_host_negotiator_pick_html()
    kb = _pick_keyboard(game, neg.user_id)
    await register_mirror_prompt_pair(
        bot,
        game,
        neg.user_id,
        _negotiator_ui_key(game, neg.user_id),
        text,
        kb,
        send_player=True,
        send_observer=no_host_observer_registered(game),
        observer_same_text=False,
        parse_mode="HTML",
    )
    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "no_host.mozakere_negotiator_panel_sent",
            neg_uid=neg.user_id,
            night_count=game.bazpors_narrator_night_count,
        )
    except Exception:
        pass
    return True


def mozakere_negotiator_act_active(game: Game, act: str) -> bool:
    if not is_mozakere_scenario(game):
        return False
    return act in ("negp", "negc", "negb")


def _actor_may_act(game: Game, actor_uid: int, neg_uid: int) -> bool:
    return actor_may_act_on_role_panel(game, actor_uid, neg_uid)


async def _sync_panel(
    bot: Bot,
    game: Game,
    neg_uid: int,
    text: str,
    kb: InlineKeyboardMarkup | None,
) -> None:
    await sync_role_mirror_panel(
        bot, game, _negotiator_ui_key(game, neg_uid), neg_uid, text, kb
    )


async def _activate_journalist_after_negotiation(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    from bot.no_host_journalist_night import (
        activate_journalist_after_mozakere_negotiation,
    )

    await activate_journalist_after_mozakere_negotiation(bot, game, gm)


async def dispatch_no_host_mozakere_negotiator(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    gm: "GameManager",
    *,
    neg_uid: int,
    actor_uid: int,
    act: str,
    tid: int,
) -> None:
    if not game.no_host_negotiator_flow_active or game.no_host_negotiator_pick_confirmed:
        await callback.answer("این مرحله دیگر فعال نیست.", show_alert=True)
        return
    neg = find_alive_negotiator(game)
    if neg is None or neg.user_id != neg_uid:
        await callback.answer("مذاکره‌کننده در بازی نیست.", show_alert=True)
        return
    if not _actor_may_act(game, actor_uid, neg_uid):
        await callback.answer(
            "فقط مذاکره‌کننده می‌تواند این انتخاب را انجام دهد.",
            show_alert=True,
        )
        return

    pool = negotiation_panel_target_pool(game)

    if act == "negp":
        if not target_in_pool(tid, pool):
            await callback.answer("انتخاب نامعتبر.", show_alert=True)
            return
        game.no_host_negotiator_pending_tid = tid
        await callback.answer("انتخاب شد؛ تأیید کنید.")
        text = build_no_host_negotiator_confirm_html(tid, game)
        kb = _confirm_keyboard(game, neg_uid)
        await _sync_panel(bot, game, neg_uid, text, kb)
        return

    if act == "negb":
        game.no_host_negotiator_pending_tid = None
        await callback.answer("بازگشت به لیست.")
        text = build_no_host_negotiator_pick_html()
        kb = _pick_keyboard(game, neg_uid)
        await _sync_panel(bot, game, neg_uid, text, kb)
        return

    if act == "negc":
        pick = game.no_host_negotiator_pending_tid
        if pick is None or not target_in_pool(pick, pool):
            await callback.answer("ابتدا یک بازیکن انتخاب کنید.", show_alert=True)
            return
        target = game.players.get(pick)
        if target is None:
            await callback.answer("انتخاب نامعتبر.", show_alert=True)
            return
        result = commit_mozakere_negotiation(game, neg, target)
        game.no_host_negotiator_pick_confirmed = True
        game.no_host_negotiator_flow_active = False
        game.no_host_negotiator_pending_tid = None
        game.no_host_mafia_shot_done = True

        await send_mozakere_negotiation_commit_notifications(
            bot, game, target_uid=pick, succeeded=result.succeeded
        )

        await callback.answer("ثبت شد.")
        wait_text = build_no_host_negotiator_waiting_html(pick, game)
        await _sync_panel(bot, game, neg_uid, wait_text, None)
        try:
            from bot.game_audit_log import log_event

            log_event(
                game,
                "no_host.mozakere_negotiation_committed",
                neg_uid=neg_uid,
                target_uid=pick,
                success=game.mozakere_negotiation_success,
                night_count=game.bazpors_narrator_night_count,
            )
        except Exception:
            pass

        await _activate_journalist_after_negotiation(bot, game, gm)

        from bot.no_host_mozakere_negotiation_reset import (
            apply_mozakere_negotiation_citizen_resets,
        )

        await apply_mozakere_negotiation_citizen_resets(bot, game, gm)
        return

    await callback.answer("عمل نامعتبر.", show_alert=True)
