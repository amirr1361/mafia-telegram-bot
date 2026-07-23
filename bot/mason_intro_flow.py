"""شب معارفه و جریان پس از آن — فقط سناریوی ماسون (no_host)."""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from aiogram import Bot

from bot.game import is_mafia_team, is_synthetic_player_uid
from bot.models import Game, Player, Role
from bot.observer_delivery import mirror_per_player_to_observer
from bot.room_mode import is_mason_scenario
from bot.roles.mason_apache import apache_receives_mafia_intro
from bot.tg_send import safe_send_message

if TYPE_CHECKING:
    from bot.game import GameManager


def build_mason_intro_night_civilian_html() -> str:
    return (
        "🌙 <b>شب معارفه آغاز شد</b>\n"
        "اعضای تیم مافیا از طریق پیام ارسالی، هم‌تیمی‌های خود را شناسایی کردند.\n"
        "😴 لطفاً چشم‌های خود را ببندید و بخوابید تا اعضای تیم مافیا "
        "فرصت بیشتری برای آشنایی با یکدیگر داشته باشند."
    )


def _mason_alive_mafia_for_intro(game: Game) -> list[Player]:
    mafs = [
        p
        for p in game.players.values()
        if p.is_alive and p.role and is_mafia_team(p.role) and p.role != Role.APACHE
    ]

    def _sort_key(p: Player) -> tuple[int, int, int]:
        if p.role == Role.GODFATHER:
            return (0, p.seat if p.seat is not None else 999, p.user_id)
        return (1, p.seat if p.seat is not None else 999, p.user_id)

    mafs.sort(key=_sort_key)
    return mafs


def build_mason_intro_night_mafia_dm_html(game: Game) -> str:
    from bot.game import scenario_role_label_fa
    from bot.main import manager

    lines = [
        "🌙 <b>شب معارفه آغاز شد.</b>",
        "شما عضو تیم مافیا هستید. اعضای تیم شما عبارت‌اند از:",
        "📋 <b>اعضای تیم مافیا:</b>",
    ]
    for p in _mason_alive_mafia_for_intro(game):
        tag = html.escape(manager.format_player_tag(p))
        role_txt = html.escape(scenario_role_label_fa(game, p.role))
        lines.append(f"• {tag} — <b>{role_txt}</b>")
    return "\n".join(lines)


async def deliver_mason_intro_night_started_messages(
    bot: Bot, game: Game
) -> None:
    """پیام معارفه — آپاچی همان پیام شهروندان را می‌گیرد."""
    civilian_text = build_mason_intro_night_civilian_html()
    mafia_text = build_mason_intro_night_mafia_dm_html(game)
    for uid, p in game.players.items():
        if not p.is_alive or is_synthetic_player_uid(uid):
            continue
        if p.role and apache_receives_mafia_intro(game, p):
            text = mafia_text
        else:
            text = civilian_text
        await safe_send_message(bot, uid, text, parse_mode="HTML")
        await mirror_per_player_to_observer(
            bot, game, uid, text, parse_mode="HTML"
        )


async def mason_after_intro_night_started(
    bot: Bot, game: Game, gm: "GameManager"
) -> None:
    """پس از تأیید شب معارفه — پیام‌ها، پنل روزانه، پنل کمک‌کننده رأی."""
    from bot.mason_day_ability import dispatch_mason_intro_day_ability_panels
    from bot.mason_helper_flow import send_mason_vote_start_prompt

    game.mason_intro_day_ability_open = True
    game.mason_intro_day_ability_locked = False
    await deliver_mason_intro_night_started_messages(bot, game)
    await dispatch_mason_intro_day_ability_panels(bot, game, gm)
    await send_mason_vote_start_prompt(bot, game)


def mason_should_use_intro_flow(game: Game) -> bool:
    return is_mason_scenario(game)
