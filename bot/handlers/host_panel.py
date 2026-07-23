"""Handler router: host_panel."""

from __future__ import annotations

import logging

from aiogram import Bot, F, Router
from aiogram.enums import ChatType
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup
from bot.app_state import ROLE_DEAL_IN_PROGRESS_MSG
from bot.app_state import manager
from bot.main import (
    HostPanel,
    SalamatHostPanel,
    _host_shuffle_hides_player_names,
    _require_private,
    build_shuffle_confirm_prompt_html,
    bump_seat_shuffle_count,
    deal_roles_full_pipeline,
    deliver_seat_assignments,
    host_deal_roles_keyboard,
    host_seat_confirm_keyboard,
    is_bazpors_narrator_room,
    safe_edit_text,
)
from bot.bazpors_player_role_pick import (
    dispatch_player_role_pick_panels as dispatch_bazpors_role_pick_panels,
    start_player_role_pick as start_bazpors_role_pick,
)
from bot.mozakere_player_role_pick import (
    dispatch_player_role_pick_panels as dispatch_mozakere_role_pick_panels,
    start_player_role_pick as start_mozakere_role_pick,
)
from bot.mason_player_role_pick import (
    dispatch_player_role_pick_panels as dispatch_mason_role_pick_panels,
    start_player_role_pick as start_mason_role_pick,
)
from bot.player_role_pick_common import any_player_role_pick_active
from bot.models import Game, Phase, Player, Role
from bot.post_game_flow import resolve_game_context
from bot.text_fa import fa_digits as _fa_digits
from bot.tg_send import safe_callback_answer


logger = logging.getLogger(__name__)
router = Router(name="host_panel")


def register_host_panel_handlers(dp) -> None:
    dp.include_router(router)


@router.message(Command("shuffle"))
async def shuffle_cmd(msg: Message) -> None:
    if not _require_private(msg):
        return
    room, _, is_host = resolve_game_context(msg.from_user.id)
    if not room or not is_host:
        await msg.answer("فقط گرداننده می‌تواند صندلی‌ها را شافل کند.")
        return
    game = manager.get_game(room)
    if not game:
        return
    if game.scenario_name == "bazpors_salamat_test":
        await msg.answer(
            f"این اتاق تست شبکه سلامت است؛ صندلی‌ها از پیش برای {_fa_digits(game.max_players)} صندلی ساختگی ثبت شده‌اند."
        )
        return
    try:
        rows = manager.prepare_shuffle(game)
    except ValueError as err:
        await msg.answer(str(err))
        return
    if _host_shuffle_hides_player_names(game):
        bump_seat_shuffle_count(game)
        await msg.answer(
            build_shuffle_confirm_prompt_html(game, rows),
            parse_mode="HTML",
            reply_markup=host_seat_confirm_keyboard(game),
        )
        return
    lines = [f"🪑 صندلی {s}: {manager.format_player_tag(p)}" for s, p in rows]
    await msg.answer(
        "🔀 پیش‌نمایش صندلی‌ها:\n"
        + "\n".join(lines)
        + "\n\n✅ تأیید: /confirmshuffle\n"
        "🔁 شافل دوباره: /shuffle"
    )


@router.message(Command("confirmshuffle"))
async def confirmshuffle_cmd(msg: Message, bot: Bot) -> None:
    if not _require_private(msg):
        return
    room, _, is_host = resolve_game_context(msg.from_user.id)
    if not room or not is_host:
        await msg.answer("فقط گرداننده می‌تواند صندلی‌ها را تأیید کند.")
        return
    game = manager.get_game(room)
    if not game:
        return
    if game.scenario_name == "bazpors_salamat_test":
        await msg.answer(
            "این اتاق تست شبکه سلامت است؛ صندلی‌ها از پیش ثبت شده‌اند و شافل لازم نیست."
        )
        return
    pending = game.pending_seat_order
    if not pending:
        await msg.answer("اول با /shuffle یک چیدمان بسازید.")
        return
    if game.roles_dealt:
        await msg.answer("نقش‌ها پخش شده؛ شافل مجدد ممکن نیست.")
        return

    failed = await deliver_seat_assignments(bot, game)
    if failed:
        await msg.answer(
            "برای این بازیکنان پیام نرفت (ربات را استارت کرده باشند): "
            + ", ".join(failed)
            + "\nبعد از رفع مشکل دوباره /confirmshuffle بزنید."
        )
        return

    try:
        manager.confirm_shuffle(game)
    except ValueError as err:
        await msg.answer(str(err))
        return

    await msg.answer(
        "✅ صندلی‌ها ثبت شد و شماره‌ها برای بازیکنان فرستاده شد.\n\n"
        "برای ادامه «پخش نقش‌های تصادفی» را بزنید:",
        reply_markup=host_deal_roles_keyboard(game),
    )


