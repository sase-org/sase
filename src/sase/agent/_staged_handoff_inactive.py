"""Failed-origin inactive settlement for staged handoffs.

Collects the typed host observations the shared Rust inactive-stage policy
decides on, and persists an identity-scoped durable settlement marker once
the host settles a never-started stage's resources.

The settlement marker is evidence, not authorization: making a stage
inactive never permits running its command or launching its successor. It
only lets admission, lane, owner, and stranded queries stop treating the
dead stage as pending ownership. Readers always match the marker against
the current staged record identity, so an old marker never suppresses a
replacement stage. The original stage, receipt, launch payload, response,
and recovery context are retained for explicit ``sase agent readopt``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sase.core.staged_handoff import STAGED_HANDOFF_WIRE_SCHEMA_VERSION

INACTIVE_SETTLEMENT_SCHEMA_VERSION = 1
INACTIVE_SETTLEMENT_FILENAME = ".sase_handoff_settled_inactive.json"

_FAILED_ORIGIN_OUTCOMES = frozenset({"failed", "epic_launch_failed"})
_FINALIZER_ACTIVE_PHASES = frozenset({"declaring", "executing"})
_SUCCESSOR_PRESENT_DELIVERY_STATES = frozenset(
    {"submitted", "started", "owned", "terminal"}
)


def observe_inactive_stage_request(
    artifacts_dir: str,
    *,
    staged_delivered: bool | None = None,
) -> dict[str, Any] | None:
    """Build the Rust inactive-stage request for one origin, or ``None``.

    Returns ``None`` when there is no stage or receipt evidence to decide
    on, or when the facts cannot be read. Read-only: never mutates resources.
    Malformed stage or receipt state is reported as malformed validity so the
    Rust policy preserves the conservative pending owner.
    """
    from sase.agent._staged_handoff_receipts import read_adoption_receipt
    from sase.agent._staged_handoff_store import (
        StagedHandoffError,
        read_staged_handoff,
    )

    try:
        root = str(artifacts_dir or "").strip()
        if not root:
            return None
        staged_record: Any = None
        try:
            staged_record = read_staged_handoff(root)
        except StagedHandoffError:
            staged_record = "malformed"
        if staged_record == "malformed":
            stage_validity, stage_id = "malformed", None
            kind = None
        elif staged_record is None:
            stage_validity, stage_id = "absent", None
            kind = None
        else:
            raw_id = staged_record.get("staged_id")
            stage_id = raw_id if isinstance(raw_id, str) and raw_id else None
            stage_validity = "valid"
            raw_kind = staged_record.get("kind")
            kind = raw_kind if isinstance(raw_kind, str) and raw_kind else None
        receipt: Any = None
        try:
            receipt = read_adoption_receipt(root)
        except StagedHandoffError:
            receipt = "malformed"
        if receipt == "malformed":
            receipt_validity, receipt_id, receipt_outcome = (
                "malformed",
                None,
                None,
            )
        elif receipt is None:
            receipt_validity, receipt_id, receipt_outcome = (
                "absent",
                None,
                None,
            )
        else:
            raw_rid = receipt.get("staged_id")
            receipt_id = raw_rid if isinstance(raw_rid, str) and raw_rid else None
            receipt_outcome = _receipt_outcome(receipt, receipt_id)
            receipt_validity = "valid"
        if stage_validity == "absent" and receipt_validity == "absent":
            return None
        origin_id, origin_identity_valid = _observe_origin_identity(root)
        origin_outcome, origin_finalizing = _observe_origin_terminal(root)
        delivered = (
            staged_delivered
            if staged_delivered is not None
            else _observe_delivered(root, staged_record, kind)
        )
        execution_state = _observe_execution(
            root, staged_record, kind, stage_id, receipt_id, delivered
        )
        recovery_state = _observe_recovery(root)
        return {
            "schema_version": STAGED_HANDOFF_WIRE_SCHEMA_VERSION,
            "stage_validity": stage_validity,
            "stage_id": stage_id,
            "receipt_validity": receipt_validity,
            "receipt_id": receipt_id,
            "receipt_outcome": receipt_outcome,
            "origin_id": origin_id,
            "origin_identity_valid": origin_identity_valid,
            "origin_outcome": origin_outcome,
            "origin_finalizing": origin_finalizing,
            "execution_state": execution_state,
            "recovery_state": recovery_state,
            "successor_delivered": delivered,
        }
    except Exception:
        return None


def observe_inactive_stage_for_monitor_id(
    monitor_id: str,
) -> dict[str, Any] | None:
    """Build the inactive-stage request for one staged monitor, or ``None``.

    Resolves the starter origin through the staged-owner index and observes
    the starter's facts. Returns ``None`` when the index does not identify a
    current stage, so a stale index row can never suppress a replacement.
    """
    return observe_inactive_stage_for_monitor(monitor_id)


def observe_inactive_stage_for_monitor(
    monitor_id: str, member_artifacts_dir: str | None = None
) -> dict[str, Any] | None:
    """Build the inactive-stage request for one staged monitor, or ``None``.

    Resolves the starter origin through the staged-owner index, falling back
    to the member's frozen launch payload once settlement has removed the
    stale pending-owner row. The candidate stage is always verified against
    the starter's current staged record, so neither a stale index row nor a
    stale payload can suppress a replacement stage.
    """
    from sase.monitor.staged_owner import read_staged_owner_index

    monitor = (monitor_id or "").strip()
    if not monitor:
        return None
    try:
        index = read_staged_owner_index(monitor)
    except Exception:
        index = None
    if isinstance(index, dict):
        request = _observe_indexed_stage(index)
        if request is not None:
            return request
    return _observe_payload_stage(member_artifacts_dir)


def _observe_indexed_stage(index: dict[str, Any]) -> dict[str, Any] | None:
    """Observe the starter named by an owner-index row, identity-checked."""
    staged_id = index.get("staged_id")
    starter = index.get("starter_artifacts_dir")
    return _observe_verified_starter(starter, staged_id)


def _observe_payload_stage(
    member_artifacts_dir: str | None,
) -> dict[str, Any] | None:
    """Observe the starter named by a member's frozen launch payload."""
    if not isinstance(member_artifacts_dir, str) or not member_artifacts_dir.strip():
        return None
    try:
        payload = json.loads(
            (
                Path(member_artifacts_dir.strip()) / "staged_monitor_launch.json"
            ).read_text(encoding="utf-8")
        )
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    staged_id = payload.get("staged_id")
    workspace = payload.get("workspace")
    claim = workspace.get("claim_context") if isinstance(workspace, dict) else None
    starter = claim.get("starter_artifacts_dir") if isinstance(claim, dict) else None
    return _observe_verified_starter(starter, staged_id)


