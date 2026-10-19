"""پس از شب مافیای روسی: اخراج انضباطی، گزارش عمومی، استعلام میز، روز بعد.

قوانین شب بازپرسی/مذاکره را اجرا نمی‌کند. فقط متن و شمارش عمومی آن‌ها را قرض می‌گیرد.
"""

from __future__ import annotations

import logging

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.models import Game, Phase, Role

logger = logging.getLogger(__name__)

_DISCIPLINE_ROLE_MARK = "</b> — "


def _fa(n: int) -> str:
    return str(n).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))


def _night_of(parts: list[str]) -> int | None:
    if len(parts) < 4:
        return None
    try:
        return int(parts[3])
    except ValueError:
        return None


def russian_table_inquiry_limit(game: Game) -> int:
    seated = sum(1 for player in game.players.values() if player.role != Role.OBSERVER)
    return 1 if seated <= 8 else 2


def _strip_discipline_roles(text: str) -> str:
    """اخراج انضباطی در گزارش عمومی نام را می‌آورد و نقش را نه."""
    lines: list[str] = []
    for line in text.split("\n"):
        if line.startswith("اخراج انضباطی:") and _DISCIPLINE_ROLE_MARK in line:
            line = line.split(_DISCIPLINE_ROLE_MARK, 1)[0] + "</b>"
        lines.append(line)
    return "\n".join(lines)


def _persist(game: Game, reason: str) -> None:
    try:
        from bot.game_snapshot import persist_game_snapshot

        persist_game_snapshot(game, reason=reason)
    except Exception:
        logger.debug("Russian Mafia snapshot skipped reason=%s", reason, exc_info=True)


async def _send(bot: Bot, uid: int, text: str, **kwargs: object) -> bool:
    from bot.russian_mafia_flow import safe_send_message

    return await safe_send_message(bot, uid, text, **kwargs)


def _discipline_ask_text(game: Game) -> str:
    night = _fa(game.russian_mafia_night_index)
    return (
        f"🌙 شب {night} — <b>اخراج انضباطی</b>\n\n"
        "نقش‌های شب تمام شد.\n"
        "آیا در این شب می‌خواهی <b>اخراج انضباطی</b> انجام بدهی؟"
    )


def _discipline_ask_keyboard(game: Game) -> InlineKeyboardMarkup:
    night = game.russian_mafia_night_index
    code = game.room_code
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ بله، اخراج انضباطی",
                    callback_data=f"rmh:{code}:disc_yes:{night}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="❌ خیر",
                    callback_data=f"rmh:{code}:disc_no:{night}",
                )
            ],
        ]
    )


def _living_rows(game: Game) -> list[list[InlineKeyboardButton]]:
    from bot.russian_mafia_flow import _alive_targets

    night = game.russian_mafia_night_index
    code = game.room_code
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for player in _alive_targets(game):
        seat = player.seat if player.seat is not None else player.user_id
        row.append(
            InlineKeyboardButton(
                text=f"{seat}. {player.full_name}"[:40],
                callback_data=f"rmh:{code}:disc_pick:{night}:{player.user_id}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text="↩️ بازگشت",
                callback_data=f"rmh:{code}:disc_back:{night}",
            )
        ]
    )
    return rows or [[
        InlineKeyboardButton(text="بازیکن زنده‌ای نیست", callback_data="noop")
    ]]


def _inquiry_ask_keyboard(game: Game) -> InlineKeyboardMarkup:
    night = game.russian_mafia_night_index
    code = game.room_code
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔘 بله",
                    callback_data=f"rmh:{code}:inq_yes:{night}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔘 خیر",
                    callback_data=f"rmh:{code}:inq_no:{night}",
                )
            ],
        ]
    )


def _inquiry_confirm_keyboard(game: Game) -> InlineKeyboardMarkup:
    night = game.russian_mafia_night_index
    code = game.room_code
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید",
                    callback_data=f"rmh:{code}:inq_ok:{night}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="↩️ بازگشت",
                    callback_data=f"rmh:{code}:inq_back:{night}",
                )
            ],
        ]
    )


