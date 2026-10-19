"""ارسال پیام بازیکنان به ناظر (حالت no_host) و رقابت اولین کلیک روی دکمه‌ها.

مسیر Player-Moderator (no_host + ناظر ثبت‌شده): هر UI صندلی — واقعی یا مصنوعی —
باید از ``register_mirror_prompt_pair`` / ``publish_mirror_prompt_pair`` /
``deliver_no_host_player_game_copy`` / ``send_to_player`` عبور کند تا ناظر
همان متن و دکمه‌ها را بگیرد (``_coerce_mirror_delivery``).
"""

from __future__ import annotations

import html
import logging
from typing import TYPE_CHECKING, Any

from aiogram import Bot
from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from aiogram.exceptions import TelegramBadRequest

from bot.async_broadcast import gather_bounded
from bot.game import is_synthetic_player_uid, role_label_fa
from bot.models import Game, Role
from bot.text_fa import fa_digits
from bot.tg_send import safe_send_message, safe_send_message_return
if TYPE_CHECKING:
    from bot.game import GameManager

logger = logging.getLogger(__name__)


class PlayerMirrorCb(CallbackData, prefix="pmr"):
    """دکمهٔ آینه برای ناظر؛ as_uid = بازیکنی که پیام برای اوست."""

    code: str
    act: str
    as_uid: int
    tid: int = 0
    rid: str = ""  # دادهٔ اختیاری (مثلاً دور دست‌دادن فاز آشوب: act=chs)


def unpack_player_mirror_cb(data: str) -> PlayerMirrorCb | None:
    """باز کردن callback؛ فرمت pmr:code:act:as_uid:tid"""
    if not data.startswith("pmr:"):
        return None
    parts = data.split(":")
    if len(parts) == 5 and parts[2] in ("d1dt", "tog"):
        try:
            return PlayerMirrorCb(
                code=parts[1],
                act=parts[2],
                as_uid=int(parts[3]),
                tid=int(parts[4]),
            )
        except ValueError:
            return None
    try:
        return PlayerMirrorCb.unpack(data)
    except ValueError:
        return None


def _russian_observer_mirror(game: Game) -> bool:
    return (
        getattr(game, "scenario_name", None) == "russian_mafia"
        and getattr(game, "bazpors_host_mode", None) == "host_helper"
        and game.observer_user_id is not None
        and game.observer_prompt_status != "skipped"
    )


def game_observer_mirror_active(game: Game) -> bool:
    return no_host_observer_registered(game) or _russian_observer_mirror(game)


def no_host_observer_registered(game: Game) -> bool:
    """ناظر فعال = شناسه ثبت شده و لغو نشده (نه فقط status==registered)."""
    return (
        game.bazpors_host_mode == "no_host"
        and game.observer_user_id is not None
        and game.observer_prompt_status != "skipped"
    )


def no_host_player_moderator_path(game: Game) -> bool:
    """مسیر Player-Moderator: هر UI صندلی باید برای ناظر آینه شود."""
    return no_host_observer_registered(game)


def _seat_uid_is_observer(game: Game, player_uid: int) -> bool:
    return (
        game.observer_user_id is not None
        and player_uid == game.observer_user_id
    )


def _coerce_mirror_delivery(
    game: Game,
    player_uid: int,
    *,
    send_player: bool,
    send_observer: bool,
) -> tuple[bool, bool]:
    if not (
        no_host_player_moderator_path(game) or _russian_observer_mirror(game)
    ):
        return send_player, send_observer
    if _seat_uid_is_observer(game, player_uid):
        return send_player, False
    return send_player, True


def _must_mirror_ui_to_observer(game: Game, player_uid: int) -> bool:
    return (
        (
            no_host_player_moderator_path(game) or _russian_observer_mirror(game)
        )
        and not _seat_uid_is_observer(game, player_uid)
    )


def _is_mirror_ui_markup(markup: object | None) -> bool:
    """فقط پنل اینلاین در رجیستر آینه؛ ReplyKeyboardRemove/Markup مستقیم به DM می‌رود."""
    return isinstance(markup, InlineKeyboardMarkup)


