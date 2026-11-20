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
from sase.bead.model import Issue, SnoozeRecord, Status
from sase.bead.snooze_gate import BEAD_SNOOZE_KIND
from sase.bead.task_gate import TASK_TRIAGE_KIND
from sase.core.time import get_timezone
from sase.notification_gates.durability import file_lock, read_json_object
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import (
    CANCELLATION_FILENAME,
    RESPONSE_FILENAME,
    assert_owned_bundle,
    bundle_paths,
    interaction_requests_dir,
)
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
    """Hash every persisted field and contract version the bead's gate renders.

    The hash covers what the gate kind :func:`expected_gate_kind` picks would
    show, so editing a field that gate never renders does not cancel and
    recreate it. Inputs a kind does not render are pinned to their empty
    value rather than dropped, so a pending gate's stored fingerprint
    survives this rule: the FlagTriage gate renders neither +1 evidence nor
    close history, and only the BeadSnooze gate renders the snooze record.
    ``status`` stays because each kind implies exactly one gateable status.

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
    kind = expected_gate_kind(issue)
    renders_history = kind != FLAG_TRIAGE_KIND
    snooze = issue.snooze if kind == BEAD_SNOOZE_KIND else None
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
        "notes": issue.notes_text,
        "created_at": issue.created_at,
        "size": issue.size.value if issue.size else None,
        "refs": list(issue.refs),
        "plus_one_evidence": [
            {
                "timestamp": evidence.timestamp,
                "reporter": evidence.reporter,
                "note": evidence.note,
                "refs": list(evidence.refs),
                **(
                    {"observed_since": evidence.observed_since}
                    if evidence.observed_since
                    else {}
                ),
                **(
                    {
                        "attachments": [
                            {
                                "name": attachment.name,
                                "sha256": attachment.sha256,
                                "size_bytes": attachment.size_bytes,
                                "mime_type": attachment.mime_type,
                            }
                            for attachment in getattr(evidence, "attachments", ())
                        ]
                    }
                    if getattr(evidence, "attachments", ())
                    else {}
                ),
            }
            for evidence in (issue.plus_one_evidence if renders_history else ())
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
            for record in (issue.close_history if renders_history else ())
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
    settle_notification: bool = True,
) -> bool:
    """Cancel one pending gate; ``False`` means a response already won.

    ``settle_notification=False`` retires a gate whose notification row a
    successor gate already adopted, so the row stays live for the successor.
    """
    paths = bundle_paths(kind, request_id)
    try:
        cancel_gate(
            paths.root,
            reason=reason,
            source="bead_task_triage",
            settle_notification=settle_notification,
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
class NotificationIndex:
    """The snooze and dismissal state of every row, read at most once.

    Dismissed rows are included so orphan reconciliation can see a user
    dismissal: the store read uses ``include_dismissed=True``.
    """

    _rows: dict[str, tuple[bool, str | None, str | None, bool]] | None = None

    def _row(
        self, notification_id: str
    ) -> tuple[bool, str | None, str | None, bool] | None:
        if self._rows is None:
            from sase.notifications.store import load_notifications

            self._rows = {
                notification.id: (
                    notification.muted,
                    notification.snooze_until,
                    notification.action_data.get("request_id"),
                    notification.dismissed,
                )
                for notification in load_notifications(include_dismissed=True)
            }
        return self._rows.get(notification_id)

    def snooze_state(self, notification_id: str) -> tuple[bool, str | None] | None:
        row = self._row(notification_id)
        return None if row is None else (row[0], row[1])

    def presented_request_id(self, notification_id: str) -> str | None:
        """Return the gate request a live row currently presents, if any."""
        row = self._row(notification_id)
        return None if row is None else row[2]

    def is_dismissed(self, notification_id: str) -> bool | None:
        """Return dismissal state, or ``None`` when the row is gone.

        A missing row means the notification was archived or deleted, which
        is not a user dismissal: callers treat ``None`` as not dismissed.
        """
        row = self._row(notification_id)
        return None if row is None else bool(row[3])

    def forget(self, notification_id: str) -> None:
        """Drop one row so a later pass re-reads what this chop just wrote."""
        if self._rows is not None:
            self._rows.pop(notification_id, None)


def heal_snoozed_notification(
    request_id: str,
    snooze: SnoozeRecord | None,
    index: NotificationIndex,
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
    notification_id: str | None = None,
) -> Any:
    """Create the one gate this bead's status and type call for.

    ``notification_id`` names the row of the pending gate this one
    supersedes; the factory's gate adopts it instead of appending a row.
    Returns the factory's creation result.
    """
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
        return flag_gate_factory(
            request_id=request_id,
            bead_id=bead_id,
            project=project_name,
            title=issue.title,
            flag=fields,
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
            notes=issue.notes_text,
            created_by=issue.created_by,
            created_at=issue.created_at,
            size=issue.size.value if issue.size else None,
            refs=issue.refs,
            task_type=issue.task_type or FLAG_TASK_TYPE,
            task_type_fields=dict(issue.task_type_fields),
            producer={"chop": "bead_task_triage", "project": project_name},
            notification_id=notification_id,
        )
    common: dict[str, Any] = {
        "request_id": request_id,
        "bead_id": bead_id,
        "project": project_name,
        "title": issue.title,
        "description": issue.description,
        "notes": issue.notes_text,
        "created_by": issue.created_by,
        "created_at": issue.created_at,
        "size": issue.size.value if issue.size else None,
        "refs": issue.refs,
        "plus_one_evidence": issue.plus_one_evidence,
        "close_history": issue.close_history,
        "task_type": issue.task_type,
        "task_type_fields": dict(issue.task_type_fields),
        "producer": {"chop": "bead_task_triage", "project": project_name},
        "notification_id": notification_id,
    }
    if kind == TASK_TRIAGE_KIND:
        return task_gate_factory(**common, closed_at=issue.closed_at)
    if issue.snooze is None:
        raise ValueError(f"snoozed task {bead_id} has no snooze record")
    return snooze_gate_factory(snooze=issue.snooze, **common)


def reap_settled_bundles(
    kinds: tuple[str, ...],
    *,
    retention_days: int,
    cap: int,
    now: float | None = None,
) -> tuple[int, bool]:
    """Delete settled automation-owned bundles older than the horizon.

    Only bundles with ``response.json`` or ``cancellation.json`` whose newest
    settlement mtime is at least ``retention_days`` old are removed. Pending
    bundles are always kept. Deletion is root-confined without following
    symlinks (via :func:`assert_owned_bundle`) and runs under the bundle's
    creation lock, so a concurrent creation retry cannot interleave. At most
    ``cap`` bundles are removed per call; the second return value reports
    whether the cap stopped the sweep early.

    sase-core's stats readers (``agent_stats/gate_bundles.rs``) only scan
    ``plan``, ``epic_plan``, and ``question`` bundles, so reaping triage,
    snooze, and flag bundles does not change those aggregates.
    """
    import shutil
    import time

    current = time.time() if now is None else now
    cutoff = current - max(1, int(retention_days)) * 86400.0
    reaped = 0
    capped = False
    for kind in sorted(set(kinds)):
        if reaped >= cap:
            capped = True
            break
        try:
            kind_dir = interaction_requests_dir() / kind
            entries = sorted(kind_dir.iterdir(), key=lambda path: path.name)
        except OSError:
            continue
        for bundle_dir in entries:
            if reaped >= cap:
                capped = True
                break
            if not bundle_dir.is_dir() or bundle_dir.is_symlink():
                continue
            request_id = bundle_dir.name
            try:
                paths = bundle_paths(kind, request_id)
            except GateError:
                continue
            try:
                owned = assert_owned_bundle(paths.root)
            except GateError:
                continue
            if owned != paths.root.expanduser().resolve(strict=False):
                continue
            stamps: list[float] = []
            for name in (RESPONSE_FILENAME, CANCELLATION_FILENAME):
                try:
                    stamps.append((paths.root / name).stat().st_mtime)
                except OSError:
                    continue
            if not stamps:
                continue
            if max(stamps) >= cutoff:
                continue
            lock_path = (
                interaction_requests_dir() / ".locks" / kind / f"{request_id}.lock"
            )
            try:
                with file_lock(lock_path, timeout=5.0):
                    fresh: list[float] = []
                    for name in (RESPONSE_FILENAME, CANCELLATION_FILENAME):
                        try:
                            fresh.append((paths.root / name).stat().st_mtime)
                        except OSError:
                            continue
                    if not fresh or max(fresh) >= cutoff:
                        continue
                    if not paths.root.is_dir() or paths.root.is_symlink():
                        continue
                    shutil.rmtree(paths.root)
            except (GateError, OSError):
                continue
            reaped += 1
    return reaped, capped
