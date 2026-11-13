"""Mason-only: mid-game elimination report invitation + immutable cutoff."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from aiogram import Bot, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)

from bot.game import is_synthetic_player_uid
from bot.models import Game, Phase, Role
from bot.room_mode import is_mason_scenario
from bot.tg_send import safe_callback_answer, safe_send_message

if TYPE_CHECKING:
    from bot.game import GameManager

logger = logging.getLogger(__name__)

MASON_ELIM_REPORT_INVITE_HTML = (
    "📋 برای مشاهده گزارش بازی تا این لحظه و اطلاع از نقش بازیکنان، "
    "روی دکمه «گزارش بازی» بزنید."
)
MASON_ELIM_REPORT_BUTTON_TEXT = "📋 گزارش بازی"
MASON_ELIM_REPORT_NOT_READY_TEXT = (
    "⏳ گزارش پس از پایان کامل شب فعلی در دسترس قرار می‌گیرد."
)

_TG_HTML_SAFE_LIMIT = 3500

router = Router(name="mason_elim_report")


class MasonElimReportCb(CallbackData, prefix="msrep"):
    """دکمهٔ گزارش حذف ماسون — as_uid بازیکن حذف‌شده."""

    code: str
    as_uid: int
    gts: int


def _game_created_ts(game: Game) -> int:
    created = game.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    return int(created.timestamp())


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def split_html_message_chunks(text: str, *, limit: int = _TG_HTML_SAFE_LIMIT) -> list[str]:
    """تقسیم پیام HTML بلند — ترجیح مرز پاراگراف/خط."""
    body = (text or "").strip()
    if not body:
        return []
    if len(body) <= limit:
        return [body]

    chunks: list[str] = []
    remaining = body
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        window = remaining[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 3:
            cut = window.rfind("\n")
        if cut < limit // 3:
            cut = window.rfind(" ")
        if cut < limit // 3:
            cut = limit
        piece = remaining[:cut].rstrip()
        if not piece:
            piece = remaining[:limit]
            cut = len(piece)
        chunks.append(piece)
        remaining = remaining[cut:].lstrip("\n")
    return chunks


def build_mason_elim_cutoff_report_html(game: Game, gm: "GameManager") -> str:
    """گزارش جزئی ماسون تا لحظهٔ حذف — بدون برنده."""
    from bot.main import (
        _build_bazpors_timeline_html,
        _build_session_recap_roster_lines,
        build_game_final_report_header_html,
    )
    from bot.post_game_flow import build_post_session_recap_snapshot

    snap = build_post_session_recap_snapshot(game, "citizen")
    rows_raw = snap.get("rows")
    rows: list[dict[str, object]] = rows_raw if isinstance(rows_raw, list) else []
    roster_block = "\n".join(
        _build_session_recap_roster_lines(rows, scenario_name="masoon")
    )
    timeline_html = _build_bazpors_timeline_html(snap)
    parts: list[str] = [
        build_game_final_report_header_html(
            game.room_code, game.scenario_name, game.max_players
        ),
        "",
        "📋 <b>بازیکنان و نقش‌ها</b>",
        roster_block,
    ]
    if timeline_html:
        parts.extend(["", "────────────", "", timeline_html])
    del gm
    return "\n".join(parts)


def capture_mason_elim_report_cutoff(
    game: Game, gm: "GameManager", uid: int
) -> dict[str, Any] | None:
    """ثبت یک‌بارهٔ گزارش قطعی در لحظهٔ حذف واقعی — idempotent.

    فقط وقتی بازیکن واقعاً مرده است؛ جذب/تبدیل ماسون بدون حذف دعوت نمی‌سازد.
    """
    if not is_mason_scenario(game):
        return None
    if not game.roles_dealt:
        return None
    if game.phase == Phase.LOBBY:
        return None
    player = game.players.get(uid)
    if player is None or player.role == Role.OBSERVER:
        return None
    # authoritative: still alive => not an elimination (e.g. recruitment)
    if player.is_alive:
        return None
    existing = game.mason_elim_report_cutoffs.get(uid)
    if isinstance(existing, dict) and existing.get("report_html"):
        return existing

    report_html = build_mason_elim_cutoff_report_html(game, gm)
    # اگر شب جاری هنوز حل نشده، گزارش کاملِ آن شب هنوز در تاریخچه نیست —
    # گزارش پس از «night.resolved» همان شب بازسازی و قطعی می‌شود.
    pending_night = int(game.bazpors_narrator_night_count or 0)
    from bot.mason_final_outcome import find_mason_final_night_outcome

    if pending_night < 1 or find_mason_final_night_outcome(game, pending_night) is not None:
        pending_night = None
    entry: dict[str, Any] = {
        "uid": uid,
        "room_code": game.room_code,
        "game_created_ts": _game_created_ts(game),
        "elim_ts": _utc_iso_now(),
        "report_html": report_html,
        "invite_sent": False,
        "pending_night": pending_night,
    }
    game.mason_elim_report_cutoffs[uid] = entry
    return entry


def refresh_mason_elim_cutoffs_after_night(
    game: Game, gm: "GameManager | None" = None
) -> None:
    """پس از حل‌شدن شب — بازسازی گزارش‌های در انتظارِ همان شب (قطعی و تغییرناپذیر).

    فقط ماسون؛ گزارش‌های قبلاً قطعی‌شده دست‌نخورده می‌مانند.
    """
    if not is_mason_scenario(game):
        return
    from bot.mason_final_outcome import find_mason_final_night_outcome

    for entry in game.mason_elim_report_cutoffs.values():
        if not isinstance(entry, dict):
            continue
        pending_night = entry.get("pending_night")
        if not pending_night:
            continue
        if find_mason_final_night_outcome(game, int(pending_night)) is None:
            continue
        entry["report_html"] = build_mason_elim_cutoff_report_html(game, gm)
        entry["pending_night"] = None


def mason_elim_cutoff_awaiting_night(game: Game, as_uid: int) -> int | None:
    """شبی که گزارش این بازیکن منتظرِ حل‌شدن آن است — None یعنی آماده."""
    entry = game.mason_elim_report_cutoffs.get(as_uid)
    if not isinstance(entry, dict):
        return None
    pending_night = entry.get("pending_night")
    if not pending_night:
        return None
    from bot.mason_final_outcome import find_mason_final_night_outcome

    if find_mason_final_night_outcome(game, int(pending_night)) is None:
        return int(pending_night)
    return None


def mason_elim_report_keyboard(game: Game, as_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=MASON_ELIM_REPORT_BUTTON_TEXT,
                    callback_data=MasonElimReportCb(
                        code=game.room_code,
                        as_uid=as_uid,
                        gts=_game_created_ts(game),
                    ).pack(),
                )
            ]
        ]
    )


async def send_mason_elim_report_invitation(
    bot: Bot, game: Game, gm: "GameManager", uid: int
) -> bool:
    """ارسال دعوت گزارش پس از پیام حذف — بدون تکرار."""
    from bot.observer_delivery import (
        no_host_observer_registered,
        observer_player_copy_prefix,
    )

    entry = capture_mason_elim_report_cutoff(game, gm, uid)
    if entry is None:
        return False
    if entry.get("invite_sent"):
        return False

    text = MASON_ELIM_REPORT_INVITE_HTML
    kb = mason_elim_report_keyboard(game, uid)
    synthetic = is_synthetic_player_uid(uid)
    sent_any = False

    if not synthetic:
        if await safe_send_message(
            bot, uid, text, parse_mode="HTML", reply_markup=kb
        ):
            sent_any = True

    if no_host_observer_registered(game):
        obs = game.observer_user_id
        if obs is not None and obs != uid:
            body = observer_player_copy_prefix(game, uid) + text
            if await safe_send_message(
                bot, obs, body, parse_mode="HTML", reply_markup=kb
            ):
                sent_any = True

    entry["invite_sent"] = True
    return sent_any


async def maybe_send_mason_elim_report_invite(
    bot: Bot, game: Game, uid: int
) -> None:
    """قلاب پس از پیام حذف — فقط ماسون؛ خطا نباید جریان بازی را بشکند."""
    if not is_mason_scenario(game):
        return
    try:
        from bot.app_state import manager

        await send_mason_elim_report_invitation(bot, game, manager, uid)
    except Exception:
        logger.exception(
            "mason elim report invite failed room=%s uid=%s",
            game.room_code,
            uid,
        )


def resolve_mason_elim_report_html(
    game: Game, as_uid: int, *, gts: int
) -> str | None:
    if not is_mason_scenario(game):
        return None
    if _game_created_ts(game) != int(gts):
        return None
    entry = game.mason_elim_report_cutoffs.get(as_uid)
    if not isinstance(entry, dict):
        return None
    if int(entry.get("game_created_ts") or 0) != int(gts):
        return None
    html_body = entry.get("report_html")
    if not isinstance(html_body, str) or not html_body.strip():
        return None
    return html_body


async def deliver_mason_elim_report_chunks(
    bot: Bot, chat_id: int, report_html: str
) -> bool:
    chunks = split_html_message_chunks(report_html)
    if not chunks:
        return False
    ok = False
    for part in chunks:
        if await safe_send_message(bot, chat_id, part, parse_mode="HTML"):
            ok = True
    return ok


async def handle_mason_elim_report_callback(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    *,
    as_uid: int,
    gts: int,
) -> None:
    """خواندن گزارش حذف‌شده — بازیکن مرده یا ناظر؛ بدون تغییر وضعیت بازی."""
    actor = callback.from_user.id if callback.from_user else None
    if actor is None:
        await safe_callback_answer(callback, "نامعتبر.", show_alert=True)
        return

    player = game.players.get(as_uid)
    if player is None or player.role == Role.OBSERVER:
        await safe_callback_answer(
            callback, "گزارش این بازیکن در دسترس نیست.", show_alert=True
        )
        return
    if player.is_alive:
        await safe_callback_answer(
            callback, "این گزارش فقط برای بازیکن حذف‌شده است.", show_alert=True
        )
        return

    obs = game.observer_user_id
    if actor != as_uid and actor != obs:
        await safe_callback_answer(
            callback, "اجازهٔ مشاهدهٔ این گزارش را ندارید.", show_alert=True
        )
        return

    from bot.app_state import manager

    # گزارش‌های در انتظارِ حل‌شدن شب حذف — بازسازی از تاریخچهٔ قطعی و قطعی‌سازی.
    refresh_mason_elim_cutoffs_after_night(game, manager)
    awaiting_night = mason_elim_cutoff_awaiting_night(game, as_uid)
    if awaiting_night is not None:
        await safe_callback_answer(
            callback,
            MASON_ELIM_REPORT_NOT_READY_TEXT,
            show_alert=True,
        )
        return

    report_html = resolve_mason_elim_report_html(game, as_uid, gts=gts)
    if report_html is None:
        await safe_callback_answer(
            callback,
            "گزارش این دست دیگر در دسترس نیست (اتاق عوض یا پاک شده).",
            show_alert=True,
        )
        return

    # گزارش زنده: در هر درخواست، گزارش تجمعی از روی تاریخچهٔ قطعیِ
    # فعلی بازسازی می‌شود؛ اسنپ‌شاتِ ثبت‌شده فقط عقب‌نشینی ایمن است.
    from bot.app_state import manager as _live_manager

    try:
        _fresh_html = build_mason_elim_cutoff_report_html(game, _live_manager)
    except Exception:
        logger.exception(
            "mason live report rebuild failed room=%s", game.room_code
        )
        _fresh_html = None
    if _fresh_html and _fresh_html.strip():
        report_html = _fresh_html
        _entry = game.mason_elim_report_cutoffs.get(as_uid)
        if isinstance(_entry, dict):
            _entry["report_html"] = _fresh_html

    await safe_callback_answer(callback)
    await deliver_mason_elim_report_chunks(bot, actor, report_html)


@router.callback_query(MasonElimReportCb.filter())
async def cb_mason_elim_report(
    callback: CallbackQuery,
    bot: Bot,
    callback_data: MasonElimReportCb,
) -> None:
    from bot.app_state import manager

    if not callback.from_user:
        return
    game = manager.get_game(callback_data.code)
    if game is None or not is_mason_scenario(game):
        await safe_callback_answer(
            callback, "اتاق دیگر فعال نیست.", show_alert=True
        )
        return
    await handle_mason_elim_report_callback(
        callback,
        bot,
        game,
        as_uid=int(callback_data.as_uid),
        gts=int(callback_data.gts),
    )


def register_mason_elim_report_handlers(dp: Any) -> None:
    dp.include_router(router)
