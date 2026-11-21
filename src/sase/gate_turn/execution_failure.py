"""Persisted execution-failure facts for gate-turn members.

A gate whose accepted option command failed before publishing a response
stays non-terminal and keeps its workspace claim. The bundle journal
already records the failure, but CLI/ACE rows read only the member's
``agent_meta.json``. This module mirrors the current pre-response failure
into ``agent_meta.json::gate_execution_failure`` so every surface can
project it without reopening the bundle, and clears it when recovery
completes.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from collections.abc import Mapping

META_KEY = "gate_execution_failure"
RESURFACED_KEY = "gate_execution_failure_resurfaced"
RESURFACED_AT_KEY = "gate_execution_failure_resurfaced_at"
RESURFACED_ACCEPTANCE_KEY = "gate_execution_failure_resurfaced_acceptance"

#: Meta keys that claim a live settler while a gate executes. Cleared when
#: a pre-response failure is persisted so the row no longer reads as running.
SETTLER_KEYS = ("pid", "process_identity", "proc_id")


def build_gate_execution_failure(
    *,
    stage: str,
    code: str,
    message: str,
    error_record: str,
    error_report_path: str,
    acceptance_id: str | None,
    attempt_id: str,
    outcome_id: str,
    resume_command: str = "",
    restart_command: str = "",
    cancel_command: str = "",
    recovery_actions: str = "",
    bundle_path: str = "",
    request_id: str = "",
    request_kind: str = "",
    at_unix: float | None = None,
) -> dict[str, Any]:
    """Return the JSON-safe failure object stored on the member."""
    return {
        "stage": stage,
        "code": code,
        "message": message,
        "error_record": error_record,
        "error_report_path": error_report_path,
        "acceptance_id": acceptance_id,
        "attempt_id": attempt_id,
        "outcome_id": outcome_id,
        "at_unix": at_unix if at_unix is not None else time.time(),
        "resume_command": resume_command,
        "restart_command": restart_command,
        "cancel_command": cancel_command,
        "recovery_actions": recovery_actions,
        "bundle_path": bundle_path,
        "request_id": request_id,
        "request_kind": request_kind,
        "resurfaced": False,
        "resurfaced_at": None,
    }


def read_gate_execution_failure(artifacts_dir: str) -> dict[str, Any] | None:
    """Return the persisted failure object, or ``None`` when absent/invalid."""
    try:
        with open(
            os.path.join(artifacts_dir, "agent_meta.json"), encoding="utf-8"
        ) as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(meta, dict):
        return None
    failure = meta.get(META_KEY)
    return dict(failure) if isinstance(failure, dict) else None


def write_gate_execution_failure(
    artifacts_dir: str,
    failure: Mapping[str, Any],
) -> None:
    """Persist *failure* and clear live-settler ownership in one write."""
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields

    payload = dict(failure)
    # A fresh acceptance resets the one-time resurface flag.
    update_meta_fields(
        artifacts_dir,
        {META_KEY: payload, "pid": None, "process_identity": None, "proc_id": None},
    )


def clear_gate_execution_failure(artifacts_dir: str) -> None:
    """Remove the persisted failure object, if present. Best-effort."""
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields

    try:
        meta_path = os.path.join(artifacts_dir, "agent_meta.json")
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        if not isinstance(meta, dict) or META_KEY not in meta:
            return
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    update_meta_fields(artifacts_dir, {}, remove_keys=(META_KEY,))


def clear_gate_member_failure_for_bundle(bundle_path: Path | str) -> None:
    """Best-effort: clear the member failure for one gate bundle."""
    try:
        from sase.notification_gates.hashing import load_and_verify_bundle

        envelope, _adapter = load_and_verify_bundle(Path(bundle_path))
        request_id = envelope.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return
        from sase.gate_turn.store import find_gate_turn_by_gate_id

        record = find_gate_turn_by_gate_id(None, request_id)
        if record is None:
            return
        clear_gate_execution_failure(record.artifacts_dir)
    except Exception:
        return


def mark_gate_execution_failure_resurfaced(
    artifacts_dir: str,
    *,
    acceptance_id: str | None,
) -> bool:
    """Record the one-time resurface. Return True when newly marked."""
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    if not isinstance(raw, dict):
        return False
    failure = raw.get(META_KEY)
    if not isinstance(failure, dict):
        return False
    if failure.get("acceptance_id") != acceptance_id:
        return False
    if failure.get("resurfaced") is True:
        return False
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields

    updated = dict(failure)
    updated["resurfaced"] = True
    try:
        from datetime import UTC, datetime

        updated["resurfaced_at"] = datetime.now(UTC).isoformat()
    except Exception:
        updated["resurfaced_at"] = None
    update_meta_fields(artifacts_dir, {META_KEY: updated})
    return True


def apply_member_failure_to_agent(
    agent: Any, failure: Mapping[str, Any] | None
) -> None:
    """Project a loaded failure object onto a TUI agent row (load-time only).

    Sets ``agent.gate_execution_failure`` and refreshes the row's status
    label and bucket so a non-terminal failed gate reads as needing a
    human. A ``None`` (or terminal) failure leaves the row untouched.
    Callers are agent-enrichment loaders, never render paths.
    """
    agent.gate_execution_failure = dict(failure) if isinstance(failure, dict) else None
    if not isinstance(agent.gate_execution_failure, dict):
        return
    try:
        from sase.gate_turn.state import (
            gate_member_status_bucket,
            gate_state_is_terminal,
        )
        from sase.gate_turn.status import (
            FAILURE_LABEL_SUFFIX,
            GATE_TURN_STATUS_ELLIPSIS,
            GATE_TURN_STATUS_MAX_CHARS,
        )
        from sase.turns.status import clamp_turn_status
    except Exception:
        return
    state = getattr(agent, "gate_state", None)
    if gate_state_is_terminal(state if isinstance(state, str) else None):
        return
    base = getattr(agent, "status", None) or ""
    if not isinstance(base, str) or not base:
        base = (
            getattr(agent, "gate_start_status", None)
            or (state if isinstance(state, str) else "")
            or ""
        )
    if base and not base.endswith(FAILURE_LABEL_SUFFIX):
        candidate = f"{base}{FAILURE_LABEL_SUFFIX}"
        if len(candidate) <= GATE_TURN_STATUS_MAX_CHARS:
            agent.status = candidate
        else:
            trimmed = base[
                : max(0, GATE_TURN_STATUS_MAX_CHARS - len(FAILURE_LABEL_SUFFIX))
            ]
            try:
                agent.status = clamp_turn_status(
                    f"{trimmed.rstrip()}{FAILURE_LABEL_SUFFIX}",
                    max_chars=GATE_TURN_STATUS_MAX_CHARS,
                    ellipsis=GATE_TURN_STATUS_ELLIPSIS,
                    noun="gate turn status",
                )
            except Exception:
                agent.status = candidate[:GATE_TURN_STATUS_MAX_CHARS]
    try:
        agent.status_bucket = gate_member_status_bucket(
            state if isinstance(state, str) else None,
            getattr(agent, "status", None),
            has_execution_failure=True,
        )
    except Exception:
        pass


def project_loaded_failure_for_agent(agent: Any) -> None:
    """Read the member's persisted failure and project it onto *agent*.

    Load-time helper for snapshot-backed agent loaders: reads
    ``agent_meta.json`` once per gate row (loaders run off the event loop,
    never render paths) and applies :func:`apply_member_failure_to_agent`.
    Best-effort: any failure leaves the row as the wire projected it.
    """
    try:
        get_dir = getattr(agent, "get_artifacts_dir", None)
        artifacts = get_dir() if callable(get_dir) else None
        if not artifacts:
            return
        apply_member_failure_to_agent(agent, read_gate_execution_failure(artifacts))
    except Exception:
        pass


def gate_execution_failure_resurfaced(
    artifacts_dir: str,
    *,
    acceptance_id: str | None,
) -> bool:
    """Return whether the current acceptance already resurfaced once."""
    failure = read_gate_execution_failure(artifacts_dir)
    if failure is None:
        return False
    if failure.get("acceptance_id") != acceptance_id:
        return False
    return failure.get("resurfaced") is True


__all__ = [
    "META_KEY",
    "SETTLER_KEYS",
    "apply_member_failure_to_agent",
    "build_gate_execution_failure",
    "clear_gate_execution_failure",
    "clear_gate_member_failure_for_bundle",
    "gate_execution_failure_resurfaced",
    "mark_gate_execution_failure_resurfaced",
    "project_loaded_failure_for_agent",
    "read_gate_execution_failure",
    "write_gate_execution_failure",
]
