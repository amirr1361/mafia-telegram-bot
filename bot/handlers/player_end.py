"""Handler router: player_end."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from bot.app_state import manager
from bot.main import (
    EmergencyLeaveCancel,
    EmergencyLeaveConfirm,
    PlayerEndApprove,
    PlayerEndBroadcastConfirm,
    PlayerEndDismiss,
    _player_end_dismiss_message,
    _process_player_end_approve,
    _require_private,
    broadcast_game,
    broadcast_player_end_vote_started,
    is_bazpors_semi_auto_room,
    notify_initiator_winner_keyboard,
    player_end_broadcast_confirm_keyboard_for,
)
from bot.models import Game, Phase, Player, Role
from bot.post_game_flow import resolve_game_context
from bot.text_fa import fa_digits as _fa_digits


logger = logging.getLogger(__name__)
router = Router(name="player_end")


def register_player_end_handlers(dp) -> None:
    dp.include_router(router)


@router.callback_query(EmergencyLeaveConfirm.filter())
async def emergency_leave_confirm_cb(
    callback: CallbackQuery,
    callback_data: EmergencyLeaveConfirm,
    bot: Bot,
) -> None:
    if not callback.from_user or callback.message is None:
        return
    game = manager.get_game(callback_data.code)
    if not game:
        await callback.answer("این اتاق دیگر فعال نیست.", show_alert=True)
        return
    if game_observer_mirror_active(game):
        await callback.answer(
            "از دکمهٔ همان پیام خودتان استفاده کنید.",
            show_alert=True,
        )
        return
    uid = callback.from_user.id
    if uid == game.host_id:
        await callback.answer("گرداننده از این مسیر خارج نمی‌شود.", show_alert=True)
        return
    if uid not in game.players:
        await callback.answer("شما در این اتاق نیستید.", show_alert=True)
        return
    host_id = game.host_id
    code = game.room_code
    cancel_s, elected = manager.remove_player_from_manual_game(game, uid)
    if cancel_s == "no":
        await callback.answer("خروج ممکن نیست.", show_alert=True)
        return
    await callback.answer("از بازی خارج شدید.")
    try:
        await callback.message.edit_text("✅ از بازی خارج شدید.", reply_markup=None)
    except Exception:
        pass
    leftover = manager.get_game(code)
    if leftover is None:
        try:
            await bot.send_message(
                host_id,
                "👋 آخرین بازیکن خارج شد؛ اتاق بسته شد.",
            )
        except Exception:
            pass
        return
    leaver = manager.format_user_tag(
        uid,
        callback.from_user.full_name or "",
        callback.from_user.username,
    )
    await broadcast_game(
        bot,
        leftover,
        f"🚪 {leaver} بازی را با خروج اضطراری ترک کرد.",
        exclude=uid,
    )
    if cancel_s == "vote_cancelled":
        await broadcast_game(
            bot,
            leftover,
            "❎ درخواست پایان بدون گرداننده لغو شد، چون درخواست‌دهنده خارج شد.",
        )
    if elected is not None:
        await notify_initiator_winner_keyboard(bot, code, elected)


@router.callback_query(EmergencyLeaveCancel.filter())
async def emergency_leave_cancel_cb(
    callback: CallbackQuery,
    callback_data: EmergencyLeaveCancel,
) -> None:
    if callback.message is None:
        return
    game = manager.get_game(callback_data.code)
    if game and game_observer_mirror_active(game):
        await callback.answer(
            "از دکمهٔ همان پیام خودتان استفاده کنید.",
            show_alert=True,
        )
        return
    await callback.answer("لغو شد.")
    try:
        await callback.message.edit_text(
            "✖️ خروج اضطراری لغو شد. همچنان در بازی هستید.",
            reply_markup=None,
        )
    except Exception:
        pass


@router.callback_query(PlayerEndDismiss.filter())
async def player_end_dismiss_cb(
    callback: CallbackQuery,
    callback_data: PlayerEndDismiss,
) -> None:
    if not callback.from_user or callback.message is None:
        return
    game = manager.get_game(callback_data.code)
    if game and game_observer_mirror_active(game):
        await callback.answer(
            "از دکمهٔ همان پیام خودتان استفاده کنید.",
            show_alert=True,
        )
        return
    await _player_end_dismiss_message(callback)


@router.message(Command("request_end"))
async def request_end_cmd(msg: Message, bot: Bot) -> None:
    if not _require_private(msg):
        return
    uid = msg.from_user.id
    room, player, is_host = resolve_game_context(uid)
    if is_host:
        await msg.answer("گرداننده برای پایان بازی از /endgame استفاده کند.")
        return
    if not room or not player:
        await msg.answer("شما در هیچ بازی فعالی به‌عنوان بازیکن نیستید.")
        return
    game = manager.get_game(room)
    if not game:
        await msg.answer("اتاق پیدا نشد.")
        return
    if game.scenario_name == "bazpors_salamat_test":
        await msg.answer(
            "در اتاق تست شبکه سلامت فقط صندلی‌های ساختگی ثبت شده‌اند؛ "
            "رأی پایان جمعی برای این حالت در نظر گرفته نشده است."
        )
        return
    if is_bazpors_semi_auto_room(game):
        await msg.answer(
            "در گردانندگی نیمه‌خودکار، پایان بازی را گرداننده با /endgame ثبت می‌کند."
        )
        return
    if game.phase != Phase.MANUAL or not game.roles_dealt:
        await msg.answer("این دستور فقط بعد از پخش نقش و در فاز روایت دستی است.")
        return
    if game.player_end_winner_picker_id is not None:
        await msg.answer(
            "اول باید برندهٔ این دست ثبت شود؛ همان بازیکنی که همه به او رأی دادند "
            "پیام انتخاب برنده را دارد."
        )
        return
    if game.player_end_initiator_id is not None and manager.player_end_vote_active(game):
        await msg.answer(
            "یک درخواست پایان بدون گرداننده هنوز فعال است؛ یا همه تأیید کنند یا مهلت تمام شود."
        )
        return
    if game.player_end_initiator_id is not None and not manager.player_end_vote_active(game):
        manager.clear_player_end_vote(game)

    if game.player_end_broadcast_pending_uid is not None:
        if manager.player_end_broadcast_confirm_expired(game):
            manager.clear_player_end_broadcast_pending(game)
        elif game.player_end_broadcast_pending_uid != uid:
            await msg.answer(
                "یک بازیکن دیگر در حال تأیید اولیهٔ درخواست پایان است. کمی صبر کنید یا با او هماهنگ کنید."
            )
            return
        else:
            await msg.answer(
                "هنوز منتظر تأیید شما از پیام قبلی هستیم.\n"
                "یکی از دو دکمه را بزنید یا اگر مهلت تمام شد دوباره /request_end بزنید.",
                reply_markup=player_end_broadcast_confirm_keyboard_for(
                    game, uid
                ),
            )
            return

    manager.set_player_end_broadcast_pending(game, uid)
    pbc_text = (
        "🗳 <b>درخواست پایان با رأی همهٔ بازیکنان</b>\n\n"
        "شما می‌خواهید این دست را تمام کنید و برای همهٔ بازیکنان (به‌جز گرداننده) "
        f"پیام رأی فرستاده شود؛ تا <b>{_fa_digits(game.player_end_approval_minutes)}</b> دقیقه باید همه تأیید کنند.\n\n"
        f"ابتدا خودتان تأیید کنید: آیا می‌خواهید این پیام برای همه برود؟\n"
        f"<i>مهلت این تأیید: {_fa_digits(game.player_end_broadcast_confirm_minutes)} دقیقه.</i>"
    )
    pbc_kb = player_end_broadcast_confirm_keyboard_for(game, uid)
    pbc_key = mirror_ui_claim_key(game.room_code, "player_end_broadcast", uid)
    await send_to_player(
        bot,
        game,
        uid,
        pbc_text,
        parse_mode="HTML",
        reply_markup=pbc_kb,
        mirror_reply_markup=pbc_kb,
        mirror_ui_key=pbc_key,
    )


@router.callback_query(PlayerEndBroadcastConfirm.filter())
async def player_end_broadcast_confirm_cb(
    callback: CallbackQuery,
    callback_data: PlayerEndBroadcastConfirm,
    bot: Bot,
) -> None:
    if not callback.from_user or callback.message is None:
        return
    game = manager.get_game(callback_data.code)
    if not game:
        await callback.answer("اتاق دیگر فعال نیست.", show_alert=True)
        return
    if game_observer_mirror_active(game):
        await callback.answer(
            "از دکمهٔ همان پیام خودتان استفاده کنید.",
            show_alert=True,
        )
        return
    uid = callback.from_user.id
    if uid != game.player_end_broadcast_pending_uid:
        await callback.answer("فقط همان کسی که /request_end زده می‌تواند تأیید کند.", show_alert=True)
        return
    if manager.player_end_broadcast_confirm_expired(game):
        manager.clear_player_end_broadcast_pending(game)
        await callback.answer("مهلت تأیید تمام شده.", show_alert=True)
        try:
            await callback.message.edit_text(
                "⌛ مهلت تأیید اولیه تمام شد. در صورت نیاز دوباره /request_end بزنید.",
                reply_markup=None,
            )
        except Exception:
            pass
        return
    if callback_data.ok == 0:
        manager.clear_player_end_broadcast_pending(game)
        await callback.answer("لغو شد.")
        try:
            await callback.message.edit_text(
                "✖️ درخواست پایان جمعی را لغو کردید.",
                reply_markup=None,
            )
        except Exception:
            pass
        return

    manager.clear_player_end_broadcast_pending(game)
    err = manager.start_player_end_vote(game, uid)
    if err:
        msgs = {
            "phase": "الان نمی‌توان این درخواست را ثبت کرد.",
            "host": "خطا.",
            "not_player": "شما در این اتاق نیستید.",
            "picker_pending": "اول برنده را ثبت کنید.",
            "already": "یک رأی فعال است.",
            "pending_confirm_other": "تداخل وضعیت؛ دوباره تلاش کنید.",
            "await_first_confirm": "وضعیت نامعتبر؛ دوباره /request_end بزنید.",
            "sandbox": "در اتاق تست شبکه سلامت رأی پایان جمعی فعال نیست.",
        }
        await callback.answer(msgs.get(err, "خطا."), show_alert=True)
        return
    await broadcast_player_end_vote_started(bot, game)
    await callback.answer("برای همه فرستاده شد.")
    try:
        n = len(game.players)
        await callback.message.edit_text(
            f"✅ درخواست برای همه فرستاده شد.\n"
            f"تا {_fa_digits(game.player_end_approval_minutes)} دقیقه باید هر {n} بازیکن یک بار تأیید کند.",
            reply_markup=None,
        )
    except Exception:
        pass


@router.callback_query(PlayerEndApprove.filter())
async def player_end_approve_cb(
    callback: CallbackQuery,
    callback_data: PlayerEndApprove,
    bot: Bot,
) -> None:
    if not callback.from_user or callback.message is None:
        return
    game = manager.get_game(callback_data.code)
    if not game:
        await callback.answer("اتاق دیگر فعال نیست.", show_alert=True)
        return
    if game_observer_mirror_active(game):
        await callback.answer(
            "از دکمهٔ همان پیام خودتان استفاده کنید.",
            show_alert=True,
        )
        return
    await _process_player_end_approve(
        callback, bot, game, callback.from_user.id
    )
