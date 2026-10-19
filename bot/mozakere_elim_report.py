"""Mozakere-only: mid-game elimination report invitation + immutable cutoff."""

from __future__ import annotations

import html
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
from bot.room_mode import is_mozakere_scenario
from bot.tg_send import safe_callback_answer, safe_send_message

if TYPE_CHECKING:
    from bot.game import GameManager

logger = logging.getLogger(__name__)

MOZAKERE_ELIM_REPORT_INVITE_HTML = (
    "📋 برای مشاهده گزارش بازی تا این لحظه و اطلاع از نقش بازیکنان، "
    "روی دکمه «گزارش بازی» بزنید."
)
MOZAKERE_ELIM_REPORT_BUTTON_TEXT = "📋 گزارش بازی"

_TG_HTML_SAFE_LIMIT = 3500

router = Router(name="mozakere_elim_report")


class MozakereElimReportCb(CallbackData, prefix="mzrep"):
    """دکمهٔ گزارش حذف مذاکره — as_uid بازیکن حذف‌شده."""

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
    """تقسیم پیام HTML بلند — ترجیح مرز پاراگراف/خط؛ بدون بریدن تگ‌های ساده."""
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


def build_mozakere_elim_cutoff_report_html(game: Game, gm: "GameManager") -> str:
    """گزارش جزئی مذاکره تا لحظهٔ حذف — بدون برنده (بازی ادامه دارد)."""
    from bot.main import (
        _build_bazpors_timeline_html,
        _build_session_recap_roster_lines,
        build_game_final_report_header_html,
    )
    from bot.post_game_flow import build_post_session_recap_snapshot

    # winner فقط برای ساخت ردیف‌هاست؛ در خروجی اعلام نمی‌شود.
    snap = build_post_session_recap_snapshot(game, "citizen")
    rows_raw = snap.get("rows")
    rows: list[dict[str, object]] = rows_raw if isinstance(rows_raw, list) else []
    roster_block = "\n".join(
        _build_session_recap_roster_lines(rows, scenario_name="mozakere")
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
    del gm  # roster/timeline از game + audit می‌آید
    return "\n".join(parts)


def capture_mozakere_elim_report_cutoff(
    game: Game, gm: "GameManager", uid: int
) -> dict[str, Any] | None:
    """ثبت یک‌بارهٔ گزارش قطعی در لحظهٔ حذف — idempotent."""
    if not is_mozakere_scenario(game):
        return None
    if not game.roles_dealt:
        return None
    if game.phase == Phase.LOBBY:
        return None
    player = game.players.get(uid)
    if player is None or player.role == Role.OBSERVER:
        return None
    if player.is_alive:
        return None
    existing = game.mozakere_elim_report_cutoffs.get(uid)
    if isinstance(existing, dict) and existing.get("report_html"):
        return existing

    report_html = build_mozakere_elim_cutoff_report_html(game, gm)
    entry: dict[str, Any] = {
        "uid": uid,
        "room_code": game.room_code,
        "game_created_ts": _game_created_ts(game),
        "elim_ts": _utc_iso_now(),
        "report_html": report_html,
        "invite_sent": False,
    }
    game.mozakere_elim_report_cutoffs[uid] = entry
    return entry


def mozakere_elim_report_keyboard(game: Game, as_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=MOZAKERE_ELIM_REPORT_BUTTON_TEXT,
                    callback_data=MozakereElimReportCb(
                        code=game.room_code,
                        as_uid=as_uid,
                        gts=_game_created_ts(game),
                    ).pack(),
                )
            ]
        ]
    )


async def send_mozakere_elim_report_invitation(
    bot: Bot, game: Game, gm: "GameManager", uid: int
) -> bool:
    """ارسال دعوت گزارش پس از پیام حذف — بدون تکرار."""
    from bot.observer_delivery import (
        no_host_observer_registered,
        observer_player_copy_prefix,
    )

    entry = capture_mozakere_elim_report_cutoff(game, gm, uid)
    if entry is None:
        return False
    if entry.get("invite_sent"):
        return False

    text = MOZAKERE_ELIM_REPORT_INVITE_HTML
    kb = mozakere_elim_report_keyboard(game, uid)
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

    # حتی اگر ارسال تلگرام شکست بخورد، cutoff ذخیره شده؛ فقط پرچم دعوت را
    # وقتی واقعاً حداقل یک مقصد داشتیم یا synthetic بدون ناظر نیست، ست می‌کنیم.
    # حتی اگر تلگرام fail شود، cutoff ذخیره است؛ پرچم دعوت از تکرار جلوگیری می‌کند.
    entry["invite_sent"] = True
    return sent_any


async def maybe_send_mozakere_elim_report_invite(
    bot: Bot, game: Game, uid: int
) -> None:
    """قلاب پس از پیام حذف — خطا نباید جریان بازی را بشکند."""
    if not is_mozakere_scenario(game):
        return
    try:
        from bot.app_state import manager

        await send_mozakere_elim_report_invitation(bot, game, manager, uid)
    except Exception:
        logger.exception(
            "mozakere elim report invite failed room=%s uid=%s",
            game.room_code,
            uid,
        )


def resolve_mozakere_elim_report_html(
    game: Game, as_uid: int, *, gts: int
) -> str | None:
    if not is_mozakere_scenario(game):
        return None
    if _game_created_ts(game) != int(gts):
        return None
    entry = game.mozakere_elim_report_cutoffs.get(as_uid)
    if not isinstance(entry, dict):
        return None
    if int(entry.get("game_created_ts") or 0) != int(gts):
        return None
    html_body = entry.get("report_html")
    if not isinstance(html_body, str) or not html_body.strip():
        return None
    return html_body


async def deliver_mozakere_elim_report_chunks(
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


async def handle_mozakere_elim_report_callback(
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

    report_html = resolve_mozakere_elim_report_html(game, as_uid, gts=gts)
    if report_html is None:
        await safe_callback_answer(
            callback,
            "گزارش این دست دیگر در دسترس نیست (اتاق عوض یا پاک شده).",
            show_alert=True,
        )
        return

    await safe_callback_answer(callback)
    await deliver_mozakere_elim_report_chunks(bot, actor, report_html)


@router.callback_query(MozakereElimReportCb.filter())
async def cb_mozakere_elim_report(
    callback: CallbackQuery,
    bot: Bot,
    callback_data: MozakereElimReportCb,
) -> None:
    from bot.app_state import manager

    if not callback.from_user:
        return
    game = manager.get_game(callback_data.code)
    if game is None or not is_mozakere_scenario(game):
        await safe_callback_answer(
            callback, "اتاق دیگر فعال نیست.", show_alert=True
        )
        return
    await handle_mozakere_elim_report_callback(
        callback,
        bot,
        game,
        as_uid=int(callback_data.as_uid),
        gts=int(callback_data.gts),
    )


def register_mozakere_elim_report_handlers(dp: Any) -> None:
    dp.include_router(router)
