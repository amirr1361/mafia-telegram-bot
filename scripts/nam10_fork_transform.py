#!/usr/bin/env python3
"""One-time snapshot transform: Bazpors no-host engine -> bot/nam10 fork.

The fork carries an internal identity of ``scenario_name == "namayande"`` with
``nmnd_host_mode == "no_host"`` while every Telegram-facing string stays
"نماینده". Re-running regenerates the package from the current tree.

Namespace rules:
- token  ``bazpors_``  ->  ``nmnd_``   (fields, function names, literals)
- dotted ``.no_host_`` ->  ``.nam10_`` (state field access) and quoted
  string field names, so getattr/setattr dynamic paths stay consistent
- module-to-module imports are remapped into the ``bot.nam10`` package
- shared neutral infra (models, observer_delivery, tg_send, game_audit_log,
  mason/mozakere role modules, data quotes) stays on the original path
"""

from __future__ import annotations

import ast
import re
import shutil
import sys
import pathlib

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
BOT = ROOT / "bot"
DST = BOT / "nam10"

NARRATOR_SRC = "bazpors_narrator.py"
NARRATOR_DST = "nmnd_narrator.py"
GAME_STATE_SRC = "game_state.py"
EXTRA_SRC = {
    "bazpors_detective_inquiry.py": "nmnd_detective_inquiry.py",
    "bazpors_night_panel_purge.py": "nmnd_night_panel_purge.py",
    "bazpors_semi_auto_state.py": "nmnd_semi_auto_state.py",
    "semi_auto_role_pick_common.py": "semi_auto_role_pick_common.py",
}
NO_HOST_SRCS = sorted(p.name for p in BOT.glob("no_host_*.py"))

# ---------------------------------------------------------------------------
# seam strips — the shared files carry fork-routing seams (applied by
# scripts/nam10_phase2_seams.py / nam10_phase3_seams.py). Snapshot copies must
# never contain them or they would recurse into themselves forever.
# Every entry is an exact (seamed, restored) string pair.
# ---------------------------------------------------------------------------
SHARED_SEAM_STRIPS: dict[str, list[tuple[str, str]]] = {}

_PM1 = (
    "    from bot.room_mode import is_namayande10_no_host_room\n"
    "\n"
    "    if is_namayande10_no_host_room(game):\n"
    "        from bot.nam10.player_mirror import dispatch_namayande10_mirror\n"
    "\n"
    "        await dispatch_namayande10_mirror(\n"
    "            callback, bot, game, callback_data=callback_data\n"
    "        )\n"
    "        return\n"
)
_PM2 = (
    "    from bot.room_mode import is_namayande10_no_host_room\n"
    "\n"
    "    if is_namayande10_no_host_room(game):\n"
    "        from bot.nam10.dayflow import dispatch_nam10_day1_defense_cb\n"
    "\n"
    "        await dispatch_nam10_day1_defense_cb(callback, bot, game, callback_data)\n"
    "        return\n"
)
_PM3 = (
    "    from bot.room_mode import is_namayande10_no_host_room\n"
    "\n"
    "    if is_namayande10_no_host_room(game):\n"
    "        from bot.nam10.dayflow import dispatch_nam10_intro_night_cb\n"
    "\n"
    "        await dispatch_nam10_intro_night_cb(callback, bot, game, callback_data)\n"
    "        return\n"
)
_LOBBY = (
    "        from bot.room_mode import is_namayande10_no_host_room\n"
    "\n"
    "        if is_namayande10_no_host_room(game):\n"
    "            err_code = manager.fill_namayande10_synthetic_lobby(game)\n"
    "        else:\n"
    "            err_code = manager.fill_no_host_synthetic_lobby(game)\n"
)
_CHECK_WINNER = (
    "        from bot.room_mode import is_namayande10_no_host_room\n"
    "\n"
    "        alive = self.alive_players(game)\n"
    "        if not alive:\n"
    "            return None\n"
    "        if is_namayande10_no_host_room(game):\n"
    "            from bot.nam10.engine import nmnd_counts_as_alive_mafia_for_win\n"
    "\n"
    "            mafia_alive = sum(\n"
    "                1 for p in alive if nmnd_counts_as_alive_mafia_for_win(game, p)\n"
    "            )\n"
    "            if mafia_alive == 0:\n"
    '                return "شهروندها برنده شدند! 🎉"\n'
    "            if mafia_alive >= len(alive) - mafia_alive:\n"
    '                return "مافیا برنده شد! 😈"\n'
    "            return None\n"
)
_FINALIZE = (
    "    from bot.room_mode import is_namayande10_no_host_room\n"
    "\n"
    "    if is_namayande10_no_host_room(game):\n"
    "        from bot.nam10.dayflow import (\n"
    "            finalize_no_host_bot_assistant as _nam10_finalize,\n"
    "        )\n"
    "\n"
    "        await _nam10_finalize(bot, game, assistant_uid, random_pick=random_pick)\n"
    "        return\n"
)
_NARR = (
    "    from bot.room_mode import is_namayande10_no_host_room\n"
    "\n"
    "    if game is not None and is_namayande10_no_host_room(game):\n"
    "        from bot.nam10.nmnd_narrator_cb import (\n"
    "            nmnd_narrator_cb as _nam10_narr_cb,\n"
    "        )\n"
    "\n"
    "        await _nam10_narr_cb(callback, callback_data, bot)\n"
    "        return\n"
)

