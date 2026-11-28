"""Idempotent land-only recovery submission for zombie epics.

This module consumes the published recovery-claim permit from
:mod:`sase.bead.recovery` without changing its identity or cutoff rules, and
submits one stable proc per ``(project, epic, close-token)`` event through an
operational lease with origin ``axe``. The proc executes the normal bead-work
launch path (``sase bead work <epic-id> --yes-to-all``) with a recovery-only
expected-close-token guard, so a child reopened after scheduling aborts before
any cleanup or agent spawn, and a retry with all phases closed launches only
the land agent.

Crash replay never mints a new proc identity: the proc id, request
fingerprint, and concurrency keys are pure functions of the claim key, so a
repeated call after a completed or failed proc returns the consumed row, a
concurrent or restarted call replays the active row, and only a missing row
reaches the store. The bounded ``epic_liveness`` AXE job
(:mod:`sase.scripts.sase_chop_epic_liveness`) is the periodic caller.
"""

from __future__ import annotations

import os
import socket
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from sase.bead.recovery import RecoveryPublicationResult, publish_recovery_claim
from sase.bead.zombie import ZombieReport, ZombieVerdict, load_zombie_report
from sase.core.recovery_facade import RecoveryClaim, recovery_claim_key
from sase.procs.models import ACTIVE_PROC_STATUSES, Proc
from sase.procs.request import ProcSubmitRequest
from sase.procs.store import get_proc

SASE_RECOVERY_CLOSE_TOKEN_ENV = "SASE_RECOVERY_CLOSE_TOKEN"
"""Env carrier for the recovery-only expected-close-token guard.

The recovery proc sets this; the ``sase bead work`` entry point converts it
into a :class:`RecoveryLaunchGuard`. Manual runs never set it, so normal
bead-work behavior is unchanged.
"""

RECOVERY_PROC_ORIGIN = "axe"
RECOVERY_LEASE_WORKFLOW = "epic-recovery"
RECOVERY_LEASE_HOLDER = "epic-recovery"
RECOVERY_PROC_TAGS = ("epic-recovery",)

OUTCOME_SUBMITTED = "submitted"
OUTCOME_REPLAYED = "replayed"
OUTCOME_CONSUMED = "consumed"
OUTCOME_ABORTED = "aborted"

REASON_PROC_ACTIVE = "proc_already_active"
REASON_PROC_TERMINAL = "proc_already_terminal"
REASON_SUBMIT_CONFLICT = "submit_conflict"
REASON_UNSUPPORTED_CORE = "unsupported_core_binding"
REASON_PROC_LOOKUP_FAILED = "proc_lookup_failed"

_ACTIVE_STATUSES = ACTIVE_PROC_STATUSES


class RecoveryGuardError(RuntimeError):
    """A recovery-only close-token guard refused submission or launch."""


@dataclass(frozen=True, slots=True)
class RecoveryLaunchGuard:
    """Execution-time guard for one recovery launch.

    ``project`` is the durable project identity and ``expected_close_token``
    is the close event the recovery claim was published for. The guard passes
    only while the shared zombie predicate still reports the epic as an
    eligible zombie with that exact token.
    """

    project: str
    expected_close_token: str


@dataclass(frozen=True, slots=True)
class RecoverySubmission:
    """Outcome of one recovery submission attempt.

    ``outcome`` is ``submitted`` (fresh proc), ``replayed`` (the existing
    active proc for this token), ``consumed`` (the token already has a
    terminal proc; never relaunched), or ``aborted`` (no proc touched).
    ``proc`` is the submitted, replayed, or consumed row when known.
    """

    outcome: str
    reason: str
    proc_id: str
    proc: Proc | None = None
    claim: RecoveryClaim | None = None
    diagnostic: str | None = None


def default_owner_machine() -> str:
    """Return this host's stable recovery-claim owner identity."""
    try:
        from sase.config.core import get_machine_name
    except Exception:  # noqa: BLE001 - config must never block a guard read.
        get_machine_name = None  # type: ignore[assignment]
    if get_machine_name is not None:
        try:
            configured = get_machine_name()
        except Exception:  # noqa: BLE001 - fall back to the hostname.
            configured = None
        if isinstance(configured, str) and configured.strip():
            return configured.strip()
    return socket.gethostname().split(".", 1)[0].strip() or "local"


