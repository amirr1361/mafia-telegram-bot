"""Shared player-selected role-number distribution (Bazpors / Mozakere / Mason)."""

from __future__ import annotations

import asyncio
import html
import logging
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from bot.app_state import manager
from bot.game import is_synthetic_player_uid, scenario_role_label_fa
from bot.models import Game, Role
from bot.text_fa import fa_digits as _fa_digits
from bot.tg_send import safe_callback_answer, safe_send_message

logger = logging.getLogger(__name__)

CLAIM_SOURCE_PLAYER = "player"
CLAIM_SOURCE_AUTOMATIC_NON_REAL = "automatic_non_real"
_ROLE_PICK_LOCKS: dict[str, asyncio.Lock] = {}


@dataclass(frozen=True)
class RolePickProfile:
    """سناریو-ویژه برای انتخاب نقش بر اساس شماره."""

    scenario_name: str
    log_label: str
    cb_prefix: str
    taken_cb_prefix: str
    state_prefix: str
    roles_for_count: Callable[[int], list[Role]]
    assign_by_player: Callable[[Any, Game, dict[int, Role]], None]
    reveal_via_private_role: bool = False


def inline_button_supports_style() -> bool:
    fields = getattr(InlineKeyboardButton, "model_fields", None)
    return isinstance(fields, dict) and "style" in fields


def is_real_player_uid(user_id: int) -> bool:
    return not is_synthetic_player_uid(user_id)


def real_player_uids(game: Game) -> list[int]:
    return sorted(uid for uid in game.players if is_real_player_uid(uid))


def non_real_player_uids(game: Game) -> list[int]:
    return sorted(uid for uid in game.players if is_synthetic_player_uid(uid))


def _state_get(game: Game, profile: RolePickProfile, suffix: str) -> Any:
    return getattr(game, f"{profile.state_prefix}_{suffix}")


def _state_set(game: Game, profile: RolePickProfile, suffix: str, value: Any) -> None:
    setattr(game, f"{profile.state_prefix}_{suffix}", value)


def role_pick_active(game: Game, profile: RolePickProfile) -> bool:
    return bool(_state_get(game, profile, "player_role_pick_active"))


def any_player_role_pick_active(game: Game) -> bool:
    return bool(
        getattr(game, "bazpors_player_role_pick_active", False)
        or getattr(game, "mozakere_player_role_pick_active", False)
        or getattr(game, "mason_player_role_pick_active", False)
        or getattr(game, "russian_mafia_player_role_pick_active", False)
    )


def claimed_number_button_text(number: int) -> str:
    return f"❌ شماره {_fa_digits(number)} — انتخاب شده"


def available_number_button_text(number: int) -> str:
    return f"شماره {_fa_digits(number)}"


def role_pick_callback_data(profile: RolePickProfile, room_code: str, number: int) -> str:
    return f"{profile.cb_prefix}:{room_code}:{number}"


def role_pick_taken_callback_data(
    profile: RolePickProfile, room_code: str, number: int
) -> str:
    return f"{profile.taken_cb_prefix}:{room_code}:{number}"


def parse_prefixed_role_pick_callback(
    data: str, *, prefix: str
) -> tuple[str, int] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != prefix:
        return None
    room_code = parts[1].strip()
    if not room_code:
        return None
    raw = parts[2].strip()
    if not raw.isdigit():
        return None
    return room_code, int(raw)


def _make_number_button(
    profile: RolePickProfile,
    game: Game,
    number: int,
    *,
    claimed: bool,
) -> InlineKeyboardButton:
    kwargs: dict[str, object] = {}
    if claimed:
        kwargs["text"] = claimed_number_button_text(number)
        kwargs["callback_data"] = role_pick_taken_callback_data(
            profile, game.room_code, number
        )
        if inline_button_supports_style():
            kwargs["style"] = "danger"
    else:
        kwargs["text"] = available_number_button_text(number)
        kwargs["callback_data"] = role_pick_callback_data(
            profile, game.room_code, number
        )
        if inline_button_supports_style():
            kwargs["style"] = "primary"
    return InlineKeyboardButton(**kwargs)


def build_role_pick_keyboard(
    profile: RolePickProfile, game: Game
) -> InlineKeyboardMarkup:
    claimed = set(_state_get(game, profile, "role_number_claims").keys())
    numbers = sorted(_state_get(game, profile, "role_number_map").keys())
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for n in numbers:
        row.append(_make_number_button(profile, game, n, claimed=n in claimed))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return InlineKeyboardMarkup(
        inline_keyboard=rows
        or [[InlineKeyboardButton(text="پایان یافت", callback_data="noop")]]
    )


