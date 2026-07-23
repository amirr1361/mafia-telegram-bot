"""امتیاز ناشناس به گرداننده — مستقل از اتاق فعال در حافظه."""

from __future__ import annotations

import html
import logging
import re
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot import db
from bot.text_fa import fa_digits as _fa_digits

if TYPE_CHECKING:
    from bot.game import GameManager

logger = logging.getLogger(__name__)

_RTS_RAW = re.compile(r"^rts:(?P<sid>\d+):(?P<stars>[1-5])$")
_RTX_RAW = re.compile(r"^rtx:(?P<sid>\d+)$")


class RateHostStars(CallbackData, prefix="rts"):
    sid: int
    stars: int


class RateHostSkip(CallbackData, prefix="rtx"):
    sid: int


def rating_stars_keyboard(session_id: int) -> InlineKeyboardMarkup:
    stars = ("⭐", "🌟", "✨", "💫", "⭐️")
    row = [
        InlineKeyboardButton(
            text=f"{i}{stars[i - 1]}",
            callback_data=RateHostStars(sid=session_id, stars=i).pack(),
        )
        for i in range(1, 6)
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            row,
            [
                InlineKeyboardButton(
                    text="✖️ انصراف (بدون امتیاز)",
                    callback_data=RateHostSkip(sid=session_id).pack(),
                ),
            ],
        ]
    )


def build_rating_prompt_html(
    gm: "GameManager",
    *,
    host_id: int,
    host_full_name: str = "",
    host_username: str | None = None,
) -> tuple[str, str]:
    host_plain = gm.format_user_tag(
        host_id,
        host_full_name or "گرداننده",
        host_username,
    )
    host_label = html.escape(host_plain)
    avg, n = db.narrator_aggregate_for_host(host_id)
    if n and avg is not None:
        cur_block = (
            "⭐ <b>امتیاز کنونی گرداننده در ربات</b>\n"
            f"میانگین <b>{avg:.2f}</b> از ۵ ستاره "
            f"({_fa_digits(n)} بازخورد)"
        )
    else:
        cur_block = (
            "⭐ <b>امتیاز کنونی گرداننده در ربات</b>\n"
            "<i>هنوز بازخوردی ثبت نشده؛ شما از اولین‌ها هستید.</i>"
        )
    body = (
        "⭐️ <b>بازخورد ناشناس به گرداننده</b>\n\n"
        f"🎙 <b>گردانندهٔ این بازی:</b> {host_label}\n\n"
        f"{cur_block}\n\n"
        "✨ <b>لطفاً امتیاز خود را ثبت کنید</b>\n"
        "یکی از دکمه‌های ۱ تا ۵ ⭐ در پایین را بزنید.\n\n"
        "🔒 امتیاز شما به‌صورت <b>ناشناس</b> ثبت می‌شود؛ "
        "نام شما برای گرداننده نمایش داده نمی‌شود و فقط در میانگین کلی ذخیره می‌شود.\n\n"
        "<i>حتی اگر اتاق بسته شده باشد، این دکمه‌ها همچنان معتبرند. "
        "در صورت مشکل: /rate</i>"
    )
    return body, host_label


async def send_rating_invites(
    bot: Bot,
    gm: "GameManager",
    *,
    session_id: int,
    host_id: int,
    players: list[dict[str, object]],
    host_full_name: str = "",
    host_username: str | None = None,
) -> None:
    text, _ = build_rating_prompt_html(
        gm,
        host_id=host_id,
        host_full_name=host_full_name,
        host_username=host_username,
    )
    kb = rating_stars_keyboard(session_id)
    for p in players:
        pid = int(p["id"])
        if pid == host_id:
            continue
        db.record_rating_invite(session_id, pid)
        try:
            await bot.send_message(
                chat_id=pid,
                text=text,
                parse_mode="HTML",
                reply_markup=kb,
            )
        except Exception:
            logger.debug("rating invite dm failed uid=%s sid=%s", pid, session_id)