def _recovery_proc_id(project_id: str, epic_id: str, close_token: str) -> str:
    """Return the deterministic proc id for one recovery event."""
    return f"epic-recovery-{recovery_claim_key(project_id, epic_id, close_token)}"


def _recovery_request_fingerprint(
    project_id: str, epic_id: str, close_token: str
) -> str:
    """Return the deterministic request fingerprint for one recovery event."""
    return f"epic-recovery:{recovery_claim_key(project_id, epic_id, close_token)}"


def _recovery_concurrency_keys(
    project_id: str, epic_id: str, close_token: str
) -> tuple[str, ...]:
    """Return the concurrency keys serializing one recovery event."""
    return (f"epic-recovery:{project_id}:{epic_id}:{close_token}",)


def _recovery_claim_request(
    *,
    project: str,
    epic_id: str,
    close_token: str,
    owner_machine: str = "",
    proc_id: str = "",
    request_fingerprint: str = "",
) -> dict[str, str]:
    """Build the claim publication request for one recovery event.

    Defaults derive from the deterministic proc identity, so crash replay on
    the owning host resumes the same reservation instead of minting a new one.
    """
    resolved_proc_id = proc_id or _recovery_proc_id(project, epic_id, close_token)
    return {
        "project_id": project,
        "epic_id": epic_id,
        "close_token": close_token,
        "owner_machine": owner_machine or default_owner_machine(),
        "proc_id": resolved_proc_id,
        "request_fingerprint": request_fingerprint
        or _recovery_request_fingerprint(project, epic_id, close_token),
    }


def _recovery_proc_request(
    *,
    project: str,
    epic_id: str,
    close_token: str,
    proc_id: str = "",
    request_fingerprint: str = "",
) -> ProcSubmitRequest:
    """Build the stable leased proc request for one recovery event.

    Execution reaches :func:`launch_epic_bead_work
    <sase.bead.cli_work_handler_launch.launch_epic_bead_work>` for the
    existing epic bead id — never a plan-file helper — with the close token
    carried for the execution-time guard.
    """
    from sase.dev_update.code_swap_lock import guarded_exec_argv

    resolved_proc_id = proc_id or _recovery_proc_id(project, epic_id, close_token)
    resolved_fingerprint = request_fingerprint or _recovery_request_fingerprint(
        project, epic_id, close_token
    )
    logical_argv = ["sase", "bead", "work", epic_id, "--yes-to-all"]
    return ProcSubmitRequest(
        argv=guarded_exec_argv(logical_argv),
        command=logical_argv,
        label=f"Epic recovery · {epic_id}",
        cwd=".",
        origin=RECOVERY_PROC_ORIGIN,
        project=project,
        proc_id=resolved_proc_id,
        concurrency_keys=list(
            _recovery_concurrency_keys(project, epic_id, close_token)
        ),
        request_fingerprint=resolved_fingerprint,
        tags=list(RECOVERY_PROC_TAGS),
        env={SASE_RECOVERY_CLOSE_TOKEN_ENV: close_token},
    )


def recovery_guard_from_env(project: str | None) -> RecoveryLaunchGuard | None:
    """Build the execution-time guard from the proc env carrier.

    Returns ``None`` for ordinary runs that never set the carrier, so manual
    bead-work behavior is unchanged. A set carrier without a project identity
    fails closed instead of launching unguarded.
    """
    token = os.environ.get(SASE_RECOVERY_CLOSE_TOKEN_ENV, "").strip()
    if not token:
        return None
    if not (project or "").strip():
        raise RecoveryGuardError(
            "recovery close-token guard is set but the project identity is "
            "unknown; refusing the launch instead of running unguarded"
        )
    return RecoveryLaunchGuard(
        project=(project or "").strip(), expected_close_token=token
    )


