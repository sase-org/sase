"""Bounded machine-local persistence for the Admin Center resume tab."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from sase.core.paths import sase_home

from .config_center_catalog import CenterTab, validated_center_tab

_STATE_FILENAME = "ace_admin_center_last_tab.txt"
_MAX_STATE_BYTES = 64


def _admin_center_last_tab_path() -> Path:
    """Return the machine-local Admin Center resume-state path."""
    return sase_home() / _STATE_FILENAME


def load_admin_center_last_tab() -> CenterTab | None:
    """Load one exact newline-terminated catalog tab, or return ``None``."""
    path = _admin_center_last_tab_path()
    try:
        with path.open("rb") as stream:
            data = stream.read(_MAX_STATE_BYTES + 1)
    except (OSError, ValueError):
        return None

    if not data or len(data) > _MAX_STATE_BYTES:
        return None
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if not text.endswith("\n") or text.count("\n") != 1:
        return None
    return validated_center_tab(text[:-1])


def save_admin_center_last_tab(tab: CenterTab) -> None:
    """Atomically persist one catalog tab with a trailing newline."""
    validated = validated_center_tab(tab)
    if validated is None:
        raise ValueError(f"invalid Admin Center tab: {tab!r}")

    path = _admin_center_last_tab_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(f"{validated}\n".encode())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


__all__ = [
    "load_admin_center_last_tab",
    "save_admin_center_last_tab",
]
