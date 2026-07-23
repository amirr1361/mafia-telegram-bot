"""جریان پایان بازی — کیبوردها، ثبت برنده، abort بدون نتیجه."""

from __future__ import annotations

import html
import logging

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot import db
from bot.app_state import PENDING_SESSION_RECAP, manager
from bot.game import is_synthetic_player_uid
from bot.models import Game, Player
from bot.observer_delivery import (
    broadcast_to_players,
    deliver_no_host_player_game_copy,
    game_observer_mirror_active,
    mirrored_endgame_winner_keyboard,
    mirror_per_player_to_observer,
    player_should_receive_game_messages,
)
from bot.tg_send import safe_send_message

logger = logging.getLogger(__name__)


class EndGamePick(CallbackData, prefix="egw"):
    code: str
    winner: str


class EndGameDismiss(CallbackData, prefix="egx"):
    code: str


class EndGameAbortConfirm(CallbackData, prefix="ega"):
    code: str
    ok: int


ENDGAME_ABORT_CONFIRM_HTML = (
    "⚠️ <b>بازی هنوز به پایان نرسیده است.</b>\n\n"
    "آیا مطمئن هستید می‌خواهید بازی را <b>بدون نتیجه</b> تمام کنید؟\n\n"
    "بعد از تمام شدن بازی، اتاق <b>بسته</b> می‌شود و "
    "<b>همهٔ بازیکنان</b> از بازی خارج می‌شوند."
)


def _players_sorted_for_recap(game: Game) -> list[Player]:
    return sorted(
        game.players.values(),
        key=lambda p: (p.seat is None, p.seat or 0, p.user_id),
    )


def build_post_session_recap_snapshot(game: Game, winner: str) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for idx, p in enumerate(_players_sorted_for_recap(game), start=1):
        seat_no = p.seat if p.seat is not None else idx
        rows.append(
            {
                "user_id": p.user_id,
                "seat": seat_no,
                "tag": manager.format_player_tag(p),
                "role": p.role.value if p.role else None,
                "yakuza_converted": p.bazpors_converted_by_yakuza,
                "original_role": (
                    p.bazpors_original_role.value
                    if p.bazpors_original_role
                    else None
                ),
                "mozakere_converted_by_negotiation": p.mozakere_converted_by_negotiation,
                "mozakere_original_role": (
                    p.mozakere_original_role.value
                    if p.mozakere_original_role
                    else None
                ),
            }
        )
    return {
        "winner": winner,
        "scenario_name": game.scenario_name,
        "room_code": game.room_code,
        "audit_log_path": game.audit_log_path,
        "host_id": game.host_id,
        "host_full_name": game.host_full_name,
        "host_username": game.host_username,
        "observer_user_id": game.observer_user_id,
        "max_players": game.max_players,
        "bazpors_host_mode": game.bazpors_host_mode,
        "rows": rows,
    }


def user_may_act_as_game_host(game: Game, user_id: int) -> bool:
    if user_id == game.host_id:
        return True
    if (
        game.scenario_name == "bazpors"
        and game.bazpors_host_mode == "no_host"
        and game.bot_assistant_user_id == user_id
    ):
        return True
    return False


def resolve_game_context(user_id: int) -> tuple[str | None, Player | None, bool]:
    game = manager.find_active_participant_game(user_id)
    if not game:
        return None, None, False
    player = game.players.get(user_id)
    is_host = user_may_act_as_game_host(game, user_id)
    return game.room_code, player, is_host


def host_endgame_needs_abort_confirm(game: Game) -> bool:
    if game.host_may_pick_winner:
        return False
    if not game.roles_dealt:
        return False
    if game.scenario_name not in ("bazpors", "bazpors_salamat_test"):
        return False
    mode = game.bazpors_host_mode or "manual"
    return mode in ("semi_auto", "manual", "no_host")


def endgame_abort_confirm_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ بله، پایان بدون نتیجه",
                    callback_data=EndGameAbortConfirm(
                        code=game.room_code, ok=1
                    ).pack(),
                )
            ],
            [
                InlineKeyboardButton(
                    text="✖️ خیر",
                    callback_data=EndGameAbortConfirm(
                        code=game.room_code, ok=0
                    ).pack(),
                )
            ],
        ]
    )


