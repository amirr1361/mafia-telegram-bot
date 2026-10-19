"""Routerهای aiogram — فاز ۲."""

from __future__ import annotations

from aiogram import Dispatcher


def register_all_handlers(dp: Dispatcher) -> None:
    """ثبت همه routerها — import تنبل برای جلوگیری از چرخه با main."""
    from bot.handlers.chaos import register_chaos_handlers
    from bot.handlers.host_panel import register_host_panel_handlers
    from bot.handlers.hub import register_hub_handlers
    from bot.handlers.lobby import register_lobby_handlers
    from bot.handlers.narrator_cb import register_narrator_cb_handlers
    from bot.handlers.no_host_player import register_no_host_player_handlers
    from bot.handlers.player_end import register_player_end_handlers
    from bot.handlers.post_game import register_post_game_handlers
    from bot.handlers.russian_mafia import register_russian_mafia_handlers
    from bot.mozakere_elim_report import register_mozakere_elim_report_handlers
    from bot.bazpors_elim_report import register_bazpors_elim_report_handlers
    from bot.mason_elim_report import register_mason_elim_report_handlers
    from bot.russian_mafia_elim_report import register_russian_mafia_elim_report_handlers

    register_narrator_cb_handlers(dp)
    register_post_game_handlers(dp)
    register_lobby_handlers(dp)
    register_no_host_player_handlers(dp)
    register_mozakere_elim_report_handlers(dp)
    register_bazpors_elim_report_handlers(dp)
    register_mason_elim_report_handlers(dp)
    register_russian_mafia_elim_report_handlers(dp)
    register_player_end_handlers(dp)
    register_hub_handlers(dp)
    register_host_panel_handlers(dp)
    register_chaos_handlers(dp)
    register_russian_mafia_handlers(dp)
