"""Torn-line-tolerant JSONL reading for tests that inspect durable logs.

A writer killed mid-append, or a row still being written while a test reads,
leaves a torn last line. Readers skip such lines (and any line that is not a
JSON object) and report how many they skipped instead of raising.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_jsonl_rows(path: Path) -> tuple[list[dict[str, Any]], int]:
    """Return ``(rows, skipped)``: JSON-object rows and the skipped line count."""
    if not path.exists():
        return [], 0
    rows: list[dict[str, Any]] = []
    skipped = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            skipped += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
        else:
            skipped += 1
    return rows, skipped