SHARED_SEAM_STRIPS["bot/handlers/no_host_player.py"] = [
    ("\n" + _PM1, "\n"),
    ("\n" + _PM2, "\n"),
    ("\n" + _PM3, "\n"),
]
SHARED_SEAM_STRIPS["bot/handlers/lobby.py"] = [("\n" + _LOBBY, "\n")]
SHARED_SEAM_STRIPS["bot/game.py"] = [
    (
        "\n" + _CHECK_WINNER,
        "\n        mafia_alive = sum(\n",
    ),
]
SHARED_SEAM_STRIPS["bot/main.py"] = [("\n" + _FINALIZE, "\n")]
SHARED_SEAM_STRIPS["bot/handlers/narrator_cb.py"] = [("\n" + _NARR, "\n")]
_ELIM = (
    "    from bot.room_mode import is_namayande10_no_host_room\n"
    "\n"
    "    if game is not None and is_namayande10_no_host_room(game):\n"
    "        from bot.nam10.no_host_elim_report import (\n"
    "            cb_nam10_elim_report as _nam10_elim_cb,\n"
    "        )\n"
    "\n"
    "        await _nam10_elim_cb(callback, bot, callback_data)\n"
    "        return\n"
)
SHARED_SEAM_STRIPS["bot/bazpors_elim_report.py"] = [("\n" + _ELIM, "\n")]


def shared_source(relpath: str) -> str:
    """Read a shared source file with all fork-routing seams stripped.

    This yields the pristine shared implementation so snapshot copies and
    day-flow extractions never inherit through-fork branches.
    """
    text = (ROOT / relpath).read_text(encoding="utf-8")
    for seam, restored in SHARED_SEAM_STRIPS.get(relpath, []):
        text = text.replace(seam, restored)
    return text

FORK_ROLES = [
    "detective", "doctor", "sniper", "shiad", "hunter", "mafia_boss",
    "nato", "interrogator", "ruintan", "simple_citizen", "simple_mafia",
    "night_state", "doctor_alive_save_capacity",
]
REGISTRY_SRC = "registry.py"
REGISTRY_DST = "role_registry.py"

KEEP_MODULES = {
    "bot.data.no_host_sage_quotes",
    "bot.game_audit_log",
    "bot.models",
    "bot.observer_delivery",
    "bot.tg_send",
    "bot.post_game_flow",
    "bot.mason_chaos",
    "bot.chaos_handshake",
    "bot.mason_force_finish_night",
    "bot.mason_game_flow",
    "bot.mason_helper_flow",
    "bot.mason_night_entry",
    "bot.mason_night_ready",
    "bot.mason_night_report",
    "bot.mason_night_resolve",
    "bot.mason_night_role",
    "bot.mason_responsibilities",
}


def tokens(s: str) -> str:
    # scenario literal: the fork's own identity
    s = s.replace('"bazpors"', '"namayande"').replace("'bazpors'", "'namayande'")
    # bazpors_* token -> nmnd_* (fields, helpers, string field names)
    s = re.sub(r"\bbazpors_([a-z0-9_]+)", r"nmnd_\1", s)
    # bare no_host_* EVERYWHERE (defs, calls, quoted names) -> nam10_* so
    # night_state property defs stay consistent with renamed accesses;
    # same-package module paths and external import statements are shielded.
    s = re.sub(r"\bno_host_([a-z0-9_]+)", r"nam10_\1", s)
    return s


FORK_ROLE_PATHS = {r for r in FORK_ROLES} | {"night_state", "registry"}


def _shield_external_imports(s: str) -> tuple[str, list[str]]:
    """Protect import statements from modules OUTSIDE the copy set, including
    their imported names, from the token rules."""
    lines = s.splitlines(keepends=True)
    stashed: list[str] = []
    out: list[str] = []
    i = 0
    pat = re.compile(r"^(\s*)(from|import) bot\.(?!nam10\b)[a-z_0-9.]")
    while i < len(lines):
        line = lines[i]
        if pat.match(line):
            block = [line]
            if "(" in line and ")" not in line:
                j = i + 1
                while j < len(lines):
                    block.append(lines[j])
                    if ")" in lines[j]:
                        break
                    j += 1
                i = j
            ph = f"KEEPLINE{len(stashed)}::"
            stashed.append("".join(block))
            out.append(ph + "\n")
        else:
            out.append(line)
        i += 1
    return "".join(out), stashed


def _unshield_external_imports(s: str, stashed: list[str]) -> str:
    for idx, orig in enumerate(stashed):
        s = s.replace(f"KEEPLINE{idx}::\n", orig)
    return s


def realias_imports(s: str) -> str:
    """For external imports whose body references the fork-renamed name, add
    ``orig as renamed`` aliases so call/resolution stays consistent."""
    lines = s.splitlines(keepends=True)
    pat = re.compile(r"^(\s*from bot\.(?!nam10\b)[a-z_0-9.]+ import )")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = pat.match(line)
        if not m:
            out.append(line)
            i += 1
            continue
        block = [line]
        if "(" in line and ")" not in line:
            j = i + 1
            while j < len(lines):
                block.append(lines[j])
                if ")" in lines[j]:
                    break
                j += 1
            i = j + 1
        else:
            i += 1
        blob_start = block[0].find("import ") + len("import ")
        blob = "".join(block)[blob_start:]
        paren = "(" in blob.split("\n")[0]
        names: list[str] = []
        for tok in blob.replace("\n", " ").split(","):
            tok = tok.strip().strip("()").strip()
            if tok:
                names.append(tok)
        aliases_written: list[str] = []

        def renamed_of(name: str) -> str | None:
            if name.startswith("no_host_"):
                cand = "nam10_" + name[len("no_host_"):]
            elif name.startswith("bazpors_"):
                cand = "nmnd_" + name[len("bazpors_"):]
            else:
                return None
            if re.search(rf"\b{re.escape(cand)}\b", s):
                return cand
            return None

        new_items: list[str] = []
        for name in names:
            if " as " in name:
                new_items.append(name)
                continue
            cand = renamed_of(name)
            if cand:
                new_items.append(f"{name} as {cand}")
                aliases_written.append(f"{name} as {cand}")
            else:
                new_items.append(name)
        if parentheses_balanced(blob) or not paren:
            if aliases_written and paren:
                head = "".join(block)[0:blob_start] + "(\n"
                body = "".join(f"    {t},\n" for t in new_items)
                tail = ")\n"
                out.append(head + body + tail)
            elif aliases_written:
                out.append(
                    "".join(block)[0:blob_start]
                    + ", ".join(new_items)
                    + "\n"
                )
            else:
                out.extend(block)
        else:
            out.extend(block)
    return "".join(out)


