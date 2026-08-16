"""Durable per-project sync hints for primary-sidecar auto-sync.

A hint records "role R in project P just changed", so the auto-sync chop can
converge a known remote change promptly instead of waiting for its next
backstop scan. Hints are SASE state outside any repository checkout (see the
ownership contract in ``sase.workspace_provider.ownership``), so recording
one never touches a project's primary or sidecar clones.
"""

from __future__ import annotations

from datetime import UTC, datetime
import json
import os
from pathlib import Path
import tempfile

from sase.core.paths import sase_subdir


def _hints_dir() -> Path:
    return sase_subdir("sidecar_sync_hints")


def _hints_path(project_key: str) -> Path:
    return _hints_dir() / f"{project_key}.json"


def mark_sidecar_sync_hint(project_key: str, role: str) -> None:
    """Record that *role* changed for *project_key* and should sync soon."""

    path = _hints_path(project_key)
    hints = _read_hints(path)
    hints[role] = datetime.now(UTC).isoformat()
    _write_hints(path, hints)


def pending_sidecar_sync_roles(project_key: str) -> tuple[str, ...]:
    """Return roles with an unconsumed sync hint for *project_key*."""

    return tuple(_read_hints(_hints_path(project_key)))


def clear_sidecar_sync_hint(project_key: str, role: str) -> None:
    """Consume one role's pending hint, if present."""

    path = _hints_path(project_key)
    hints = _read_hints(path)
    if role not in hints:
        return
    del hints[role]
    _write_hints(path, hints)


def _read_hints(path: Path) -> dict[str, str]:
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        role: hinted_at
        for role, hinted_at in payload.items()
        if isinstance(role, str) and isinstance(hinted_at, str)
    }


def _write_hints(path: Path, hints: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(hints, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


__all__ = [
    "clear_sidecar_sync_hint",
    "mark_sidecar_sync_hint",
    "pending_sidecar_sync_roles",
]
