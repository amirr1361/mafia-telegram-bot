#!/usr/bin/env python3
"""Phase 3 seam patches (idempotent): production routing for the fork.

- bot/handlers/narrator_cb.py: the shared assistant-panel router delegates
  namayande-10 no-host rooms to the fork copy of the same handler
  (``bot/nam10/nmnd_narrator_cb.py``), before the shared narrator
  authorization gate runs (the shared gate only knows Bazpors state).

The generator (scripts/nam10_fork_transform.py) strips this exact block
before snapshotting, so the fork copy never delegates into itself.
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


failed = False

# 1) shared narrator panel router: route fork rooms to the fork panel copy
NARR_ANCHOR = """    game = manager.get_game(callback_data.code)
    if not game or not narrator_callback_user_may_act(
        game, callback.from_user.id
    ):"""

NARR_SEAM = """    game = manager.get_game(callback_data.code)
    from bot.room_mode import is_namayande10_no_host_room

    if game is not None and is_namayande10_no_host_room(game):
        from bot.nam10.nmnd_narrator_cb import (
            nmnd_narrator_cb as _nam10_narr_cb,
        )

        await _nam10_narr_cb(callback, callback_data, bot)
        return
    if not game or not narrator_callback_user_may_act(
        game, callback.from_user.id
    ):"""

# stale variant from the first generation (entry was later renamed to
# nmnd_narrator_cb by the token rules) — replaced by the current seam
NARR_SEAM_STALE = NARR_SEAM.replace("nmnd_narrator_cb as", "bazpors_narrator_cb as")

_narr_path = ROOT / "bot/handlers/narrator_cb.py"
_narr_text = _narr_path.read_text(encoding="utf-8")
if NARR_SEAM in _narr_text:
    print("  [skip] bot/handlers/narrator_cb.py: branch already present")
elif NARR_SEAM_STALE in _narr_text:
    _narr_text = _narr_text.replace(NARR_SEAM_STALE, NARR_SEAM, 1)
    _narr_path.write_text(_narr_text, encoding="utf-8")
    print("  [ok] bot/handlers/narrator_cb.py (stale seam re-targeted)")
else:
    if NARR_ANCHOR not in _narr_text:
        print("  [FAIL] bot/handlers/narrator_cb.py: anchor not found")
        failed = True
    else:
        _narr_text = _narr_text.replace(NARR_ANCHOR, NARR_SEAM, 1)
        _narr_path.write_text(_narr_text, encoding="utf-8")
        print("  [ok] bot/handlers/narrator_cb.py")

# 2) eliminated-player notifications: fork rooms use the fork report module
failed |= patch(
    "bot/observer_delivery.py",
    """        else:
            from bot.bazpors_elim_report import (
                is_bazpors_elim_report_scenario,
                maybe_send_bazpors_elim_report_invite,
            )""",
    """        else:
            from bot.room_mode import is_namayande10_no_host_room

            if is_namayande10_no_host_room(game):
                from bot.nam10.no_host_elim_report import (
                    maybe_send_nam10_elim_report_invite,
                )

                await maybe_send_nam10_elim_report_invite(bot, game, uid)
                return
            from bot.bazpors_elim_report import (
                is_bazpors_elim_report_scenario,
                maybe_send_bazpors_elim_report_invite,
            )""",
)

# 3) recap snapshot: fork conversions and host mode on fork state
failed |= patch(
    "bot/post_game_flow.py",
    """def build_post_session_recap_snapshot(game: Game, winner: str) -> dict[str, object]:
    rows: list[dict[str, object]] = []""",
    """def build_post_session_recap_snapshot(game: Game, winner: str) -> dict[str, object]:
    from bot.room_mode import is_namayande10_no_host_room

    is_nam10 = is_namayande10_no_host_room(game)
    rows: list[dict[str, object]] = []""",
)
failed |= patch(
    "bot/post_game_flow.py",
    """                "yakuza_converted": p.bazpors_converted_by_yakuza,
                "original_role": (
                    p.bazpors_original_role.value
                    if p.bazpors_original_role
                    else None
                ),""",
    """                "yakuza_converted": (
                    p.nmnd_converted_by_yakuza
                    if is_nam10
                    else p.bazpors_converted_by_yakuza
                ),
                "original_role": (
                    (
                        p.nmnd_original_role.value
                        if p.nmnd_original_role
                        else None
                    )
                    if is_nam10
                    else (
                        p.bazpors_original_role.value
                        if p.bazpors_original_role
                        else None
                    )
                ),""",
)
failed |= patch(
    "bot/post_game_flow.py",
    """        "bazpors_host_mode": game.bazpors_host_mode,
        "rows": rows,
    }""",
    """        "bazpors_host_mode": game.bazpors_host_mode,
        **(
            {"nmnd_host_mode": game.nmnd_host_mode}
            if is_nam10
            else {}
        ),
        "rows": rows,
    }""",
)

# 4) game-end broadcast: fork rooms emit via the fork day-flow builder
_PGF = ROOT / "bot/post_game_flow.py"
_pgf_text = _PGF.read_text(encoding="utf-8")
_stale4 = (
    "        from bot.nam10.dayflow import build_nmnd_game_end_broadcast_html\n"
    "\n"
    "        text_n = build_nmnd_game_end_broadcast_html(game, winner)\n"
)
_fixed4 = (
    "        from bot.nam10.dayflow import build_bazpors_game_end_broadcast_html\n"
    "\n"
    "        text_n = build_bazpors_game_end_broadcast_html(game, winner)\n"
)
if _fixed4 in _pgf_text:
    print("  [skip] bot/post_game_flow.py: fork broadcast export ok")
elif _stale4 in _pgf_text:
    _pgf_text = _pgf_text.replace(_stale4, _fixed4, 1)
    _PGF.write_text(_pgf_text, encoding="utf-8")
    print("  [ok] bot/post_game_flow.py (fork broadcast export retargeted)")
else:
    failed |= patch(
    "bot/post_game_flow.py",
    """    if game.scenario_name not in (
        "bazpors",
        "bazpors_salamat_test",
        "mozakere",
        "masoon",
    ):
        return""",
    """    if game.scenario_name not in (
        "bazpors",
        "bazpors_salamat_test",
        "mozakere",
        "masoon",
    ):
        return""",
    """    from bot.room_mode import is_namayande10_no_host_room

    if is_namayande10_no_host_room(game):
        from bot.nam10.dayflow import build_bazpors_game_end_broadcast_html

        text_n = build_bazpors_game_end_broadcast_html(game, winner)
        for uid_n, p_n in sorted(game.players.items(), key=lambda x: x[0]):
            if p_n.role == Role.OBSERVER:
                continue
            if not p_n.is_alive and not player_should_receive_game_messages(
                game, uid_n
            ):
                continue
            await safe_send_message(bot, uid_n, text_n, parse_mode="HTML")
        return
    if game.scenario_name not in (
        "bazpors",
        "bazpors_salamat_test",
        "mozakere",
        "masoon",
    ):
        return""",
)

# 5) elim-report callback router: fork rooms delegate to the fork module
failed |= patch(
    "bot/bazpors_elim_report.py",
    """    game = manager.get_game(callback_data.code)
    if game is None or not is_bazpors_elim_report_scenario(game):
        await safe_callback_answer(
            callback, "اتاق دیگر فعال نیست.", show_alert=True
        )
        return""",
    """    game = manager.get_game(callback_data.code)
    from bot.room_mode import is_namayande10_no_host_room

    if game is not None and is_namayande10_no_host_room(game):
        from bot.nam10.no_host_elim_report import (
            cb_nam10_elim_report as _nam10_elim_cb,
        )

        await _nam10_elim_cb(callback, bot, callback_data)
        return
    if game is None or not is_bazpors_elim_report_scenario(game):
        await safe_callback_answer(
            callback, "اتاق دیگر فعال نیست.", show_alert=True
        )
        return""",
)

if failed:
    raise SystemExit(1)
print("phase 3 seams applied")