def _observe_verified_starter(starter: Any, staged_id: Any) -> dict[str, Any] | None:
    """Observe one starter only when it still holds *staged_id*."""
    if not isinstance(staged_id, str) or not staged_id:
        return None
    if not isinstance(starter, str) or not starter.strip():
        return None
    try:
        from sase.agent._staged_handoff_store import read_staged_handoff

        current = read_staged_handoff(starter)
    except Exception:
        return None
    if not isinstance(current, dict) or current.get("staged_id") != staged_id:
        return None
    return observe_inactive_stage_request(starter)


def _receipt_outcome(receipt: dict[str, Any], receipt_id: str | None) -> str | None:
    if not isinstance(receipt_id, str) or not receipt_id:
        return None
    try:
        from sase.agent._staged_handoff_receipts import receipt_authorizes
    except Exception:
        receipt_authorizes = None  # type: ignore[assignment]
    if receipt_authorizes is not None:
        try:
            if receipt_authorizes(receipt, receipt_id):
                return "adopted"
        except Exception:
            return None
    else:
        if receipt.get("outcome") == "adopted":
            return "adopted"
    if receipt.get("outcome") == "handoff_not_adopted":
        return "held"
    return None


def _observe_origin_identity(root: str) -> tuple[str | None, bool]:
    try:
        metadata = json.loads((Path(root) / "agent_meta.json").read_text())
    except Exception:
        metadata = None
    if not isinstance(metadata, dict):
        return Path(root).name or None, False
    for key in ("name", "agent_session"):
        raw = metadata.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip(), True
    return Path(root).name or None, False


