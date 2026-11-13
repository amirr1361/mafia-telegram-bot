#!/usr/bin/env python3
"""Generate fork copies of the no-host simulation harness files.

Produces ``tests/nam10_flow_harness.py`` and ``tests/nam10_game_loop.py``
from their Bazpors originals. The fork transform (``remap_imports``) already
handles module path remapping and field/token renaming globally. This script
adds targeted fixes that the generic transform cannot know:

- ``from bot.roles import <role modules>`` -> attribute aliases of
  ``bot.nam10.roles_*`` copies (shared role modules would write Bazpors state)
- single-name ``from bot.main import <day-flow driver>`` -> fork
  ``bot.nam10.dayflow`` bindings
- ``patch("bot.main.X")`` -> fork dayflow binding when X is a dayflow name
- room creation flags -> fork flags (``nam10_no_host=True``)
- synthetic lobby fill -> ``fill_namayande10_synthetic_lobby``
- harness class rename to ``Nam10FlowHarness``
"""
from __future__ import annotations

import re
import sys
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent

FILES = [
    ("tests/no_host_flow_harness.py", "tests/nam10_flow_harness.py"),
    ("tests/no_host_game_loop.py", "tests/nam10_game_loop.py"),
]

FORK_ROLE_BLOCK = """\
from bot import nam10 as _nm10_rolls

detective = _nm10_rolls.roles_detective
doctor = _nm10_rolls.roles_doctor
hunter = _nm10_rolls.roles_hunter
interrogator = _nm10_rolls.roles_interrogator
shiad = _nm10_rolls.roles_shiad
sniper = _nm10_rolls.roles_sniper
ruintan = _nm10_rolls.roles_ruintan
"""

# names that exist as bindings on bot.nam10.dayflow and must be patched there
DAYFLOW_LAZY_IMPORTS = (
    "_execute_no_host_intro_night_start",
    "_dispatch_no_host_day1_defense_act",
    "_no_host_day1_defense_outcome_keyboard",
    "_process_no_host_day1_skip_night",
    "_process_no_host_day1_show_vote_panel",
)


def load_dayflow_names() -> set[str]:
    src = (ROOT / "bot/nam10/dayflow.py").read_text(encoding="utf-8")
    names = set(
        re.findall(r"^(?:async )?def ([A-Za-z_][A-Za-z_0-9]*)\(", src, flags=re.M)
    )
    # plus module-level imported bindings (header + lazy blocks)
    for m in re.finditer(
        r"^from [\w.]+ import \(([^)]*)\)", src, flags=re.M | re.S
    ):
        blob = m.group(1).replace("\n", " ")
        for tok in blob.split(","):
            tok = tok.strip()
            if tok:
                names.add(tok.split(" as ")[-1])
    for m in re.finditer(
        r"^from [\w.]+ import ([A-Za-z_0-9, ]+)$", src, flags=re.M
    ):
        for tok in m.group(1).split(","):
            tok = tok.strip()
            if tok:
                names.add(tok.split(" as ")[-1])
    return names


def apply_manual_fixes(s: str, df_names: set[str]) -> str:
    # room creation -> fork flags (post-token the kwarg reads nmnd_host_mode)
    s = re.sub(
        r'nmnd_host_mode="no_host",\n',
        "nam10_no_host=True,\n",
        s,
    )
    # synthetic lobby fill -> fork fill
    s = s.replace(
        "gm.fill_bazpors_no_host_synthetic_lobby(game)",
        "gm.fill_namayande10_synthetic_lobby(game)",
    )
    # lazy single-name day-flow imports -> fork dayflow bindings
    for name in DAYFLOW_LAZY_IMPORTS:
        s = s.replace(
            f"from bot.main import {name}\n",
            f"from bot.nam10.dayflow import {name}\n",
        )
    # patch targets: retarget dayflow-resolved names to the fork module
    def _fix_patch(m: re.Match) -> str:
        target = m.group(0).strip('"')
        if target.startswith("bot.main."):
            head = target.split(".")[2]
            if head in df_names:
                return f'"bot.nam10.dayflow.{head}"'
        return m.group(0)

    s = re.sub(r'"bot\.main\.[A-Za-z_0-9.]+"', _fix_patch, s)
    # plain role-module imports -> fork copies (the remap rewrites the path
    # but breaks the alias list; bind proper module aliases instead)
    s = s.replace(
        "from bot.nam10 import roles_detective, doctor, hunter, interrogator,"
        " shiad, sniper\n",
        FORK_ROLE_BLOCK,
    )
    return s


def harness_fixups(s: str) -> str:
    s = s.replace("__FORK_ROLE_BLOCK__\n", FORK_ROLE_BLOCK)
    s = s.replace("class NoHostFlowHarness", "class Nam10FlowHarness")
    s = s.replace("NoHostFlowHarness(", "Nam10FlowHarness(")
    s = s.replace("NoHostFlowHarness,", "Nam10FlowHarness,")
    s = s.replace(" NoHostFlowHarness", " Nam10FlowHarness")
    return s


def main() -> None:
    sys.path.insert(0, str(HERE))
    import nam10_fork_transform as tf

    df_names = load_dayflow_names()
    for src_rel, dst_rel in FILES:
        src = ROOT / src_rel
        text = src.read_text(encoding="utf-8")
        text = tf.remap_imports(text)
        text = apply_manual_fixes(text, df_names)
        text = harness_fixups(text)
        dst = ROOT / dst_rel
        dst.write_text(text, encoding="utf-8")
        print("wrote", dst_rel)


if __name__ == "__main__":
    main()
