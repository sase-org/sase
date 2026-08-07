#!/usr/bin/env python3
"""Raise and reconcile the one pending gate each live task bead may have.

A task bead is either ready — awaiting a ``TaskTriage`` decision — or snoozed,
awaiting a ``BeadSnooze`` wake. Both gate kinds are reconciled here, in one
lane state and under one lock, because "which gate does this bead have" is a
single question: a second chop owning the second kind could only race this one
into giving a bead two pending gates.
"""

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from sase.bead.model import Issue, IssueType, SnoozeRecord, Status
from sase.bead.snooze_gate import BEAD_SNOOZE_KIND, create_bead_snooze_gate
from sase.bead.store_locator import canonical_beads_dir_for_project
from sase.bead.task_gate import TASK_TRIAGE_KIND, create_task_triage_gate
from sase.chops.builtin import BuiltinChopRuntime, builtin_chop, run_builtin_chop
from sase.chops.sdk import ChopLogger, ChopResultBuilder
from sase.core import bead_read_facade as rust_beads
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.time import get_timezone
from sase.notification_gates.durability import file_lock, read_json_object
from sase.notification_gates.executor import cancel_gate
from sase.notification_gates.models import GateError
from sase.notification_gates.paths import bundle_paths
from sase.notification_gates.poller import poll_gate

_STATE_SCHEMA_VERSION = 3
_STATE_FILENAME = "bead_task_triage.json"
_LOCK_FILENAME = "bead_task_triage.lock"

# Bumped whenever a gate preview or notification-note renderer changes shape, so
# the reconciler replaces pending gates still advertising the superseded one.
_PRESENTATION_FORMAT_VERSION = 2

_GateState = Literal["pending", "terminal", "missing"]

_GATEABLE_STATUSES = (Status.READY, Status.SNOOZED)
_GATE_KINDS = (TASK_TRIAGE_KIND, BEAD_SNOOZE_KIND)
_REQUEST_ID_PREFIXES = {
    TASK_TRIAGE_KIND: "bead-task-triage",
    BEAD_SNOOZE_KIND: "bead-snooze",
}


@dataclass
class _ProjectState:
    gates: dict[str, str] = field(default_factory=dict)
    generations: dict[str, int] = field(default_factory=dict)
    fingerprints: dict[str, str] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)


def _read_state(path: Path) -> dict[str, _ProjectState]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    raw_projects = payload.get("projects")
    if not isinstance(raw_projects, dict):
        return {}

    projects: dict[str, _ProjectState] = {}
    for project_name, raw_project in raw_projects.items():
        if not isinstance(project_name, str) or not isinstance(raw_project, dict):
            continue
        raw_gates = raw_project.get("gates")
        raw_generations = raw_project.get("generations")
        raw_fingerprints = raw_project.get("fingerprints")
        raw_kinds = raw_project.get("kinds")
        gates = (
            {
                bead_id: request_id
                for bead_id, request_id in raw_gates.items()
                if isinstance(bead_id, str) and isinstance(request_id, str)
            }
            if isinstance(raw_gates, dict)
            else {}
        )
        generations = (
            {
                bead_id: generation
                for bead_id, generation in raw_generations.items()
                if isinstance(bead_id, str)
                and isinstance(generation, int)
                and not isinstance(generation, bool)
                and generation >= 1
            }
            if isinstance(raw_generations, dict)
            else {}
        )
        fingerprints = (
            {
                bead_id: fingerprint
                for bead_id, fingerprint in raw_fingerprints.items()
                if isinstance(bead_id, str)
                and bead_id in gates
                and isinstance(fingerprint, str)
                and fingerprint
            }
            if isinstance(raw_fingerprints, dict)
            else {}
        )
        # A version-2 state file recorded no kind because triage was the only
        # one; every gate it names is therefore a TaskTriage gate.
        kinds = (
            {
                bead_id: kind
                for bead_id, kind in raw_kinds.items()
                if isinstance(bead_id, str) and bead_id in gates and kind in _GATE_KINDS
            }
            if isinstance(raw_kinds, dict)
            else {}
        )
        if gates or generations or fingerprints:
            projects[project_name] = _ProjectState(
                gates=gates,
                generations=generations,
                fingerprints=fingerprints,
                kinds=kinds,
            )
    return projects