async def _edit_or_send(
    callback: CallbackQuery | None,
    bot: Bot,
    game: Game,
    text: str,
    markup: InlineKeyboardMarkup | None,
) -> bool:
    from bot.russian_mafia_flow import russian_helper_user_id

    if callback is not None and callback.message is not None:
        try:
            await callback.message.edit_text(
                text, reply_markup=markup, parse_mode="HTML"
            )
            return True
        except Exception:
            logger.debug("Russian Mafia helper panel edit failed", exc_info=True)
    return await _send(
        bot,
        russian_helper_user_id(game),
        text,
        parse_mode="HTML",
        reply_markup=markup,
    )


def _stale_night(game: Game, night: int | None) -> bool:
    return night is None or night != game.russian_mafia_night_index


async def _answer(callback: CallbackQuery, text: str, *, alert: bool = False) -> None:
    from bot.russian_mafia_flow import safe_callback_answer

    await safe_callback_answer(callback, text, show_alert=alert)


async def publish_russian_night_report(bot: Bot, game: Game) -> None:
    night = game.russian_mafia_night_index
    if game.russian_mafia_night_result_sent_index == night:
        logger.info(
            "Russian Mafia room=%s night result already sent; skipping duplicate",
            game.room_code,
        )
        return
    from bot.app_state import manager
    from bot.game import is_synthetic_player_uid
    from bot.no_host_night_resolve import (
        build_no_host_night_results_broadcast_html,
        deliver_night_results_to_eliminated_from_night,
    )
    from bot.observer_delivery import broadcast_to_alive_players
    from bot.russian_mafia import russian_mafia_observer_registered
    from bot.russian_mafia_flow import russian_helper_user_id

    results = _strip_discipline_roles(
        build_no_host_night_results_broadcast_html(game, manager)
    )
    await broadcast_to_alive_players(
        bot,
        game,
        results,
        parse_mode="HTML",
        is_synthetic_uid=is_synthetic_player_uid,
    )
    game.russian_mafia_night_result_sent_index = night
    try:
        await deliver_night_results_to_eliminated_from_night(
            bot, game, manager, results
        )
    except Exception:
        logger.exception(
            "Russian Mafia room=%s night report delivery to eliminated failed",
            game.room_code,
        )
    helper = russian_helper_user_id(game)
    helper_player = game.players.get(helper)
    if helper_player is None or not helper_player.is_alive:
        await _send(bot, helper, results, parse_mode="HTML")
    if russian_mafia_observer_registered(game) and game.observer_user_id is not None:
        observer = game.players.get(game.observer_user_id)
        if observer is None or not observer.is_alive:
            await _send(bot, game.observer_user_id, results, parse_mode="HTML")
    logger.info(
        "Russian Mafia room=%s night result announcement sent",
        game.room_code,
    )
    _persist(game, "russian_night_report")


async def _announce_winner_once(bot: Bot, game: Game) -> None:
    from bot.russian_mafia import winner_of
    from bot.russian_mafia_flow import russian_helper_user_id

    if game.phase != Phase.ENDED or game.russian_mafia_winner_announced:
        return
    winner = winner_of(game)
    if winner is None:
        return
    game.russian_mafia_winner_announced = True
    await _send(
        bot,
        russian_helper_user_id(game),
        "شهروندها برنده شدند." if winner == "town" else "مافیا برنده شد.",
    )


async def _open_next_day(bot: Bot, game: Game) -> None:
    from bot.russian_mafia_flow import open_day

    if game.phase == Phase.ENDED:
        return
    night = game.russian_mafia_night_index
    if game.russian_mafia_inquiry_completed_night == night:
        logger.info(
            "Russian Mafia room=%s next day already opened for night=%s",
            game.room_code,
            night,
        )
        return
    game.russian_mafia_inquiry_completed_night = night
    game.russian_mafia_post_night_stage = "done"
    await open_day(bot, game)
    logger.info(
        "Russian Mafia room=%s next day opened day=%s",
        game.room_code,
        game.russian_mafia_day_index,
    )


