"""Gate identity, presentation, and notification helpers for task triage."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal

from sase.bead.flag_due import flag_removal_due
from sase.bead.flag_fields import FLAG_TASK_TYPE, flag_fields
from sase.bead.flag_gate import FLAG_TRIAGE_KIND
from sase.bead.model import FlagRecord, Issue, SnoozeRecord, Status
from sase.bead.snooze_gate import BEAD_SNOOZE_KIND
from sase.bead.task_gate import TASK_TRIAGE_KIND
from sase.core.time import get_timezone
from sase.notification_gates.durability import read_json_object
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import bundle_paths
from sase.notification_gates.poller import poll_gate

GateState = Literal["pending", "terminal", "missing"]

REQUEST_ID_PREFIXES = {
    TASK_TRIAGE_KIND: "bead-task-triage",
    BEAD_SNOOZE_KIND: "bead-snooze",
    FLAG_TRIAGE_KIND: "bead-flag-triage",
}


def expected_gate_kind(issue: Issue) -> str:
    """Return the one gate kind a live bead's status and type call for."""
    if issue.task_type == FLAG_TASK_TYPE:
        return FLAG_TRIAGE_KIND
    return BEAD_SNOOZE_KIND if issue.status == Status.SNOOZED else TASK_TRIAGE_KIND


def request_id(project_name: str, bead_id: str, generation: int, kind: str) -> str:
    identity = f"{project_name}\0{bead_id}".encode()
    digest = hashlib.sha256(identity).hexdigest()[:12]
    bead_component = bead_id[:80]
    prefix = REQUEST_ID_PREFIXES[kind]
    return f"{prefix}-{bead_component}-{digest}-g{generation}"


def presentation_fingerprint(
    issue: Issue,
    *,
    format_version: int,
    gate_contract_version: int,
    flag_due_state: str | None = None,
    task_type_display: Mapping[str, object] | None = None,
) -> str:
    """Hash every persisted field and contract version that changes a gate.

    The snooze record is part of it because both the wake gate's notification
    note and its preview render the wake conditions: a re-snooze must replace
    the pending gate rather than leave it advertising the old wake time. A
    flag block -- key, kind, both thresholds, and *flag_due_state* -- is
    added only when :func:`~sase.bead.flag_fields.flag_fields` can read the
    bead, so no existing task gate's fingerprint changes. ``due_as_of`` and
    ``release`` are deliberately not part of it: they are presentation
    pinning, and including them would cancel and recreate every pending
    flag gate daily.

    A ``task_type_display`` block is added only when the caller supplies the
    frozen glyph/name/accent/facts mapping, so an untyped bead's fingerprint
    keeps the same keys. The block is hashed rather than the raw
    ``task_type`` slug: installing, upgrading, or removing a plugin -- or
    editing ``bead.task_types`` -- changes a pending gate's presentation
    without mutating the bead.

    The supplied versions cover renderer and trusted-interaction changes whose
    outputs cannot be inferred from the bead fields alone.
    """
    snooze = issue.snooze
    payload: dict[str, Any] = {
        "format_version": format_version,
        "gate_contract_version": gate_contract_version,
        "status": issue.status.value,
        "snooze": (
            None
            if snooze is None
            else {
                "until": snooze.until,
                "snoozed_at": snooze.snoozed_at,
                "snoozed_by": snooze.snoozed_by,
                "plus_one_target": snooze.plus_one_target,
                "plus_one_baseline": snooze.plus_one_baseline,
                "reason": snooze.reason,
            }
        ),
        "title": issue.title,
        "description": issue.description,
        "notes": issue.notes,
        "created_at": issue.created_at,
        "size": issue.size.value if issue.size else None,
        "refs": list(issue.refs),
        "plus_one_evidence": [
            {
                "timestamp": evidence.timestamp,
                "reporter": evidence.reporter,
                "note": evidence.note,
                "refs": list(evidence.refs),
            }
            for evidence in issue.plus_one_evidence
        ],
        "close_history": [
            {
                "closed_at": record.closed_at,
                "close_reason": record.close_reason,
                "resolution": record.resolution.value if record.resolution else None,
                "reopened_at": record.reopened_at,
                "reopened_via": record.reopened_via.value,
                "reopened_by": record.reopened_by,
            }
            for record in issue.close_history
        ],
    }
    fields = flag_fields(issue)
    if fields is not None:
        payload["flag"] = {
            "key": fields.key,
            "kind": fields.kind,
            "remove_by_date": fields.remove_by_date,
            "remove_by_release": fields.remove_by_release,
            "due_state": flag_due_state,
        }
    if task_type_display is not None:
        payload["task_type_display"] = task_type_display
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def gate_state(kind: str, request_id: str) -> GateState:
    paths = bundle_paths(kind, request_id)
    if not paths.request.is_file():
        return "missing"
    return "pending" if poll_gate(paths.root) is None else "terminal"


def cancel_pending_gate(
    kind: str,
    request_id: str,
    *,
    reason: str = "task_bead_no_longer_ready",
) -> bool:
    paths = bundle_paths(kind, request_id)
    try:
        cancel_gate(
            paths.root,
            reason=reason,
            source="bead_task_triage",
        )
    except GateError as exc:
        if exc.code == "already_answered":
            return False
        raise
    return True