def _write_state(path: Path, projects: dict[str, _ProjectState]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": _STATE_SCHEMA_VERSION,
        "projects": {
            project_name: {
                "gates": dict(sorted(project.gates.items())),
                "generations": dict(sorted(project.generations.items())),
                "fingerprints": dict(sorted(project.fingerprints.items())),
                "kinds": dict(sorted(project.kinds.items())),
            }
            for project_name, project in sorted(projects.items())
            if project.gates or project.generations or project.fingerprints
        },
    }
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def _enabled_project_stores(log: ChopLogger) -> list[tuple[str, Path]]:
    records = list_project_records(
        sase_projects_dir(),
        "enabled",
        include_home=False,
        projects_only=True,
    )
    stores: list[tuple[str, Path]] = []
    for record in records:
        if (
            not record.is_project
            or record.state != "enabled"
            or record.system_managed
            or record.project_name == "home"
        ):
            continue
        try:
            beads_dir = canonical_beads_dir_for_project(record.project_name)
        except Exception as exc:  # noqa: BLE001 - continue with healthy projects.
            log.warning(
                f"[bead_task_triage] Failed to locate bead store for "
                f"{record.project_name}: {exc}"
            )
            continue
        if beads_dir is None:
            continue
        stores.append((record.project_name, beads_dir))
    return stores


def _gateable_tasks(beads_dir: Path) -> list[Issue]:
    """Read every task bead that owes the user a gate, in one store pass."""
    return rust_beads.list_issues(
        beads_dir,
        statuses=list(_GATEABLE_STATUSES),
        issue_types=[IssueType.TASK],
    )


def _expected_gate_kind(issue: Issue) -> str:
    """Return the one gate kind a live task bead's status calls for."""
    return BEAD_SNOOZE_KIND if issue.status == Status.SNOOZED else TASK_TRIAGE_KIND


def _request_id(project_name: str, bead_id: str, generation: int, kind: str) -> str:
    identity = f"{project_name}\0{bead_id}".encode()
    digest = hashlib.sha256(identity).hexdigest()[:12]
    bead_component = bead_id[:80]
    prefix = _REQUEST_ID_PREFIXES[kind]
    return f"{prefix}-{bead_component}-{digest}-g{generation}"


