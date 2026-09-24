"""In-flight markers and aborted-handoff recording for agent handoffs.

An in-agent handoff command (above all ``sase monitor start``) can be killed
mid-flight: a yielding harness exec, a CLI timeout, or OOM. The pending
handoff marker then never lands and the run falls into a normal-looking
declaration recovery with no signal to the user.

To close that gap, an in-agent handoff command writes a small in-flight
marker into ``SASE_ARTIFACTS_DIR`` before any slow work. The marker is
superseded when the pending handoff marker is written and removed on every
error exit. When the provider turn ends with no pending handoff marker, the
runner consults the in-flight marker:

- owning process still alive: wait a bounded time for the pending marker,
  then adopt the handoff normally;
- owning process dead: record ``handoff_aborted`` (``handoff_aborted.json``,
  ``workflow_state.json``, and ``done.json``) and notify the user.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.gate_intent import atomic_write_json
from sase.agent.pending_handoff import has_pending_handoff

_logger = logging.getLogger(__name__)

HANDOFF_INFLIGHT_MARKER = ".sase_handoff_inflight"
HANDOFF_ABORTED_FILENAME = "handoff_aborted.json"

HANDOFF_ADOPT_WAIT_ENV = "SASE_HANDOFF_ADOPT_WAIT_SECONDS"
HANDOFF_ADOPT_WAIT_DEFAULT_SECONDS = 30.0
HANDOFF_ADOPT_POLL_SECONDS = 0.25


def _handoff_inflight_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return whether the current process runs inside an agent runner."""
    current = env if env is not None else os.environ
    return bool(current.get("SASE_AGENT"))


def write_handoff_inflight_marker(
    command: str,
    *,
    lane: str | None = None,
    artifacts_dir: str | None = None,
) -> Path | None:
    """Record that an in-agent handoff command started, best-effort.

    Returns the marker path, or ``None`` when outside an agent or without an
    artifacts dir. Never raises: a marker must not break the handoff itself.
    """
    from sase.core.process_identity import process_identity_token

    resolved = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not resolved or not _handoff_inflight_enabled():
        return None
    pid = os.getpid()
    payload = {
        "command": command,
        "lane": lane,
        "agent": os.environ.get("SASE_AGENT"),
        "agent_name": os.environ.get("SASE_AGENT_NAME"),
        "pid": pid,
        "process_identity": process_identity_token(pid),
        "argv": list(sys.argv),
        "started_at": time.time(),
    }
    try:
        path = Path(resolved) / HANDOFF_INFLIGHT_MARKER
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, payload)
        return path
    except OSError as exc:
        _logger.warning("could not write handoff in-flight marker: %s", exc)
        return None


def _read_handoff_inflight_marker(artifacts_dir: str | None) -> dict[str, Any] | None:
    """Return the in-flight handoff marker payload, if one is on disk."""
    if not artifacts_dir:
        return None
    import json

    try:
        raw = (Path(artifacts_dir) / HANDOFF_INFLIGHT_MARKER).read_text(
            encoding="utf-8"
        )
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def clear_handoff_inflight_marker(artifacts_dir: str | None) -> None:
    """Remove the in-flight handoff marker, best-effort."""
    if not artifacts_dir:
        return None
    try:
        (Path(artifacts_dir) / HANDOFF_INFLIGHT_MARKER).unlink(missing_ok=True)
    except OSError:
        pass
    return None


def _inflight_owner_alive(marker: Mapping[str, Any]) -> bool:
    """Return whether the process that wrote *marker* is still its owner.

    A bare PID can be recycled, so a live PID is additionally checked against
    the recorded boot-aware process identity. Any definite mismatch — dead
    PID or recycled PID — means the handoff owner is gone.
    """
    from sase.core.process_identity import process_identity_matches

    pid = marker.get("pid")
    if isinstance(pid, bool):
        return False
    try:
        pid = int(pid)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    except OSError:
        return False
    return bool(process_identity_matches(pid, marker.get("process_identity")))


def _wait_for_pending_handoff(
    artifacts_dir: str,
    *,
    timeout_seconds: float = HANDOFF_ADOPT_WAIT_DEFAULT_SECONDS,
    poll_seconds: float = HANDOFF_ADOPT_POLL_SECONDS,
) -> bool:
    """Poll for a pending handoff marker up to *timeout_seconds*."""
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        if has_pending_handoff(artifacts_dir):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_seconds)


def _adopt_wait_seconds(env: Mapping[str, str] | None = None) -> float:
    """Return the bounded adopt-wait budget for a live in-flight owner."""
    current = env if env is not None else os.environ
    try:
        return max(0.0, float(current.get(HANDOFF_ADOPT_WAIT_ENV, "") or ""))
    except (TypeError, ValueError):
        pass
    return HANDOFF_ADOPT_WAIT_DEFAULT_SECONDS


def _record_handoff_aborted(
    artifacts_dir: str,
    marker: Mapping[str, Any],
    *,
    reason: str,
) -> dict[str, Any]:
    """Persist a ``handoff_aborted`` record for a killed handoff command.

    Writes ``handoff_aborted.json``, stamps ``workflow_state.json`` when one
    exists, and merges the record into an already-written ``done.json``. The
    not-yet-written ``done.json`` picks the record up from disk when the
    runner finalize path builds it.
    """
    import json

    record = {
        "command": marker.get("command"),
        "lane": marker.get("lane"),
        "agent": marker.get("agent") or marker.get("agent_name"),
        "pid": marker.get("pid"),
        "started_at": marker.get("started_at"),
        "detected_at": time.time(),
        "reason": reason,
    }
    root = Path(artifacts_dir)
    try:
        root.mkdir(parents=True, exist_ok=True)
        atomic_write_json(root / HANDOFF_ABORTED_FILENAME, record)
    except OSError as exc:
        _logger.warning("could not write handoff_aborted.json: %s", exc)
    _stamp_workflow_state(root, record)
    _merge_record_into_done_json(root, record)
    return record