def endgame_winner_keyboard(game: Game) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 برد مافیا",
                    callback_data=EndGamePick(
                        code=game.room_code, winner="mafia"
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="🟢 برد شهروند",
                    callback_data=EndGamePick(
                        code=game.room_code, winner="citizen"
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✖️ انصراف",
                    callback_data=EndGameDismiss(code=game.room_code).pack(),
                ),
            ],
        ]
    )


def endgame_winner_keyboard_for(game: Game, as_uid: int) -> InlineKeyboardMarkup:
    if game_observer_mirror_active(game):
        return mirrored_endgame_winner_keyboard(game, as_uid)
    return endgame_winner_keyboard(game)


async def abort_game_without_result(
    bot: Bot, game: Game, *, actor_uid: int
) -> None:
    code = game.room_code
    notice = (
        "⛔ <b>گرداننده بازی را بدون نتیجه به پایان رساند.</b>\n\n"
        "اتاق بسته شد و همه از بازی خارج شدند."
    )
    await broadcast_to_players(
        bot,
        game,
        notice,
        is_synthetic_uid=is_synthetic_player_uid,
    )
    try:
        from bot.game_audit_log import log_game_ended

        log_game_ended(game, "aborted", actor_uid, manager)
    except Exception:
        logger.exception("audit log game abort failed")
    manager.end_game(code)
    await safe_send_message(
        bot,
        actor_uid,
        f"✅ اتاق <code>{html.escape(code)}</code> بسته شد.\n"
        "همهٔ بازیکنان از بازی خارج شدند.",
        parse_mode="HTML",
    )


async def finalize_game_winner(
    bot: Bot,
    game: Game,
    winner: str,
    picker_uid: int,
) -> None:
    players_payload = [
        {"id": p.user_id, "fn": p.full_name, "un": p.username}
        for p in game.players.values()
    ]
    host_id = game.host_id
    recap_snap = build_post_session_recap_snapshot(game, winner)
    session_id = db.insert_game_session(
        game.room_code,
        host_id,
        game.scenario_name,
        winner,
        players_payload,
        medal_giver_id=(picker_uid if picker_uid != game.host_id else None),
        recap_snapshot=recap_snap,
    )
    PENDING_SESSION_RECAP[session_id] = recap_snap
    try:
        from bot.game_audit_log import log_game_ended

        log_game_ended(game, winner, picker_uid, manager)
    except Exception:
        logger.exception("audit log game end failed")
    manager.end_game(game.room_code)
    from bot.main import begin_post_game_session

    await begin_post_game_session(
        bot,
        session_id=session_id,
        host_id=host_id,
        players=players_payload,
        host_full_name=game.host_full_name,
        host_username=game.host_username,
    )


async def broadcast_bazpors_game_end_to_players(
    bot: Bot, game: Game, winner: str
) -> None:
    from bot.main import build_bazpors_game_end_broadcast_html
    from bot.models import Role
    from bot.room_mode import is_mason_no_host_room, is_mozakere_no_host_room

    if game.scenario_name not in (
        "bazpors",
        "bazpors_salamat_test",
        "mozakere",
        "masoon",
    ):
        return
    if game.scenario_name == "mozakere" and not is_mozakere_no_host_room(game):
        return
    if game.scenario_name == "masoon" and not is_mason_no_host_room(game):
        return
    text = build_bazpors_game_end_broadcast_html(game, winner)
    for uid, p in sorted(game.players.items(), key=lambda x: x[0]):
        if p.role == Role.OBSERVER:
            continue
        if not p.is_alive and not player_should_receive_game_messages(game, uid):
            await safe_send_message(bot, uid, text, parse_mode="HTML")
            await mirror_per_player_to_observer(
                bot, game, uid, text, parse_mode="HTML"
            )
            continue
        await deliver_no_host_player_game_copy(
            bot,
            game,
            uid,
            text,
            parse_mode="HTML",
            is_synthetic_uid=is_synthetic_player_uid,
        )