def parentheses_balanced(blob: str) -> bool:
    return blob.count("(") == blob.count(")")


def remap_imports(s: str, *, remap_engine_room_mode: bool = True) -> str:
    # 1a) shield bot.roles.<submodule> attribute paths of forked modules
    role_plh: dict[str, str] = {}

    def _shield_role(m: "re.Match[str]") -> str:
        name = m.group(1)
        if name == "night_state":
            dst = "roles_night_state"
        elif name == "registry":
            dst = "role_registry"
        else:
            dst = f"roles_{name}"
        key = f"ROLEPATHu92::{len(role_plh):x}u92"
        role_plh[key] = dst
        return f"bot.{key}"

    s = re.sub(
        r"\bbot\.roles\.(night_state|registry|doctor_alive_save_capacity"
        r"|detective|doctor|sniper|shiad|hunter|mafia_boss|nato"
        r"|interrogator|ruintan|simple_citizen|simple_mafia)\b",
        _shield_role,
        s,
    )

    # 1b) shield module paths with token-free placeholders
    plh: dict[str, str] = {}

    def _shield_path(m: re.Match) -> str:
        orig = m.group(1)
        key = f"NAM10PATH::{len(plh):x}u92"
        plh[key] = orig
        return f"bot.{key}"

    s = re.sub(r"\bbot\.(no_host_[a-z_0-9]+)", _shield_path, s)
    s = s.replace("bot.bazpors_narrator", "bot.NARRPATH")
    s = re.sub(r"\bbot\.(bazpors_(?:detective_inquiry|night_panel_purge|semi_auto_state))\b", _shield_path, s)
    s = re.sub(r"\bbot\.(?:semi_auto_role_pick_common|game_state)\b",
               lambda m: "bot." + ("SEMIPTH" if m.group(0).endswith("role_pick_common") else "GSTPATH"), s)

    # 1b) shield import statements from external modules (names + paths)
    s, stashed = _shield_external_imports(s)

    # 2) token rules cannot touch protected paths/statements
    s = tokens(s)

    # 3) deploy placeholders into the fork package
    dst_overrides = {
        "bazpors_detective_inquiry": "nmnd_detective_inquiry",
        "bazpors_night_panel_purge": "nmnd_night_panel_purge",
        "bazpors_semi_auto_state": "nmnd_semi_auto_state",
    }
    for key, orig in plh.items():
        dst = dst_overrides.get(orig, orig)
        s = s.replace(f"bot.{key}", f"bot.nam10.{dst}")
    s = re.sub(r"\bbot\.NARRPATH\b", "bot.nam10.nmnd_narrator", s)
    for key, dst in role_plh.items():
        s = s.replace(f"bot.{key}", f"bot.nam10.{dst}")
    s = re.sub(r"\bbot\.SEMIPTH\b", "bot.nam10.semi_auto_role_pick_common", s)
    s = re.sub(r"\bbot\.GSTPATH\b", "bot.nam10.game_state", s)
    s = _unshield_external_imports(s, stashed)
    s = realias_imports(s)

    # 4) single-name / as-forms of role module imports by membership
    for role in FORK_ROLES:
        s = re.sub(rf"\bfrom bot\.roles import {role}\b", f"from bot.nam10 import roles_{role}", s)
        s = re.sub(rf"\bfrom bot\.roles import {role} as", f"from bot.nam10 import roles_{role} as", s)

    # 5) game/room_mode go through fork shim modules
    s = re.sub(r"\bfrom bot\.nam10\.engine import", "from bot.nam10.engine import", s)
    if remap_engine_room_mode:
        s = re.sub(r"\bfrom bot\.game import", "from bot.nam10.engine import", s)
        s = re.sub(r"\bfrom bot\.room_mode import", "from bot.nam10.mode import", s)
    # fork copies delegate the day-flow panel driver to the fork dayflow
    s = s.replace(
        "from bot.main import send_no_host_day1_defense_pick_panel",
        "from bot.nam10.dayflow import send_no_host_day1_defense_pick_panel",
    )
    return s


def transform(s: str) -> str:
    return remap_imports(s)


def transform_fragment(s: str, variant: str) -> str:
    """Fragment-level transform (dayflow defs / handler copy)."""
    return remap_imports(s, remap_engine_room_mode=(variant == "copy"))


# ---------------------------------------------------------------------------
# bot/nam10/dayflow.py — extraction closure of main.py's no-host day drivers
# ---------------------------------------------------------------------------

DAYFLOW_SEEDS = [
    "build_no_host_intro_night_start_html",
    "build_bazpors_game_end_broadcast_html",
    "build_no_host_intro_night_confirm_html",
    "intro_night_start_keyboard_for",
    "intro_night_confirm_keyboard_for",
    "build_no_host_intro_night_civilian_html",
    "build_no_host_intro_night_mafia_dm_html",
    "deliver_no_host_intro_night_started_messages",
    "send_no_host_intro_night_start_prompt",
    "_refresh_intro_night_prompt_panel",
    "_handle_no_host_intro_night_action",
    "_execute_no_host_intro_night_start",
    "day1_vote_choice_keyboard_for",
    "send_no_host_day1_vote_prompt",
    "build_no_host_day1_defense_no_exit_broadcast_html",
    "build_no_host_day1_no_defense_votes_broadcast_html",
    "build_no_host_day1_skip_vote_broadcast_html",
    "_process_no_host_day1_skip_night",
    "_process_no_host_day1_show_vote_panel",
    "_no_host_day1_defense_pick_ui_key",
    "_no_host_day1_defense_outcome_ui_key",
    "_no_host_day1_pick_elim_ui_key",
    "_no_host_day1_confirm_elim_ui_key",
    "_day1_defense_pool_players",
    "_alive_players_sorted",
    "_no_host_day1_defense_actor_may_act",
    "build_no_host_day1_defense_pick_html",
    "_no_host_day1_defense_pick_keyboard",
    "day1_defense_pick_keyboard_for",
    "send_no_host_day1_defense_pick_panel",
    "refresh_no_host_day1_defense_pick_panel",
    "build_no_host_day1_defense_outcome_html",
    "_dispatch_no_host_day1_defense_act",
    "finalize_no_host_bot_assistant",
    "send_no_host_bot_assistant_prompt",
    "no_host_maybe_end_on_faction_win",
]

