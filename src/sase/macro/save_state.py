"""Small per-user state for xprompt save-panel defaults."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
from typing import Literal

from sase.core.paths import sase_home
from sase.legacy_xprompt_names import (
    LEGACY_XPROMPT_SAVE_STATE_FILENAME,
    LEGACY_XPROMPT_SAVE_STATE_KEY,
    MACRO_SAVE_STATE_FILENAME,
    MACRO_SAVE_STATE_KEY,
    read_json_new_first,
)

SaveKind = Literal["xprompt", "snippet"]
_SAVE_STATE_FILE: Path | None = None


def _state_file() -> Path:
    return _SAVE_STATE_FILE or sase_home() / MACRO_SAVE_STATE_FILENAME


def _legacy_state_file() -> Path:
    if _SAVE_STATE_FILE is not None:
        return _SAVE_STATE_FILE.parent / LEGACY_XPROMPT_SAVE_STATE_FILENAME
    return sase_home() / LEGACY_XPROMPT_SAVE_STATE_FILENAME


def load_last_used_locations() -> dict[SaveKind, str]:
    """Return valid last-used location strings from the state file.

    Reads the canonical file first, falling back to the pre-rename file and
    key. The in-memory ``SaveKind`` spellings are unchanged; only the on-disk
    file and key use the canonical macro names.
    """
    payload, _ = read_json_new_first(_state_file(), _legacy_state_file())
    if not isinstance(payload, dict):
        return {}
    result: dict[SaveKind, str] = {}
    xprompt = payload.get(MACRO_SAVE_STATE_KEY)
    if xprompt is None:
        xprompt = payload.get(LEGACY_XPROMPT_SAVE_STATE_KEY)
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
    canonical = {
        (MACRO_SAVE_STATE_KEY if key == "xprompt" else key): value
        for key, value in state.items()
    }
    target = _state_file()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".macro-save.", dir=target.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(canonical, handle, indent=2, sort_keys=True)
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
    legacy_state_file = _legacy_state_file()
    if legacy_state_file != target:
        try:
            legacy_state_file.unlink(missing_ok=True)
        except OSError:
            pass
    return True


__all__ = ["load_last_used_locations", "save_last_used_location"]