def _observe_origin_terminal(root: str) -> tuple[str, bool]:
    finalizing = _origin_finalizing(root)
    try:
        done = json.loads((Path(root) / "done.json").read_text())
    except Exception:
        done = None
    if isinstance(done, dict):
        outcome = done.get("outcome")
        if isinstance(outcome, str) and outcome.strip():
            if outcome.strip() in _FAILED_ORIGIN_OUTCOMES:
                return "failed", False
            return "succeeded", False
        return "unknown", bool(finalizing)
    if finalizing:
        return "running", True
    if _origin_process_alive(root):
        return "running", False
    return "unknown", False


def _origin_finalizing(root: str) -> bool:
    try:
        metadata = json.loads((Path(root) / "agent_meta.json").read_text())
    except Exception:
        return False
    if not isinstance(metadata, dict):
        return False
    summary = metadata.get("finalizer_status")
    if not isinstance(summary, dict):
        return False
    phase = summary.get("phase")
    return isinstance(phase, str) and phase.strip().lower() in _FINALIZER_ACTIVE_PHASES


def _origin_process_alive(root: str) -> bool:
    try:
        metadata = json.loads((Path(root) / "agent_meta.json").read_text())
    except Exception:
        return False
    if not isinstance(metadata, dict):
        return False
    pid = metadata.get("pid")
    if type(pid) is not int or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _observe_delivered(root: str, staged_record: Any, kind: str | None) -> bool:
    if not isinstance(staged_record, dict):
        return False
    try:
        from sase.axe._run_agent_exec_staged_recovery_shared import (
            adopted_stage_needs_delivery,
            classify_receipt,
        )
        from sase.axe.run_agent_exec_staged_recovery_facts import (
            observe_destination,
        )
    except Exception:
        return False
    try:
        staged_id = staged_record.get("staged_id")
        if not isinstance(staged_id, str) or not staged_id:
            return False
        receipt_state, receipt = classify_receipt(root, staged_id)
        if receipt_state != "adopted":
            return False
        if not adopted_stage_needs_delivery(receipt, kind):
            return True
        return observe_destination(staged_record, artifacts_dir=root) in (
            "owned",
            "terminal",
        )
    except Exception:
        return False


def _observe_execution(
    root: str,
    staged_record: Any,
    kind: str | None,
    stage_id: str | None,
    receipt_id: str | None,
    delivered: bool,
) -> str:
    """Return ``present``, ``absent``, or ``unknown`` for observed execution.

    A positively delivered successor proves the command ran. Otherwise a
    submitted proc row or a recorded successor counts as present execution;
    only positively empty probes report absence. Any unreadable probe keeps
    the conservative unknown state, which never enters the absence branch.
    """
    if delivered:
        return "present"
    identity = stage_id or receipt_id
    if kind == "monitor" or kind is None:
        monitor_ids = _monitor_ids_for_stage(root, staged_record, identity)
        if monitor_ids is None:
            return "unknown"
        try:
            from sase.procs.store import get_proc
        except Exception:
            return "unknown"
        try:
            for monitor_id in monitor_ids:
                if get_proc(monitor_id) is not None:
                    return "present"
        except Exception:
            return "unknown"
        if kind == "monitor" and not monitor_ids:
            return "unknown"
        if _successor_present(root, identity):
            return "present"
        if _successor_unknown(root, identity):
            return "unknown"
        return "absent"
    try:
        if _successor_present(root, identity):
            return "present"
        if _successor_unknown(root, identity):
            return "unknown"
    except Exception:
        return "unknown"
    return "absent"