def build_observer_players_roster_html(game: Game, gm: "GameManager") -> str:
    """فهرست بازیکنان اتاق با نقش — فقط برای ناظر."""
    room = html.escape(game.room_code)
    lines = [
        f"👁 <b>فهرست بازیکنان و نقش‌ها</b>\n"
        f"اتاق <code>{room}</code>\n",
    ]
    players = sorted(
        (p for p in game.players.values() if p.role != Role.OBSERVER),
        key=lambda p: (p.seat if p.seat is not None else 999, p.user_id),
    )
    if not players:
        lines.append("<i>هنوز بازیکنی در اتاق ثبت نشده است.</i>")
        return "\n".join(lines)
    if not game.roles_dealt:
        lines.append("<i>نقش‌ها هنوز پخش نشده‌اند.</i>\n")
    russian = game.scenario_name == "russian_mafia"
    russian_label = None
    fa_digits = None
    if russian:
        from bot.russian_mafia import russian_role_label_fa as russian_label
        from bot.text_fa import fa_digits as fa_digits
    for p in players:
        tag = html.escape(gm.format_player_tag(p))
        if russian:
            seat = fa_digits(p.seat) if p.seat is not None else "—"
            if p.role is not None:
                role_txt = html.escape(russian_label(p.role))
                lines.append(f"• صندلی {seat} — {tag} — <b>{role_txt}</b>")
            else:
                lines.append(f"• صندلی {seat} — {tag} — <i>نقش نامشخص</i>")
        elif p.role is not None:
            role_txt = html.escape(role_label_fa(p.role))
            lines.append(f"• {tag} — <b>{role_txt}</b>")
        else:
            lines.append(f"• {tag} — <i>نقش نامشخص</i>")
    return "\n".join(lines)


async def send_observer_players_roster(
    bot: Bot,
    game: Game,
    gm: "GameManager",
) -> None:
    """ارسال فهرست بازیکنان و نقش‌ها فقط به ناظر."""
    if game.observer_user_id is None:
        return
    if (
        game.scenario_name == "russian_mafia"
        and game.russian_mafia_observer_roster_sent
    ):
        logger.info(
            "Russian Mafia room=%s observer roster already sent; skipping duplicate",
            game.room_code,
        )
        return
    text = build_observer_players_roster_html(game, gm)
    sent = await safe_send_message(
        bot, game.observer_user_id, text, parse_mode="HTML"
    )
    if game.scenario_name == "russian_mafia" and sent:
        seated = [pl for pl in game.players.values() if pl.role != Role.OBSERVER]
        assigned = sum(1 for pl in seated if pl.role is not None)
        game.russian_mafia_observer_roster_sent = True
        logger.info(
            "Russian Mafia observer roster sent room=%s players=%s assigned_roles=%s",
            game.room_code,
            len(seated),
            assigned,
        )


async def notify_no_host_observer(
    bot: Bot,
    game: Game,
    text: str,
    *,
    use_broadcast_prefix: bool = False,
    **kwargs: Any,
) -> None:
    """یک نسخهٔ اعلان همگانی برای ناظر (فقط وقتی per-seat لازم نیست)."""
    if not no_host_observer_registered(game):
        return
    obs_id = game.observer_user_id
    if obs_id is None:
        return
    body = (
        observer_broadcast_copy_prefix(game) + text
        if use_broadcast_prefix
        else text
    )
    await safe_send_message(bot, obs_id, body, **kwargs)


async def mirror_per_player_to_observer(
    bot: Bot,
    game: Game,
    recipient_uid: int,
    text: str,
    **kwargs: Any,
) -> None:
    """نسخهٔ پیام همگانی برای ناظر — گویی همان بازیکن گیرنده بوده."""
    if not no_host_observer_registered(game):
        return
    obs_id = game.observer_user_id
    if obs_id is None or obs_id == recipient_uid:
        return
    body = observer_player_copy_prefix(game, recipient_uid) + text
    await safe_send_message(bot, obs_id, body, **kwargs)


async def deliver_no_host_player_game_copy(
    bot: Bot,
    game: Game,
    player_uid: int,
    text: str,
    *,
    is_synthetic_uid: Any | None = None,
    simulate_all_seats: bool | None = None,
    mirror_ui_key: str | None = None,
    **kwargs: Any,
) -> None:
    """همان منطقِ «بازیکن این را می‌گیرد»؛ در no_host با ناظر، نسخهٔ آینه برای ناظر.

    صندلی مصنوعی: فقط آینه برای ناظر (وقتی ناظر ثبت شده).
    بازیکن واقعی: DM در صورت مجاز بودن + آینه برای ناظر.
    بازیکن واقعی بدون حق دریافت (مثلاً مرده) ولی simulate: فقط آینه.
  """
    reply_markup = kwargs.get("reply_markup")
    if mirror_ui_key is not None or _is_mirror_ui_markup(reply_markup):
        ui_key = mirror_ui_key or mirror_ui_claim_key(
            game.room_code, "seat_msg", player_uid
        )
        send_player = (
            not (is_synthetic_uid(player_uid) if is_synthetic_uid else False)
            and player_should_receive_game_messages(game, player_uid)
        )
        send_player, send_observer = _coerce_mirror_delivery(
            game,
            player_uid,
            send_player=send_player,
            send_observer=True,
        )
        await register_mirror_prompt_pair(
            bot,
            game,
            player_uid,
            ui_key,
            text,
            reply_markup,
            send_player=send_player,
            send_observer=send_observer,
            **kwargs,
        )
        return

    synthetic = is_synthetic_uid(player_uid) if is_synthetic_uid is not None else False
    simulate = should_simulate_all_seats_for_observer(
        game, simulate_all_seats=simulate_all_seats
    )
    if synthetic:
        if _must_mirror_ui_to_observer(game, player_uid):
            await mirror_per_player_to_observer(bot, game, player_uid, text, **kwargs)
        return
    if not player_should_receive_game_messages(game, player_uid):
        if simulate or _must_mirror_ui_to_observer(game, player_uid):
            await mirror_per_player_to_observer(bot, game, player_uid, text, **kwargs)
        return
    await safe_send_message(bot, player_uid, text, **kwargs)
    if _must_mirror_ui_to_observer(game, player_uid):
        await mirror_per_player_to_observer(bot, game, player_uid, text, **kwargs)