DAYFLOW_BLOCKED = {
    "broadcast_game",
    "apply_mirror_claim_winner",
    "try_claim_mirror_ui",
    "update_mirror_prompt_pair",
    "publish_mirror_prompt_pair",
    "promote_mirror_prompt_to_panel",
    "broadcast_to_alive_players",
    "broadcast_to_players",
    "gather_bounded",
    "safe_send_message",
    "send_to_player",
    "safe_callback_answer",
    "safe_edit_text",
    "ensure_private_role_card_delivered",
    "send_private_role",
    "finalize_game_winner",
    "notify_initiator_winner_keyboard",
    "broadcast_player_end_vote_started",
    "game_observer_mirror_active",
    "mirror_ui_claim_key",
    "unpack_player_mirror_cb",
    "_answer_mirror_claim",
    "_player_end_dismiss_message",
    "_process_player_end_approve",
}

DAYFLOW_NAME_RE = re.compile(
    r"^(no_host_|_no_host_|build_no_host_|day1_|intro_night_"
    r"|_refresh_intro|deliver_no_host|send_no_host|finalize_no_host"
    r"|_process_no_host|_dispatch_no_host|_execute_no_host|_alive_players)"
)

# Hand-written fork seam drivers, appended to dayflow.py. They mirror the
# shared aiogram callbacks in handlers/no_host_player.py but gate on the
# nam10_* fork state so fork rooms never touch shared no-host flags.
DAYFLOW_TAIL = '''

# ---------------------------------------------------------------------------
# Fork callback drivers (hand-written fork seam; mirrors the shared aiogram
# callbacks while reading/writing nam10_* fork state only).
# ---------------------------------------------------------------------------


async def dispatch_nam10_day1_defense_cb(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    callback_data,
) -> None:
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        await callback.answer("این دکمه برای این اتاق نیست.", show_alert=True)
        return
    assistant_uid = game.bot_assistant_user_id

    def _audit_reject(reason: str) -> None:
        try:
            from bot.game_audit_log import log_no_host_day1_defense_callback

            log_no_host_day1_defense_callback(
                game,
                act=callback_data.act,
                actor_uid=callback.from_user.id,
                assistant_uid=assistant_uid,
                source="nhd",
                target_uid=callback_data.tid or None,
                outcome="rejected",
                reject_reason=reason,
            )
        except Exception:
            pass

    if game_observer_mirror_active(game):
        _audit_reject("mirror_use_pmr")
        await callback.answer(
            "از دکمهٔ همان پیام خودتان (یا نسخهٔ ناظر) استفاده کنید.",
            show_alert=True,
        )
        return
    if assistant_uid is None:
        _audit_reject("no_assistant")
        await callback.answer("کمک‌کننده ربات مشخص نیست.", show_alert=True)
        return
    if not game.nam10_day1_defense_active:
        _audit_reject("defense_inactive")
        await callback.answer("پنل دفاعیه فعال نیست.", show_alert=True)
        return
    await _dispatch_no_host_day1_defense_act(
        callback,
        bot,
        game,
        assistant_uid,
        callback.from_user.id,
        callback_data.act,
        tid=callback_data.tid,
        source="nhd",
    )


async def dispatch_nam10_intro_night_cb(
    callback: CallbackQuery,
    bot: Bot,
    game: Game,
    callback_data,
) -> None:
    from bot.room_mode import is_namayande10_no_host_room

    if not is_namayande10_no_host_room(game):
        await callback.answer("این دکمه برای این اتاق نیست.", show_alert=True)
        return
    assistant_uid = game.bot_assistant_user_id
    if assistant_uid is None:
        await callback.answer("کمک‌کننده ربات مشخص نیست.", show_alert=True)
        return
    if game_observer_mirror_active(game) and callback.from_user.id != assistant_uid:
        await callback.answer(
            "از دکمهٔ همان پیام خودتان (یا نسخهٔ ناظر) استفاده کنید.",
            show_alert=True,
        )
        return
    if callback.from_user.id != assistant_uid:
        await callback.answer("فقط کمک‌کننده ربات.", show_alert=True)
        return
    await _handle_no_host_intro_night_action(
        callback,
        bot,
        game,
        assistant_uid,
        callback.from_user.id,
        callback_data.act,
    )
'''

DAYFLOW_HEADER = '''"""Fork day-flow drivers — extracted closure of main.py no-host drivers.

Independent of the Bazpors day1-defense / day-vote / intro-night flows: all
state reads/writes go through the ``nam10_*`` / ``nmnd_*`` fork fields, and
no-host module helpers resolve inside ``bot.nam10``.
"""

from __future__ import annotations

import html
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from bot.app_state import manager
from bot.models import Game, Phase, Player, Role
from bot.text_fa import fa_digits as _fa_digits
'''


def _names_used(src: str) -> set[str]:
    """Free (loaded, non-local) names of a top-level function source."""
    try:
        mod = ast.parse(src)
    except SyntaxError:
        return set()
    bound: set[str] = set()
    func = mod.body[0] if mod.body else None
    if isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
        a = func.args
        for arg in a.posonlyargs + list(a.args) + list(a.kwonlyargs):
            bound.add(arg.arg)
        for extra in (a.vararg, a.kwarg):
            if extra is not None:
                bound.add(extra.arg)
    for node in ast.walk(mod):
        if isinstance(node, ast.Name) and not isinstance(
            node.ctx, ast.Load
        ):
            bound.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ) and node is not mod.body[0]:
            # nested def/class: local binding in the enclosing scope
            bound.add(node.name)
        elif isinstance(node, ast.Lambda):
            la = node.args
            for arg in la.posonlyargs + list(la.args) + list(la.kwonlyargs):
                bound.add(arg.arg)
            for extra in (la.vararg, la.kwarg):
                if extra is not None:
                    bound.add(extra.arg)
        elif isinstance(node, ast.comprehension):
            bound |= {
                n.id
                for n in ast.walk(node.target)
                if isinstance(n, ast.Name)
            }
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound.add(alias.asname or alias.name.split(".")[0])
    loaded = {
        n.id
        for n in ast.walk(mod)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    }
    return loaded - bound


