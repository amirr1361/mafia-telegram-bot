#!/usr/bin/env python3
"""تولید bot/data/no_host_sage_quotes.py از bot/data/sage_quotes_source.md"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "bot" / "data" / "sage_quotes_source.md"
OUT = ROOT / "bot" / "data" / "no_host_sage_quotes.py"


def _parse_line(line: str) -> tuple[str, str] | None:
    line = line.strip()
    if not line:
        return None
    if " - " not in line:
        raise ValueError(f"bad line (no author separator): {line!r}")
    quote, author = line.rsplit(" - ", 1)
    quote, author = quote.strip(), author.strip()
    if not quote or not author:
        raise ValueError(f"bad line (empty quote or author): {line!r}")
    return quote, author


def load_quotes(path: Path) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        parsed = _parse_line(raw)
        if parsed is not None:
            rows.append(parsed)
    return rows


def _py_string(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def write_output(quotes: list[tuple[str, str]], path: Path) -> None:
    lines = [
        '"""جملات بزرگان — سرگرمی شب بدون گرداننده.',
        "",
        f"منبع: bot/data/sage_quotes_source.md ({len(quotes)} جمله).",
        '"""',
        "",
        "from __future__ import annotations",
        "",
        "SAGE_QUOTES: tuple[str, ...] = (",
    ]
    for quote, author in quotes:
        lines.append(f'    "{_py_string(quote)} — {_py_string(author)}",')
    lines.append(")")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"source not found: {SOURCE}")
    quotes = load_quotes(SOURCE)
    write_output(quotes, OUT)
    print(f"Wrote {len(quotes)} quotes to {OUT}")


if __name__ == "__main__":
    main()