def should_simulate_all_seats_for_observer(
    game: Game,
    *,
    simulate_all_seats: bool | None,
) -> bool:
    """در تست no_host: هر صندلی (حتی بات مصنوعی) یک پیام جدا برای ناظر."""
    if simulate_all_seats is not None:
        return simulate_all_seats
    return no_host_player_moderator_path(game)


def mirror_ui_claim_key(room: str, kind: str, as_player_uid: int) -> str:
    return f"{kind}:{room}:{as_player_uid}"


ELIMINATED_PLAYER_MESSAGE_HTML = (
    "💀 <b>شما از بازی خارج شدید.</b>\n\n"
    "لطفاً بازی را ترک کنید یا ادامه بازی را در سکوت تماشا کنید."
)


def player_should_receive_game_messages(game: Game, uid: int) -> bool:
    """بازیکن خارج‌شده پیام بازی نمی‌گیرد؛ کمک‌کننده، ناظر و گردانندهٔ semi_auto استثنا هستند."""
    if (
        game.scenario_name == "bazpors"
        and game.bazpors_host_mode == "semi_auto"
        and uid == game.host_id
    ):
        return True
    if uid == game.bot_assistant_user_id:
        return True
    if game.observer_user_id is not None and uid == game.observer_user_id:
        return True
    player = game.players.get(uid)
    if player is None:
        return True
    return player.is_alive


def queue_player_elimination_notify(game: Game, uid: int) -> None:
    if game.observer_user_id is not None and uid == game.observer_user_id:
        return
    if uid not in game.players:
        return
    if uid not in game.eliminated_notify_uids:
        game.eliminated_notify_uids.append(uid)


async def notify_eliminated_player(bot: Bot, game: Game, uid: int) -> None:
    if game.observer_user_id is not None and uid == game.observer_user_id:
        return
    if uid not in game.players:
        return
    extra = game.bazpors_elim_private_extra_html.pop(uid, None)
    body = ELIMINATED_PLAYER_MESSAGE_HTML
    if extra:
        body = f"{body}\n\n{extra}"
    russian = game.scenario_name == "russian_mafia"
    if not (russian and is_synthetic_player_uid(uid)):
        await safe_send_message(bot, uid, body, parse_mode="HTML")
    if no_host_observer_registered(game):
        await mirror_per_player_to_observer(
            bot,
            game,
            uid,
            body,
            parse_mode="HTML",
        )
    elif russian:
        from bot.russian_mafia import russian_mafia_observer_registered

        if russian_mafia_observer_registered(game):
            observer = game.observer_user_id
            if observer is not None and observer != uid:
                await safe_send_message(
                    bot,
                    observer,
                    observer_player_copy_prefix(game, uid) + body,
                    parse_mode="HTML",
                )

    try:
        from bot.room_mode import is_mason_scenario, is_mozakere_scenario

        if game.scenario_name == "russian_mafia":
            from bot.russian_mafia_elim_report import (
                maybe_send_russian_mafia_elim_report_invite,
            )

            await maybe_send_russian_mafia_elim_report_invite(bot, game, uid)
        elif is_mozakere_scenario(game):
            from bot.mozakere_elim_report import maybe_send_mozakere_elim_report_invite

            await maybe_send_mozakere_elim_report_invite(bot, game, uid)
        elif is_mason_scenario(game):
            from bot.mason_elim_report import maybe_send_mason_elim_report_invite

            await maybe_send_mason_elim_report_invite(bot, game, uid)
        else:
            from bot.bazpors_elim_report import (
                is_bazpors_elim_report_scenario,
                maybe_send_bazpors_elim_report_invite,
            )

            if is_bazpors_elim_report_scenario(game):
                await maybe_send_bazpors_elim_report_invite(bot, game, uid)
    except Exception:
        pass