def _load_handoff_aborted_record(
    artifacts_dir: str | None,
) -> dict[str, Any] | None:
    """Return a previously recorded ``handoff_aborted`` payload, if any."""
    if not artifacts_dir:
        return None
    import json

    try:
        raw = (Path(artifacts_dir) / HANDOFF_ABORTED_FILENAME).read_text(
            encoding="utf-8"
        )
    except OSError:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def merge_handoff_aborted_into_done_marker(
    artifacts_dir: str,
    done_marker: dict[str, Any],
) -> dict[str, Any]:
    """Attach an on-disk ``handoff_aborted`` record to a done marker being built."""
    if "handoff_aborted" in done_marker:
        return done_marker
    record = _load_handoff_aborted_record(artifacts_dir)
    if record is not None:
        done_marker["handoff_aborted"] = record
    return done_marker


def _stamp_workflow_state(root: Path, record: Mapping[str, Any]) -> None:
    import json

    state_path = root / "workflow_state.json"
    try:
        raw = state_path.read_text(encoding="utf-8")
    except OSError:
        return
    try:
        state = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(state, dict):
        return
    state["handoff_aborted"] = dict(record)
    try:
        state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        _logger.warning("could not stamp workflow_state.json: %s", exc)


def _merge_record_into_done_json(root: Path, record: Mapping[str, Any]) -> None:
    import json

    done_path = root / "done.json"
    try:
        raw = done_path.read_text(encoding="utf-8")
    except OSError:
        return
    try:
        done = json.loads(raw)
    except json.JSONDecodeError:
        return
    if not isinstance(done, dict) or "handoff_aborted" in done:
        return
    done["handoff_aborted"] = dict(record)
    try:
        done_path.write_text(json.dumps(done, indent=2), encoding="utf-8")
    except OSError as exc:
        _logger.warning("could not merge handoff_aborted into done.json: %s", exc)


def _notify_handoff_aborted(
    record: Mapping[str, Any],
    *,
    agent_name: str | None,
    assigned_bead_id: str | None,
    artifacts_dir: str | None = None,
) -> None:
    """Send a SASE notification naming the killed handoff's agent and bead."""
    from datetime import datetime
    from uuid import uuid4

    from sase.core.time import get_timezone
    from sase.notifications.models import Notification, normalize_notification_tags
    from sase.notifications.store import upsert_notification

    command = record.get("command") or "unknown command"
    agent_label = agent_name or record.get("agent") or "unknown agent"
    bead_label = assigned_bead_id or "no assigned bead"
    notes = [
        "Aborted handoff: an in-agent handoff command was killed before "
        "its monitor started",
        f"Agent: {agent_label}",
        f"Assigned bead: {bead_label}",
        f"Command: {command}",
        "This run tried the command above but it was killed before the "
        "monitor started; no follow-up agent will run.",
    ]
    notification = Notification(
        id=str(uuid4()),
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="handoff_aborted",
        icon="!",
        color="#D14343",
        notes=notes,
        files=[artifacts_dir] if artifacts_dir else [],
        tags=normalize_notification_tags(["handoff", "aborted", "monitor"]),
        action_data={},
    )
    upsert_notification(notification)


def adopt_or_record_aborted_handoff(
    artifacts_dir: str | None,
    *,
    agent_name: str | None = None,
    assigned_bead_id: str | None = None,
) -> dict[str, Any] | None:
    """Adopt a late handoff or record it as aborted.

    Returns the ``handoff_aborted`` record when the in-flight owner is dead,
    else ``None`` (no marker, a pending handoff already pending or adopted
    after a bounded wait, or an owner still alive that never settled).
    """
    if not artifacts_dir:
        return None
    marker = _read_handoff_inflight_marker(artifacts_dir)
    if marker is None:
        return None
    if has_pending_handoff(artifacts_dir):
        clear_handoff_inflight_marker(artifacts_dir)
        return None
    if _inflight_owner_alive(marker):
        if _wait_for_pending_handoff(
            artifacts_dir, timeout_seconds=_adopt_wait_seconds()
        ):
            clear_handoff_inflight_marker(artifacts_dir)
            return None
        if has_pending_handoff(artifacts_dir):
            clear_handoff_inflight_marker(artifacts_dir)
            return None
        # Still alive but never settled: not aborted, so say nothing and
        # leave the marker for a later handoff write to supersede.
        _logger.warning(
            "handoff in-flight owner still alive without a pending marker; "
            "leaving the marker in place"
        )
        return None
    record = _record_handoff_aborted(
        artifacts_dir, marker, reason="handoff_process_dead"
    )
    clear_handoff_inflight_marker(artifacts_dir)
    try:
        _notify_handoff_aborted(
            record,
            agent_name=agent_name,
            assigned_bead_id=assigned_bead_id,
            artifacts_dir=artifacts_dir,
        )
    except Exception as exc:  # noqa: BLE001 - notification must not fail the run
        _logger.warning("could not send handoff_aborted notification: %s", exc)
    return record


__all__ = [
    "HANDOFF_ABORTED_FILENAME",
    "HANDOFF_ADOPT_POLL_SECONDS",
    "HANDOFF_ADOPT_WAIT_DEFAULT_SECONDS",
    "HANDOFF_ADOPT_WAIT_ENV",
    "HANDOFF_INFLIGHT_MARKER",
    "adopt_or_record_aborted_handoff",
    "clear_handoff_inflight_marker",
    "merge_handoff_aborted_into_done_marker",
    "write_handoff_inflight_marker",
]
