"""Gate lifecycle operations for the bead-task-triage reconciler."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sase.bead.model import Issue
from sase.chops.builtin import BuiltinChopRuntime
from sase.chops.sdk import ChopLogger, ChopResultBuilder
from sase.notification_gates.models import GateError
from sase.scripts._bead_task_triage_gates import NotificationIndex
from sase.scripts._bead_task_triage_state import ProjectState


@dataclass(frozen=True)
class Superseded:
    """A pending gate whose successor adopts its notification row."""

    kind: str
    request_id: str
    fingerprint: str | None
    notification_id: str


def summary(
    runtime: BuiltinChopRuntime,
    *,
    gated: int = 0,
    canceled: int = 0,
    skipped: int = 0,
    deferred: int = 0,
    resnoozed: int = 0,
    suppressed: int = 0,
    swept_projects: int = 0,
    untracked_canceled: int = 0,
    reaped_bundles: int = 0,
    other_dismissed_pending: int = 0,
    reason: str | None = None,
) -> ChopResultBuilder:
    counters: dict[str, int] = {
        "gated": gated,
        "canceled": canceled,
        "skipped": skipped,
        "deferred": deferred,
        "resnoozed": resnoozed,
        "suppressed": suppressed,
        "swept_projects": swept_projects,
        "untracked_canceled": untracked_canceled,
    }
    if reaped_bundles:
        counters["reaped_bundles"] = reaped_bundles
    if other_dismissed_pending:
        counters["other_dismissed_pending"] = other_dismissed_pending
    return runtime.emit_summary(
        counters,
        reason=reason,
    )


def notification_dismissed(
    kind: str,
    request_id: str,
    notifications: NotificationIndex,
    *,
    notification_id_for: Callable[[str, str], str | None],
) -> bool:
    """Return whether the gate's notification row is dismissed.

    A missing notification id or a missing row is not a dismissal: the row
    may have been archived, and an archived dismissal must not cancel a live
    gate. Only an explicit dismissed row counts.
    """
    notification_id = notification_id_for(kind, request_id)
    if notification_id is None:
        return False
    try:
        return notifications.is_dismissed(notification_id) is True
    except Exception:
        return False


def count_other_dismissed_pending(
    notifications: NotificationIndex,
    *,
    owned_kinds: tuple[str, ...],
    notification_id_for: Callable[[str, str], str | None],
) -> int:
    """Count dismissed-but-pending gates this chop does not own.

    Other gate kinds are only counted: nothing here cancels or reaps them.
    """
    from sase.notification_gates.paths import interaction_requests_dir

    try:
        root = interaction_requests_dir()
        kind_dirs = [entry for entry in root.iterdir() if entry.is_dir()]
    except OSError:
        return 0
    owned = set(owned_kinds)
    count = 0
    for kind_dir in kind_dirs:
        if kind_dir.name.startswith(".") or kind_dir.name in owned:
            continue
        try:
            bundles = sorted(kind_dir.iterdir(), key=lambda path: path.name)
        except OSError:
            continue
        for bundle_dir in bundles:
            if not bundle_dir.is_dir() or bundle_dir.is_symlink():
                continue
            if (bundle_dir / "response.json").exists() or (
                bundle_dir / "cancellation.json"
            ).exists():
                continue
            try:
                request_id = bundle_dir.name
                notification_id = notification_id_for(kind_dir.name, request_id)
            except Exception:
                continue
            if notification_id is None:
                continue
            try:
                if notifications.is_dismissed(notification_id) is True:
                    count += 1
            except Exception:
                continue
    return count


def create_bead_gate(
    log: ChopLogger,
    project_state: ProjectState,
    *,
    kind: str,
    project_name: str,
    bead_id: str,
    issue: Issue,
    notification_id: str | None,
    request_id_for: Callable[[str, str, int, str], str],
    create_gate: Callable[..., Any],
    cancel_conflicting_gate: Callable[..., None],
) -> tuple[str, int, Any] | None:
    """Create a bead's next-generation gate; ``None`` when none exists yet.

    A ``request_id_conflict`` retires the conflicting gate, records a fresh
    generation that survives even if the bounded retry fails, and retries.
    """
    generation = project_state.generations.get(bead_id, 0) + 1
    request_id = request_id_for(project_name, bead_id, generation, kind)
    try:
        result = create_gate(
            kind,
            request_id=request_id,
            bead_id=bead_id,
            project_name=project_name,
            issue=issue,
            notification_id=notification_id,
        )
    except GateError as exc:
        if exc.code != "request_id_conflict":
            log.warning(
                f"[bead_task_triage] Failed to create gate for "
                f"{project_name}:{bead_id}: {exc}"
            )
            return None

        # A conflicting id belongs to an earlier gate specification.
        # Retire it when it is still pending, then record a fresh
        # generation that survives even if the bounded retry fails.
        try:
            cancel_conflicting_gate(
                kind, request_id, adopted_notification_id=notification_id
            )
        except GateError as cancel_exc:
            if cancel_exc.code not in {
                "already_answered",
                "already_canceled",
                "not_pending",
            }:
                log.warning(
                    f"[bead_task_triage] Failed to cancel conflicting "
                    f"gate {request_id}: {cancel_exc}"
                )
        except Exception as cancel_exc:  # noqa: BLE001 - keep generation durable.
            log.warning(
                f"[bead_task_triage] Failed to cancel conflicting "
                f"gate {request_id}: {cancel_exc}"
            )

        retry_generation = generation + 1
        retry_request_id = request_id_for(project_name, bead_id, retry_generation, kind)
        project_state.generations[bead_id] = retry_generation
        log.warning(
            f"[bead_task_triage] request_id_conflict for {request_id}; "
            f"retrying with {retry_request_id}"
        )
        try:
            result = create_gate(
                kind,
                request_id=retry_request_id,
                bead_id=bead_id,
                project_name=project_name,
                issue=issue,
                notification_id=notification_id,
            )
        except Exception as retry_exc:  # noqa: BLE001 - retry next pass.
            log.warning(
                f"[bead_task_triage] Failed to create gate for "
                f"{project_name}:{bead_id}: {retry_exc}"
            )
            return None
        return retry_request_id, retry_generation, result
    except Exception as exc:  # noqa: BLE001 - retry deterministically.
        log.warning(
            f"[bead_task_triage] Failed to create gate for "
            f"{project_name}:{bead_id}: {exc}"
        )
        return None
    return request_id, generation, result


def retire_predecessor(
    log: ChopLogger,
    predecessor: Superseded,
    *,
    successor_row: str | None,
    cancel_pending_gate: Callable[..., bool],
    retire_superseded_gate: Callable[..., bool],
) -> int:
    """Retire the gate a successor re-presented; 1 when this pass canceled it.

    When the successor adopted the predecessor's row, the cancellation leaves
    the row to the successor; otherwise the predecessor settles its own row.
    A failure leaves the predecessor untracked, so the untracked sweep
    retires it on a later pass.
    """
    try:
        if successor_row == predecessor.notification_id:
            was_canceled = retire_superseded_gate(
                predecessor.kind,
                predecessor.request_id,
                reason="task_triage_presentation_changed",
            )
        else:
            was_canceled = cancel_pending_gate(
                predecessor.kind,
                predecessor.request_id,
                reason="task_triage_presentation_changed",
            )
    except Exception as exc:  # noqa: BLE001 - the untracked sweep retries it.
        log.warning(
            f"[bead_task_triage] Failed to retire superseded gate "
            f"{predecessor.request_id}: {exc}"
        )
        return 0
    return int(was_canceled)


def keep_tracking(
    project_state: ProjectState, bead_id: str, predecessor: Superseded
) -> None:
    """Re-track a superseded gate whose successor could not be created."""
    project_state.gates[bead_id] = predecessor.request_id
    project_state.kinds[bead_id] = predecessor.kind
    if predecessor.fingerprint is not None:
        project_state.fingerprints[bead_id] = predecessor.fingerprint


def log_live_agent_work(
    log: ChopLogger,
    *,
    project_name: str,
    bead_id: str,
    agent_name: str | None,
    action: str,
) -> None:
    owner = agent_name or "unknown"
    log.info(
        f"[bead_task_triage] Live agent {owner} is working "
        f"{project_name}:{bead_id}; {action}"
    )


def pending_refresh_reason(*, worked: bool, wrong_kind: bool) -> str:
    if worked:
        return "bead_work_in_flight"
    if wrong_kind:
        return "bead_status_changed"
    return "task_triage_presentation_changed"