async def flush_elimination_notifications(bot: Bot, game: Game) -> None:
    pending = list(game.eliminated_notify_uids)
    game.eliminated_notify_uids.clear()

    async def _notify(uid: int) -> None:
        await notify_eliminated_player(bot, game, uid)

    await gather_bounded(pending, _notify)


def _format_player_tag(game: Game, uid: int) -> str:
    p = game.players.get(uid)
    if not p:
        return f"#{uid}"
    if p.username:
        return f"@{p.username}"
    return p.full_name


def observer_player_copy_prefix(game: Game, as_player_uid: int) -> str:
    p = game.players.get(as_player_uid)
    seat = p.seat if p and p.seat is not None else None
    seat_txt = fa_digits(seat) if seat is not None else "—"
    tag = html.escape(_format_player_tag(game, as_player_uid))
    if p is not None and p.role is not None:
        role_txt = html.escape(role_label_fa(p.role))
    else:
        role_txt = "نقش نامشخص"
    return (
        f"👁 <i>ناظر — پیام صندلی {seat_txt} ({tag}) ({role_txt})</i>\n\n"
    )


def observer_broadcast_copy_prefix(game: Game) -> str:
    room = html.escape(game.room_code)
    return f"👁 <i>ناظر — پیام همگانی بازیکنان اتاق {room}</i>\n\n"


def _observer_display_tag(game: Game) -> str:
    if game.observer_username:
        return f"@{game.observer_username}"
    return game.observer_full_name or "ناظر بازی"


def _store_mirror_prompt_ref(
    game: Game,
    ui_key: str,
    role: str,
    chat_id: int,
    message_id: int,
    text: str,
) -> None:
    entry = game.mirror_prompt_messages.setdefault(ui_key, {})
    entry["text"] = text
    entry[role] = (chat_id, message_id)


def _mirror_observer_body(
    game: Game,
    player_uid: int,
    text: str,
    *,
    observer_same_text: bool,
) -> str:
    if observer_same_text:
        return text
    obs_id = game.observer_user_id
    if obs_id is not None and obs_id == player_uid:
        return text
    return observer_player_copy_prefix(game, player_uid) + text


async def _try_edit_mirror_message(
    bot: Bot,
    chat_id: int,
    message_id: int,
    body: str,
    reply_markup: InlineKeyboardMarkup | None,
    *,
    parse_mode: str = "HTML",
) -> bool:
    try:
        await bot.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=body,
            parse_mode=parse_mode,
            reply_markup=reply_markup,
        )
        return True
    except TelegramBadRequest:
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=reply_markup,
            )
            return True
        except TelegramBadRequest:
            return False


async def _send_observer_mirror_ref(
    bot: Bot,
    game: Game,
    ui_key: str,
    player_uid: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    *,
    observer_same_text: bool = False,
    parse_mode: str = "HTML",
    **kwargs: Any,
) -> bool:
    russian_mirror_key = _russian_observer_mirror(game) and (
        "defense" in ui_key or ":obs" in ui_key
    )
    if not (no_host_observer_registered(game) or russian_mirror_key):
        return False
    obs_id = game.observer_user_id
    if obs_id is None or obs_id == player_uid:
        return False
    obs_body = _mirror_observer_body(
        game, player_uid, text, observer_same_text=observer_same_text
    )
    obs_msg = await safe_send_message_return(
        bot, obs_id, obs_body, reply_markup=reply_markup, parse_mode=parse_mode, **kwargs
    )
    if obs_msg is None:
        return False
    _store_mirror_prompt_ref(
        game, ui_key, "observer", obs_id, obs_msg.message_id, text
    )
    return True


async def _edit_remove_keyboard(
    bot: Bot, chat_id: int, message_id: int
) -> None:
    try:
        await bot.edit_message_reply_markup(
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None,
        )
    except TelegramBadRequest:
        logger.debug(
            "edit_message_reply_markup failed chat_id=%s message_id=%s",
            chat_id,
            message_id,
        )