def all_real_players_have_selected(profile: RolePickProfile, game: Game) -> bool:
    claims = _state_get(game, profile, "player_role_claims")
    real_uids = real_player_uids(game)
    if not real_uids:
        return True
    return all(uid in claims for uid in real_uids)


def _all_players_assigned(profile: RolePickProfile, game: Game) -> bool:
    return len(_state_get(game, profile, "player_role_claims")) >= len(game.players)


def _record_claim(
    profile: RolePickProfile,
    game: Game,
    *,
    uid: int,
    number: int,
    claim_source: str,
) -> None:
    claimed_at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    role_map = _state_get(game, profile, "role_number_map")
    role_value = role_map[number]
    number_claims = _state_get(game, profile, "role_number_claims")
    player_claims = _state_get(game, profile, "player_role_claims")
    number_claims[number] = uid
    player_claims[uid] = {
        "number": number,
        "role": role_value,
        "claimed_at": claimed_at,
        "claim_source": claim_source,
    }


def auto_assign_remaining_numbers_to_non_real(
    profile: RolePickProfile, game: Game
) -> bool:
    if _state_get(game, profile, "non_real_role_assignment_completed"):
        return True

    role_map = _state_get(game, profile, "role_number_map")
    number_claims = _state_get(game, profile, "role_number_claims")
    player_claims = _state_get(game, profile, "player_role_claims")
    remaining = [n for n in sorted(role_map.keys()) if n not in number_claims]
    unassigned_non_real = [
        uid for uid in non_real_player_uids(game) if uid not in player_claims
    ]
    if len(remaining) != len(unassigned_non_real):
        logger.error(
            "%s role-pick auto-assignment mismatch: "
            "room=%s remaining_numbers=%s synthetic_players=%s",
            profile.log_label,
            game.room_code,
            len(remaining),
            len(unassigned_non_real),
        )
        return False

    if unassigned_non_real:
        logger.info(
            "All real %s players selected. Auto-assigning remaining numbers "
            "to %s synthetic players. room=%s",
            profile.log_label,
            len(unassigned_non_real),
            game.room_code,
        )
        shuffled = list(remaining)
        random.shuffle(shuffled)
        for uid, number in zip(unassigned_non_real, shuffled):
            _record_claim(
                profile,
                game,
                uid=uid,
                number=number,
                claim_source=CLAIM_SOURCE_AUTOMATIC_NON_REAL,
            )
            logger.info(
                "Auto-assigned non-real player %s to number %s room=%s scenario=%s",
                uid,
                number,
                game.room_code,
                profile.scenario_name,
            )

    _state_set(game, profile, "non_real_role_assignment_completed", True)
    return True


def _log_waiting_for_real_players(profile: RolePickProfile, game: Game) -> None:
    claims = _state_get(game, profile, "player_role_claims")
    real_uids = real_player_uids(game)
    completed = sum(1 for uid in real_uids if uid in claims)
    logger.info(
        "%s role pick waiting for real players: completed=%s expected=%s room=%s",
        profile.log_label,
        completed,
        len(real_uids),
        game.room_code,
    )


def try_complete_after_real_selection(profile: RolePickProfile, game: Game) -> bool:
    if not all_real_players_have_selected(profile, game):
        _log_waiting_for_real_players(profile, game)
        return False
    if not auto_assign_remaining_numbers_to_non_real(profile, game):
        return False
    player_claims = _state_get(game, profile, "player_role_claims")
    if not _all_players_assigned(profile, game):
        logger.error(
            "%s role pick incomplete after auto-assign: room=%s claims=%s players=%s",
            profile.log_label,
            game.room_code,
            len(player_claims),
            len(game.players),
        )
        return False
    manual = sum(
        1
        for info in player_claims.values()
        if info.get("claim_source") == CLAIM_SOURCE_PLAYER
    )
    automatic = sum(
        1
        for info in player_claims.values()
        if info.get("claim_source") == CLAIM_SOURCE_AUTOMATIC_NON_REAL
    )
    logger.info(
        "%s player-role-pick finalized: manual=%s automatic=%s total=%s room=%s",
        profile.log_label,
        manual,
        automatic,
        len(player_claims),
        game.room_code,
    )
    _state_set(game, profile, "player_role_pick_active", False)
    return True


