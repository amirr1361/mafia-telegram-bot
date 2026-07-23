"""Callback پنل بازپرس / کمک‌کننده ربات — استخراج‌شده از main.py (فاز ۲)."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from bot.app_state import manager
from bot.bazpors_narrator import (
    ASK_NIGHT_EXTRA,
    BazporsNarrCb,
    CITIZEN_WIN_GATE,
    DAY_DISCUSS,
    MAFIA_TIE_GATE,
    NS_ROLE_ABSENT,
    citizen_win_popup_text,
    detective_inquiry_alert_text,
    hunter_chain_confirm_alert_text,
    ki_as_hand_resolve_day_active,
    mafia_citizen_equal,
    mafia_tie_popup_text,
    narrator_callback_user_may_act,
    narrator_compact_ack_html,
    narrator_operator_user_id,
    no_host_assistant_narrator_active,
    no_mafia_alive,
    post_night_host_popup_text,
    preserve_night_end_host_message,
    semi_auto_chaos_host_picks_winner,
    process_narrator_callback,
    role_absent_popup_text,
    shiad_detective_alert_text,
)
from bot.chaos_handshake import (
    RESULT_CITIZENS_HTML,
    RESULT_MAFIA_HTML,
    reset_chaos_handshake_state,
)
from bot.models import Game
from bot.post_game_flow import (
    broadcast_bazpors_game_end_to_players,
    endgame_winner_keyboard,
    finalize_game_winner,
)
from bot.no_host_handoff import NO_HOST_HANDOFF_OFFER
from bot.no_host_interrog_day import NO_HOST_INTERROG_DAY
from bot.no_host_table_inquiry import (
    NO_HOST_TABLE_INQUIRY,
    apply_no_host_table_inquiry_confirm,
)
from bot.observer_delivery import flush_elimination_notifications
from bot.tg_send import safe_callback_answer, safe_send_message

logger = logging.getLogger(__name__)

router = Router(name="narrator_cb")


def register_narrator_cb_handlers(dp: Dispatcher) -> None:
    dp.include_router(router)


async def _delete_callback_message(message: Message | None) -> None:
    if not message:
        return
    try:
        await message.delete()
    except TelegramBadRequest:
        logger.debug(
            "delete callback message failed chat_id=%s message_id=%s",
            message.chat.id,
            message.message_id,
        )


async def _prompt_manual_endgame(
    bot: Bot,
    callback: CallbackQuery,
    game: Game,
) -> None:
    game.host_may_pick_winner = True
    game.bazpors_narrator_step = None
    await safe_callback_answer(
        callback,
        "از دستور /endgame برای تعیین دستی برنده استفاده کنید.",
        show_alert=True,
    )
    await _delete_callback_message(callback.message)
    await safe_send_message(
        bot,
        game.host_id,
        "برنده را خودتان مشخص کنید:\n"
        "دستور <code>/endgame</code> را بزنید و تیم برنده را انتخاب کنید.",
        parse_mode="HTML",
        reply_markup=endgame_winner_keyboard(game),
    )


async def _finalize_tie_winner(
    bot: Bot,
    callback: CallbackQuery,
    game: Game,
    winner: str,
    alert_text: str,
) -> None:
    await safe_callback_answer(callback, alert_text, show_alert=True)
    await _delete_callback_message(callback.message)
    if no_host_assistant_narrator_active(game):
        await broadcast_bazpors_game_end_to_players(bot, game, winner)
    assert callback.from_user
    await finalize_game_winner(
        bot, game, winner, callback.from_user.id
    )


async def _handle_tie_citizen(
    bot: Bot,
    callback: CallbackQuery,
    game: Game,
    act: str,
) -> bool:
    if act not in ("tie_citizen_yes", "tie_citizen_no"):
        return False
    citizen_step_ok = game.bazpors_narrator_step == CITIZEN_WIN_GATE or (
        game.bazpors_narrator_step == ASK_NIGHT_EXTRA
        and no_mafia_alive(game, manager)
    )
    if not citizen_step_ok:
        await safe_callback_answer(callback, "نامعتبر.", show_alert=True)
        return True
    if act == "tie_citizen_yes":
        await _finalize_tie_winner(
            bot,
            callback,
            game,
            "citizen",
            "شهروند برنده شد — اتاق ثبت و بسته می‌شود.",
        )
        return True
    await _prompt_manual_endgame(bot, callback, game)
    return True


async def _handle_tie_mafia(
    bot: Bot,
    callback: CallbackQuery,
    game: Game,
    act: str,
) -> bool:
    if act not in ("tie_mafia_yes", "tie_mafia_no"):
        return False
    tie_step_ok = game.bazpors_narrator_step == MAFIA_TIE_GATE or (
        game.bazpors_narrator_step == ASK_NIGHT_EXTRA
        and mafia_citizen_equal(game, manager)
    )
    if not tie_step_ok:
        await safe_callback_answer(callback, "نامعتبر.", show_alert=True)
        return True
    if act == "tie_mafia_yes":
        await _finalize_tie_winner(
            bot,
            callback,
            game,
            "mafia",
            "مافیا برنده شد — اتاق ثبت و بسته می‌شود.",
        )
        return True
    await _prompt_manual_endgame(bot, callback, game)
    return True


async def _finalize_ki_as_chaos_winner(
    bot: Bot,
    callback: CallbackQuery,
    game: Game,
    winner: str,
) -> None:
    from bot.observer_delivery import broadcast_to_alive_players
    from bot.game import is_synthetic_player_uid

    public_html = RESULT_MAFIA_HTML if winner == "mafia" else RESULT_CITIZENS_HTML
    if winner == "mafia":
        game.bazpors_mafia_win_via_chaos = True
    alert = (
        "مافیا برنده شد — اتاق ثبت و بسته می‌شود."
        if winner == "mafia"
        else "شهروند برنده شد — اتاق ثبت و بسته می‌شود."
    )
    await safe_callback_answer(callback, alert, show_alert=True)
    await _delete_callback_message(callback.message)
    await broadcast_to_alive_players(
        bot,
        game,
        public_html,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    game.bazpors_ki_as_today = False
    reset_chaos_handshake_state(game)
    assert callback.from_user
    await finalize_game_winner(bot, game, winner, callback.from_user.id)


async def _handle_ki_as_win(
    bot: Bot,
    callback: CallbackQuery,
    game: Game,
    act: str,
) -> bool:
    if act not in ("ki_as_mafia_win", "ki_as_citizen_win"):
        return False
    if semi_auto_chaos_host_picks_winner(game):
        if (
            game.bazpors_narrator_step != DAY_DISCUSS
            or not ki_as_hand_resolve_day_active(game, manager)
        ):
            await safe_callback_answer(callback, "نامعتبر.", show_alert=True)
            return True
        winner = "mafia" if act == "ki_as_mafia_win" else "citizen"
        await _finalize_ki_as_chaos_winner(bot, callback, game, winner)
        return True
    await safe_callback_answer(
        callback,
        "نتیجهٔ دست از انتخاب بازیکنان محاسبه می‌شود.",
        show_alert=True,
    )
    return True


def _audit_narrator_callback(
    game: Game,
    *,
    act: str,
    tid: int,
    rid: str,
    step_before: str | None,
    substep_before: str | None,
    pending_uid_before: int | None,
    err: str | None,
) -> None:
    try:
        from bot.game_audit_log import log_narrator_callback

        log_narrator_callback(
            game,
            manager,
            act=act,
            tid=tid,
            rid=rid,
            step_before=step_before,
            ns_before=substep_before,
            pending_before=pending_uid_before,
            error=err,
        )
    except Exception:
        logger.exception("audit log narrator callback failed")


async def _post_process_discipline(
    bot: Bot,
    callback: CallbackQuery,
    game: Game,
    act: str,
) -> bool:
    if not (
        no_host_assistant_narrator_active(game)
        and act in ("disc_no_ok", "disc_ok")
    ):
        return False
    from bot.bazpors_narrator import refresh_host_message_after_callback
    from bot.no_host_night_resolve import no_host_complete_discipline_and_resolve

    kick_uid = (
        game.bazpors_night_discipline_kick_uid if act == "disc_ok" else None
    )
    await safe_callback_answer(callback, "ثبت شد.")
    panel_sent = await no_host_complete_discipline_and_resolve(
        bot,
        game,
        manager,
        kicked_uid=kick_uid,
    )
    if not panel_sent:
        await refresh_host_message_after_callback(
            bot,
            game,
            manager,
            edit_in_place=callback.message,
        )
    await flush_elimination_notifications(bot, game)
    return True


async def _post_process_no_host_apply_resolve(
    bot: Bot,
    callback: CallbackQuery,
    game: Game,
    act: str,
) -> bool:
    if not (
        no_host_assistant_narrator_active(game) and act == "apply_resolve"
    ):
        return False
    from bot.no_host_night_resolve import no_host_complete_discipline_and_resolve

    await safe_callback_answer(callback, "ثبت شد.")
    await no_host_complete_discipline_and_resolve(
        bot,
        game,
        manager,
        send_discipline_broadcast=False,
    )
    await flush_elimination_notifications(bot, game)
    return True


def _assistant_panel_in_place(
    game: Game,
    callback: CallbackQuery,
    act: str,
    step_before: str | None,
) -> bool:
    from bot.bazpors_narrator import HOST_DISCIPLINE_FLOW_ACTS
    from bot.no_host_interrog_day import INTERROG_DAY_FLOW_ACTS
    from bot.no_host_table_inquiry import TABLE_INQUIRY_FLOW_ACTS

    if not (
        no_host_assistant_narrator_active(game)
        and callback.message is not None
    ):
        return False
    if act in HOST_DISCIPLINE_FLOW_ACTS:
        return True
    if act in TABLE_INQUIRY_FLOW_ACTS and (
        step_before == NO_HOST_TABLE_INQUIRY
        or game.bazpors_narrator_step == NO_HOST_TABLE_INQUIRY
    ):
        return True
    if act in INTERROG_DAY_FLOW_ACTS and (
        step_before == NO_HOST_INTERROG_DAY
        or game.bazpors_narrator_step == NO_HOST_INTERROG_DAY
    ):
        return True
    return False


async def _answer_popup_alerts(
    callback: CallbackQuery,
    game: Game,
    act: str,
    *,
    role_absent_alert: str | None,
    post_night_alert: str | None,
    citizen_win_alert: str | None,
    mafia_tie_alert: str | None,
    hunter_chain_alert: str | None,
    assistant_panel_in_place: bool,
) -> None:
    alert_chain: list[tuple[str | None, bool]] = [
        (shiad_detective_alert_text(game, act), True),
        (detective_inquiry_alert_text(game), True),
        (role_absent_alert, True),
        (post_night_alert, True),
        (citizen_win_alert, True),
        (mafia_tie_alert, True),
        (hunter_chain_alert, True),
    ]
    for text, use_alert in alert_chain:
        if text:
            await safe_callback_answer(
                callback, text, show_alert=use_alert
            )
            return
    if not assistant_panel_in_place:
        await safe_callback_answer(callback, "ثبت شد.")


async def _post_process_assistant_panel(
    bot: Bot,
    callback: CallbackQuery,
    game: Game,
    act: str,
) -> None:
    from bot.bazpors_narrator import (
        dismiss_no_host_narrator_operator_panels,
        finalize_assistant_panel_message,
        refresh_host_message_after_callback,
    )
    from bot.no_host_interrog_day import (
        apply_no_host_interrog_day_narrator_async,
        no_host_interrog_vote_hunter_chain_alert,
    )

    if act == "ih_req_ok":
        await apply_no_host_interrog_day_narrator_async(
            bot, game, manager, act
        )
        await safe_callback_answer(callback, "ثبت شد.")
        await finalize_assistant_panel_message(
            bot,
            game,
            callback.message,
            "✅ درخواست به بازپرس و بازیکنان ارسال شد.",
        )
    elif act == "ih_vok":
        pending_vote = game.no_host_interrog_day_pending_vote
        await apply_no_host_interrog_day_narrator_async(
            bot, game, manager, act
        )
        chain_alert = no_host_interrog_vote_hunter_chain_alert(
            game, manager, pending_vote
        )
        if chain_alert:
            await safe_callback_answer(callback, chain_alert, show_alert=True)
        else:
            await safe_callback_answer(callback, "ثبت شد.")
        if game.bazpors_narrator_step == NO_HOST_HANDOFF_OFFER:
            if callback.message:
                ref_c = game.bazpors_assistant_panel_chat_id
                ref_m = game.bazpors_assistant_panel_message_id
                msg = callback.message
                if ref_c != msg.chat.id or ref_m != msg.message_id:
                    try:
                        await bot.delete_message(
                            chat_id=msg.chat.id,
                            message_id=msg.message_id,
                        )
                    except TelegramBadRequest:
                        logger.debug(
                            "delete stale interrog panel chat_id=%s message_id=%s",
                            msg.chat.id,
                            msg.message_id,
                        )
        else:
            await refresh_host_message_after_callback(
                bot,
                game,
                manager,
                edit_in_place=callback.message,
            )
    elif act == "tinq_ok":
        clicked = callback.message
        await dismiss_no_host_narrator_operator_panels(
            bot, game, clicked=clicked
        )
        await apply_no_host_table_inquiry_confirm(bot, game, manager)
        await safe_callback_answer(callback, "ثبت شد.")
        if game.bazpors_narrator_step != NO_HOST_HANDOFF_OFFER:
            await refresh_host_message_after_callback(
                bot,
                game,
                manager,
                edit_in_place=None,
            )
    else:
        await safe_callback_answer(callback, "ثبت شد.")
        await refresh_host_message_after_callback(
            bot,
            game,
            manager,
            edit_in_place=callback.message,
        )
    await flush_elimination_notifications(bot, game)


async def _post_process_semi_auto_default(
    bot: Bot,
    callback: CallbackQuery,
    game: Game,
    act: str,
    tid: int,
    rid: str,
    step_before: str | None,
    pending_uid_before: int | None,
) -> None:
    from bot.bazpors_narrator import refresh_host_message_after_callback

    if callback.message and not preserve_night_end_host_message(
        step_before, act
    ):
        await _delete_callback_message(callback.message)
    if act == "apply_resolve":
        from bot.bazpors_night_panel_purge import (
            purge_stale_night_and_day_panel_messages,
        )

        await purge_stale_night_and_day_panel_messages(bot, game)
        await refresh_host_message_after_callback(bot, game, manager)
        return
    compact = narrator_compact_ack_html(
        game,
        manager,
        act,
        tid,
        rid,
        pending_uid_before=pending_uid_before,
    )
    await safe_send_message(
        bot,
        narrator_operator_user_id(game),
        compact,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    await refresh_host_message_after_callback(bot, game, manager)
    await flush_elimination_notifications(bot, game)


@router.callback_query(BazporsNarrCb.filter())
async def bazpors_narrator_cb(
    callback: CallbackQuery,
    callback_data: BazporsNarrCb,
    bot: Bot,
) -> None:
    if not callback.from_user or not callback.message:
        return
    if callback.message.chat.type != ChatType.PRIVATE:
        await safe_callback_answer(callback, "فقط در چت خصوصی.", show_alert=True)
        return
    game = manager.get_game(callback_data.code)
    if not game or not narrator_callback_user_may_act(
        game, callback.from_user.id
    ):
        await safe_callback_answer(
            callback,
            "فقط کمک‌کننده ربات یا ناظر (در حالت بدون گرداننده) می‌تواند این دکمه را بزند.",
            show_alert=True,
        )
        return

    act = callback_data.act
    if await _handle_tie_citizen(bot, callback, game, act):
        return
    if await _handle_tie_mafia(bot, callback, game, act):
        return
    if await _handle_ki_as_win(bot, callback, game, act):
        return

    pending_uid_before = game.bazpors_narrator_pending_uid
    step_before = game.bazpors_narrator_step
    substep_before = game.bazpors_night_substep
    role_absent_alert = (
        role_absent_popup_text(game, manager)
        if act == "role_absent_ok" and substep_before == NS_ROLE_ABSENT
        else None
    )
    post_night_alert = post_night_host_popup_text(
        game, manager, act, step_before
    )
    citizen_win_alert = (
        citizen_win_popup_text(game, manager)
        if game.bazpors_narrator_step != CITIZEN_WIN_GATE
        else None
    )
    mafia_tie_alert = (
        mafia_tie_popup_text(game, manager)
        if game.bazpors_narrator_step != MAFIA_TIE_GATE
        else None
    )
    hunter_chain_alert = None
    if pending_uid_before and act in (
        "confirm_intr_vote_yes",
        "confirm_day_yes",
    ):
        hunter_chain_alert = hunter_chain_confirm_alert_text(
            game, manager, pending_uid_before, public=True
        )

    err = process_narrator_callback(
        game,
        manager,
        act,
        callback_data.tid,
        callback_data.rid or "",
    )
    _audit_narrator_callback(
        game,
        act=act,
        tid=callback_data.tid,
        rid=callback_data.rid or "",
        step_before=step_before,
        substep_before=substep_before,
        pending_uid_before=pending_uid_before,
        err=err,
    )
    if err:
        await safe_callback_answer(callback, err, show_alert=True)
        return

    if act in ("handoff_skip", "handoff_pick") and (
        step_before == "no_host_handoff_offer"
        or game.bazpors_narrator_step == "no_host_handoff_offer"
    ):
        from bot.no_host_handoff import apply_handoff_narrator_async

        await safe_callback_answer(callback, "ثبت شد.")
        await _delete_callback_message(callback.message)
        await apply_handoff_narrator_async(
            bot,
            game,
            manager,
            act,
            callback_data.tid,
        )
        await flush_elimination_notifications(bot, game)
        return
    if await _post_process_discipline(bot, callback, game, act):
        return
    if await _post_process_no_host_apply_resolve(bot, callback, game, act):
        return

    assistant_panel = _assistant_panel_in_place(
        game, callback, act, step_before
    )
    await _answer_popup_alerts(
        callback,
        game,
        act,
        role_absent_alert=role_absent_alert,
        post_night_alert=post_night_alert,
        citizen_win_alert=citizen_win_alert,
        mafia_tie_alert=mafia_tie_alert,
        hunter_chain_alert=hunter_chain_alert,
        assistant_panel_in_place=assistant_panel,
    )
    if assistant_panel:
        await _post_process_assistant_panel(bot, callback, game, act)
        return

    await _post_process_semi_auto_default(
        bot,
        callback,
        game,
        act,
        callback_data.tid,
        callback_data.rid or "",
        step_before,
        pending_uid_before,
    )