async def dismiss_player_mirror_prompt(
    bot: Bot,
    game: Game,
    ui_key: str,
    as_player_uid: int,
) -> None:
    """ناظر زودتر زده — پیام انتخاب بازیکن را ببند و اطلاع بده."""
    obs_tag = html.escape(_observer_display_tag(game))
    notice = f"\n\n👁 <b>{obs_tag}</b> به‌جای شما این انتخاب را انجام داد."
    entry = game.mirror_prompt_messages.get(ui_key)
    if entry:
        base = str(entry.get("text") or "")
        player_ref = entry.get("player")
        if isinstance(player_ref, tuple) and len(player_ref) == 2:
            chat_id, message_id = int(player_ref[0]), int(player_ref[1])
            try:
                await bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=message_id,
                    text=base + notice,
                    parse_mode="HTML",
                    reply_markup=None,
                )
                return
            except TelegramBadRequest:
                await _edit_remove_keyboard(bot, chat_id, message_id)
                await safe_send_message(
                    bot,
                    as_player_uid,
                    f"👁 <b>{obs_tag}</b> به‌جای شما این انتخاب را انجام داد.",
                    parse_mode="HTML",
                )
                return
    await safe_send_message(
        bot,
        as_player_uid,
        f"👁 <b>{obs_tag}</b> به‌جای شما این انتخاب را انجام داد.\n"
        "<i>پیام قبلی دیگر اعتبار ندارد.</i>",
        parse_mode="HTML",
    )


async def dismiss_observer_mirror_prompt(
    bot: Bot,
    game: Game,
    ui_key: str,
) -> None:
    """بازیکن خودش زده — دکمهٔ همان پیام روی نسخهٔ ناظر برداشته شود."""
    entry = game.mirror_prompt_messages.get(ui_key)
    if not entry:
        return
    obs_ref = entry.get("observer")
    if isinstance(obs_ref, tuple) and len(obs_ref) == 2:
        await _edit_remove_keyboard(
            bot, int(obs_ref[0]), int(obs_ref[1])
        )


async def close_mirror_prompt_keyboards(
    bot: Bot,
    game: Game,
    ui_key: str,
    *,
    skip_message_ids: frozenset[int] | None = None,
) -> None:
    """دکمه‌های inline یک پنل آینه را بردار (بدون تغییر متن)."""
    skip = skip_message_ids or frozenset()
    entry = game.mirror_prompt_messages.get(ui_key)
    if not entry:
        return
    for role in ("player", "observer"):
        ref = entry.get(role)
        if isinstance(ref, tuple) and len(ref) == 2:
            message_id = int(ref[1])
            if message_id in skip:
                continue
            await _edit_remove_keyboard(bot, int(ref[0]), message_id)


async def apply_mirror_claim_winner(
    bot: Bot,
    game: Game,
    ui_key: str,
    actor_uid: int,
    as_player_uid: int,
) -> None:
    obs = game.observer_user_id
    if obs is None or not game_observer_mirror_active(game):
        return
    if actor_uid == obs and actor_uid != as_player_uid:
        await dismiss_player_mirror_prompt(bot, game, ui_key, as_player_uid)
    elif actor_uid == as_player_uid:
        await dismiss_observer_mirror_prompt(bot, game, ui_key)


def try_claim_mirror_ui(
    game: Game,
    ui_key: str,
    actor_uid: int,
    as_player_uid: int,
) -> str | None:
    """None = موفق؛ در غیر این صورت کد خطا."""
    if not game_observer_mirror_active(game):
        if actor_uid != as_player_uid:
            return "forbidden"
        return None
    obs = game.observer_user_id
    if actor_uid != as_player_uid and actor_uid != obs:
        return "forbidden"
    existing = game.mirror_action_claims.get(ui_key)
    if existing is not None:
        if existing == actor_uid:
            return "dup_self"
        return "already_claimed"
    game.mirror_action_claims[ui_key] = actor_uid
    return None


async def update_mirror_prompt_pair(
    bot: Bot,
    game: Game,
    ui_key: str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    *,
    assistant_uid: int,
    parse_mode: str = "HTML",
    fresh_observer_copy: bool = False,
    observer_same_text: bool = False,
    **kwargs: Any,
) -> None:
    """به‌روزرسانی متن و دکمه‌های بازیکن و ناظر (پنل چندمرحله‌ای).

    اگر ``fresh_observer_copy`` باشد یا ویرایش/رف ناظر ناموفق، پیام تازه برای ناظر ارسال می‌شود.
    """
    entry = game.mirror_prompt_messages.setdefault(ui_key, {})
    entry["text"] = text
    if _must_mirror_ui_to_observer(game, assistant_uid) and not entry.get("observer"):
        fresh_observer_copy = True
    player_ref = entry.get("player")
    if isinstance(player_ref, tuple) and len(player_ref) == 2:
        chat_id, message_id = int(player_ref[0]), int(player_ref[1])
        await _try_edit_mirror_message(
            bot,
            chat_id,
            message_id,
            text,
            reply_markup,
            parse_mode=parse_mode,
        )

    if fresh_observer_copy:
        entry.pop("observer", None)

    obs_ref = entry.get("observer")
    obs_body = _mirror_observer_body(
        game, assistant_uid, text, observer_same_text=observer_same_text
    )
    observer_ok = False
    if isinstance(obs_ref, tuple) and len(obs_ref) == 2:
        observer_ok = await _try_edit_mirror_message(
            bot,
            int(obs_ref[0]),
            int(obs_ref[1]),
            obs_body,
            reply_markup,
            parse_mode=parse_mode,
        )

    if fresh_observer_copy or not observer_ok:
        await _send_observer_mirror_ref(
            bot,
            game,
            ui_key,
            assistant_uid,
            text,
            reply_markup,
            observer_same_text=observer_same_text,
            parse_mode=parse_mode,
            **kwargs,
        )


