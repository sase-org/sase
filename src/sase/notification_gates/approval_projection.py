"""Receipt-derived approval labels and honest commit status.

``TALE APPROVED`` / ``EPIC APPROVED`` (and the other branch-specific decision
labels) come from the acceptance receipt so a fresh load does not wait for
option commands to finish. ``PLAN COMMITTED`` waits for archive success and
is rolled back when that archive fails. A durable failure outcome replaces
those labels so an approved decision cannot hide a failed execution.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.agent.status_buckets import (
    EPIC_APPROVED_STATUS,
    EPIC_FAILED_STATUS,
    FEEDBACK_STATUS,
    PLAN_APPROVED_STATUS,
    PLAN_COMMITTED_STATUS,
    PLAN_FAILED_STATUS,
    TALE_APPROVED_STATUS,
)
from sase.axe.agent_meta import write_agent_meta_atomic
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.core.agent_tribe import canonicalize_agent_tribe_metadata
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.paths import RESPONSE_FILENAME

log = logging.getLogger(__name__)

_PLAN_REJECTED_STATUS = "PLAN REJECTED"
_EPIC_REJECTED_STATUS = "EPIC REJECTED"

_COMMIT_ACTION = "commit"
_FAILED_ACTION = "failed"
_EPIC_FAILED_ACTION = "epic_failed"
_PLAN_KINDS = frozenset({"plan", "epic_plan"})


def _decision_projection(
    kind: str,
    selected_option_ids: Sequence[str],
) -> tuple[str | None, str | None]:
    """Return ``(plan_action, display_label)`` for one accepted selection.

    ``plan_action`` is the planner metadata value. ``display_label`` is the
    gate-shell status to show from the receipt. Commit-only selections return
    ``("commit", None)``: the committed label waits for archive success.
    """
    selected = frozenset(selected_option_ids)
    if kind == "epic_plan":
        if selected == frozenset({"approve"}):
            return "epic", EPIC_APPROVED_STATUS
        if selected == frozenset({"reject"}):
            return None, _EPIC_REJECTED_STATUS
        if selected == frozenset({"feedback"}):
            return None, FEEDBACK_STATUS
        return None, None
    if kind != "plan":
        return None, None
    if selected == frozenset({"approve", "commit"}):
        return "tale", TALE_APPROVED_STATUS
    if selected == frozenset({"approve"}):
        return "approve", PLAN_APPROVED_STATUS
    if selected == frozenset({"commit"}):
        return _COMMIT_ACTION, None
    if selected == frozenset({"reject"}):
        return None, _PLAN_REJECTED_STATUS
    if selected == frozenset({"feedback"}):
        return None, FEEDBACK_STATUS
    return None, None


def _failure_projection(kind: str) -> tuple[str, str]:
    """Return ``(plan_action, display_label)`` for a failed execution."""
    if kind == "epic_plan":
        return _EPIC_FAILED_ACTION, EPIC_FAILED_STATUS
    return _FAILED_ACTION, PLAN_FAILED_STATUS


def project_accepted_decision(
    bundle_path: Path,
    envelope: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> None:
    """Project an accepted decision into planner and gate-shell metadata."""
    kind = str(envelope.get("kind") or "")
    if kind not in _PLAN_KINDS:
        return
    selected = _selected_option_ids(receipt)
    action, label = _decision_projection(kind, selected)
    try:
        if action is not None and action != _COMMIT_ACTION:
            _write_planner_projection(
                envelope,
                {
                    "plan_approved": True,
                    "plan_action": action,
                },
            )
        if label is not None:
            _write_gate_shell_projection(
                envelope,
                {"gate_start_status": label},
            )
    except Exception:
        log.warning(
            "Failed to project accepted gate decision into status metadata",
            extra={"bundle_path": str(bundle_path)},
            exc_info=True,
        )


def project_plan_committed(
    bundle_path: Path,
    envelope: Mapping[str, Any] | None = None,
    *,
    action: str | None = None,
) -> None:
    """Show ``PLAN COMMITTED`` after archive success and record commit state."""
    resolved = envelope if envelope is not None else _envelope(bundle_path)
    if resolved is None:
        return
    kind = str(resolved.get("kind") or "")
    try:
        fields: dict[str, Any] = {"plan_committed": True}
        resolved_action = action
        if resolved_action is None:
            receipt = _receipt(bundle_path)
            selected = _selected_option_ids(receipt) if receipt is not None else ()
            resolved_action, _label = _decision_projection(kind, selected)
        if resolved_action == _COMMIT_ACTION:
            fields["plan_approved"] = True
            fields["plan_action"] = _COMMIT_ACTION
            _write_gate_shell_projection(
                resolved,
                {"gate_start_status": PLAN_COMMITTED_STATUS},
            )
        _write_planner_projection(resolved, fields)
    except Exception:
        log.warning(
            "Failed to project plan commit status after archive success",
            extra={"bundle_path": str(bundle_path)},
            exc_info=True,
        )


def project_execution_failure(
    bundle_path: Path,
    envelope: Mapping[str, Any] | None = None,
) -> None:
    """Replace approved/committed labels with the distinct failure status."""
    resolved = envelope if envelope is not None else _envelope(bundle_path)
    if resolved is None:
        return
    kind = str(resolved.get("kind") or "")
    if kind not in _PLAN_KINDS:
        return
    action, label = _failure_projection(kind)
    try:
        _write_planner_projection(
            resolved,
            {
                "plan_action": action,
                "plan_committed": False,
            },
        )
        _write_gate_shell_projection(
            resolved,
            {"gate_start_status": label, "gate_stop_status": label},
        )
    except Exception:
        log.warning(
            "Failed to project gate execution failure into status metadata",
            extra={"bundle_path": str(bundle_path)},
            exc_info=True,
        )


def projected_gate_status(bundle_path: Path) -> str | None:
    """Return the receipt-derived gate label for a fresh load, if any.

    Commit-only receipts stay silent until archive success so the committed
    label cannot appear early. Failure metadata written beside the receipt
    wins over the approved label.
    """
    envelope = _envelope(bundle_path)
    if envelope is None:
        return None
    kind = str(envelope.get("kind") or "")
    if kind not in _PLAN_KINDS:
        return None
    receipt = _receipt(bundle_path)
    if receipt is None:
        return None
    selected = _selected_option_ids(receipt)
    action, label = _decision_projection(kind, selected)
    if action == _COMMIT_ACTION:
        return PLAN_COMMITTED_STATUS if _archive_succeeded(bundle_path) else None
    return label


def _selected_option_ids(receipt: Mapping[str, Any]) -> tuple[str, ...]:
    raw = receipt.get("selected_option_ids")
    if not isinstance(raw, list):
        return ()
    return tuple(str(item) for item in raw if isinstance(item, str))


def _envelope(bundle_path: Path) -> dict[str, Any] | None:
    request_path = bundle_path / "request.json"
    if not request_path.exists():
        return None
    try:
        payload = read_json_object(request_path)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _receipt(bundle_path: Path) -> dict[str, Any] | None:
    from sase.notification_gates.decision import DECISION_RECEIPT_FILENAME

    receipt_path = bundle_path / DECISION_RECEIPT_FILENAME
    if not receipt_path.exists():
        return None
    try:
        payload = read_json_object(receipt_path)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _archive_succeeded(bundle_path: Path) -> bool:
    response_path = bundle_path / RESPONSE_FILENAME
    if not response_path.exists():
        return False
    try:
        response = read_json_object(response_path)
    except Exception:
        return False
    if not isinstance(response, dict):
        return False
    if response.get("plan_archive_state") == "archived":
        return True
    option_results = response.get("option_results")
    if not isinstance(option_results, list):
        return False
    for entry in option_results:
        if not isinstance(entry, Mapping):
            continue
        result = entry.get("result")
        if (
            isinstance(result, Mapping)
            and result.get("plan_archive_state") == "archived"
        ):
            return True
    return False


def _write_planner_projection(
    envelope: Mapping[str, Any],
    fields: Mapping[str, Any],
) -> None:
    artifacts_dir = _planner_artifacts_dir(envelope)
    if artifacts_dir is None:
        return
    _patch_agent_meta(artifacts_dir, fields)


def _write_gate_shell_projection(
    envelope: Mapping[str, Any],
    fields: Mapping[str, Any],
) -> None:
    from sase.axe.run_agent_helpers_artifacts import update_meta_fields
    from sase.gate_shell.store import find_gate_shell_by_gate_id

    if not isinstance(envelope.get("shell"), dict):
        return
    gate_id = str(envelope.get("request_id") or "")
    if not gate_id:
        return
    record = find_gate_shell_by_gate_id(None, gate_id)
    if record is None:
        return
    update_meta_fields(record.artifacts_dir, dict(fields))


def _planner_artifacts_dir(envelope: Mapping[str, Any]) -> str | None:
    from sase._plan_approval_artifacts import resolve_plan_agent_artifacts_dir

    action_data: dict[str, str] = {}
    presentation = envelope.get("presentation")
    if isinstance(presentation, Mapping):
        raw = presentation.get("action_data")
        if isinstance(raw, Mapping):
            action_data = {
                str(key): str(value)
                for key, value in raw.items()
                if isinstance(key, str) and isinstance(value, str)
            }
    producer = envelope.get("producer")
    if isinstance(producer, Mapping):
        artifacts = producer.get("artifacts_dir")
        if isinstance(artifacts, str) and artifacts.strip():
            action_data.setdefault("artifacts_dir", artifacts)
    return resolve_plan_agent_artifacts_dir(action_data)


def _patch_agent_meta(artifacts_dir: str, fields: Mapping[str, Any]) -> None:
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        meta = payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        meta = {}
    meta.update(fields)
    canonicalize_agent_tribe_metadata(meta)
    try:
        write_agent_meta_atomic(
            artifacts_dir,
            meta,
            index_updater=update_agent_artifact_index_for_marker_mutation,
        )
    except OSError:
        pass


__all__ = [
    "project_accepted_decision",
    "project_execution_failure",
    "project_plan_committed",
    "projected_gate_status",
]
