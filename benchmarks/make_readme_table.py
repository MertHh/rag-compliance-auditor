"""Writes the benchmark tables into README.md between the two markers, from
benchmarks/results/*.json only; numbers are never typed by hand.

Run: python -m benchmarks.make_readme_table           rewrite README.md
     python -m benchmarks.make_readme_table --check   exit 1 when README.md is out of date

Exit 1 also when any result file is unreadable; the README still shows the error line.
"""

import argparse
import sys
from pathlib import Path

from auditor.benchmark_results import load_results

START = "<!-- BENCHMARKS:START -->"
END = "<!-- BENCHMARKS:END -->"
ORDER = ("retrieval", "chunking", "context_prefix", "presence", "audit")
ERROR_LIMIT = 200


def _rank(result: dict) -> int:
    stem = result["file"].removesuffix(".json")
    return next((i for i, prefix in enumerate(ORDER) if stem.startswith(prefix)), len(ORDER))


def _inline(text) -> str:
    """One line, no table-breaking pipes: whitespace collapsed, '|' escaped."""
    return " ".join(str(text).split()).replace("|", "\\|")


def _cell(value) -> str:
    if value is None:
        return "–"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        if 0 < abs(value) < 1e-3:
            return f"{value:.4g}"
        return f"{value:.4f}".rstrip("0").rstrip(".")
    return _inline(value)


def _error_line(result: dict) -> str:
    message = " ".join(str(result["error"]).split())
    if len(message) > ERROR_LIMIT:
        message = message[:ERROR_LIMIT] + "…"
    return f"> {_inline(result['file'])}: {_inline(message)}"


def render(results: list[dict]) -> str:
    groups: dict[str, list[dict]] = {}
    for result in sorted(results, key=lambda r: (_rank(r), r["file"])):
        groups.setdefault(result["title"], []).append(result)
    sections = []
    for title, items in groups.items():
        lines = [f"### {_inline(title)}", ""]
        rows = [row for item in items if not item["error"] for row in item["rows"]]
        if rows:
            columns = list(dict.fromkeys(key for row in rows for key in row))
            lines.append("| " + " | ".join(_inline(c) for c in columns) + " |")
            lines.append("|" + "|".join(" --- " for _ in columns) + "|")
            lines.extend("| " + " | ".join(_cell(row.get(c)) for c in columns) + " |" for row in rows)
        lines.extend(_error_line(item) for item in items if item["error"])
        notes = [item["notes"] for item in items if item["notes"]]
        dates = sorted({item["created_at"] for item in items if item["created_at"]})
        files = ", ".join(_inline(item["file"]) for item in items)
        lines.append("")
        lines.append(f"_Source: {files}" + (f"; measured {', '.join(_inline(d) for d in dates)}" if dates else "") + "._")
        lines.extend(f"- {_inline(note)}" for note in notes)
        sections.append("\n".join(lines))
    return "\n\n".join(sections) if sections else "_No benchmark results yet._"


def update_readme(text: str, tables: str) -> str:
    start, end = text.find(START), text.find(END)
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"README has no benchmark markers; add {START} and {END}")
    return text[:start + len(START)] + "\n\n" + tables + "\n\n" + text[end:]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="make_readme_table")
    parser.add_argument("--readme", default="README.md")
    parser.add_argument("--results", default="benchmarks/results")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    readme = Path(args.readme)
    text = readme.read_text(encoding="utf-8")
    results = load_results(Path(args.results))
    try:
        updated = update_readme(text, render(results))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    status = 0
    broken = [r["file"] for r in results if r["error"]]
    if broken:
        print(f"error: unreadable result files: {', '.join(broken)}", file=sys.stderr)
        status = 1
    if args.check:
        if updated != text:
            print("README.md benchmark tables are out of date; run python -m benchmarks.make_readme_table")
            status = 1
        return status
    if updated != text:
        readme.write_text(updated, encoding="utf-8")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