def _monitor_ids_for_stage(
    root: str, staged_record: Any, identity: str | None
) -> list[str] | None:
    """Return monitor ids evidencing this stage, or ``None`` when unknown."""
    ids: list[str] = []
    if isinstance(staged_record, dict):
        payload = staged_record.get("payload")
        if isinstance(payload, dict):
            raw = payload.get("monitor_id")
            if isinstance(raw, str) and raw.strip():
                ids.append(raw.strip())
    try:
        from sase.monitor.staged_owner import STAGED_OWNER_DIRNAME
        from sase.core.paths import sase_home
    except Exception:
        return ids
    try:
        index_dir = sase_home() / STAGED_OWNER_DIRNAME
        rows = list(index_dir.glob("*.json"))
    except Exception:
        return ids
    for row in rows:
        try:
            payload = json.loads(row.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        if identity is not None and payload.get("staged_id") != identity:
            continue
        starter = payload.get("starter_artifacts_dir")
        member = payload.get("artifacts_dir")
        if starter != root and member != root:
            continue
        monitor_id = row.stem
        if monitor_id and monitor_id not in ids:
            ids.append(monitor_id)
    return ids


def _successor_present(root: str, identity: str | None) -> bool:
    if not identity:
        return False
    try:
        from sase.agent._staged_handoff_successor import read_staged_successor
    except Exception:
        raise
    successor = read_staged_successor(root, staged_id=identity)
    if successor is None:
        return False
    state = successor.get("delivery_state")
    return isinstance(state, str) and bool(state.strip())


def _successor_unknown(root: str, identity: str | None) -> bool:
    if not identity:
        return False
    try:
        from sase.agent._staged_handoff_successor import read_staged_successor
        from sase.agent._staged_handoff_store import StagedHandoffError
    except Exception:
        return True
    try:
        read_staged_successor(root, staged_id=identity)
    except StagedHandoffError:
        return True
    except Exception:
        return True
    return False


def _observe_recovery(root: str) -> str:
    try:
        from sase.agent.auto_restart.forward import recovery_in_flight
    except Exception:
        return "unknown"
    try:
        return "active" if recovery_in_flight(root) else "inactive"
    except Exception:
        return "unknown"


def read_inactive_settlement(artifacts_dir: str) -> dict[str, Any] | None:
    """Return the durable inactive-settlement marker, or ``None``.

    Absent, unreadable, and malformed markers all read as no settlement, so a
    corrupt marker keeps the conservative pending owner instead of hiding it.
    """
    try:
        payload = json.loads(
            (Path(str(artifacts_dir)) / INACTIVE_SETTLEMENT_FILENAME).read_text(
                encoding="utf-8"
            )
        )
    except (FileNotFoundError, NotADirectoryError):
        return None
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema_version") != INACTIVE_SETTLEMENT_SCHEMA_VERSION:
        return None
    staged_id = payload.get("staged_id")
    if not isinstance(staged_id, str) or not staged_id:
        return None
    return payload


def write_inactive_settlement_locked(
    payload: dict[str, Any], *, artifacts_dir: str
) -> Path:
    """Persist the inactive-settlement marker. The caller holds the locks."""
    from sase.core.atomic_json import write_json_marker_atomic

    path = Path(str(artifacts_dir)) / INACTIVE_SETTLEMENT_FILENAME
    write_json_marker_atomic(path, dict(payload))
    return path


def clear_inactive_settlement_locked(
    artifacts_dir: str, *, staged_id: str | None = None
) -> bool:
    """Remove the settlement marker, optionally only for one staged ID.

    Returns whether a marker was removed. A marker for a different staged ID
    is left untouched so genuine execution of a replacement stage cannot be
    confused with the settled one.
    """
    path = Path(str(artifacts_dir)) / INACTIVE_SETTLEMENT_FILENAME
    if staged_id is not None:
        current = read_inactive_settlement(str(artifacts_dir))
        if current is None or current.get("staged_id") != staged_id:
            return False
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def settlement_matches_stage(artifacts_dir: str, staged_id: str | None) -> bool:
    """Return whether the durable marker settles exactly *staged_id*."""
    if not isinstance(staged_id, str) or not staged_id:
        return False
    marker = read_inactive_settlement(artifacts_dir)
    return marker is not None and marker.get("staged_id") == staged_id


__all__ = [
    "INACTIVE_SETTLEMENT_FILENAME",
    "INACTIVE_SETTLEMENT_SCHEMA_VERSION",
    "clear_inactive_settlement_locked",
    "observe_inactive_stage_for_monitor",
    "observe_inactive_stage_for_monitor_id",
    "observe_inactive_stage_request",
    "read_inactive_settlement",
    "settlement_matches_stage",
    "write_inactive_settlement_locked",
]