async def _offer_inquiry_or_day(
    bot: Bot, game: Game, callback: CallbackQuery | None = None
) -> None:
    if game.phase == Phase.ENDED:
        game.russian_mafia_post_night_stage = "done"
        return
    limit = russian_table_inquiry_limit(game)
    used = game.russian_mafia_table_inquiry_used
    if used >= limit:
        logger.info(
            "Russian Mafia room=%s table inquiry skipped used=%s limit=%s",
            game.room_code,
            used,
            limit,
        )
        await _open_next_day(bot, game)
        return
    from bot.no_host_table_inquiry import build_table_inquiry_ask_panel

    game.russian_mafia_table_inquiry_pending = None
    sent = await _edit_or_send(
        callback,
        bot,
        game,
        build_table_inquiry_ask_panel(),
        _inquiry_ask_keyboard(game),
    )
    if not sent:
        logger.info(
            "Russian Mafia room=%s table inquiry panel was not delivered",
            game.room_code,
        )
        return
    game.russian_mafia_post_night_stage = "inquiry_ask"
    logger.info(
        "Russian Mafia room=%s table inquiry prompt opened used=%s limit=%s",
        game.room_code,
        used,
        limit,
    )


async def begin_russian_post_night(bot: Bot, game: Game) -> None:
    """شب حل شد. تا تمام شدن اخراج انضباطی، گزارش نهایی و روز بعد شروع نمی‌شود."""
    from bot.russian_mafia_flow import (
        _close_russian_defense_panels,
        _close_slot,
        russian_helper_user_id,
    )

    night = game.russian_mafia_night_index
    if game.russian_mafia_night_result_sent_index == night:
        logger.info(
            "Russian Mafia room=%s night result already sent; skipping duplicate",
            game.room_code,
        )
        return
    if game.russian_mafia_discipline_prompt_night == night or game.russian_mafia_post_night_stage in {
        "discipline_ask",
        "discipline_pick",
        "discipline_confirm",
        "inquiry_ask",
        "inquiry_confirm",
    }:
        logger.info(
            "Russian Mafia room=%s post-night already open stage=%s",
            game.room_code,
            game.russian_mafia_post_night_stage,
        )
        return
    for slot in ("mafia", "doctor", "detective"):
        await _close_slot(bot, game, slot)
    await _close_russian_defense_panels(bot, game)
    snap = game.bazpors_alive_at_night_start or {uid: True for uid in game.players}
    deaths = [
        uid
        for uid, was_alive in snap.items()
        if was_alive and uid in game.players and not game.players[uid].is_alive
    ]
    if deaths:
        from bot.observer_delivery import flush_elimination_notifications

        await flush_elimination_notifications(bot, game)
        logger.info(
            "Russian Mafia room=%s night resolved death_user_id=%s",
            game.room_code,
            ",".join(str(uid) for uid in deaths),
        )
    else:
        logger.info(
            "Russian Mafia room=%s night resolved no_death=True",
            game.room_code,
        )
    if game.phase == Phase.ENDED:
        await publish_russian_night_report(bot, game)
        await _announce_winner_once(bot, game)
        game.russian_mafia_post_night_stage = "done"
        logger.info(
            "Russian Mafia room=%s game ended after night; skipping discipline and next day",
            game.room_code,
        )
        return
    sent = await _send(
        bot,
        russian_helper_user_id(game),
        _discipline_ask_text(game),
        parse_mode="HTML",
        reply_markup=_discipline_ask_keyboard(game),
    )
    if not sent:
        logger.info(
            "Russian Mafia room=%s disciplinary prompt was not delivered",
            game.room_code,
        )
        return
    game.russian_mafia_post_night_stage = "discipline_ask"
    game.russian_mafia_discipline_prompt_night = night
    game.russian_mafia_discipline_target = None
    logger.info(
        "Russian Mafia room=%s disciplinary prompt opened night=%s",
        game.room_code,
        night,
    )


async def _after_discipline(
    callback: CallbackQuery, bot: Bot, game: Game
) -> None:
    await publish_russian_night_report(bot, game)
    if game.phase == Phase.ENDED:
        await _announce_winner_once(bot, game)
        game.russian_mafia_post_night_stage = "done"
        logger.info(
            "Russian Mafia room=%s victory after discipline; no further panels",
            game.room_code,
        )
        return
    await _offer_inquiry_or_day(bot, game, callback)


async def _show_discipline_pick(callback: CallbackQuery, bot: Bot, game: Game) -> None:
    game.russian_mafia_post_night_stage = "discipline_pick"
    await _edit_or_send(
        callback,
        bot,
        game,
        "🚪 <b>اخراج انضباطی</b>\n\nبازیکنی را که قصد اخراج انضباطی داری انتخاب کن.",
        InlineKeyboardMarkup(inline_keyboard=_living_rows(game)),
    )


