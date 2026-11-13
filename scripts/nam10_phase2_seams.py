#!/usr/bin/env python3
"""Phase 2 seam patches (idempotent): wire fork routing in shared files.

- bot/handlers/no_host_player.py: fork branches for pmr router,
  day1-defense cb, intro-night cb.
- bot/handlers/lobby.py: dev fill button picks the fork fill.
- bot/game.py: check_winner uses fork alive-mafia counting.
- bot/main.py: finalize_no_host_bot_assistant delegates to the fork copy.
"""
from __future__ import annotations

import sys
import pathlib

ROOT = pathlib.Path(sys.argv[1]).resolve()


def patch(relpath: str, old: str, new: str) -> bool:
    p = ROOT / relpath
    text = p.read_text(encoding="utf-8")
    if new in text:
        print(f"  [skip] {relpath}: branch already present")
        return False
    if old not in text:
        print(f"  [FAIL] {relpath}: anchor not found")
        return True
    text = text.replace(old, new, 1)
    p.write_text(text, encoding="utf-8")
    print(f"  [ok] {relpath}")
    return False


def patch_count(relpath: str, old: str, new: str, expect: int) -> bool:
    p = ROOT / relpath
    text = p.read_text(encoding="utf-8")
    n = text.count(old)
    if new in text:
        print(f"  [skip] {relpath}: branch already present")
        return False
    if n != expect:
        print(f"  [FAIL] {relpath}: anchor count {n} != {expect}")
        return True
    text = text.replace(old, new)
    p.write_text(text, encoding="utf-8")
    print(f"  [ok] {relpath} ({expect} sites)")
    return False


failed = False

# 1) shared pmr router: route fork rooms to the fork mirror engine
failed |= patch(
    "bot/handlers/no_host_player.py",
    '''    actor = callback.from_user.id
    as_uid = callback_data.as_uid
    act = callback_data.act
    room = game.room_code

    if game.scenario_name == "russian_mafia":''',
    '''    actor = callback.from_user.id
    as_uid = callback_data.as_uid
    act = callback_data.act
    room = game.room_code

    from bot.room_mode import is_namayande10_no_host_room

    if is_namayande10_no_host_room(game):
        from bot.nam10.player_mirror import dispatch_namayande10_mirror

        await dispatch_namayande10_mirror(
            callback, bot, game, callback_data=callback_data
        )
        return

    if game.scenario_name == "russian_mafia":''',
)

# 2) dedicated day1-defense cb
failed |= patch(
    "bot/handlers/no_host_player.py",
    '''    if not game or not (
        no_host_bot_assistant_flow_enabled(game)
        or is_russian_mafia_host_helper_room(game)
    ):
        await callback.answer("این دکمه برای این اتاق نیست.", show_alert=True)
        return
    assistant_uid = game.bot_assistant_user_id''',
    '''    if not game or not (
        no_host_bot_assistant_flow_enabled(game)
        or is_russian_mafia_host_helper_room(game)
    ):
        await callback.answer("این دکمه برای این اتاق نیست.", show_alert=True)
        return
    from bot.room_mode import is_namayande10_no_host_room

    if is_namayande10_no_host_room(game):
        from bot.nam10.dayflow import dispatch_nam10_day1_defense_cb

        await dispatch_nam10_day1_defense_cb(callback, bot, game, callback_data)
        return
    assistant_uid = game.bot_assistant_user_id''',
)

# 3) dedicated intro-night cb
failed |= patch(
    "bot/handlers/no_host_player.py",
    '''    if not game or not no_host_bot_assistant_flow_enabled(game):
        await callback.answer("این دکمه برای این اتاق نیست.", show_alert=True)
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        await callback.answer("کمک‌کننده ربات مشخص نیست.", show_alert=True)
        return
    if game_observer_mirror_active(game) and callback.from_user.id != assistant_uid:''',
    '''    if not game or not no_host_bot_assistant_flow_enabled(game):
        await callback.answer("این دکمه برای این اتاق نیست.", show_alert=True)
        return
    from bot.room_mode import is_namayande10_no_host_room

    if is_namayande10_no_host_room(game):
        from bot.nam10.dayflow import dispatch_nam10_intro_night_cb

        await dispatch_nam10_intro_night_cb(callback, bot, game, callback_data)
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        await callback.answer("کمک‌کننده ربات مشخص نیست.", show_alert=True)
        return
    if game_observer_mirror_active(game) and callback.from_user.id != assistant_uid:''',
)

# 4) dev fill button
failed |= patch(
    "bot/handlers/lobby.py",
    '''    if is_no_host_player_room(game):
        err_code = manager.fill_no_host_synthetic_lobby(game)''',
    '''    if is_no_host_player_room(game):
        from bot.room_mode import is_namayande10_no_host_room

        if is_namayande10_no_host_room(game):
            err_code = manager.fill_namayande10_synthetic_lobby(game)
        else:
            err_code = manager.fill_no_host_synthetic_lobby(game)''',
)

# 5) check_winner fork counting
failed |= patch(
    "bot/game.py",
    '''    def check_winner(self, game: Game) -> str | None:
        alive = self.alive_players(game)
        if not alive:
            return None
        mafia_alive = sum(
            1 for p in alive if bazpors_counts_as_alive_mafia_for_win(game, p)
        )''',
    '''    def check_winner(self, game: Game) -> str | None:
        from bot.room_mode import is_namayande10_no_host_room

        alive = self.alive_players(game)
        if not alive:
            return None
        if is_namayande10_no_host_room(game):
            from bot.nam10.engine import nmnd_counts_as_alive_mafia_for_win

            mafia_alive = sum(
                1 for p in alive if nmnd_counts_as_alive_mafia_for_win(game, p)
            )
            if mafia_alive == 0:
                return "شهروندها برنده شدند! 🎉"
            if mafia_alive >= len(alive) - mafia_alive:
                return "مافیا برنده شد! 😈"
            return None
        mafia_alive = sum(
            1 for p in alive if bazpors_counts_as_alive_mafia_for_win(game, p)
        )''',
)

# 6) assistant finalize delegating to the fork day-flow copy
failed |= patch(
    "bot/main.py",
    '''async def finalize_no_host_bot_assistant(
    bot: Bot, game: Game, assistant_uid: int, *, random_pick: bool = True
) -> None:
    if not no_host_bot_assistant_flow_enabled(game):
        return
    game.bot_assistant_user_id = assistant_uid''',
    '''async def finalize_no_host_bot_assistant(
    bot: Bot, game: Game, assistant_uid: int, *, random_pick: bool = True
) -> None:
    if not no_host_bot_assistant_flow_enabled(game):
        return
    from bot.room_mode import is_namayande10_no_host_room

    if is_namayande10_no_host_room(game):
        from bot.nam10.dayflow import (
            finalize_no_host_bot_assistant as _nam10_finalize,
        )

        await _nam10_finalize(bot, game, assistant_uid, random_pick=random_pick)
        return
    game.bot_assistant_user_id = assistant_uid''',
)

print("patch failures" if failed else "all patches applied")
sys.exit(1 if failed else 0)
