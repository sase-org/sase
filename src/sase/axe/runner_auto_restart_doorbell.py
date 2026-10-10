"""Stdlib-only update-skew recovery doorbell for the dying runner.

This module is imported at runner boot and runs inside the dying runner,
whose interpreter may already be torn by a mid-run code swap. It therefore
uses only the standard library and performs no function-local imports. An
AST test enforces both rules, mirroring
``src/sase/axe/runner_failure_facts.py``.

When the failure facts look like update skew, the failure path:

1. merges ``recovery = {state: "pending", ...}`` into ``done.json``;
2. atomically drops a doorbell file under
   ``~/.sase/agent_auto_restart/doorbell/`` (tmp file plus rename, so the
   scheduler job never reads a torn payload);
3. lets shutdown send the completion notification with ``silent=True``.

The doorbell write happens before the notification, so a broken
notification path cannot lose it. No doorbell is dropped for user kills:
callers pass ``killed=True`` (from ``was_killed()``) and the write is
skipped.
"""

from __future__ import annotations

import datetime
import json
import os
import time
from typing import Any

SCHEMA_VERSION = 1

#: ``done.json`` recovery states that keep waiters parked and suppress the
#: terminal-blocker notification while a recovery is in flight.
IN_FLIGHT_RECOVERY_STATES = frozenset({"pending", "deferred", "launching"})

_DOORBELL_SUBDIR = ("agent_auto_restart", "doorbell")


def _sase_home() -> str:
    override = os.environ.get("SASE_HOME")
    if override:
        return os.path.expanduser(override)
    return os.path.join(os.path.expanduser("~"), ".sase")


def _doorbell_dir() -> str:
    """Return the doorbell directory (never inside an artifacts directory)."""
    return os.path.join(_sase_home(), *_DOORBELL_SUBDIR)


def _doorbell_filename(project: str, artifacts_timestamp: str) -> str:
    """Return the doorbell filename stem for one failed row."""
    safe_project = (
        "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in str(project)
        ).strip("_")
        or "project"
    )
    safe_stamp = (
        "".join(
            ch if ch.isalnum() or ch in ("-", "_") else "_"
            for ch in str(artifacts_timestamp)
        ).strip("_")
        or "row"
    )
    return f"{safe_project}__{safe_stamp}.json"


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def pending_recovery_payload() -> dict[str, Any]:
    """Return a fresh ``pending`` recovery object for ``done.json``."""
    now = _utc_now_iso()
    return {
        "state": "pending",
        "reason": None,
        "reason_text": "recovery pending: update-skew auto-restart may relaunch once",
        "requested_at": now,
        "updated_at": now,
        "episode_id": None,
        "ledger_key": None,
    }


def drop_doorbell(
    *,
    artifacts_dir: str,
    project: str,
    agent_name: str | None,
    failed_at: float | None = None,
    skew_suspect: bool = True,
) -> str | None:
    """Atomically drop a recovery doorbell. Never raises.

    Returns the doorbell path on success, else None. Uses tmp-plus-rename
    so the scheduler job never reads a torn payload.
    """
    try:
        return _drop_doorbell(
            artifacts_dir=artifacts_dir,
            project=project,
            agent_name=agent_name,
            failed_at=failed_at,
            skew_suspect=skew_suspect,
        )
    except Exception:
        return None


def _drop_doorbell(
    *,
    artifacts_dir: str,
    project: str,
    agent_name: str | None,
    failed_at: float | None,
    skew_suspect: bool,
) -> str | None:
    directory = _doorbell_dir()
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError:
        return None
    stamp = os.path.basename(os.path.normpath(artifacts_dir))
    payload = {
        "schema_version": SCHEMA_VERSION,
        "artifacts_dir": artifacts_dir,
        "project": project,
        "agent_name": agent_name,
        "failed_at": failed_at if failed_at is not None else time.time(),
        "skew_suspect": bool(skew_suspect),
    }
    path = os.path.join(directory, _doorbell_filename(project, stamp))
    tmp_path = f"{path}.tmp-{os.getpid()}-{int(time.time() * 1000)}"
    try:
        with open(tmp_path, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
        os.replace(tmp_path, path)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return None
    return path


def _recovery_state_from_done(done_path: str) -> str | None:
    """Return the ``recovery.state`` in ``done.json``, or None. Never raises."""
    try:
        with open(done_path, encoding="utf-8") as stream:
            done = json.load(stream)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(done, dict):
        return None
    recovery = done.get("recovery")
    if not isinstance(recovery, dict):
        return None
    state = recovery.get("state")
    return state if isinstance(state, str) and state else None


def recovery_requests_silence(done_path: str) -> bool:
    """Return whether ``done.json`` asks shutdown to silence its notification."""
    try:
        return _recovery_state_from_done(done_path) == "pending"
    except Exception:
        return False


__all__ = [
    "IN_FLIGHT_RECOVERY_STATES",
    "SCHEMA_VERSION",
    "drop_doorbell",
    "pending_recovery_payload",
    "recovery_requests_silence",
]