def start_player_role_pick(profile: RolePickProfile, game: Game) -> str | None:
    if game.scenario_name != profile.scenario_name:
        return f"این قابلیت فقط برای سناریوی {profile.log_label} است."
    if game.roles_dealt:
        return "نقش‌ها قبلاً پخش شده‌اند."
    if any_player_role_pick_active(game):
        return "انتخاب نقش توسط بازیکنان قبلاً شروع شده است."
    n = len(game.players)
    roles = list(profile.roles_for_count(n))
    random.shuffle(roles)
    _state_set(
        game,
        profile,
        "role_number_map",
        {idx: role.value for idx, role in enumerate(roles, start=1)},
    )
    _state_set(game, profile, "role_number_claims", {})
    _state_set(game, profile, "player_role_claims", {})
    _state_set(game, profile, "role_pick_panel_messages", {})
    _state_set(
        game,
        profile,
        "role_pick_started_at",
        datetime.now(timezone.utc).isoformat(timespec="microseconds"),
    )
    _state_set(game, profile, "non_real_role_assignment_completed", False)
    _state_set(game, profile, "player_role_pick_active", True)
    logger.info(
        "%s player-role-pick started: room=%s real=%s synthetic=%s",
        profile.log_label,
        game.room_code,
        len(real_player_uids(game)),
        len(non_real_player_uids(game)),
    )
    logger.info(
        "Role number map created with %s numbers room=%s scenario=%s",
        n,
        game.room_code,
        profile.scenario_name,
    )
    return None


async def _close_player_panel(bot: Bot, ref: tuple[int, int]) -> None:
    chat_id, message_id = ref
    try:
        await bot.edit_message_text(
            "✅ نقش شما انتخاب شد.",
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=None,
        )
    except TelegramBadRequest:
        pass


async def _close_all_panels(profile: RolePickProfile, bot: Bot, game: Game) -> None:
    refs = _state_get(game, profile, "role_pick_panel_messages")
    for ref in list(refs.values()):
        await _close_player_panel(bot, ref)


async def refresh_role_pick_panels(
    profile: RolePickProfile, bot: Bot, game: Game
) -> None:
    kb = build_role_pick_keyboard(profile, game)
    text = "لطفا یک شماره را انتخاب کنید تا نقش شما آشکار شود"
    refs = _state_get(game, profile, "role_pick_panel_messages")
    claims = _state_get(game, profile, "player_role_claims")
    for uid, ref in list(refs.items()):
        if uid in claims:
            await _close_player_panel(bot, ref)
            continue
        chat_id, message_id = ref
        try:
            await bot.edit_message_text(
                text,
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=kb,
            )
        except TelegramBadRequest:
            continue


async def _deliver_assigned_private_roles(bot: Bot, game: Game) -> None:
    from bot.main import send_private_role

    for player in game.players.values():
        if is_synthetic_player_uid(player.user_id) or player.role is None:
            continue
        try:
            await send_private_role(bot, player.user_id, player.role, game=game)
        except Exception:
            logger.debug(
                "role-pick private role delivery failed uid=%s room=%s",
                player.user_id,
                game.room_code,
                exc_info=True,
            )


async def finalize_player_role_pick(
    profile: RolePickProfile, bot: Bot, game: Game
) -> None:
    if game.roles_dealt:
        return
    from bot.main import finalize_roles_deal_pipeline

    role_by_player: dict[int, Role] = {}
    claims = _state_get(game, profile, "player_role_claims")
    for uid, info in claims.items():
        raw = str(info.get("role") or "").strip()
        role_by_player[uid] = Role(raw)
    profile.assign_by_player(manager, game, role_by_player)
    _state_set(game, profile, "player_role_pick_active", False)
    logger.info(
        "All %s role numbers claimed. Finalizing role distribution. room=%s",
        profile.log_label,
        game.room_code,
    )
    if profile.reveal_via_private_role:
        await _deliver_assigned_private_roles(bot, game)
    await finalize_roles_deal_pipeline(bot, game)


async def dispatch_player_role_pick_panels(
    profile: RolePickProfile, bot: Bot, game: Game
) -> None:
    kb = build_role_pick_keyboard(profile, game)
    text = "لطفا یک شماره را انتخاب کنید تا نقش شما آشکار شود"
    refs: dict[int, tuple[int, int]] = {}
    for uid in real_player_uids(game):
        try:
            msg = await bot.send_message(uid, text, reply_markup=kb)
        except Exception:
            logger.debug(
                "send role-pick panel failed uid=%s room=%s scenario=%s",
                uid,
                game.room_code,
                profile.scenario_name,
                exc_info=True,
            )
            continue
        refs[uid] = (msg.chat.id, msg.message_id)
    _state_set(game, profile, "role_pick_panel_messages", refs)

    lock = _ROLE_PICK_LOCKS.setdefault(
        f"{profile.scenario_name}:{game.room_code}", asyncio.Lock()
    )
    should_finalize = False
    async with lock:
        should_finalize = try_complete_after_real_selection(profile, game)
    if should_finalize:
        await _close_all_panels(profile, bot, game)
        await finalize_player_role_pick(profile, bot, game)