def check_recovery_close_token(
    project: str,
    epic_id: str,
    expected_close_token: str,
    *,
    load_report: Callable[[str], ZombieReport] | None = None,
) -> ZombieVerdict:
    """Re-verify one epic against the shared zombie predicate.

    Returns the matching verdict when the epic is still an eligible zombie
    with exactly *expected_close_token*. Raises :class:`RecoveryGuardError`
    when the report failed, the epic has no zombie row, it is no longer
    eligible (reopened child, live owner, unknown evidence), or the token
    changed (a later close event superseded the claim). Python never
    re-implements the predicate: the verdict comes from the shared core
    evaluation through :func:`load_zombie_report
    <sase.bead.zombie.load_zombie_report>`.
    """
    loader = load_report or load_zombie_report
    report = loader(project)
    if report.collection_failed:
        raise RecoveryGuardError(
            f"recovery guard cannot verify {epic_id}: "
            f"{report.failure_reason or 'zombie report collection failed'}"
        )
    row = next(
        (verdict for verdict in report.report.rows if verdict.plan_id == epic_id),
        None,
    )
    if row is None:
        raise RecoveryGuardError(
            f"recovery guard refused {epic_id}: no zombie-plan row for the epic"
        )
    if row.state != "zombie" or not row.recovery_eligible:
        detail = row.recovery_reason or row.unknown_reason or row.state
        raise RecoveryGuardError(
            f"recovery guard refused {epic_id}: epic is no longer an eligible "
            f"zombie ({detail})"
        )
    if not row.close_token or row.close_token != expected_close_token:
        raise RecoveryGuardError(
            f"recovery guard refused {epic_id}: close token changed "
            f"(expected {expected_close_token!r}, "
            f"now {row.close_token!r}); a child reopened or a later close "
            "event superseded the claim"
        )
    return row


def _aborted(
    *,
    proc_id: str,
    reason: str,
    claim: RecoveryClaim | None = None,
    diagnostic: str | None = None,
) -> RecoverySubmission:
    return RecoverySubmission(
        outcome=OUTCOME_ABORTED,
        reason=reason,
        proc_id=proc_id,
        claim=claim,
        diagnostic=diagnostic,
    )


def _submit_with_permit(
    *,
    project: str,
    epic_id: str,
    close_token: str,
    claim: RecoveryClaim,
    lookup_proc: Callable[[str], Proc | None] | None = None,
    load_report: Callable[[str], ZombieReport] | None = None,
    submit_proc: Callable[[ProcSubmitRequest], Proc] | None = None,
) -> RecoverySubmission:
    """Guard, then submit or replay the stable proc for a permitted claim."""
    lookup = lookup_proc or get_proc
    try:
        existing = lookup(claim.proc_id)
    except Exception as exc:  # noqa: BLE001 - an unreadable store cannot submit.
        return _aborted(
            proc_id=claim.proc_id,
            reason=REASON_PROC_LOOKUP_FAILED,
            claim=claim,
            diagnostic=str(exc),
        )
    if existing is not None and existing.status in _ACTIVE_STATUSES:
        return RecoverySubmission(
            outcome=OUTCOME_REPLAYED,
            reason=REASON_PROC_ACTIVE,
            proc_id=claim.proc_id,
            proc=existing,
            claim=claim,
        )
    if existing is not None:
        return RecoverySubmission(
            outcome=OUTCOME_CONSUMED,
            reason=REASON_PROC_TERMINAL,
            proc_id=claim.proc_id,
            proc=existing,
            claim=claim,
        )
    try:
        check_recovery_close_token(
            project, epic_id, close_token, load_report=load_report
        )
    except RecoveryGuardError as exc:
        return _aborted(
            proc_id=claim.proc_id,
            reason=f"guard_refused:{exc}",
            claim=claim,
            diagnostic=str(exc),
        )
    request = _recovery_proc_request(
        project=project,
        epic_id=epic_id,
        close_token=close_token,
        proc_id=claim.proc_id,
        request_fingerprint=claim.request_fingerprint,
    )
    submit = submit_proc or _lease_and_submit
    try:
        proc = submit(request)
    except Exception as exc:  # noqa: BLE001 - report conflicts, do not raise.
        replayed = _reread_active_proc(lookup, claim.proc_id)
        if replayed is not None:
            return RecoverySubmission(
                outcome=OUTCOME_REPLAYED,
                reason=f"{REASON_SUBMIT_CONFLICT}:{exc}",
                proc_id=claim.proc_id,
                proc=replayed,
                claim=claim,
                diagnostic=str(exc),
            )
        return _aborted(
            proc_id=claim.proc_id,
            reason=f"{REASON_SUBMIT_CONFLICT}:{exc}",
            claim=claim,
            diagnostic=str(exc),
        )
    return RecoverySubmission(
        outcome=OUTCOME_SUBMITTED,
        reason="claim_permit_submitted",
        proc_id=claim.proc_id,
        proc=proc,
        claim=claim,
    )


