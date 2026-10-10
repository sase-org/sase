"""Waiter safety for update-skew auto-restart.

The healer's forced-reuse wipe removes the failed row's artifacts
directory. Name-based waits rebind through the replacement automatically,
but identity- (or ref-) based waits pin the old artifacts dir. This module
maps an old artifacts directory to its replacement through the restart
ledger, and reports whether a row's ``done.json`` recovery is still in
flight so wait resolution stays parked instead of going terminal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

IN_FLIGHT_RECOVERY_STATES = frozenset({"pending", "deferred", "launching"})


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _recovery_state(artifacts_dir: str | Path) -> str | None:
    """Return the ``recovery.state`` of a row's ``done.json``, if any."""
    done = _read_json(Path(str(artifacts_dir)) / "done.json")
    if done is None:
        return None
    recovery = done.get("recovery")
    if not isinstance(recovery, dict):
        return None
    state = recovery.get("state")
    return state if isinstance(state, str) and state else None


def recovery_in_flight(artifacts_dir: str | Path) -> bool:
    """Return whether a row's recovery is still in flight."""
    try:
        return _recovery_state(artifacts_dir) in IN_FLIGHT_RECOVERY_STATES
    except Exception:
        return False


def find_replacement_artifacts_dir(old_artifacts_dir: str | Path) -> str | None:
    """Map a wiped row to its auto-restart replacement, if one launched.

    Consults the restart ledger for a record whose ``failed_artifacts_dir``
    is the old row and returns its ``launched_artifacts_dir``. Returns None
    when no record owns the failure yet or no replacement launched.
    """
    try:
        from sase.agent.auto_restart import ledger as ledger_mod
    except Exception:
        return None
    try:
        records = ledger_mod.iter_ledger_records()
    except Exception:
        return None
    wanted = str(old_artifacts_dir)
    for stored in records:
        try:
            failed = stored.record.failed_artifacts_dir
            launched = stored.record.launched_artifacts_dir
        except AttributeError:
            continue
        if failed == wanted and isinstance(launched, str) and launched:
            return launched
    return None


__all__ = [
    "IN_FLIGHT_RECOVERY_STATES",
    "find_replacement_artifacts_dir",
    "recovery_in_flight",
]