async def promote_mirror_prompt_to_panel(
    bot: Bot,
    game: Game,
    *,
    from_ui_key: str,
    to_ui_key: str,
    assistant_uid: int,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    parse_mode: str = "HTML",
) -> bool:
    """همان پیام انتخاب قبلی را به پنل جدید (متن + دکمه) تبدیل می‌کند."""
    from_entry = game.mirror_prompt_messages.get(from_ui_key) or {}
    game.mirror_prompt_messages[to_ui_key] = {"text": text}
    ok = False
    obs_id = game.observer_user_id

    async def _edit_one(
        chat_id: int, message_id: int, body: str, role: str
    ) -> None:
        nonlocal ok
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=body,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
            ok = True
        except TelegramBadRequest:
            try:
                await bot.edit_message_reply_markup(
                    chat_id=chat_id,
                    message_id=message_id,
                    reply_markup=reply_markup,
                )
                ok = True
            except TelegramBadRequest:
                return
        _store_mirror_prompt_ref(
            game, to_ui_key, role, chat_id, message_id, text
        )

    player_ref = from_entry.get("player")
    if isinstance(player_ref, tuple) and len(player_ref) == 2:
        await _edit_one(int(player_ref[0]), int(player_ref[1]), text, "player")

    obs_ref = from_entry.get("observer")
    if isinstance(obs_ref, tuple) and len(obs_ref) == 2 and obs_id is not None:
        obs_body = text
        if obs_id != assistant_uid:
            obs_body = observer_player_copy_prefix(game, assistant_uid) + text
        await _edit_one(int(obs_ref[0]), int(obs_ref[1]), obs_body, "observer")

    return ok


async def register_mirror_prompt_pair(
    bot: Bot,
    game: Game,
    player_uid: int,
    ui_key: str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    *,
    send_player: bool = True,
    send_observer: bool = True,
    observer_same_text: bool = False,
    **kwargs: Any,
) -> None:
    """ثبت پیام انتخاب برای بازیکن و ناظر (برای بستن دکمه بعد از claim)."""
    send_player, send_observer = _coerce_mirror_delivery(
        game,
        player_uid,
        send_player=send_player,
        send_observer=send_observer,
    )
    entry = game.mirror_prompt_messages.setdefault(ui_key, {})
    entry["text"] = text
    send_player_dm = (
        send_player
        and player_should_receive_game_messages(game, player_uid)
        and not is_synthetic_player_uid(player_uid)
    )
    if send_player_dm:
        msg = await safe_send_message_return(
            bot, player_uid, text, reply_markup=reply_markup, **kwargs
        )
        if msg is not None:
            _store_mirror_prompt_ref(
                game, ui_key, "player", player_uid, msg.message_id, text
            )
    if send_observer:
        await _send_observer_mirror_ref(
            bot,
            game,
            ui_key,
            player_uid,
            text,
            reply_markup,
            observer_same_text=observer_same_text,
            **kwargs,
        )


async def ensure_observer_mirror_prompt(
    bot: Bot,
    game: Game,
    player_uid: int,
    ui_key: str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    *,
    observer_same_text: bool = False,
    parse_mode: str = "HTML",
) -> bool:
    """اگر ناظر دیرتر ثبت شده و آینهٔ این پنل نیست — یک‌بار بفرست."""
    if not no_host_observer_registered(game):
        return False
    entry = game.mirror_prompt_messages.get(ui_key) or {}
    if entry.get("observer"):
        return False
    game.mirror_prompt_messages.setdefault(ui_key, {})["text"] = text
    return await _send_observer_mirror_ref(
        bot,
        game,
        ui_key,
        player_uid,
        text,
        reply_markup,
        observer_same_text=observer_same_text,
        parse_mode=parse_mode,
    )