def gate_notification_id(kind: str, request_id: str) -> str | None:
    """Return the notification a pending gate published, if it named one."""
    try:
        envelope = read_json_object(bundle_paths(kind, request_id).request)
    except (GateError, OSError):
        return None
    notification_id = envelope.get("notification_id")
    if isinstance(notification_id, str) and notification_id:
        return notification_id
    return None


def _parse_instant(value: str | None) -> datetime | None:
    """Parse one offset-bearing ISO-8601 instant, or return None."""
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


@dataclass
class NotificationSnoozeIndex:
    """The snooze state of every live notification, read at most once."""

    _rows: dict[str, tuple[bool, str | None]] | None = None

    def snooze_state(self, notification_id: str) -> tuple[bool, str | None] | None:
        if self._rows is None:
            from sase.notifications.store import load_notifications

            self._rows = {
                notification.id: (notification.muted, notification.snooze_until)
                for notification in load_notifications()
            }
        return self._rows.get(notification_id)

    def forget(self, notification_id: str) -> None:
        """Drop one row so a later pass re-reads what this chop just wrote."""
        if self._rows is not None:
            self._rows.pop(notification_id, None)


def heal_snoozed_notification(
    request_id: str,
    snooze: SnoozeRecord | None,
    index: NotificationSnoozeIndex,
    *,
    notification_id_for: Callable[[str, str], str | None],
) -> bool:
    """Re-snooze a wake gate's notification that drifted from its wake time.

    This keeps a snoozed bead's notification snoozed to its wake time after a
    crash or manual unmute. A wake time already in the past is left alone: the
    notification snooze expiry has legitimately resurfaced that row.
    """
    wake = _parse_instant(snooze.until if snooze is not None else None)
    if wake is None or wake <= datetime.now(get_timezone()):
        return False
    notification_id = notification_id_for(BEAD_SNOOZE_KIND, request_id)
    if notification_id is None:
        return False
    state = index.snooze_state(notification_id)
    if state is None:
        return False
    muted, snooze_until = state
    if muted and _parse_instant(snooze_until) == wake:
        return False
    from sase.notifications.store import mark_snoozed

    if not mark_snoozed(notification_id, wake):
        return False
    index.forget(notification_id)
    return True


def create_gate(
    kind: str,
    *,
    request_id: str,
    bead_id: str,
    project_name: str,
    issue: Issue,
    task_gate_factory: Callable[..., Any],
    snooze_gate_factory: Callable[..., Any],
    flag_gate_factory: Callable[..., Any],
) -> None:
    """Create the one gate this bead's status and type call for."""
    if kind == FLAG_TRIAGE_KIND:
        fields = flag_fields(issue)
        if fields is None:
            raise ValueError(f"flag bead {bead_id} has no flag metadata")
        import sase
        from sase.core import time as core_time
        from sase.feature_flags.registry import feature_flag_definitions

        today = core_time.local_now().date()
        release = sase.__version__
        due_state = flag_removal_due(
            fields.remove_by_date,
            fields.remove_by_release,
            today=today,
            release=release,
        )
        definition = feature_flag_definitions().get(fields.key)
        flag_gate_factory(
            request_id=request_id,
            bead_id=bead_id,
            project=project_name,
            title=issue.title,
            flag=FlagRecord(
                key=fields.key,
                remove_by_date=fields.remove_by_date,
                remove_by_release=fields.remove_by_release,
            ),
            kind=fields.kind,
            due_state=due_state,
            due_as_of=today.isoformat(),
            release=release,
            definition=(
                {"kind": definition.kind, "description": definition.description}
                if definition is not None
                else None
            ),
            description=issue.description,
            notes=issue.notes,
            created_by=issue.created_by,
            created_at=issue.created_at,
            size=issue.size.value if issue.size else None,
            refs=issue.refs,
            task_type=issue.task_type or FLAG_TASK_TYPE,
            task_type_fields=dict(issue.task_type_fields),
            producer={"chop": "bead_task_triage", "project": project_name},
        )
        return
    common: dict[str, Any] = {
        "request_id": request_id,
        "bead_id": bead_id,
        "project": project_name,
        "title": issue.title,
        "description": issue.description,
        "notes": issue.notes,
        "created_by": issue.created_by,
        "created_at": issue.created_at,
        "size": issue.size.value if issue.size else None,
        "refs": issue.refs,
        "plus_one_evidence": issue.plus_one_evidence,
        "close_history": issue.close_history,
        "closed_at": issue.closed_at,
        "task_type": issue.task_type,
        "task_type_fields": dict(issue.task_type_fields),
        "producer": {"chop": "bead_task_triage", "project": project_name},
    }
    if kind == TASK_TRIAGE_KIND:
        task_gate_factory(**common)
        return
    if issue.snooze is None:
        raise ValueError(f"snoozed task {bead_id} has no snooze record")
    snooze_gate_factory(snooze=issue.snooze, **common)
