"""تشخیص حالت اتاق بازپرس — استخراج از main (فاز ۳)."""

from __future__ import annotations

from bot.models import Game


def is_bazpors_semi_auto_room(game: Game) -> bool:
    return (
        game.scenario_name == "bazpors"
        and game.bazpors_host_mode == "semi_auto"
    )


def is_bazpors_no_host_room(game: Game) -> bool:
    """اتاق بازپرس با گردانندگی بدون گرداننده (سازنده بازیکن است)."""
    return (
        game.scenario_name == "bazpors"
        and game.bazpors_host_mode == "no_host"
    )


def no_host_bot_assistant_flow_enabled(game: Game) -> bool:
    """کمک‌کننده ربات — بازپرس یا مذاکرهٔ بازیکن‌گرداننده."""
    return is_no_host_player_room(game)


def narrator_assist_after_roles_dealt(game: Game) -> bool:
    """پنل نریتور پس از پخش نقش — semi_auto بازپرس/مذاکره یا اتاق تست."""
    return is_bazpors_narrator_room(game) or (
        is_mozakere_scenario(game) and game.bazpors_host_mode == "semi_auto"
    )


def bazpors_lobby_dev_fill_enabled(game: Game) -> bool:
    """دکمه‌های پر کردن تصادفی / انتظار در لابی بازپرس."""
    return is_bazpors_semi_auto_room(game) or is_bazpors_no_host_room(game)


def is_mozakere_scenario(game: Game) -> bool:
    """سناریوی مذاکره — قوانین نقش‌ها جدا از بازپرس."""
    return game.scenario_name == "mozakere"


def is_mason_scenario(game: Game) -> bool:
    """سناریوی ماسون — قوانین نقش‌ها جدا از بازپرس و مذاکره."""
    return game.scenario_name == "masoon"


def is_mozakere_no_host_room(game: Game) -> bool:
    """اتاق مذاکره با گردانندگی بازیکن‌گرداننده."""
    return (
        is_mozakere_scenario(game)
        and game.bazpors_host_mode == "no_host"
    )


def mozakere_no_host_uses_parallel_night_ui(game: Game) -> bool:
    """مذاکرهٔ no_host — بدون پنل «شروع اجرای نقش‌های شب»؛ فقط جمع‌آوری موازی."""
    return is_mozakere_no_host_room(game)


def is_mason_no_host_room(game: Game) -> bool:
    """اتاق ماسون با گردانندگی بازیکن‌گرداننده."""
    return (
        is_mason_scenario(game)
        and game.bazpors_host_mode == "no_host"
    )


def is_no_host_player_room(game: Game) -> bool:
    """بازپرس، مذاکره یا ماسون — سازنده در صندلی و لابی مشترک no_host."""
    return (
        is_bazpors_no_host_room(game)
        or is_mozakere_no_host_room(game)
        or is_mason_no_host_room(game)
    )


def is_russian_mafia_host_helper_room(game: Game) -> bool:
    """مافیای روسی — سازنده بازیکن است؛ کمک‌کننده ربات بعداً انتخاب می‌شود."""
    return (
        game.scenario_name == "russian_mafia"
        and game.bazpors_host_mode == "host_helper"
    )


def lobby_dev_fill_enabled(game: Game) -> bool:
    """دکمه‌های لابی تست — بازپرس یا مذاکره/ماسونٔ بازیکن‌گرداننده."""
    return (
        bazpors_lobby_dev_fill_enabled(game)
        or is_mozakere_no_host_room(game)
        or is_mason_no_host_room(game)
        or is_russian_mafia_host_helper_room(game)
    )


def is_bazpors_narrator_room(game: Game) -> bool:
    return game.scenario_name == "bazpors_salamat_test" or is_bazpors_semi_auto_room(
        game
    )


def host_receives_moderator_deal_messages(game: Game) -> bool:
    """لیست کامل نقش‌ها و پنل «نقش‌ها فرستاده شد» فقط برای گردانندهٔ انسانی."""
    if is_russian_mafia_host_helper_room(game):
        return False
    return not is_no_host_player_room(game)


def players_receive_post_deal_hub_message(game: Game) -> bool:
    """بعد از پخش نقش، پیام راهنما/کیبورد به بازیکنان برود یا نه."""
    if game.scenario_name == "bazpors_salamat_test":
        return False
    if is_bazpors_semi_auto_room(game):
        return False
    if is_no_host_player_room(game):
        return False
    return True
