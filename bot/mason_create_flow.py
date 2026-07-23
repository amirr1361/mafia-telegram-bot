"""ساخت اتاق سناریوی ماسون — wrapperهای ایزوله روی UI مشترک.

منطق بازپرس/مذاکره دست‌نخورده می‌ماند؛ این ماژول فقط مسیر /create ماسون را
روی helperهای عمومی سوار می‌کند.
"""

from __future__ import annotations

import html

from aiogram import Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup

from bot.game import MASOON_PLAYER_COUNTS
from bot.main import (
    bazpors_host_mode_keyboard,
    bazpors_host_mode_prompt_html,
    build_host_mode_created_room_html,
    semi_auto_lobby_dev_keyboard,
)
from bot.models import Game

MASON_HOST_MODE_STUB_HTML = "این حالت برای سناریوی ماسون فعلاً آماده نیست."


def mason_player_counts() -> frozenset[int]:
    return MASOON_PLAYER_COUNTS


def mason_player_count_invalid_alert() -> str:
    return "ماسون: ۱۲ تا ۱۸ بازیکن."


def mason_host_mode_prompt_html(label: str, count: int) -> str:
    return bazpors_host_mode_prompt_html(label, count)


def mason_host_mode_keyboard(slug: str, count: int) -> InlineKeyboardMarkup:
    return bazpors_host_mode_keyboard(slug, count)


def build_mason_manual_created_room_html(
    game: Game,
    *,
    invite_link: str,
    host_label: str,
    scenario_label: str,
    roster_html: str,
) -> str:
    """همان پنل «اتاق ساخته شد» که قبلاً بلافاصله پس از انتخاب ظرفیت ماسون بود."""
    rle = "\u202B"
    pdf = "\u202C"
    lri = "\u2066"
    pdi = "\u2069"

    def rtl_line(s: str) -> str:
        return f"{rle}{s}{pdf}"

    return (
        f"{rtl_line('✅ <b>اتاق ساخته شد</b>')}\n\n"
        f"{rtl_line(f'🔑 کد ورود: <b>{html.escape(game.room_code)}</b>')}\n"
        f"{rtl_line(f'🎭 سناریو: {html.escape(scenario_label)}')}\n"
        f"{rtl_line(f'👥 ظرفیت: {game.max_players} نفر')}\n"
        f"{rtl_line(f'🎙 گرداننده: {html.escape(host_label)}')}\n\n"
        f"{roster_html}\n\n"
        f"{rtl_line('📥 بازیکنان با کد بالا یا لینک زیر وارد شوند:')}\n"
        f'{rtl_line(f"🔗 <a href=\"{html.escape(invite_link)}\">ورود به اتاق (یک ضربه)</a>")}\n'
        f"{rtl_line(f'همچنین می‌توانند بفرستند: {lri}/join {html.escape(game.room_code)}{pdi}')}"
    )


def build_mason_host_mode_created_room_html(
    game: Game,
    *,
    mode: str,
    invite_link: str,
    host_label: str,
    scenario_label: str,
    roster_html: str,
    creator_registered: bool = False,
) -> str:
    return build_host_mode_created_room_html(
        game,
        mode=mode,
        invite_link=invite_link,
        host_label=host_label,
        scenario_label=scenario_label,
        roster_html=roster_html,
        creator_registered=creator_registered,
    )


async def present_mason_host_mode_created_room(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    *,
    mode: str,
    host_uid: int,
    host_full_name: str,
    creator_registered: bool = False,
) -> None:
    """پنل اتاق پس از انتخاب بازیکن‌گرداننده یا نیمه‌خودکار (ماسون)."""
    if not callback.message:
        return
    bot_username = (await bot.get_me()).username or "YourBot"
    invite_link = f"https://t.me/{bot_username}?start={game.room_code}"
    from bot.app_state import manager
    from bot.game import role_roster_banner_text
    from bot.main import format_roster_plain_to_html

    label = manager.scenario_display_name(game.scenario_name)
    roster_plain = role_roster_banner_text(
        game.scenario_name, game.max_players, manager
    )
    roster_html = format_roster_plain_to_html(roster_plain)
    host_label = manager.get_user_display_name(
        host_uid,
        (host_full_name or "").strip() or "—",
    )
    text = build_mason_host_mode_created_room_html(
        game,
        mode=mode,
        invite_link=invite_link,
        host_label=host_label,
        scenario_label=label,
        roster_html=roster_html,
        creator_registered=creator_registered,
    )
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_markup=(
            semi_auto_lobby_dev_keyboard(game)
            if mode in ("semi_auto", "no_host")
            else None
        ),
    )