async def resend_pending_rating_prompt(
    bot: Bot, gm: "GameManager", user_id: int
) -> bool:
    sid = db.latest_unrated_session_for_user(user_id)
    if sid is None:
        return False
    row = db.get_session(sid)
    if row is None:
        return False
    host_id = int(row["host_id"])
    if user_id == host_id:
        return False
    err = db.rating_submission_error(sid, user_id)
    if err is not None:
        return False
    text, _ = build_rating_prompt_html(gm, host_id=host_id)
    await bot.send_message(
        chat_id=user_id,
        text=(
            "🔁 <b>امتیاز معلق این دست</b>\n\n"
            f"{text}"
        ),
        parse_mode="HTML",
        reply_markup=rating_stars_keyboard(sid),
    )
    db.record_rating_invite(sid, user_id)
    return True


async def _apply_rating_stars(
    callback: CallbackQuery,
    *,
    sid: int,
    stars: int,
) -> None:
    if callback.from_user is None or callback.message is None:
        return
    uid = callback.from_user.id
    err = db.rating_submission_error(sid, uid)
    if err is not None:
        await callback.answer(err, show_alert=True)
        return
    ok = db.save_narrator_rating(sid, uid, stars)
    if not ok:
        await callback.answer("قبلاً برای این دست امتیاز داده‌اید.", show_alert=True)
        return
    await callback.answer("با تشکر، ثبت شد.")
    try:
        await callback.message.edit_text(
            f"✅ امتیاز <b>{stars}</b> از ۵ ستاره (ناشناس) ثبت شد.",
            parse_mode="HTML",
            reply_markup=None,
        )
    except Exception:
        pass


async def _apply_rating_skip(callback: CallbackQuery, *, sid: int) -> None:
    if callback.from_user is None or callback.message is None:
        return
    uid = callback.from_user.id
    err = db.rating_submission_error(sid, uid)
    if err is not None:
        if err == "شما بازیکن این دست نبودید.":
            await callback.answer(err, show_alert=True)
            return
        await callback.answer()
        return
    await callback.answer("بستید بدون امتیاز.")
    try:
        await callback.message.edit_text(
            "✖️ بدون ثبت امتیاز بستید.",
            reply_markup=None,
        )
    except Exception:
        pass


def register_post_game_rating_handlers(
    dp: Dispatcher, gm: "GameManager"
) -> None:
    router = Router(name="post_game_rating")

    @router.callback_query(RateHostStars.filter())
    async def rate_host_stars_cb(
        callback: CallbackQuery,
        callback_data: RateHostStars,
    ) -> None:
        await _apply_rating_stars(
            callback, sid=callback_data.sid, stars=callback_data.stars
        )

    @router.callback_query(RateHostSkip.filter())
    async def rate_host_skip_cb(
        callback: CallbackQuery,
        callback_data: RateHostSkip,
    ) -> None:
        await _apply_rating_skip(callback, sid=callback_data.sid)

    @router.callback_query(F.data.regexp(_RTS_RAW))
    async def rate_host_stars_raw_cb(callback: CallbackQuery) -> None:
        data = callback.data or ""
        m = _RTS_RAW.match(data)
        if m is None:
            return
        await _apply_rating_stars(
            callback,
            sid=int(m.group("sid")),
            stars=int(m.group("stars")),
        )

    @router.callback_query(F.data.regexp(_RTX_RAW))
    async def rate_host_skip_raw_cb(callback: CallbackQuery) -> None:
        data = callback.data or ""
        m = _RTX_RAW.match(data)
        if m is None:
            return
        await _apply_rating_skip(callback, sid=int(m.group("sid")))

    @router.message(Command("rate"))
    async def rate_cmd(msg: Message, bot: Bot) -> None:
        if msg.chat.type != ChatType.PRIVATE or msg.from_user is None:
            await msg.answer("فقط در چت خصوصی با ربات.")
            return
        sent = await resend_pending_rating_prompt(bot, gm, msg.from_user.id)
        if sent:
            await msg.answer("پنل امتیاز دوباره فرستاده شد.")
        else:
            await msg.answer(
                "امتیاز معلقی برای ثبت ندارید، یا قبلاً برای آخرین دست امتیاز داده‌اید."
            )

    dp.include_router(router)