@router.callback_query(SalamatHostPanel.filter())
async def salamat_host_panel_cb(
    callback: CallbackQuery,
    callback_data: SalamatHostPanel,
    bot: Bot,
) -> None:
    if not callback.from_user:
        return
    game = manager.get_game(callback_data.code)
    if not game or not is_bazpors_narrator_room(game):
        await safe_callback_answer(
            callback, "این پنل فقط برای گردانندگی نیمه‌خودکار بازپرس است.",
            show_alert=True,
        )
        return
    if callback.from_user.id != game.host_id:
        await safe_callback_answer(callback, "فقط گرداننده همین اتاق.", show_alert=True)
        return
    act = callback_data.act
    if act == "book":
        for chunk in bzs_rules.RULEBOOK_CHUNKS:
            try:
                await bot.send_message(
                    game.host_id,
                    chunk,
                    parse_mode="HTML",
                )
            except Exception:
                pass
        await safe_callback_answer(callback, "بخش‌های قانون ارسال شد.")
        return
    if act == "night":
        try:
            await bot.send_message(
                game.host_id,
                bzs_rules.NIGHT_ORDER_MAIN,
                parse_mode="HTML",
            )
        except Exception:
            pass
        await safe_callback_answer(callback, "ارسال شد.")
        return
    if act == "phase":
        try:
            await bot.send_message(
                game.host_id,
                bzs_rules.PHASES_OVERVIEW,
                parse_mode="HTML",
            )
        except Exception:
            pass
        await safe_callback_answer(callback, "ارسال شد.")
        return
    if act == "rep":
        try:
            await bot.send_message(
                game.host_id,
                bzs_rules.INTERROGATOR_QUICK_REF,
                parse_mode="HTML",
            )
        except Exception:
            pass
        await safe_callback_answer(callback, "ارسال شد.")
        return
    await safe_callback_answer(callback, "دکمه نامعتبر است.", show_alert=True)


