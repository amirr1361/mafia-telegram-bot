#!/usr/bin/env python3
"""Standalone generator of the Namayande-10 fork state fields for bot/models.py.

- Scans bot/nam10 for fork field references (``nam10_*`` / ``nmnd_*``) and
  maps each to its Bazpors origin declaration (verbatim, continuations included).
- ``no_host_*`` family  ->  ``nam10_*``; ``bazpors_*`` family  ->  ``nmnd_*``.
- Idempotent: removes any previous fork blocks, then regenerates.
"""
import pathlib
import re
import subprocess

ROOT = pathlib.Path(".")
MODELS = ROOT / "bot" / "models.py"
NAM10 = ROOT / "bot" / "nam10"


def pristine_models_src() -> str:
    """models.py checked out at HEAD (read-only git inspection)."""
    return subprocess.run(
        ["git", "show", "HEAD:bot/models.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def split_fields(src: str) -> dict[str, str]:
    """name -> full (possibly multi-line) declaration block of dataclass fields."""
    lines = src.splitlines()
    out: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^    ([a-z][a-z0-9_]+): ", line)
        if m and not line.lstrip().startswith(("#", "@", '"')):
            block = [line]

            def _open(b: list[str]) -> int:
                joined = "\n".join(b)
                return joined.count("(") - joined.count(")")

            while _open(block) > 0 and i + 1 < len(lines):
                i += 1
                block.append(lines[i])
            name = m.group(1)
            out.setdefault(name, "\n".join(block))
        i += 1
    return out


def main() -> None:
    src = pristine_models_src()

    all_text = "".join(p.read_text() for p in NAM10.glob("*.py"))
    refs_dotted = set(re.findall(r"\.((?:nam10|nmnd)_[a-z0-9_]+)", all_text))
    refs_quoted = set(re.findall(r"[\"']((?:nam10|nmnd)_[a-z0-9_]+)[\"']", all_text))
    refs = refs_dotted | refs_quoted
    # drop names that are not state fields (methods etc. resolve at runtime);
    # we keep everything whose origin exists in models.py
    fields = split_fields(src)
    print("orig fields parsed:", len(fields))

    player_head = src[src.index("class Player") : src.index("class NightActions")]

    game_lines: list[str] = []
    player_lines: list[str] = []
    seen: set[str] = set()
    for ref in sorted(refs):
        fam, rest = ref.split("_", 1)
        origin_prefix = "no_host_" if fam == "nam10" else "bazpors_"
        origin = origin_prefix + rest
        decl = fields.get(origin)
        if decl is None:
            continue
        renamed = decl.replace(f"    {origin}:", f"    {ref}:", 1)
        is_player = bool(re.search(rf"^    {re.escape(origin)}: ", player_head, flags=re.M))
        target = player_lines if is_player else game_lines
        if renamed not in seen:
            seen.add(renamed)
            target.append(renamed)

    game_lines.append("    nmnd_host_mode: str | None = None")
    print("fork game fields:", len(game_lines) - 1, "player fields:", len(player_lines))

    game_marker = "    mirror_prompt_messages: dict[str, dict[str, object]] = field(default_factory=dict)"
    assert game_marker in src
    src = src.replace(
        game_marker,
        game_marker
        + "\n    # ---- Namayande 10-player fork state (bot/nam10, independent of Bazpors) ----\n"
        + "\n".join(game_lines),
    )

    pm = "    mozakere_armored_armor_used: bool = False"
    assert pm in src
    if player_lines:
        src = src.replace(
            pm,
            pm
            + "\n    # Namayande 10-player fork state\n"
            + "\n".join(player_lines),
        )

    MODELS.write_text(src + "\n", encoding="utf-8")
    print("written:", MODELS)


if __name__ == "__main__":
    main()