async def publish_mirror_prompt_pair(
    bot: Bot,
    game: Game,
    player_uid: int,
    ui_key: str,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    *,
    fresh_observer_copy: bool | None = None,
    send_player: bool = True,
    send_observer: bool = True,
    observer_same_text: bool = False,
    **kwargs: Any,
) -> None:
    """ارسال یا به‌روزرسانی پنل انتخاب — همیشه نسخهٔ ناظر را تضمین می‌کند."""
    send_player, send_observer = _coerce_mirror_delivery(
        game,
        player_uid,
        send_player=send_player,
        send_observer=send_observer,
    )
    if _must_mirror_ui_to_observer(game, player_uid):
        fresh_observer_copy = True if fresh_observer_copy is None else fresh_observer_copy
    existing = game.mirror_prompt_messages.get(ui_key)
    if fresh_observer_copy is None:
        fresh_observer_copy = bool(existing)
    if existing:
        await update_mirror_prompt_pair(
            bot,
            game,
            ui_key,
            text,
            reply_markup,
            assistant_uid=player_uid,
            fresh_observer_copy=fresh_observer_copy,
            observer_same_text=observer_same_text,
            **kwargs,
        )
        if (
            send_player
            and not existing.get("player")
            and player_should_receive_game_messages(game, player_uid)
            and not is_synthetic_player_uid(player_uid)
        ):
            msg = await safe_send_message_return(
                bot, player_uid, text, reply_markup=reply_markup, **kwargs
            )
            if msg is not None:
                _store_mirror_prompt_ref(
                    game, ui_key, "player", player_uid, msg.message_id, text
                )
        if send_observer and no_host_observer_registered(game):
            entry_after = game.mirror_prompt_messages.get(ui_key) or {}
            if not entry_after.get("observer"):
                await _send_observer_mirror_ref(
                    bot,
                    game,
                    ui_key,
                    player_uid,
                    text,
                    reply_markup,
                    observer_same_text=observer_same_text,
                    **kwargs,
                )
        return
    await register_mirror_prompt_pair(
        bot,
        game,
        player_uid,
        ui_key,
        text,
        reply_markup,
        send_player=send_player,
        send_observer=send_observer,
        observer_same_text=observer_same_text,
        **kwargs,
    )


async def send_to_player(
    bot: Bot,
    game: Game,
    player_uid: int,
    text: str,
    *,
    mirror_reply_markup: InlineKeyboardMarkup | None = None,
    mirror_ui_key: str | None = None,
    observer_same_text: bool = False,
    **kwargs: Any,
) -> bool:
    """پیام خصوصی به بازیکن؛ در مسیر Player-Moderator همیشه آینه برای ناظر."""
    inline_kb = mirror_reply_markup
    if inline_kb is None:
        raw = kwargs.get("reply_markup")
        inline_kb = raw if _is_mirror_ui_markup(raw) else None
    if mirror_ui_key is not None or inline_kb is not None:
        ui_key = mirror_ui_key or mirror_ui_claim_key(
            game.room_code, "seat_msg", player_uid
        )
        kb = inline_kb
        send_player = (
            player_should_receive_game_messages(game, player_uid)
            and not is_synthetic_player_uid(player_uid)
        )
        await register_mirror_prompt_pair(
            bot,
            game,
            player_uid,
            ui_key,
            text,
            kb,
            send_player=send_player,
            send_observer=True,
            observer_same_text=observer_same_text,
            **kwargs,
        )
        return send_player

    await deliver_no_host_player_game_copy(
        bot,
        game,
        player_uid,
        text,
        is_synthetic_uid=is_synthetic_player_uid,
        **kwargs,
    )
    return player_should_receive_game_messages(
        game, player_uid
    ) and not is_synthetic_player_uid(player_uid)


async def send_to_bot_assistant(
    bot: Bot,
    game: Game,
    text: str,
    **kwargs: Any,
) -> bool:
    """پیام به کمک‌کننده ربات حتی اگر در بازی کشته شده باشد."""
    uid = game.bot_assistant_user_id
    if uid is None or game.bazpors_host_mode != "no_host":
        return False
    return (await safe_send_message_return(bot, uid, text, **kwargs)) is not None


async def _broadcast_deliver_many(
    bot: Bot,
    game: Game,
    targets: list[int],
    text: str,
    *,
    is_synthetic_uid: Any = None,
    simulate_all_seats: bool | None = None,
    **kwargs: Any,
) -> None:
    async def _one(uid: int) -> None:
        await deliver_no_host_player_game_copy(
            bot,
            game,
            uid,
            text,
            is_synthetic_uid=is_synthetic_uid,
            simulate_all_seats=simulate_all_seats,
            **kwargs,
        )

    await gather_bounded(sorted(targets), _one)


