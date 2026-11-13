#!/usr/bin/env python3
"""Idempotent generate/refresh of the Namayande-10 fork state fields in models.py.

Prefix rule: candidates discovered via ``.nam10_*`` references (the dev-rename
of the ``no_host_*`` family) keep the ``nam10_`` prefix; candidates from the
``bazpors_*`` family get the ``nmnd_`` prefix.
"""
import ast
import pathlib
import re

data = ast.literal_eval(pathlib.Path("/tmp/nam10_fieldgen.json").read_text())
models = pathlib.Path("bot/models.py")
src = models.read_text(encoding="utf-8")

# 1) strip previously generated blocks (idempotency)
src = re.sub(r"    # ---- Namayande 10-player fork state.*?(?=    nmnd_host_mode)", "", src, flags=re.S)
src = re.sub(
    r"    # ---- Namayande 10-player fork state \(bot/nam10, independent of Bazpors\) ----\n(    (?:nmnd|nam10)_[^\n]*\n)+    nmnd_host_mode: str \| None = None",
    "    mirror_prompt_messages: dict[str, dict[str, object]] = field(default_factory=dict)KEEP",
    src,
) if "KEEP" in "" else src
src = re.sub(
    r"    # ---- Namayande 10-player fork state \(bot/nam10, independent of Bazpors\) ----\n(    (?:nmnd|nam10)_[^\n]*\n)+",
    "",
    src,
)
src = src.replace(
    "    mirror_prompt_messages: dict[str, dict[str, object]]KEEP",
    "    mirror_prompt_messages: dict[str, dict[str, object]] = field(default_factory=dict)",
)
src = re.sub(r"    # Namayande 10-player fork state\n(    (?:nmnd|nam10)_[^\n]*\n)+", "", src)
src = re.sub(r"    # Namayande 10-player fork state\n(    nmnd_[^\n]*\n){2}", "", src)

# leftover safety nets for earlier generated shapes
src = re.sub(r"\n    nmnd_host_mode: str \| None = None(?=\n|$)", "", src)

# 2) locate the original defs for prefix decision
def_lookup = {}
for m in re.finditer(r"^    ((?:no_host|bazpors)_[a-z0-9_]+): (.+?)$", src, flags=re.M):
    def_lookup[m.group(1)] = m.group(2)


def fork_name(n: str) -> str:
    if ("no_host_" + n) in def_lookup:
        return "nam10_" + n
    if ("bazpors_" + n) in def_lookup:
        return "nmnd_" + n
    raise SystemExit(f"unmapped candidate field: {n}")


# 3) classify Player vs Game
head = src[src.index("class Player") : src.index("class NightActions")]

game_lines = []
player_lines = []
for n, _default in data["game"]:
    fname = fork_name(n)
    origin = ("no_host_" if fname.startswith("nam10_") else "bazpors_") + n
    is_player = bool(re.search(rf"^    {re.escape(origin)}: ", head, flags=re.M))
    line = f"    {fname}: {def_lookup[origin]}"
    (player_lines if is_player else game_lines).append(line)
game_lines.append("    nmnd_host_mode: str | None = None")

seen = set()
game_lines = [ln for ln in game_lines if not (ln in seen or seen.add(ln))]

marker = "    mirror_prompt_messages: dict[str, dict[str, object]] = field(default_factory=dict)"
assert marker in src, "Game tail marker missing"
assert "# ---- Namayande 10-player fork state" not in src, "stale fork block remains"
assert "nmnd_host_mode" not in src, "stale nmnd_host_mode remains"
src = src.replace(
    marker,
    marker
    + "\n    # ---- Namayande 10-player fork state (bot/nam10, independent of Bazpors) ----\n"
    + "\n".join(game_lines),
)

pm = r"    mozakere_armored_armor_used: bool = False"
assert pm in src, "Player marker missing"
assert "# Namayande 10-player fork state" not in src, "stale player block"
src = src.replace(
    pm,
    pm
    + "\n    # Namayande 10-player fork state\n"
    + "\n".join(player_lines),
)

models.write_text(src, encoding="utf-8")
print("models.py refreshed:", len(game_lines), "game flds,", len(player_lines), "player flds")
