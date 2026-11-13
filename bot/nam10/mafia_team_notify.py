"""Namayande mafia-team informational notifications (private, no buttons).

Recipients: alive authorised Mafia teammates (excluding the acting
player) — real players get a private DM, synthetic seats are delivered
through the established Observer mirroring system, and the registered
Observer receives the notification with the game-copy policy of
``deliver_no_host_player_game_copy``. Never sent to Town players or the
public chat. Text-only: no reply markup, no acknowledgements.
"""

from __future__ import annotations

import logging

from aiogram import Bot

from bot.models import Game, Player

logger = logging.getLogger(__name__)


def _audit(game: Game, event: str, **data) -> None:
    try:
        from bot.game_audit_log import log_event

        log_event(game, event, **data)
    except Exception:
        pass


def _strip_role_suffix(p: Player, raw: str) -> str:
    from bot.game import is_synthetic_player_uid, synthetic_player_base_name

    if not is_synthetic_player_uid(p.user_id):
        return raw
    base = synthetic_player_base_name(raw)
    if base != raw:
        return base
    if p.role is None:
        return raw
    from bot.nam10.role_labels import nam10_role_label_fa

    suffix = f"-{nam10_role_label_fa(p.role)}"
    if raw.endswith(suffix):
        return raw[: -len(suffix)]
    return raw


def plain_player_name(p: Player | None, uid: int) -> str:
    """Display-name priority: /myname custom name, Telegram full_name,
    numeric id fallback. No @username. Synthetic role suffixes are hidden
    (informational text, not an authorised annotated panel)."""
    from bot.app_state import custom_display_name
    from bot.game import is_synthetic_player_uid

    if p is None:
        return str(uid)
    if is_synthetic_player_uid(p.user_id):
        label = custom_display_name(p.user_id) or p.full_name or str(uid)
        label = _strip_role_suffix(p, label)
        return label or str(uid)
    label = custom_display_name(p.user_id) or p.full_name
    return (label or str(uid)).strip() or str(uid)


def build_betrayal_vote_notification_text(
    op: str, rep_uid: int, rep_index: int, p: Player | None
) -> str:
    from bot.text_fa import fa_digits

    name = plain_player_name(p, rep_uid)
    if op == "add":
        return (
            "🗳️ رأی خیانت رئیس مافیا ثبت شد: "
            f"یک رأی به نماینده {fa_digits(rep_index)} ({name}) اضافه شد."
        )
    return (
        "🗳️ رأی خیانت رئیس مافیا ثبت شد: "
        f"یک رأی از نماینده {fa_digits(rep_index)} ({name}) کم شد."
    )


def build_shot_notification_text(mode_text: str, target_name: str) -> str:
    return (
        "🔴 انتخاب امشب تیم مافیا ثبت شد."
        f"\n\nنوع شلیک: {mode_text}"
        f"\n\n🎯 هدف: {target_name}"
    )


def build_nato_notification_text(role_label: str, target_name: str) -> str:
    return (
        "🎯 انتخاب ناتویی امشب تیم مافیا ثبت شد."
        f"\n\n🎭 نقش حدس‌زده‌شده: {role_label}"
        f"\n\n👤 بازیکن انتخاب‌شده: {target_name}"
    )


async def notify_mafia_teammates(
    bot: Bot,
    game: Game,
    text: str,
    *,
    exclude_uid: int | None = None,
    event: str | None = None,
) -> None:
    """فقط هم‌تیمی‌های مافیا: بازیکن واقعی → DM، صندلی مصنوعی → آینهٔ ناظر."""
    from bot.game import is_synthetic_player_uid
    from bot.observer_delivery import deliver_no_host_player_game_copy
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        return
    from bot.nam10.night2 import _alive_players, _is_mafia_member

    recipients = [
        p.user_id
        for p in _alive_players(game)
        if _is_mafia_member(game, p)
        and (exclude_uid is None or p.user_id != exclude_uid)
    ]
    for uid in sorted(recipients):
        try:
            await deliver_no_host_player_game_copy(
                bot,
                game,
                uid,
                text,
                is_synthetic_uid=is_synthetic_player_uid,
            )
        except Exception:
            logger.exception(
                "mafia teammate notification failed room=%s uid=%s",
                game.room_code,
                uid,
            )
    if event:
        _audit(
            game,
            event,
            recipients=recipients,
            exclude_uid=exclude_uid,
        )