def _main_defs_index(lines: list[str]):
    tree = ast.parse("\n".join(lines))
    segs: dict[str, tuple[int, int]] = {}
    order: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name not in segs:
                segs[node.name] = (node.lineno, node.end_lineno)
                order.append(node.name)
    return segs, order


FORK_MODULE_MAP = {
    "bot.bazpors_narrator": "bot.nam10.nmnd_narrator",
    "bot.game_state": "bot.nam10.game_state",
    "bot.semi_auto_role_pick_common": "bot.nam10.semi_auto_role_pick_common",
}


def _fork_module_for(mod: str) -> str | None:
    if mod.startswith("bot.no_host_"):
        return "bot.nam10." + mod[len("bot."):]
    return FORK_MODULE_MAP.get(mod)


def _main_name_sources(lines: list[str]) -> dict[str, str]:
    """column-0 import statements of main.py: imported name -> source module."""
    src = "\n".join(lines)
    sources: dict[str, str] = {}
    pat = re.compile(
        r"^from bot\.([a-z_0-9.]+) import ?(?:\(([^)]*)\)|([^#\n]+))",
        flags=re.M,
    )
    for m in pat.finditer(src):
        mod = "bot." + m.group(1)
        blob = m.group(2) if m.group(2) is not None else m.group(3)
        for n in blob.replace("\n", " ").split(","):
            n = n.strip().rstrip(",")
            if not n:
                continue
            alias = n
            if " as " in n:
                alias = n.split(" as ", 1)[1].strip()
            sources.setdefault(alias, mod)
    return sources


def generate_dayflow_text() -> tuple[str, list[str]]:
    lines = shared_source("bot/main.py").splitlines()
    segs, _order = _main_defs_index(lines)

    extracted: list[str] = []
    got: set[str] = set()
    pending = list(DAYFLOW_SEEDS)
    while pending:
        name = pending.pop()
        if name in got:
            continue
        if name in DAYFLOW_BLOCKED or name not in segs:
            continue
        got.add(name)
        extracted.append(name)
        seg_src = "\n".join(lines[segs[name][0] - 1 : segs[name][1]])
        for used in sorted(_names_used(seg_src)):
            if used not in segs or used in got:
                continue
            if used in DAYFLOW_BLOCKED:
                continue
            if used in DAYFLOW_SEEDS or DAYFLOW_NAME_RE.match(used):
                pending.append(used)

    # emit definitions, transformed; free names computed on transformed text
    parts: list[str] = []
    for name in extracted:
        seg_src = "\n".join(lines[segs[name][0] - 1 : segs[name][1]])
        parts.append(transform_fragment(seg_src, "dayflow"))

    def_names: set[str] = set()
    for part in parts:
        m = re.search(r"^(?:async )?def ([A-Za-z_0-9]+)\(", part, flags=re.M)
        if m:
            def_names.add(m.group(1))

    import builtins

    builtin_names = set(dir(builtins))
    header_names = {
        "html", "logging", "Bot", "CallbackQuery", "Message",
        "InlineKeyboardButton", "InlineKeyboardMarkup", "TelegramBadRequest",
        "manager", "Game", "Phase", "Player", "Role", "_fa_digits",
    }
    used: set[str] = set()
    for part in parts:
        used |= _names_used(part)
    free = used - def_names - builtin_names - header_names

    sources = _main_name_sources(lines)

    def orig_name_for(n: str) -> str | None:
        if n.startswith("nam10_"):
            return "no_host_" + n[len("nam10_"):]
        if n.startswith("nmnd_"):
            return "bazpors_" + n[len("nmnd_"):]
        return None

    def src_module_for(n: str) -> str:
        cands = [n]
        orig = orig_name_for(n)
        if orig:
            cands.append(orig)
        for c in cands:
            if c in sources:
                return sources[c]
        return "bot.main"

    per_module: dict[str, list[tuple[str, str | None]]] = {}
    main_names: list[str] = []
    for n in sorted(free):
        mod = src_module_for(n)
        orig = orig_name_for(n)
        forkmod = _fork_module_for(mod)
        if forkmod is not None:
            per_module.setdefault(forkmod, []).append((n, None))
        elif mod == "bot.main":
            main_names.append(n)
        elif orig and orig in sources:
            # shared module exposing the original name: alias to the
            # fork-renamed name used inside the transformed defs.
            per_module.setdefault(mod, []).append((orig, n))
        else:
            per_module.setdefault(mod, []).append((n, None))

    head_parts = [DAYFLOW_HEADER]
    for mod in sorted(per_module):
        body = []
        for orig, alias in sorted(per_module[mod]):
            body.append(
                f"    {orig}" + (f" as {alias}," if alias else ",")
            )
        head_parts.append(
            f"from {mod} import (\n" + "\n".join(body) + "\n)\n"
        )
    if main_names:
        head_parts.append(
            "from bot.main import (\n"
            + "".join(f"    {n},\n" for n in main_names)
            + ")\n"
        )
    head = "\n\n".join(head_parts) + "\n\n\n"
    print("  dayflow exports:", len(def_names), "defs")
    for mod in sorted(per_module):
        print(
            f"    {mod}: "
            + " ".join(
                o + (f" as {a}" if a else "") for o, a in sorted(per_module[mod])
            )
        )
    print("    bot.main:", " ".join(main_names))
    return head + "\n\n".join(parts) + "\n" + DAYFLOW_TAIL, list(def_names)