async def broadcast_to_alive_non_mafia_players(
    bot: Bot,
    game: Game,
    text: str,
    *,
    exclude: int | None = None,
    is_synthetic_uid: Any = None,
    simulate_all_seats: bool | None = None,
    **kwargs: Any,
) -> None:
    """همگانی به بازیکنان زندهٔ غیرمافیا؛ صندلی مصنوعی → آینه برای ناظر."""
    from bot.bazpors_narrator import _visually_mafia

    targets: list[int] = []
    for uid, player in game.players.items():
        if not player.is_alive:
            continue
        if exclude is not None and uid == exclude:
            continue
        if _visually_mafia(game, player):
            continue
        targets.append(uid)
    await _broadcast_deliver_many(
        bot,
        game,
        targets,
        text,
        is_synthetic_uid=is_synthetic_uid,
        simulate_all_seats=simulate_all_seats,
        **kwargs,
    )


async def broadcast_to_alive_players(
    bot: Bot,
    game: Game,
    text: str,
    *,
    exclude: int | None = None,
    is_synthetic_uid: Any = None,
    simulate_all_seats: bool | None = None,
    **kwargs: Any,
) -> None:
    """همگانی فقط به بازیکنان زنده."""
    targets: list[int] = []
    for uid, player in game.players.items():
        if not player.is_alive:
            continue
        if exclude is not None and uid == exclude:
            continue
        targets.append(uid)
    await _broadcast_deliver_many(
        bot,
        game,
        targets,
        text,
        is_synthetic_uid=is_synthetic_uid,
        simulate_all_seats=simulate_all_seats,
        **kwargs,
    )


async def broadcast_to_players(
    bot: Bot,
    game: Game,
    text: str,
    *,
    exclude: int | None = None,
    is_synthetic_uid: Any = None,
    simulate_all_seats: bool | None = None,
    **kwargs: Any,
) -> None:
    """پیام همگانی به بازیکنان؛ با ناظر فعال، به‌ازای هر صندلی یک نسخه برای ناظر."""
    targets = set(game.players.keys())
    targets.add(game.host_id)
    if exclude is not None:
        targets.discard(exclude)

    await _broadcast_deliver_many(
        bot,
        game,
        list(targets),
        text,
        is_synthetic_uid=is_synthetic_uid,
        simulate_all_seats=simulate_all_seats,
        **kwargs,
    )


def mirrored_player_end_keyboard(game: Game, as_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ تأیید پایان این دست (بدون گرداننده)",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="pea", as_uid=as_uid
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✖️ انصراف (بدون تأیید)",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="pex", as_uid=as_uid
                    ).pack(),
                ),
            ],
        ]
    )


def mirrored_player_end_broadcast_confirm_keyboard(
    game: Game, as_uid: int
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ بله، برای همه پیام رأی بفرست",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="pbc", as_uid=as_uid, tid=1
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✖️ خیر، منصرف شدم",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="pbc", as_uid=as_uid, tid=0
                    ).pack(),
                ),
            ],
        ]
    )


def mirrored_endgame_winner_keyboard(game: Game, as_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔴 برد مافیا",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="egwm", as_uid=as_uid
                    ).pack(),
                ),
                InlineKeyboardButton(
                    text="🟢 برد شهروند",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="egwc", as_uid=as_uid
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✖️ انصراف",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="egx", as_uid=as_uid
                    ).pack(),
                ),
            ],
        ]
    )


def mirrored_day1_vote_choice_keyboard(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔹 کسی برای دفاعیه انتخاب نشد؛ پس به فاز شب می‌رویم",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act="d1_skip",
                        as_uid=assistant_uid,
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔹 رأی‌گیری لازم است؛ پنل انتخاب بازیکن را نمایش بده",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act="d1_vote",
                        as_uid=assistant_uid,
                    ).pack(),
                ),
            ],
        ]
    )


def mirrored_intro_night_start_keyboard(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🌙 شروع شب معارفه",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act="intro_night",
                        as_uid=assistant_uid,
                    ).pack(),
                ),
            ],
        ]
    )


def mirrored_intro_night_confirm_keyboard(
    game: Game, assistant_uid: int
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ ادامه",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act="intro_night_ok",
                        as_uid=assistant_uid,
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="↩️ بازگشت",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code,
                        act="intro_night_back",
                        as_uid=assistant_uid,
                    ).pack(),
                ),
            ],
        ]
    )


def mirrored_emergency_leave_keyboard(game: Game, as_uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ بله، مطمئنم؛ از بازی خارج می‌شوم",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="elc", as_uid=as_uid
                    ).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✖️ انصراف",
                    callback_data=PlayerMirrorCb(
                        code=game.room_code, act="elx", as_uid=as_uid
                    ).pack(),
                ),
            ],
        ]
    )
