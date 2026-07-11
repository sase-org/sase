"""Small per-user state for xprompt save-panel defaults."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Literal

from sase.core.paths import sase_home

SaveKind = Literal["xprompt", "snippet"]
_SAVE_STATE_FILE: Path | None = None


def _state_file() -> Path:
    return _SAVE_STATE_FILE or sase_home() / "xprompt_save_state.json"


def load_last_used_locations() -> dict[SaveKind, str]:
    """Return valid last-used location strings from the state file."""
    try:
        payload = json.loads(_state_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    result: dict[SaveKind, str] = {}
    xprompt = payload.get("xprompt")
    snippet = payload.get("snippet")
    if isinstance(xprompt, str) and xprompt:
        result["xprompt"] = xprompt
    if isinstance(snippet, str) and snippet:
        result["snippet"] = snippet
    return result


def save_last_used_location(kind: SaveKind, path: str) -> bool:
    """Atomically remember *path* as the last destination for *kind*."""
    state = load_last_used_locations()
    state[kind] = path
    target = _state_file()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".xprompt-save.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(temporary, target)
        except OSError:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            return False
    except OSError:
        return False
    return True


__all__ = ["load_last_used_locations", "save_last_used_location"]
