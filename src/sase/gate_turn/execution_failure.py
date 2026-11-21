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
#: Once-per-acceptance resurface history, kept separate from the transient
#: failure object so recovery clearing the failure does not grant a second
#: allowance for the same acceptance. Maps acceptance_id -> ISO timestamp.
RESURFACED_HISTORY_KEY = "gate_execution_failure_resurfaced_history"
#: First-observation timestamps for dismissed rows that predate dismissal
#: tracking, mapping notification id -> unix seconds. Legacy rows never
#: infer dismissal from failure time.
DISMISSAL_OBSERVED_KEY = "gate_execution_failure_dismissal_observed"

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


def _read_history(artifacts_dir: str) -> dict[str, Any]:
    """Return the persisted once-per-acceptance resurface history."""
    try:
        with open(
            os.path.join(artifacts_dir, "agent_meta.json"), encoding="utf-8"
        ) as f:
            meta = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(meta, dict):
        return {}
    history = meta.get(RESURFACED_HISTORY_KEY)
    return dict(history) if isinstance(history, dict) else {}


def write_gate_execution_failure(
    artifacts_dir: str,
    failure: Mapping[str, Any],
) -> None:
    """Persist *failure* and clear live-settler ownership in one write.

    Preserves once-per-acceptance resurface history across new attempts of
    the same acceptance: a repeated failure on the same acceptance never
    earns a second allowance. A genuinely new acceptance starts fresh.
    """
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields

    payload = dict(failure)
    acceptance_id = payload.get("acceptance_id")
    history = _read_history(artifacts_dir)
    if isinstance(acceptance_id, str) and acceptance_id:
        # A repeated attempt on an already-resurfaced acceptance keeps its
        # marker; identical retries replay the same acceptance.
        if acceptance_id in history:
            payload["resurfaced"] = True
            existing = history.get(acceptance_id)
            if isinstance(existing, str) and not payload.get("resurfaced_at"):
                payload["resurfaced_at"] = existing
        else:
            # A genuinely new acceptance starts a new allowance.
            payload["resurfaced"] = False
            payload["resurfaced_at"] = None
    else:
        payload["resurfaced"] = False
        payload["resurfaced_at"] = None
    update_meta_fields(
        artifacts_dir,
        {
            META_KEY: payload,
            RESURFACED_HISTORY_KEY: history,
            "pid": None,
            "process_identity": None,
            "proc_id": None,
        },
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
    """Record the one-time resurface. Return True when newly marked.

    Records in both the transient failure object and the durable
    per-acceptance history so clearing the failure on recovery does not
    grant the same acceptance a second allowance.
    """
    if not isinstance(acceptance_id, str) or not acceptance_id:
        return False
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    if not isinstance(raw, dict):
        return False
    history = raw.get(RESURFACED_HISTORY_KEY)
    history = dict(history) if isinstance(history, dict) else {}
    if acceptance_id in history:
        return False
    failure = raw.get(META_KEY)
    if not isinstance(failure, dict):
        return False
    if failure.get("acceptance_id") != acceptance_id:
        return False
    if failure.get("resurfaced") is True:
        # Transient flag already set without history (legacy): adopt it.
        try:
            from datetime import UTC, datetime

            stamp = datetime.now(UTC).isoformat()
        except Exception:
            stamp = None
        from sase.axe.run_agent_helpers_artifacts import update_meta_fields

        history[acceptance_id] = stamp if isinstance(stamp, str) else True
        update_meta_fields(artifacts_dir, {RESURFACED_HISTORY_KEY: history})
        return False
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields

    try:
        from datetime import UTC, datetime

        stamp = datetime.now(UTC).isoformat()
    except Exception:
        stamp = None
    updated = dict(failure)
    updated["resurfaced"] = True
    updated["resurfaced_at"] = stamp
    history[acceptance_id] = stamp if isinstance(stamp, str) else True
    update_meta_fields(
        artifacts_dir, {META_KEY: updated, RESURFACED_HISTORY_KEY: history}
    )
    return True


def record_dismissal_observation(
    artifacts_dir: str, notification_id: str, *, now: float
) -> float:
    """Record first observation of a legacy dismissed row; return its time.

    For dismissed rows with no dismissal timestamp, the first observation
    starts the one-hour wait. Never infers dismissal from failure time.
    """
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        raw = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        raw = {}
    if not isinstance(raw, dict):
        raw = {}
    observed = raw.get(DISMISSAL_OBSERVED_KEY)
    observed = dict(observed) if isinstance(observed, dict) else {}
    existing = observed.get(notification_id)
    if isinstance(existing, (int, float)):
        return float(existing)
    observed[notification_id] = float(now)
    try:
        from sase.axe.run_agent_helpers_artifacts import update_meta_fields

        update_meta_fields(artifacts_dir, {DISMISSAL_OBSERVED_KEY: observed})
    except Exception:
        pass
    return float(now)


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


def gate_execution_failure_resurfaced(
    artifacts_dir: str,
    *,
    acceptance_id: str | None,
) -> bool:
    """Return whether the current acceptance already resurfaced once."""
    if not isinstance(acceptance_id, str) or not acceptance_id:
        return False
    history = _read_history(artifacts_dir)
    if acceptance_id in history:
        return True
    failure = read_gate_execution_failure(artifacts_dir)
    if failure is None:
        return False
    if failure.get("acceptance_id") != acceptance_id:
        return False
    return failure.get("resurfaced") is True


__all__ = [
    "DISMISSAL_OBSERVED_KEY",
    "META_KEY",
    "RESURFACED_HISTORY_KEY",
    "SETTLER_KEYS",
    "apply_member_failure_to_agent",
    "build_gate_execution_failure",
    "clear_gate_execution_failure",
    "clear_gate_member_failure_for_bundle",
    "gate_execution_failure_resurfaced",
    "mark_gate_execution_failure_resurfaced",
    "read_gate_execution_failure",
    "record_dismissal_observation",
    "write_gate_execution_failure",
]
