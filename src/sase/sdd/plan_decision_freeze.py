"""Frozen accepted-sheet definitions for environment-independent rendering."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SCHEMA = 1
SUFFIX = ".plan-decisions.json"


def sibling_path_for_plan(plan_path: str | Path) -> Path:
    """Return the frozen-definitions sibling for a plan file."""
    path = Path(str(plan_path)).expanduser()
    return path.parent / f"{path.stem}{SUFFIX}"


def read_frozen_definitions(plan_path: str | Path) -> list[dict[str, Any]] | None:
    """Return frozen definitions when the sibling is well-formed, else None."""
    sibling = sibling_path_for_plan(plan_path)
    try:
        payload = json.loads(sibling.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") != SCHEMA:
        return None
    definitions = payload.get("definitions")
    if not isinstance(definitions, list) or not definitions:
        return None
    cleaned: list[dict[str, Any]] = []
    for item in definitions:
        if not isinstance(item, dict):
            return None
        raw_id = item.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            return None
        cleaned.append(dict(item))
    return cleaned


def write_frozen_definitions_if_missing(
    plan_path: str | Path, definitions: list[dict[str, Any]] | None
) -> bool:
    """Write the sibling when missing; never overwrite. Return True if wrote."""
    if not definitions:
        return False
    sibling = sibling_path_for_plan(plan_path)
    try:
        if sibling.is_file():
            return False
    except OSError:
        return False
    payload = {"schema": SCHEMA, "definitions": [dict(item) for item in definitions]}
    try:
        sibling.parent.mkdir(parents=True, exist_ok=True)
        sibling.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except (OSError, UnicodeError, ValueError):
        return False
    return True


__all__ = [
    "SCHEMA",
    "SUFFIX",
    "read_frozen_definitions",
    "sibling_path_for_plan",
    "write_frozen_definitions_if_missing",
]
