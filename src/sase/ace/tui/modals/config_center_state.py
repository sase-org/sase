"""Bounded machine-local persistence for the Admin Center tab history."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from sase.core.paths import sase_home

from .config_center_catalog import validated_center_tab
from .config_center_history import AdminCenterTabHistory

_STATE_FILENAME = "ace_admin_center_last_tab.txt"
_MAX_STATE_BYTES = 64


def _admin_center_last_tab_path() -> Path:
    """Return the machine-local Admin Center resume-state path."""
    return sase_home() / _STATE_FILENAME


def load_admin_center_tab_history() -> AdminCenterTabHistory:
    """Load the persisted ``(current, alternate)`` pair, or an empty history."""
    path = _admin_center_last_tab_path()
    try:
        with path.open("rb") as stream:
            data = stream.read(_MAX_STATE_BYTES + 1)
    except (OSError, ValueError):
        return AdminCenterTabHistory()

    if not data or len(data) > _MAX_STATE_BYTES:
        return AdminCenterTabHistory()
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return AdminCenterTabHistory()
    if not text.endswith("\n"):
        return AdminCenterTabHistory()

    lines = text[:-1].split("\n")
    if len(lines) not in (1, 2):
        return AdminCenterTabHistory()

    current = validated_center_tab(lines[0])
    if current is None:
        return AdminCenterTabHistory()
    if len(lines) == 1:
        return AdminCenterTabHistory(current=current)

    alternate = validated_center_tab(lines[1])
    if alternate is None:
        return AdminCenterTabHistory()
    if alternate == current:
        # Degenerate/corrupt on-disk pair: keep ``current``, drop the
        # alternate rather than rejecting the whole file.
        return AdminCenterTabHistory(current=current)
    return AdminCenterTabHistory(current=current, alternate=alternate)


def save_admin_center_tab_history(history: AdminCenterTabHistory) -> None:
    """Atomically persist ``history`` as one or two newline-terminated lines."""
    current = validated_center_tab(history.current)
    if current is None:
        raise ValueError(f"invalid Admin Center tab: {history.current!r}")
    alternate = history.alternate if history.alternate != current else None

    payload = f"{current}\n" if alternate is None else f"{current}\n{alternate}\n"

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
            stream.write(payload.encode())
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
    "load_admin_center_tab_history",
    "save_admin_center_tab_history",
]
