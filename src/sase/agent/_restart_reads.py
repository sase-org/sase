"""Tolerant artifact reads shared by the ``sase agent restart`` modules.

Every reader here degrades to an empty value instead of raising: a restart is
planned from whatever a historical artifacts directory still holds, and a
missing or corrupt marker must not become a traceback.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def read_raw_prompt(path: Path) -> str | None:
    """Return the stored prompt at *path*, or None when it is missing/blank."""
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return text if text.strip() else None


def read_json_dict(path: Path) -> dict[str, Any]:
    """Return the JSON object at *path*, or an empty dict when unreadable."""
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            loaded = json.load(handle)
    except (json.JSONDecodeError, OSError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def optional_str(value: object) -> str | None:
    """Return *value* when it is a non-empty string, else None."""
    return value if isinstance(value, str) and value else None


def resolved_path(path: Path | str) -> Path:
    """Return *path* expanded and resolved for identity comparisons."""
    return Path(path).expanduser().resolve(strict=False)