def generate_player_mirror_text(dayflow_names: list[str]) -> str:
    src = shared_source("bot/handlers/no_host_player.py")
    # strip the original module docstring + first __future__ line:
    # the fork module has its own header and future import.
    src = re.sub(
        r'^""".*?"""\n', "", src, count=1, flags=re.DOTALL
    )
    src = src.replace(
        "from __future__ import annotations\n", "", 1
    )
    text = transform_fragment(src, "player_mirror")
    dfn = set(dayflow_names)

    m = re.search(r"from bot\.main import \((.*?)\n\)\n", text, flags=re.S)
    if m:
        raw = m.group(1)
        names = [
            n.strip().rstrip(",")
            for n in raw.replace("\n", " ").split(",")
            if n.strip()
        ]
        from_df = [n for n in names if n in dfn]
        rest = [n for n in names if n not in dfn]
        block = "from bot.main import (\n" + "".join(
            f"    {n},\n" for n in rest
        ) + ")\n\nfrom bot.nam10.dayflow import (\n" + "".join(
            f"    {n},\n" for n in from_df
        ) + ")\n"
        text = text[: m.start()] + block + text[m.end():]
        print(
            "  player_mirror: main->dayflow redirect:",
            ", ".join(from_df) or "(none)",
        )
    else:
        print("  player_mirror: no bot.main import block found")

    # model import for the wrapper annotation if missing
    if "from bot.models import" not in text:
        text = text.replace(
            "from bot.app_state import manager",
            "from bot.app_state import manager\nfrom bot.models import Game",
        )

    # neutralise accidental handler registration
    text = text.replace(
        "def register_no_host_player_handlers(dp) -> None:",
        "def _unused_fork_register_no_host_player_handlers(dp) -> None:",
    )

    # append the dispatch wrapper from the body of player_mirror_cb
    lines = text.splitlines(keepends=True)
    start = None
    for i, ln in enumerate(lines):
        if ln.strip() == "actor = callback.from_user.id":
            start = i
            break
    assert start is not None, "player_mirror_cb body marker not found"
    body = "".join(lines[start:])
    wrapper = (
        "\n\nasync def dispatch_namayande10_mirror(\n"
        "    callback: CallbackQuery,\n"
        "    bot: Bot,\n"
        "    game: Game,\n"
        "    *,\n"
        "    callback_data,\n"
        ") -> None:\n"
        + body
    )
    header = (
        '"""Fork mirror-dispatch engine (snapshot of no_host_player router).\n'
        "\n"
        "Registered aiogram handlers in this module are unused; the shared\n"
        "`player_mirror_cb` routes fork rooms here via dispatch_namayande10_mirror.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
    )
    return header + text + wrapper


def generate_elim_report_text() -> str:
    """Fork snapshot of ``bot/bazpors_elim_report.py`` (mid-game elim report).

    The scenario predicate is replaced by the fork-mode check (classic
    namayande rooms must never receive fork reports), the registration is
    neutralised, and Bazpors-qualified external names are re-labelled for
    the fork context.
    """
    src = (BOT / "bazpors_elim_report.py").read_text(encoding="utf-8")
    text = transform(src)
    renames = {
        "is_bazpors_elim_report_scenario": "is_fork_elim_report_scenario",
        "maybe_send_bazpors_elim_report_invite": "maybe_send_nam10_elim_report_invite",
        "build_bazpors_elim_cutoff_report_html": "build_nam10_elim_cutoff_report_html",
        "capture_bazpors_elim_report_cutoff": "capture_nam10_elim_report_cutoff",
        "send_bazpors_elim_report_invitation": "send_nam10_elim_report_invitation",
        "resolve_bazpors_elim_report_html": "resolve_nam10_elim_report_html",
        "deliver_bazpors_elim_report_chunks": "deliver_nam10_elim_report_chunks",
        "handle_bazpors_elim_report_callback": "handle_nam10_elim_report_callback",
        "cb_bazpors_elim_report": "cb_nam10_elim_report",
        "register_bazpors_elim_report_handlers": "_unused_fork_register_nam10_elim_report_handlers",
        "BAZPORS_ELIM_REPORT_INVITE_HTML": "NAM10_ELIM_REPORT_INVITE_HTML",
        "BAZPORS_ELIM_REPORT_BUTTON_TEXT": "NAM10_ELIM_REPORT_BUTTON_TEXT",
    }
    for old, new in renames.items():
        text = re.sub(rf"\b{old}\b", new, text)
    # fork predicate: classic namayande rooms must not receive fork reports
    text = text.replace(
        'return game.scenario_name in ("namayande", "bazpors_salamat_test")',
        "return is_namayande10_no_host_room(game)",
    )
    if "from bot.room_mode import is_namayande10_no_host_room" not in text:
        text = text.replace(
            "from bot.game import is_synthetic_player_uid",
            "from bot.game import is_synthetic_player_uid\n"
            "from bot.room_mode import is_namayande10_no_host_room",
        )
    return text


