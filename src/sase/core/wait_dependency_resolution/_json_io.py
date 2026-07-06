"""JSON helpers for wait-dependency artifact files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_json_dict(path: Path) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None