def _reread_active_proc(
    lookup: Callable[[str], Proc | None], proc_id: str
) -> Proc | None:
    """Return the active proc row after a submit conflict, if there is one."""
    try:
        current = lookup(proc_id)
    except Exception:  # noqa: BLE001 - conflict already reported; stay quiet.
        return None
    if current is not None and current.status in _ACTIVE_STATUSES:
        return current
    return None


def _lease_and_submit(request: ProcSubmitRequest) -> Proc:
    """Submit *request* inside an operational lease with origin axe.

    The lease checkout replaces the placeholder cwd and the claim transfers
    to the acknowledged supervisor, so a restarted host resumes the same
    reservation instead of spawning a duplicate.
    """
    from sase.workspace_provider.lease import (
        acquire_operational_lease,
        submit_via_lease,
    )

    lease_project = request.project or "sase"
    lease = acquire_operational_lease(
        lease_project,
        workflow=RECOVERY_LEASE_WORKFLOW,
        holder=RECOVERY_LEASE_HOLDER,
    )
    return submit_via_lease(request, lease)


def submit_recovery_launch(
    project: str,
    epic_id: str,
    *,
    close_token: str,
    owner_machine: str = "",
    publish_claim: (
        Callable[[str, Mapping[str, Any]], RecoveryPublicationResult] | None
    ) = None,
    lookup_proc: Callable[[str], Proc | None] | None = None,
    load_report: Callable[[str], ZombieReport] | None = None,
    submit_proc: Callable[[ProcSubmitRequest], Proc] | None = None,
) -> RecoverySubmission:
    """Publish the recovery claim, then submit or replay the stable proc.

    This is the scheduler-facing entry: it publishes through the
    machine-owned store, requires the launch permit, rechecks the shared
    zombie predicate immediately before submission, and submits the stable
    proc through an operational lease. A missing permit, a failed guard, an
    active row, or a terminal row all return without spawning: the first two
    abort, the active row replays, and the terminal row stays consumed.
    """
    try:
        proc_id = _recovery_proc_id(project, epic_id, close_token)
        fingerprint = _recovery_request_fingerprint(project, epic_id, close_token)
    except RuntimeError as exc:
        return RecoverySubmission(
            outcome=OUTCOME_ABORTED,
            reason=REASON_UNSUPPORTED_CORE,
            proc_id="",
            diagnostic=str(exc),
        )
    publish = publish_claim or publish_recovery_claim
    permit = publish(
        project,
        _recovery_claim_request(
            project=project,
            epic_id=epic_id,
            close_token=close_token,
            owner_machine=owner_machine or default_owner_machine(),
            proc_id=proc_id,
            request_fingerprint=fingerprint,
        ),
    )
    if not permit.launch_permit or permit.claim is None:
        return _aborted(
            proc_id=proc_id,
            reason=f"no_launch_permit:{permit.reason}",
            claim=permit.claim,
            diagnostic=permit.diagnostic,
        )
    return _submit_with_permit(
        project=project,
        epic_id=epic_id,
        close_token=close_token,
        claim=permit.claim,
        lookup_proc=lookup_proc,
        load_report=load_report,
        submit_proc=submit_proc,
    )


__all__ = [
    "OUTCOME_ABORTED",
    "OUTCOME_CONSUMED",
    "OUTCOME_REPLAYED",
    "OUTCOME_SUBMITTED",
    "REASON_PROC_ACTIVE",
    "REASON_PROC_LOOKUP_FAILED",
    "REASON_PROC_TERMINAL",
    "REASON_SUBMIT_CONFLICT",
    "REASON_UNSUPPORTED_CORE",
    "RECOVERY_LEASE_HOLDER",
    "RECOVERY_LEASE_WORKFLOW",
    "RECOVERY_PROC_ORIGIN",
    "RECOVERY_PROC_TAGS",
    "SASE_RECOVERY_CLOSE_TOKEN_ENV",
    "RecoveryGuardError",
    "RecoveryLaunchGuard",
    "RecoverySubmission",
    "check_recovery_close_token",
    "default_owner_machine",
    "recovery_guard_from_env",
    "submit_recovery_launch",
]
