"""Benchmark result files. The benchmark scripts write one JSON file per table into
benchmarks/results/; the API reads them and the UI draws tables and charts. The README
table is generated from the same files, so numbers are never typed by hand. The first
column labels the row; column names must not contain "." or "[" (chart field paths)."""

import json
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, Field, ValidationError

# NaN and Infinity cannot be rendered as JSON, so they are rejected at load time.
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class BenchmarkFile(BaseModel):
    title: str
    created_at: str | None = None
    rows: list[dict[str, str | FiniteFloat | int | None]]
    notes: str = ""


def load_results(directory: Path) -> list[dict]:
    if not directory.is_dir():
        return []
    results = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = BenchmarkFile.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValidationError, UnicodeDecodeError) as exc:
            results.append({"file": path.name, "title": path.stem, "created_at": None,
                            "rows": [], "notes": "", "error": f"unreadable result file: {exc}"})
            continue
        results.append({"file": path.name, **data.model_dump(), "error": None})
    return results