@router.callback_query(HostPanel.filter())
async def host_panel_cb(
    callback: CallbackQuery,
    callback_data: HostPanel,
    bot: Bot,
) -> None:
    if not callback.message or callback.message.chat.type != ChatType.PRIVATE:
        await safe_callback_answer(callback, "فقط در چت خصوصی.", show_alert=True)
        return
    if not callback.from_user:
        return
    game = manager.get_game(callback_data.code)
    if not game or callback.from_user.id != game.host_id:
        await safe_callback_answer(callback, "فقط گرداننده همین اتاق.", show_alert=True)
        return

    act = callback_data.act

    if game.scenario_name == "bazpors_salamat_test" and act in (
        "fs",
        "fd",
        "sr",
        "sy",
    ):
        await safe_callback_answer(
            callback,
            "اتاق تست سلامت: صندلی‌ها از پیش ثبت است؛ از این دکمه‌ها استفاده نکنید.",
            show_alert=True,
        )
        return

    if act == "fs":
        if game.phase != Phase.LOBBY or game.roles_dealt:
            await safe_callback_answer(callback, "الان این کار ممکن نیست.", show_alert=True)
            return
        try:
            rows = manager.prepare_shuffle(game)
        except ValueError as err:
            await safe_callback_answer(callback, str(err)[:200], show_alert=True)
            return
        if _host_shuffle_hides_player_names(game):
            bump_seat_shuffle_count(game)
            text = build_shuffle_confirm_prompt_html(game, rows)
            await safe_callback_answer(callback)
            await safe_edit_text(
                callback.message,
                text,
                reply_markup=host_seat_confirm_keyboard(game),
                parse_mode="HTML",
            )
            return
        text = build_shuffle_confirm_prompt_html(game, rows)
        await safe_callback_answer(callback)
        await callback.message.answer(
            text,
            reply_markup=host_seat_confirm_keyboard(game),
            parse_mode="HTML",
        )
        return

    if act == "fd":
        if game.phase != Phase.LOBBY:
            await safe_callback_answer(callback, "بازی در لابی نیست.", show_alert=True)
            return
        if not game.seats_finalized:
            await safe_callback_answer(
                callback,
                "ابتدا «شافل شماره صندلی» را بزنید و تأیید کنید.",
                show_alert=True,
            )
            return
        if game.roles_dealt:
            await safe_callback_answer(callback, "نقش‌ها قبلاً پخش شده‌اند.", show_alert=True)
            return
        await safe_callback_answer(callback)
        await callback.message.answer(
            "🎭 برای ادامه پخش نقش‌های تصادفی را بزنید:",
            reply_markup=host_deal_roles_keyboard(game),
        )
        return

    if act == "sr":
        if game.phase != Phase.LOBBY or game.roles_dealt:
            await safe_callback_answer(callback, "الان مجاز نیست.", show_alert=True)
            return
        try:
            rows = manager.prepare_shuffle(game)
        except ValueError as err:
            await safe_callback_answer(callback, str(err)[:200], show_alert=True)
            return
        if _host_shuffle_hides_player_names(game):
            bump_seat_shuffle_count(game)
        text = build_shuffle_confirm_prompt_html(game, rows)
        changed = await safe_edit_text(
            callback.message,
            text,
            reply_markup=host_seat_confirm_keyboard(game),
            parse_mode="HTML",
        )
        n = game.bazpors_seat_shuffle_count
        ack = (
            f"شماره صندلی‌ها {_fa_digits(n)} بار شافل شد."
            if _host_shuffle_hides_player_names(game)
            else ("چیدمان جدید شد." if changed else "همین چیدمان فعال است.")
        )
        await safe_callback_answer(callback, ack)
        return

    if act == "sy":
        if game.phase != Phase.LOBBY or game.roles_dealt:
            await safe_callback_answer(callback, "الان مجاز نیست.", show_alert=True)
            return
        if not game.pending_seat_order:
            await safe_callback_answer(callback, "ابتدا شافل را انجام دهید.", show_alert=True)
            return
        await safe_callback_answer(callback, "⏳ در حال ارسال شماره صندلی به بازیکنان…")
        failed = await deliver_seat_assignments(bot, game)
        if failed:
            await callback.message.answer(
                "⚠️ ارسال صندلی ناموفق برای: "
                + ", ".join(failed)
                + "\nبعد از رفع، دوباره تأیید کنید."
            )
            return
        try:
            manager.confirm_shuffle(game)
        except ValueError as err:
            await callback.message.answer(str(err)[:500])
            return
        await safe_edit_text(
            callback.message,
            "✅ شماره صندلی‌ها ثبت و برای بازیکنان فرستاده شد.\n\n"
            "برای ادامه پخش نقش‌های تصادفی را بزنید:",
            reply_markup=host_deal_roles_keyboard(game),
            parse_mode="HTML",
        )
        return

    if act == "dr":
        if any_player_role_pick_active(game):
            await safe_callback_answer(
                callback,
                "جریان انتخاب نقش توسط بازیکنان فعال است.",
                show_alert=True,
            )
            return
        if game.roles_dealt:
            await safe_callback_answer(callback, "نقش‌ها قبلاً پخش شده‌اند.", show_alert=True)
            return
        if game.phase != Phase.LOBBY:
            await safe_callback_answer(callback, "الان پخش نقش از اینجا ممکن نیست.", show_alert=True)
            return
        await safe_callback_answer(callback, "⏳ در حال پخش نقش‌ها و ارسال برای بازیکنان…")
        err = await deal_roles_full_pipeline(bot, game)
        if err:
            if err == ROLE_DEAL_IN_PROGRESS_MSG:
                await callback.message.answer(err)
            else:
                await callback.message.answer(f"⚠️ {err}")
            return
        await safe_edit_text(
            callback.message,
            "✅ نقش‌ها پخش شد. لیست کامل نقش‌ها فقط برای شما در پیام جدا فرستاده شد."
        )
        return

    if act == "pr":
        if game.scenario_name not in ("bazpors", "mozakere", "masoon"):
            await safe_callback_answer(
                callback,
                "این گزینه برای این سناریو فعال نیست.",
                show_alert=True,
            )
            return
        if game.phase != Phase.LOBBY or game.roles_dealt:
            await safe_callback_answer(callback, "الان مجاز نیست.", show_alert=True)
            return
        if any_player_role_pick_active(game):
            await safe_callback_answer(
                callback,
                "انتخاب نقش توسط بازیکنان قبلاً شروع شده است.",
                show_alert=True,
            )
            return
        if game.scenario_name == "bazpors":
            err = start_bazpors_role_pick(game)
            dispatch = dispatch_bazpors_role_pick_panels
        elif game.scenario_name == "mozakere":
            err = start_mozakere_role_pick(game)
            dispatch = dispatch_mozakere_role_pick_panels
        else:
            err = start_mason_role_pick(game)
            dispatch = dispatch_mason_role_pick_panels
        if err:
            await safe_callback_answer(callback, err, show_alert=True)
            return
        await safe_callback_answer(callback, "شروع شد.")
        await dispatch(bot, game)
        await safe_edit_text(
            callback.message,
            "✅ جریان «انتخاب نقش‌ها توسط بازیکنان» شروع شد.\n\n"
            "پنل انتخاب شماره برای همه بازیکنان ارسال شد.",
            reply_markup=None,
            parse_mode="HTML",
        )
        return

    await safe_callback_answer(callback, "دکمه نامعتبر است.", show_alert=True)


@router.message(Command("dealroles"))
async def dealroles_cmd(msg: Message, bot: Bot) -> None:
    if not _require_private(msg):
        return
    room, _, is_host = resolve_game_context(msg.from_user.id)
    if not room or not is_host:
        await msg.answer("فقط گرداننده می‌تواند نقش بپراکند.")
        return
    game = manager.get_game(room)
    if not game:
        return

    err = await deal_roles_full_pipeline(bot, game)
    if err:
        await msg.answer(err)


@router.message(Command("startgame"))
async def start_game_cmd(msg: Message) -> None:
    if not _require_private(msg):
        return
    await msg.answer(
        "📋 مراحل شروع (گرداننده):\n\n"
        "۱ 🔀 لابی پر → /shuffle → /confirmshuffle\n"
        "۲ 🎭 /dealroles\n\n"
        "✍️ روایت همیشه دستی است و ربات فاز را پیش نمی‌برد."
    )