def generate_narrator_cb_text(dayflow_names: list[str]) -> str:
    """Fork snapshot of ``bot/handlers/narrator_cb.py`` (assistant panel router).

    The whole module is remapped like a scenario copy: shared narrator
    helpers resolve from ``bot.nam10.nmnd_narrator``, no-host drivers from
    the fork copies, day-flow names from ``bot.nam10.dayflow``. Aiogram
    registration is neutralised; the shared router delegates fork rooms to
    ``bazpors_narrator_cb`` here.
    """
    src = shared_source("bot/handlers/narrator_cb.py")
    src = re.sub(r'^""".*?"""\n', "", src, count=1, flags=re.DOTALL)
    src = src.replace("from __future__ import annotations\n", "", 1)
    text = transform_fragment(src, "narrator_cb")
    dfn = set(dayflow_names)

    m = re.search(r"from bot\.main import \((.*?)\n\)\n", text, flags=re.S)
    if m:
        raw = m.group(1)
        names = [
            n.strip().rstrip(",")
            for n in raw.replace("\n", " ").split(",")
            if n.strip()
        ]
        from_df = [n for n in names if n in dfn]
        rest = [n for n in names if n not in dfn]
        block = "from bot.main import (\n" + "".join(
            f"    {n},\n" for n in rest
        ) + ")\n\nfrom bot.nam10.dayflow import (\n" + "".join(
            f"    {n},\n" for n in from_df
        ) + ")\n"
        text = text[: m.start()] + block + text[m.end():]
        print(
            "  narrator_cb: main->dayflow redirect:",
            ", ".join(from_df) or "(none)",
        )
    else:
        print("  narrator_cb: no bot.main import block found")

    def _fix_lazy_main(m: re.Match) -> str:
        blob = m.group(1).strip()
        return (
            f"from bot.nam10.dayflow import {blob}"
            if blob in dfn
            else m.group(0)
        )

    text = re.sub(r"from bot\.main import ([A-Za-z_][A-Za-z_0-9]*)", _fix_lazy_main, text)

    text = text.replace(
        "def register_narrator_cb_handlers(dp: Dispatcher) -> None:",
        "def _unused_fork_register_narrator_cb_handlers(dp: Dispatcher) -> None:",
    )

    text = text.replace(
        'router = Router(name="narrator_cb")',
        'router = Router(name="nam10_narrator_cb_unused")',
    )

    # strip the router seam the shared file carries so the fork copy never
    # delegates into itself (mirrors scripts/nam10_phase3_seams.py block 1)
    text = text.replace(
        """    from bot.room_mode import is_namayande10_no_host_room

    if game is not None and is_namayande10_no_host_room(game):
        from bot.nam10.nmnd_narrator_cb import (
            nmnd_narrator_cb as _nam10_narr_cb,
        )

        await _nam10_narr_cb(callback, callback_data, bot)
        return
    if not game or not narrator_callback_user_may_act(""",
        "    if not game or not narrator_callback_user_may_act(",
    )

    header = (
        '"""Fork narrator-panel router (snapshot of handlers/narrator_cb.py).\n'
        "\n"
        "Registered aiogram handlers in this module are unused; the shared\n"
        "`bazpors_narrator_cb` routes namayande-10 rooms to the fork copy\n"
        "of the same function here.\n"
        '"""\n'
        "\n"
        "from __future__ import annotations\n"
    )
    return header + text


ENGINE_PY = '''"""Fork engine shim — neutral re-exports plus fork-scoped helpers.

Copies of the Bazpors engine helpers whose semantics must live on the fork
state namespace (``nmnd_*`` fields) are defined here; shared-neutral names
are transparent re-exports.
"""

from __future__ import annotations

from bot.game import (
    GameManager,  # noqa: F401
    _digits_fa,  # noqa: F401
    is_mafia_team,  # noqa: F401
    is_synthetic_player_uid,  # noqa: F401
    role_label_fa,  # noqa: F401
    synthetic_player_base_name,  # noqa: F401
)
from bot.models import Game, Player, Role


def nmnd_counts_as_mafia_faction(game: Game, p: Player) -> bool:
    """Mafia-faction identity on fork state (reports / table inquiry / sniper)."""
    if game.scenario_name != "namayande":
        return is_mafia_team(p.role)
    if p.user_id in game.nmnd_mafia_recruit_ids:
        return True
    return is_mafia_team(p.role)


def nmnd_counts_as_alive_mafia_for_win(game: Game, p: Player) -> bool:
    """Alive mafia (or yakuza-converted) for win checks; sniper victims never count."""
    if not p.is_alive:
        return False
    if p.user_id in game.nmnd_sniper_eliminated_uids:
        return False
    return nmnd_counts_as_mafia_faction(game, p)


def apply_bazpors_yakuzai_recruit(game: Game, p: Player) -> None:
    """Successful yakuza recruit (fork name kept for copy-import compatibility)."""
    if p.user_id in game.nmnd_sniper_eliminated_uids:
        return
    if p.nmnd_original_role is None:
        p.nmnd_original_role = p.role
    p.nmnd_converted_by_yakuza = True
    game.nmnd_mafia_recruit_ids.add(p.user_id)
    p.role = Role.MAFIA_BASIC
    game.mafia_ids.add(p.user_id)


def mark_bazpors_eliminated_by_sniper(game: Game, uid: int) -> None:
    """Successful sniper elimination (fork name kept for copy-import compatibility)."""
    if game.scenario_name != "namayande":
        return
    game.nmnd_sniper_eliminated_uids.add(uid)
    game.mafia_ids.discard(uid)
    game.nmnd_mafia_recruit_ids.discard(uid)


# Import-compat aliases: copies keep the original helper names.
bazpors_counts_as_mafia_faction = nmnd_counts_as_mafia_faction
bazpors_counts_as_alive_mafia_for_win = nmnd_counts_as_alive_mafia_for_win
'''

