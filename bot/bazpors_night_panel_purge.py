"""حذف پیام‌های پنل شب/روز گذشته پس از محاسبهٔ پایان شب."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bot.models import Game, Role

if TYPE_CHECKING:
    from aiogram import Bot


def _bazpors_panel_purge_enabled(game: Game) -> bool:
    return game.scenario_name in ("bazpors", "bazpors_salamat_test")


def night_panel_purge_recipient_uids(game: Game) -> set[int]:
    """بازیکنان زنده، ناظر، و اپراتور پنل (کمک‌کننده یا گرداننده)."""
    uids: set[int] = set()
    for pl in game.players.values():
        if pl.role == Role.OBSERVER:
            continue
        if pl.is_alive:
            uids.add(pl.user_id)
    if game.observer_user_id is not None:
        uids.add(game.observer_user_id)
    if (
        game.bazpors_host_mode == "no_host"
        and game.no_host_assistant_narrator_active
        and game.bot_assistant_user_id is not None
    ):
        uids.add(game.bot_assistant_user_id)
    elif game.host_id:
        uids.add(game.host_id)
    return uids


def collect_tracked_panel_message_refs(game: Game) -> list[tuple[int, int]]:
    """همهٔ (chat_id, message_id) ثبت‌شده برای پنل‌های اینلاین."""
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []

    def add(chat_id: int | None, message_id: int | None) -> None:
        if chat_id is None or message_id is None:
            return
        pair = (int(chat_id), int(message_id))
        if pair in seen:
            return
        seen.add(pair)
        out.append(pair)

    for entry in game.mirror_prompt_messages.values():
        if not isinstance(entry, dict):
            continue
        for role in ("player", "observer"):
            ref = entry.get(role)
            if isinstance(ref, tuple) and len(ref) >= 2:
                add(ref[0], ref[1])

    for ref in game.no_host_mafia_night1_refs.values():
        if isinstance(ref, tuple) and len(ref) >= 2:
            add(ref[0], ref[1])

    for ref in game.bazpors_assistant_panel_refs.values():
        if isinstance(ref, tuple) and len(ref) >= 2:
            add(ref[0], ref[1])

    for ref in game.bazpors_observer_narrator_mirror_refs.values():
        if isinstance(ref, tuple) and len(ref) >= 2:
            add(ref[0], ref[1])

    add(game.bazpors_assistant_panel_chat_id, game.bazpors_assistant_panel_message_id)
    add(
        game.bazpors_observer_narrator_mirror_chat_id,
        game.bazpors_observer_narrator_mirror_message_id,
    )
    return out


def clear_tracked_panel_message_state(game: Game) -> None:
    game.mirror_prompt_messages.clear()
    game.mirror_action_claims.clear()
    game.no_host_mafia_night1_refs.clear()
    game.bazpors_assistant_panel_refs.clear()
    game.bazpors_observer_narrator_mirror_refs.clear()
    game.bazpors_assistant_panel_chat_id = None
    game.bazpors_assistant_panel_message_id = None
    game.bazpors_observer_narrator_mirror_chat_id = None
    game.bazpors_observer_narrator_mirror_message_id = None


async def _try_delete_panel_message(
    bot: "Bot", chat_id: int, message_id: int
) -> bool:
    from aiogram.exceptions import TelegramBadRequest

    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
        return True
    except TelegramBadRequest:
        try:
            await bot.edit_message_reply_markup(
                chat_id=chat_id,
                message_id=message_id,
                reply_markup=None,
            )
        except TelegramBadRequest:
            pass
        return False


async def purge_stale_night_and_day_panel_messages(
    bot: "Bot", game: Game
) -> int:
    """پس از resolve شب: حذف پنل‌های قدیمی از چت بازیکنان زنده، ناظر و کمک‌کننده.

    Returns:
        تعداد پیام‌هایی که از تلگرام حذف شدند.
    """
    if not _bazpors_panel_purge_enabled(game):
        return 0

    recipient_chats = night_panel_purge_recipient_uids(game)
    refs = collect_tracked_panel_message_refs(game)
    deleted = 0
    for chat_id, message_id in refs:
        if chat_id not in recipient_chats:
            continue
        if await _try_delete_panel_message(bot, chat_id, message_id):
            deleted += 1

    clear_tracked_panel_message_state(game)

    try:
        from bot.game_audit_log import log_event

        log_event(
            game,
            "bazpors.night_panel_purge",
            deleted_count=deleted,
            tracked_refs=len(refs),
            recipient_count=len(recipient_chats),
        )
    except Exception:
        pass

    return deleted