async def handle_player_role_pick_taken_callback(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    number: int,
) -> None:
    _ = (bot, game, number)
    await safe_callback_answer(
        callback,
        "این شماره قبلاً انتخاب شده است.",
        show_alert=True,
    )


async def _reveal_claim_to_player(
    profile: RolePickProfile,
    bot: Bot,
    game: Game,
    uid: int,
    role: Role,
) -> None:
    if profile.reveal_via_private_role:
        from bot.main import send_private_role

        await send_private_role(bot, uid, role, game=game)
        return
    role_label = html.escape(scenario_role_label_fa(game, role))
    await safe_send_message(
        bot,
        uid,
        f"نقش شما <b>{role_label}</b> است.",
        parse_mode="HTML",
    )


async def handle_player_role_pick_callback(
    profile: RolePickProfile,
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    number: int,
) -> None:
    if not callback.from_user:
        return
    uid = callback.from_user.id
    if game.scenario_name != profile.scenario_name:
        await safe_callback_answer(
            callback, "این دکمه برای این اتاق نیست.", show_alert=True
        )
        return
    if not role_pick_active(game, profile):
        await safe_callback_answer(callback, "انتخاب نقش فعال نیست.", show_alert=True)
        return
    if game.roles_dealt:
        await safe_callback_answer(
            callback, "نقش‌ها قبلاً نهایی شده‌اند.", show_alert=True
        )
        return
    if uid not in game.players:
        await safe_callback_answer(
            callback, "فقط بازیکنان همین اتاق.", show_alert=True
        )
        return
    if is_synthetic_player_uid(uid):
        await safe_callback_answer(
            callback, "این بازیکن قابل انتخاب دستی نیست.", show_alert=True
        )
        return
    player_claims = _state_get(game, profile, "player_role_claims")
    if uid in player_claims:
        await safe_callback_answer(
            callback, "شما قبلا نقش خود را انتخاب کرده‌اید.", show_alert=True
        )
        return
    role_map = _state_get(game, profile, "role_number_map")
    if number not in role_map:
        await safe_callback_answer(callback, "شماره نامعتبر است.", show_alert=True)
        return

    lock = _ROLE_PICK_LOCKS.setdefault(
        f"{profile.scenario_name}:{game.room_code}", asyncio.Lock()
    )
    role_value: str | None = None
    should_finalize = False
    async with lock:
        if not role_pick_active(game, profile) or game.roles_dealt:
            await safe_callback_answer(
                callback, "انتخاب نقش فعال نیست.", show_alert=True
            )
            return
        player_claims = _state_get(game, profile, "player_role_claims")
        if uid in player_claims:
            await safe_callback_answer(
                callback, "شما قبلا نقش خود را انتخاب کرده‌اید.", show_alert=True
            )
            return
        number_claims = _state_get(game, profile, "role_number_claims")
        owner = number_claims.get(number)
        if owner is not None:
            logger.info(
                "Rejected claim: scenario=%s room=%s number=%s already claimed by %s",
                profile.scenario_name,
                game.room_code,
                number,
                owner,
            )
            await safe_callback_answer(
                callback,
                "این شماره قبلا انتخاب شده است. لطفا یک شماره دیگر انتخاب کنید.",
                show_alert=True,
            )
            return
        role_value = role_map[number]
        _record_claim(
            profile,
            game,
            uid=uid,
            number=number,
            claim_source=CLAIM_SOURCE_PLAYER,
        )
        claimed_at = player_claims[uid]["claimed_at"]
        logger.info(
            "%s player %s claimed number %s at %s room=%s",
            profile.log_label,
            uid,
            number,
            claimed_at,
            game.room_code,
        )
        should_finalize = try_complete_after_real_selection(profile, game)

    await safe_callback_answer(callback, "ثبت شد.")
    assert role_value is not None
    await _reveal_claim_to_player(profile, bot, game, uid, Role(role_value))
    await refresh_role_pick_panels(profile, bot, game)

    if should_finalize:
        await _close_all_panels(profile, bot, game)
        await finalize_player_role_pick(profile, bot, game)