SHIMS = {
    "lobby.py": '''"""Fork lobby/role-deal helpers (snapshot of Bazpors 10-player no-host)."""

from __future__ import annotations

import random

from bot.game import is_mafia_team
from bot.models import Game, Role


def roles_for_count(n: int) -> list[Role]:
    """Fork ships the 10-player Bazpors snapshot composition only."""
    if n != 10:
        raise ValueError("namayande-10 fork supports exactly 10 players")
    return [
        Role.MAFIA_BOSS,
        Role.NATO,
        Role.SHIAD,
        Role.HUNTER,
        Role.INTERROGATOR,
        Role.DETECTIVE,
        Role.DOCTOR,
        Role.RUINTAN,
        Role.CITIZEN,
        Role.CITIZEN,
    ]


def assign_roles_namayande10(game: Game) -> None:
    n = len(game.players)
    roles = roles_for_count(n)
    player_ids = list(game.players.keys())
    random.shuffle(player_ids)
    game.mafia_ids.clear()
    game.nmnd_mafia_recruit_ids.clear()
    for pid, role in zip(player_ids, roles):
        pl = game.players[pid]
        pl.role = role
        pl.nmnd_original_role = None
        pl.nmnd_converted_by_yakuza = False
        if is_mafia_team(role):
            game.mafia_ids.add(pid)


def assign_roles_by_player_namayande10(
    game: Game, role_by_player: dict[int, Role]
) -> None:
    """Pre-determined role application (players pick roles during deal)."""
    game.mafia_ids.clear()
    game.nmnd_mafia_recruit_ids.clear()
    for pid, pl in game.players.items():
        role = role_by_player.get(pid)
        if role is None:
            raise ValueError("همهٔ بازیکن‌ها باید نقش داشته باشند.")
        pl.role = role
        pl.nmnd_original_role = None
        pl.nmnd_converted_by_yakuza = False
        if is_mafia_team(role):
            game.mafia_ids.add(pid)


def sync_synthetic_player_display_names_nam10(game: Game) -> None:
    """Synthetic display names follow roles — same UX as Bazpors, fork-gated."""
    from bot.game import (
        is_synthetic_player_uid,
        role_label_fa,
        synthetic_player_base_name,
    )

    if game.scenario_name != "namayande":
        return
    for p in sorted(
        game.players.values(),
        key=lambda pl: (pl.seat if pl.seat is not None else 999, pl.user_id),
    ):
        if not is_synthetic_player_uid(p.user_id) or p.role is None:
            continue
        base = synthetic_player_base_name(p.full_name)
        p.full_name = f"{base}-{role_label_fa(p.role)}"
''',
    "mode.py": '''"""Fork room-mode gates — bot.nam10 non-shared identity helpers."""

from __future__ import annotations

from bot.models import Game
from bot.room_mode import (
    is_mason_scenario,  # noqa: F401  (shared-neutral)
    is_mozakere_scenario,  # noqa: F401  (shared-neutral)
    mozakere_no_host_uses_parallel_night_ui,  # noqa: F401
    is_no_host_player_room as _shared_is_no_host_player_room,
)


def is_nam10_fork_room(game: Game) -> bool:
    """Namayande 10-player fork identity (independent of Bazpors)."""
    return (
        game.scenario_name == "namayande"
        and game.nmnd_host_mode == "no_host"
    )


def is_no_host_player_room(game: Game) -> bool:
    if is_nam10_fork_room(game):
        return True
    return _shared_is_no_host_player_room(game)
''',
    "engine.py": ENGINE_PY,
}


def main() -> None:
    if DST.exists():
        shutil.rmtree(DST)
    DST.mkdir(parents=True)
    (DST / "__init__.py").write_text(
        '"""Namayande 10-player fork (snapshot of Bazpors no-host)."""\n',
        encoding="utf-8",
    )
    for shim_name, shim_text in SHIMS.items():
        (DST / shim_name).write_text(shim_text, encoding="utf-8")
        print(f"  (shim) {shim_name}")

    print("generating dayflow (main.py closure):")
    dayflow_text, dayflow_names = generate_dayflow_text()
    (DST / "dayflow.py").write_text(dayflow_text, encoding="utf-8")
    print("  wrote dayflow.py")

    print("generating player_mirror (no_host_player snapshot):")
    pm_text = generate_player_mirror_text(dayflow_names)
    (DST / "player_mirror.py").write_text(pm_text, encoding="utf-8")
    print("  wrote player_mirror.py")

    print("generating narrator_cb (assistant panel snapshot):")
    ncb_text = generate_narrator_cb_text(dayflow_names)
    (DST / "nmnd_narrator_cb.py").write_text(ncb_text, encoding="utf-8")
    print("  wrote nmnd_narrator_cb.py")

    print("generating Elim report snapshot:")
    elim_text = generate_elim_report_text()
    (DST / "no_host_elim_report.py").write_text(elim_text, encoding="utf-8")
    print("  wrote no_host_elim_report.py")

    def emit(src_name: str, dst_name: str, text: str) -> None:
        (DST / dst_name).write_text(text, encoding="utf-8")
        print(f"  {src_name} -> nam10/{dst_name}")

    print("copying scenario modules:")
    for src in NO_HOST_SRCS:
        emit(src, src, transform((BOT / src).read_text(encoding="utf-8")))
    emit(GAME_STATE_SRC, GAME_STATE_SRC, transform((BOT / GAME_STATE_SRC).read_text(encoding="utf-8")))
    for src, dst in EXTRA_SRC.items():
        emit(src, dst, transform((BOT / src).read_text(encoding="utf-8")))
    emit(NARRATOR_SRC, NARRATOR_DST, transform((BOT / NARRATOR_SRC).read_text(encoding="utf-8")))

    for role in FORK_ROLES:
        src = BOT / "roles" / f"{role}.py"
        emit(f"roles/{role}.py", f"roles_{role}.py", transform(src.read_text(encoding="utf-8")))

    emit(f"roles/{REGISTRY_SRC}", REGISTRY_DST,
         transform((BOT / "roles" / REGISTRY_SRC).read_text(encoding="utf-8")))

    # registry paren-import: separate fork role modules from shared ones
    reg = DST / REGISTRY_DST
    text = reg.read_text(encoding="utf-8")
    m = re.search(r"from bot\.roles import \((.*?)\)\n", text, flags=re.S)
    if m:
        block = m.group(1)
        names = [ln.strip().rstrip(",") for ln in block.strip().splitlines() if ln.strip()]
        skip = ("night_state", "doctor_alive_save_capacity")
        fork_lines = [
            f"    roles_{n} as {n}," for n in names if n in FORK_ROLES and n not in skip
        ]
        shared_lines = [f"    {n}," for n in names if n not in FORK_ROLES or n in skip]
        new_block = (
            "from bot.nam10 import (\n" + "\n".join(fork_lines) + "\n)\n\n"
            "from bot.roles import (\n" + "\n".join(shared_lines) + "\n)\n"
        )
        text = text[:m.start()] + new_block + text[m.end():]
        reg.write_text(text, encoding="utf-8")
        print("  registry import split done")

    print("done; ", len(list(DST.glob("*.py"))), "modules in bot/nam10")


if __name__ == "__main__":
    main()