async def handle_russian_host_post_night(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    act: str,
    parts: list[str],
) -> None:
    from bot.russian_mafia import STALE_ACTION_FA
    from bot.russian_mafia_flow import eliminate, finish_if_won

    night = _night_of(parts)
    if _stale_night(game, night):
        logger.info(
            "Russian Mafia room=%s blocked stale post-night callback act=%s generation=%s expected=%s",
            game.room_code,
            act,
            night,
            game.russian_mafia_night_index,
        )
        await _answer(callback, STALE_ACTION_FA, alert=True)
        return
    stage = game.russian_mafia_post_night_stage

    if act == "disc_yes":
        if stage != "discipline_ask":
            await _answer(callback, STALE_ACTION_FA, alert=True)
            return
        logger.info("Russian Mafia room=%s disciplinary decision=YES", game.room_code)
        await _show_discipline_pick(callback, bot, game)
        await _answer(callback, "بازیکن را انتخاب کنید.")
        return

    if act == "disc_no":
        if stage != "discipline_ask":
            await _answer(callback, STALE_ACTION_FA, alert=True)
            return
        logger.info("Russian Mafia room=%s disciplinary decision=NO", game.room_code)
        game.russian_mafia_post_night_stage = "discipline_skipped"
        game.russian_mafia_discipline_target = None
        await _answer(callback, "بدون اخراج انضباطی.")
        await _after_discipline(callback, bot, game)
        return

    if act == "disc_pick":
        if stage != "discipline_pick" or len(parts) < 5:
            await _answer(callback, STALE_ACTION_FA, alert=True)
            return
        try:
            uid = int(parts[4])
        except ValueError:
            await _answer(callback, "دکمه نامعتبر.", alert=True)
            return
        player = game.players.get(uid)
        if player is None or not player.is_alive or player.role == Role.OBSERVER:
            await _answer(callback, "این بازیکن قابل اخراج نیست.", alert=True)
            return
        game.russian_mafia_discipline_target = uid
        game.russian_mafia_post_night_stage = "discipline_confirm"
        from bot.app_state import manager

        tag = manager.format_player_tag(player)
        import html

        await _edit_or_send(
            callback,
            bot,
            game,
            f"تأیید اخراج انضباطی؟\n<b>{html.escape(tag)}</b>",
            InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ تأیید اخراج",
                            callback_data=f"rmh:{game.room_code}:disc_ok:{night}",
                        ),
                        InlineKeyboardButton(
                            text="↩️ برگشت",
                            callback_data=f"rmh:{game.room_code}:disc_back:{night}",
                        ),
                    ]
                ]
            ),
        )
        await _answer(callback, "تأیید را بزنید.")
        return

    if act == "disc_back":
        if stage == "discipline_confirm":
            game.russian_mafia_discipline_target = None
            await _show_discipline_pick(callback, bot, game)
            await _answer(callback, "بازگشت.")
            return
        if stage == "discipline_pick":
            game.russian_mafia_discipline_target = None
            game.russian_mafia_post_night_stage = "discipline_ask"
            await _edit_or_send(
                callback,
                bot,
                game,
                _discipline_ask_text(game),
                _discipline_ask_keyboard(game),
            )
            await _answer(callback, "بازگشت.")
            return
        await _answer(callback, STALE_ACTION_FA, alert=True)
        return

    if act == "disc_ok":
        if stage != "discipline_confirm":
            await _answer(callback, STALE_ACTION_FA, alert=True)
            return
        uid = game.russian_mafia_discipline_target
        player = game.players.get(uid) if uid is not None else None
        if player is None or not player.is_alive:
            await _answer(callback, "این انتخاب مجاز نیست.", alert=True)
            return
        game.russian_mafia_post_night_stage = "discipline_applying"
        eliminate(game, player.user_id, source="discipline")
        game.bazpors_night_discipline_kick_uid = player.user_id
        game.russian_mafia_discipline_target = None
        logger.info(
            "Russian Mafia room=%s disciplinary target confirmed user_id=%s",
            game.room_code,
            player.user_id,
        )
        finish_if_won(game)
        _persist(game, "russian_discipline")
        await _answer(callback, "اخراج ثبت شد.")
        from bot.observer_delivery import flush_elimination_notifications

        await flush_elimination_notifications(bot, game)
        await _after_discipline(callback, bot, game)
        return

    if act == "inq_yes":
        if stage != "inquiry_ask":
            await _answer(callback, STALE_ACTION_FA, alert=True)
            return
        from bot.no_host_table_inquiry import build_table_inquiry_confirm_panel

        game.russian_mafia_table_inquiry_pending = "yes"
        game.russian_mafia_post_night_stage = "inquiry_confirm"
        await _edit_or_send(
            callback,
            bot,
            game,
            build_table_inquiry_confirm_panel("yes"),
            _inquiry_confirm_keyboard(game),
        )
        await _answer(callback, "تأیید را بزنید.")
        return

    if act == "inq_no":
        if stage != "inquiry_ask":
            await _answer(callback, STALE_ACTION_FA, alert=True)
            return
        if game.russian_mafia_inquiry_completed_night == night:
            await _answer(callback, STALE_ACTION_FA, alert=True)
            return
        logger.info(
            "Russian Mafia room=%s table inquiry decision=NO used=%s",
            game.room_code,
            game.russian_mafia_table_inquiry_used,
        )
        await _answer(callback, "بدون استعلام.")
        await _open_next_day(bot, game)
        return

    if act == "inq_back":
        if stage != "inquiry_confirm":
            await _answer(callback, STALE_ACTION_FA, alert=True)
            return
        from bot.no_host_table_inquiry import build_table_inquiry_ask_panel

        game.russian_mafia_table_inquiry_pending = None
        game.russian_mafia_post_night_stage = "inquiry_ask"
        await _edit_or_send(
            callback,
            bot,
            game,
            build_table_inquiry_ask_panel(),
            _inquiry_ask_keyboard(game),
        )
        await _answer(callback, "بازگشت.")
        return

    if act == "inq_ok":
        if stage != "inquiry_confirm" or game.russian_mafia_table_inquiry_pending != "yes":
            await _answer(callback, STALE_ACTION_FA, alert=True)
            return
        if game.russian_mafia_inquiry_completed_night == night:
            logger.info(
                "Russian Mafia room=%s blocked duplicate table inquiry confirm",
                game.room_code,
            )
            await _answer(callback, STALE_ACTION_FA, alert=True)
            return
        game.russian_mafia_post_night_stage = "inquiry_applying"
        limit = russian_table_inquiry_limit(game)
        if game.russian_mafia_table_inquiry_used < limit:
            from bot.app_state import manager
            from bot.game import is_synthetic_player_uid
            from bot.no_host_table_inquiry import build_table_inquiry_yes_broadcast_html
            from bot.observer_delivery import broadcast_to_alive_players
            from bot.russian_mafia import russian_mafia_observer_registered
            from bot.russian_mafia_flow import russian_helper_user_id

            text = build_table_inquiry_yes_broadcast_html(game, manager)
            try:
                await broadcast_to_alive_players(
                    bot,
                    game,
                    text,
                    parse_mode="HTML",
                    is_synthetic_uid=is_synthetic_player_uid,
                )
            except Exception:
                game.russian_mafia_post_night_stage = "inquiry_confirm"
                logger.exception(
                    "Russian Mafia room=%s table inquiry broadcast failed",
                    game.room_code,
                )
                await _answer(callback, "ارسال استعلام ناموفق بود.", alert=True)
                return
            helper = russian_helper_user_id(game)
            helper_player = game.players.get(helper)
            if helper_player is None or not helper_player.is_alive:
                await _send(bot, helper, text, parse_mode="HTML")
            if (
                russian_mafia_observer_registered(game)
                and game.observer_user_id is not None
            ):
                observer = game.players.get(game.observer_user_id)
                if observer is None or not observer.is_alive:
                    await _send(bot, game.observer_user_id, text, parse_mode="HTML")
            game.russian_mafia_table_inquiry_used += 1
            _persist(game, "russian_table_inquiry")
        logger.info(
            "Russian Mafia room=%s table inquiry decision=YES used=%s limit=%s",
            game.room_code,
            game.russian_mafia_table_inquiry_used,
            limit,
        )
        await _answer(callback, "استعلام ثبت شد.")
        await _open_next_day(bot, game)
        return

    await _answer(callback, "الان مجاز نیست.", alert=True)