def _presentation_fingerprint(issue: Issue) -> str:
    """Hash every persisted field that changes the pending gate presentation.

    The snooze record is part of it because both the wake gate's notification
    note and its preview render the wake conditions: a re-snooze must replace
    the pending gate rather than leave it advertising the old wake time.

    ``_PRESENTATION_FORMAT_VERSION`` is folded in too, even though it is not a
    bead field: it hashes the renderers' *inputs*, not their output, so a pure
    format change (like omitting a blank Notes section) does not otherwise
    change the fingerprint. Bump the constant whenever a preview or
    notification-note renderer's output shape changes, so every pending gate
    is cancelled and recreated against the new shape on the next chop tick.
    """

    snooze = issue.snooze
    payload = {
        "format_version": _PRESENTATION_FORMAT_VERSION,
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
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _gate_state(kind: str, request_id: str) -> _GateState:
    paths = bundle_paths(kind, request_id)
    if not paths.request.is_file():
        return "missing"
    return "pending" if poll_gate(paths.root) is None else "terminal"


def _cancel_pending_gate(
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


def _gate_notification_id(kind: str, request_id: str) -> str | None:
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
class _NotificationSnoozeIndex:
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


def _heal_snoozed_notification(
    request_id: str,
    snooze: SnoozeRecord | None,
    index: _NotificationSnoozeIndex,
) -> bool:
    """Re-snooze a wake gate's notification that drifted from its wake time.

    This is what keeps "a snoozed bead's notification is snoozed to its wake
    time" true after a crash or a manual unmute, rather than merely true at
    creation. A wake time already in the past is left alone: the notification
    snooze expiry has legitimately resurfaced that row.
    """
    wake = _parse_instant(snooze.until if snooze is not None else None)
    if wake is None or wake <= datetime.now(get_timezone()):
        return False
    notification_id = _gate_notification_id(BEAD_SNOOZE_KIND, request_id)
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


def _summary(
    runtime: BuiltinChopRuntime,
    *,
    gated: int = 0,
    canceled: int = 0,
    skipped: int = 0,
    resnoozed: int = 0,
    reason: str | None = None,
) -> ChopResultBuilder:
    return runtime.emit_summary(
        {
            "gated": gated,
            "canceled": canceled,
            "skipped": skipped,
            "resnoozed": resnoozed,
        },
        reason=reason,
    )


def _create_gate(
    kind: str,
    *,
    request_id: str,
    bead_id: str,
    project_name: str,
    issue: Issue,
) -> None:
    """Create the one gate this bead's status calls for."""
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
        "producer": {"chop": "bead_task_triage", "project": project_name},
    }
    if kind == TASK_TRIAGE_KIND:
        create_task_triage_gate(**common)
        return
    if issue.snooze is None:
        raise ValueError(f"snoozed task {bead_id} has no snooze record")
    create_bead_snooze_gate(snooze=issue.snooze, **common)


def _reconcile(runtime: BuiltinChopRuntime, state_path: Path) -> ChopResultBuilder:
    if runtime.context.dry_run:
        return _summary(runtime, reason="dry_run")

    projects = _read_state(state_path)
    try:
        project_stores = _enabled_project_stores(runtime.log)
    except Exception as exc:  # noqa: BLE001 - a bad inventory must fail closed.
        runtime.log.warning(
            f"[bead_task_triage] Failed to load enabled projects: {exc}"
        )
        return _summary(runtime, reason="project_inventory_unavailable")

    gated = 0
    canceled = 0
    skipped = 0
    resnoozed = 0
    state_changed = False
    notifications = _NotificationSnoozeIndex()
    for project_name, beads_dir in project_stores:
        try:
            live_tasks = {issue.id: issue for issue in _gateable_tasks(beads_dir)}
        except Exception as exc:  # noqa: BLE001 - one store must not stop the chop.
            runtime.log.warning(
                f"[bead_task_triage] Failed to read gateable tasks for "
                f"{project_name}: {exc}"
            )
            continue

        project_state = projects.setdefault(project_name, _ProjectState())
        for bead_id, request_id in list(project_state.gates.items()):
            kind = project_state.kinds.get(bead_id, TASK_TRIAGE_KIND)
            try:
                gate_state = _gate_state(kind, request_id)
            except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                runtime.log.warning(
                    f"[bead_task_triage] Failed to inspect gate {request_id}: {exc}"
                )
                live_tasks.pop(bead_id, None)
                continue

            issue = live_tasks.pop(bead_id, None)
            if issue is not None and gate_state == "pending":
                # A status change outranks the presentation check: the pending
                # gate asks the wrong question entirely, so its fingerprint is
                # not worth comparing.
                wrong_kind = kind != _expected_gate_kind(issue)
                fingerprint = _presentation_fingerprint(issue)
                if (
                    not wrong_kind
                    and project_state.fingerprints.get(bead_id) == fingerprint
                ):
                    skipped += 1
                    try:
                        if kind == BEAD_SNOOZE_KIND and _heal_snoozed_notification(
                            request_id, issue.snooze, notifications
                        ):
                            resnoozed += 1
                    except Exception as exc:  # noqa: BLE001 - retry next tick.
                        runtime.log.warning(
                            f"[bead_task_triage] Failed to re-snooze the "
                            f"notification for gate {request_id}: {exc}"
                        )
                    continue
                try:
                    was_canceled = _cancel_pending_gate(
                        kind,
                        request_id,
                        reason=(
                            "bead_status_changed"
                            if wrong_kind
                            else "task_triage_presentation_changed"
                        ),
                    )
                except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                    runtime.log.warning(
                        f"[bead_task_triage] Failed to refresh stale presentation "
                        f"for gate {request_id}: {exc}"
                    )
                    continue
                canceled += int(was_canceled)

            if issue is None and gate_state == "pending":
                try:
                    was_canceled = _cancel_pending_gate(kind, request_id)
                except Exception as exc:  # noqa: BLE001 - retry on the next tick.
                    runtime.log.warning(
                        f"[bead_task_triage] Failed to cancel stale gate "
                        f"{request_id}: {exc}"
                    )
                    continue
                canceled += int(was_canceled)

            del project_state.gates[bead_id]
            project_state.fingerprints.pop(bead_id, None)
            project_state.kinds.pop(bead_id, None)
            state_changed = True
            if issue is not None:
                live_tasks[bead_id] = issue

        for bead_id, issue in sorted(live_tasks.items()):
            generation = project_state.generations.get(bead_id, 0) + 1
            kind = _expected_gate_kind(issue)
            request_id = _request_id(project_name, bead_id, generation, kind)
            try:
                _create_gate(
                    kind,
                    request_id=request_id,
                    bead_id=bead_id,
                    project_name=project_name,
                    issue=issue,
                )
            except Exception as exc:  # noqa: BLE001 - retry deterministically.
                runtime.log.warning(
                    f"[bead_task_triage] Failed to create gate for "
                    f"{project_name}:{bead_id}: {exc}"
                )
                continue
            project_state.gates[bead_id] = request_id
            project_state.generations[bead_id] = generation
            project_state.fingerprints[bead_id] = _presentation_fingerprint(issue)
            project_state.kinds[bead_id] = kind
            gated += 1
            state_changed = True

    if state_changed:
        try:
            _write_state(state_path, projects)
        except Exception as exc:  # noqa: BLE001 - gate ids make recovery idempotent.
            runtime.log.warning(
                f"[bead_task_triage] Failed to persist reconciliation state: {exc}"
            )

    reason = None if gated or canceled or resnoozed else "no_triage_changes"
    return _summary(
        runtime,
        gated=gated,
        canceled=canceled,
        skipped=skipped,
        resnoozed=resnoozed,
        reason=reason,
    )


@builtin_chop("bead_task_triage")
def _run(runtime: BuiltinChopRuntime) -> ChopResultBuilder:
    state_dir = Path(runtime.context.state_dir)
    state_path = state_dir / _STATE_FILENAME
    with file_lock(state_dir / _LOCK_FILENAME):
        return _reconcile(runtime, state_path)


def main() -> None:
    run_builtin_chop("bead_task_triage")


if __name__ == "__main__":
    main()
