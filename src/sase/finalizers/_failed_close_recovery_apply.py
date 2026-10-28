"""Machine-lane mutation and coordination for failed-close recovery."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.finalizers._failed_close_recovery_assess import (
    assess_terminal_failure,
    build_recovery_note,
    declaration_evidence_path,
    run_provenance,
)
from sase.finalizers.artifacts import write_json_atomic
from sase.procs.text_bounding import bound_and_redact_text

RECOVERY_REQUEST_FILENAME = "failed_close_recovery_request.json"
RECOVERY_OUTCOME_FILENAME = "failed_close_recovery_outcome.json"
_RECOVERY_JOURNAL_EVENT = "failed_close_recovery"
_MACHINE_WORKFLOW = "failed_close_recovery"
_DIAGNOSTIC_MAX_CHARS = 4000
_RECOVERY_COMMIT_SUBJECT = "recover failed-run closes for "


@dataclass
class _RecoveryOutcome:
    """What the coordinator did (or deliberately skipped) for one failure."""

    attempted: bool = False
    skipped_reason: str = ""
    recovered: list[str] = field(default_factory=list)
    already_applied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    published: bool = False
    publication_error: str = ""
    error: str = ""
    snapshot_locations: list[str] = field(default_factory=list)
    snapshot_errors: list[dict[str, str]] = field(default_factory=list)


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _redact_diagnostic(text: str) -> str:
    """Redact secrets and keep the bounded tail of one diagnostic string."""
    return bound_and_redact_text(text, _DIAGNOSTIC_MAX_CHARS) or ""


def _failure_code_and_message(failure: BaseException) -> tuple[str, str]:
    """Derive a stable failure code and message from a terminal exception."""
    from sase.finalizers.commit_types import BuiltinCommitFinalizerError
    from sase.finalizers.controller_context import FinalizerControllerError

    message = _redact_diagnostic(str(failure).strip() or type(failure).__name__)
    if isinstance(failure, BuiltinCommitFinalizerError):
        diagnostics = failure.result.diagnostics if failure.result else ()
        if diagnostics:
            return str(diagnostics[0].code or "commit_failed"), message
        return "commit_failed", message
    code = getattr(failure, "code", None)
    if isinstance(code, str) and code.strip():
        return code.strip(), message
    if "declaration recovery failed" in message.lower():
        return "declaration_recovery_failed", message
    return type(failure).__name__, message


def _persist_recovery_artifact(
    artifacts_dir: str,
    filename: str,
    payload: Mapping[str, Any],
) -> str | None:
    """Write one recovery JSON artifact; return its path or ``None``."""
    try:
        path = Path(artifacts_dir) / filename
        write_json_atomic(path, payload)
        return str(path)
    except Exception:
        return None


def _record_recovery_journal(
    artifacts_dir: str,
    fields: Mapping[str, Any],
) -> None:
    """Append one recovery record to the finalizer journal; never raises."""
    try:
        from sase.finalizers.progress import ProgressJournal

        ProgressJournal(artifacts_dir).record(_RECOVERY_JOURNAL_EVENT, **dict(fields))
    except Exception:
        pass


def _resolve_machine_project(artifacts_dir: str) -> str | None:
    """Return the project owning the checkout the failed run worked in."""
    try:
        from sase.llm_provider.commit_finalizer_config import (
            resolve_finalizer_project_dir,
        )
        from sase.workspace_provider.marker import find_marker_from_cwd

        project_dir = resolve_finalizer_project_dir()
        found = find_marker_from_cwd(project_dir)
        if found is None:
            return None
        _, marker = found
        return marker.project_name or None
    except Exception:
        return None


def _acquire_recovery_store(project: str, run_id: str) -> Any:
    """Yield a machine-writable bead store for the recovery mutation."""
    from sase.bead.background_store import writable_bead_store_for_machine

    return writable_bead_store_for_machine(
        project,
        workflow=_MACHINE_WORKFLOW,
        holder=f"recover-close:{run_id}",
        prefer_existing_claim=True,
    )


def _refresh_recovery_store(beads_dir: Path) -> None:
    """Best-effort pull of the recovery store before mutation."""
    try:
        from sase.bead.sync import refresh_bead_store

        refresh_bead_store(beads_dir)
    except Exception:
        pass


def _commit_recovery_mutation(
    beads_dir: Path,
    run_id: str,
    *,
    already_locked: bool = False,
    operation_context: Any | None = None,
) -> bool:
    from sase.bead.sync import commit_failed_close_recovery

    return commit_failed_close_recovery(
        beads_dir,
        run_id,
        already_locked=already_locked,
        mutation_origin="machine",
        operation_context=operation_context,
    )


def _push_recovery_mutation(beads_dir: Path) -> Any:
    from sase.bead.sync import push_bead_work_launch

    return push_bead_work_launch(beads_dir)


def _bead_state_is_dirty(beads_dir: Path) -> bool:
    from sase.bead.sync import bead_state_is_clean

    return not bead_state_is_clean(beads_dir)


def _recovery_is_locally_committed(beads_dir: Path, run_id: str) -> bool:
    """Return whether this run's recovery events are in a local commit."""
    import subprocess

    from sase.bead._sync_git import (
        bead_state_is_clean,
        find_git_root,
        relative_pathspec,
    )

    repo = find_git_root(beads_dir)
    if repo is None or not bead_state_is_clean(beads_dir):
        return False
    result = subprocess.run(
        ["git", "log", "--format=%s", "--", relative_pathspec(beads_dir, repo)],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    needle = f"{_RECOVERY_COMMIT_SUBJECT}{run_id}"
    return any(needle in line for line in result.stdout.splitlines())


def _ensure_recovery_committed(
    beads_dir: Path,
    run_id: str,
    *,
    already_locked: bool,
    operation_context: Any | None,
    required: bool,
) -> tuple[bool, str]:
    """Commit pending recovery events, or prove they are already committed.

    An idempotent core result is not a commit receipt. ``(False, "")`` means
    there was no recovery work to publish; a non-empty error is a real
    failure.
    """
    if _recovery_is_locally_committed(beads_dir, run_id):
        return True, ""
    if not required and not _bead_state_is_dirty(beads_dir):
        return False, ""
    committed = _commit_recovery_mutation(
        beads_dir,
        run_id,
        already_locked=already_locked,
        operation_context=operation_context,
    )
    if _recovery_is_locally_committed(beads_dir, run_id) or committed:
        return True, ""
    return False, "recovery mutation was not committed to the bead store"


def _run_machine_lane_recovery(
    project: str,
    request: Mapping[str, Any],
    *,
    run_id: str,
) -> tuple[dict[str, Any], bool, str]:
    """Apply the recovery mutation through the machine write lane.

    Returns ``(report, committed, publication_error)``. ``committed`` is
    true only when the recovery events are in a local commit. An idempotent
    core result is not a commit receipt; a pending recovery-store commit is
    retried through this same machine-owned lane before push. The failed
    product hook is never invoked to commit the note, and the user-owned
    primary snapshot is never touched.
    """
    from sase.bead.background_store import schedule_beads_sidecar_convergence
    from sase.bead.store_locator import open_bead_project_for_beads_dir
    from sase.bead.sync import bead_store_write_lock
    from sase.core import bead_mutation_facade as rust_beads

    with _acquire_recovery_store(project, run_id) as store:
        beads_dir = Path(store.beads_dir)
        _refresh_recovery_store(beads_dir)
        with bead_store_write_lock(beads_dir) as already_locked:
            with open_bead_project_for_beads_dir(beads_dir):
                report = rust_beads.recover_failed_closes(beads_dir, request)
            changed = bool(report.get("changed"))
            already_applied = bool(report.get("already_applied"))
            needs_publication = (
                changed or already_applied or _bead_state_is_dirty(beads_dir)
            )
            committed, commit_error = _ensure_recovery_committed(
                beads_dir,
                run_id,
                already_locked=already_locked,
                operation_context=store.context,
                required=needs_publication,
            )
            if not committed:
                if needs_publication:
                    return (
                        dict(report),
                        False,
                        commit_error
                        or "recovery mutation was not committed to the bead store",
                    )
                return dict(report), False, ""
        push_error = ""
        try:
            outcome = _push_recovery_mutation(beads_dir)
            pushed = bool(
                getattr(outcome, "pushed", False)
                or getattr(outcome, "skipped_no_remote", False)
            )
            if not pushed:
                push_error = str(
                    getattr(outcome, "error", None)
                    or "bead store push reported no publication"
                )
        except Exception as exc:
            push_error = str(exc) or type(exc).__name__
        if changed or already_applied or committed:
            try:
                schedule_beads_sidecar_convergence(store.project)
            except Exception:
                pass
        return dict(report), committed, push_error


def _recovered_ids(report: Mapping[str, Any], key: str) -> list[str]:
    ids: list[str] = []
    entries = report.get(key)
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, Mapping):
                issue_id = entry.get("issue_id")
                if isinstance(issue_id, str) and issue_id:
                    ids.append(issue_id)
    return ids


def coordinate_failed_close_recovery(
    artifacts_dir: str | None,
    *,
    failure: BaseException,
) -> _RecoveryOutcome:
    """Recover this run's closes after a terminal finalization failure.

    Assesses landing proofs, persists the recovery request and outcome in
    durable run artifacts and the finalizer journal, and applies the bead
    mutation through the machine write lane. Never raises: the caller still
    raises the original failure, so recovery diagnostics must never mask it.
    """
    outcome = _RecoveryOutcome()
    try:
        return _coordinate_failed_close_recovery(artifacts_dir, failure, outcome)
    except Exception as exc:  # noqa: BLE001 - recovery must never mask failure.
        outcome.error = _redact_diagnostic(str(exc) or type(exc).__name__)
        return outcome


def _coordinate_failed_close_recovery(
    artifacts_dir: str | None,
    failure: BaseException,
    outcome: _RecoveryOutcome,
) -> _RecoveryOutcome:
    failure_code, failure_message = _failure_code_and_message(failure)
    provenance = run_provenance()
    assessment = assess_terminal_failure(
        artifacts_dir,
        failure_code=failure_code,
        failure_message=failure_message,
        provenance=provenance,
    )
    if not assessment.should_recover or provenance is None:
        # Skip paths stay silent in the journal: ``phase_finished`` remains
        # the terminal journal event for failures that need no bead action.
        outcome.skipped_reason = assessment.reason
        return outcome
    assert artifacts_dir is not None
    run_id = str(provenance.get("run_id", ""))
    agent_name = str(provenance.get("agent_name", ""))
    artifact_dir = str(provenance.get("artifact_dir", ""))
    from sase.finalizers._failed_close_recovery_snapshots import (
        capture_failed_close_snapshots,
    )

    try:
        snapshot_evidence = capture_failed_close_snapshots(
            artifacts_dir, assessment, run_id=run_id
        )
        snapshots = [dict(row) for row in snapshot_evidence.records]
        snapshot_locations = list(snapshot_evidence.locations)
        snapshot_errors = [dict(row) for row in snapshot_evidence.errors]
        previous_evidence_locations = list(
            snapshot_evidence.previous_evidence_locations
        )
    except Exception as exc:  # noqa: BLE001 - snapshot failure must not block reopening.
        snapshots = []
        snapshot_locations = []
        snapshot_errors = [
            {"repo": "snapshot coordinator", "error": _redact_diagnostic(str(exc))}
        ]
        previous_evidence_locations = []
    evidence_locations = list(
        dict.fromkeys(
            str(location)
            for location in [
                artifacts_dir,
                artifact_dir,
                declaration_evidence_path(artifacts_dir),
                *previous_evidence_locations,
                *snapshot_locations,
            ]
            if location
        )
    )
    outcome.snapshot_locations = snapshot_locations
    outcome.snapshot_errors = snapshot_errors
    note = build_recovery_note(
        assessment,
        provenance,
        artifacts_dir=artifacts_dir,
        evidence_locations=evidence_locations,
        snapshot_errors=snapshot_errors,
    )
    request = {
        "run_id": run_id,
        "failed_at": _utc_now(),
        "failure_code": failure_code,
        "evidence_locations": evidence_locations,
        "snapshots": snapshots,
        "snapshot_locations": snapshot_locations,
        "snapshot_errors": snapshot_errors,
        "note": note,
        "actor": agent_name,
    }
    _persist_recovery_artifact(artifacts_dir, RECOVERY_REQUEST_FILENAME, request)
    project = _resolve_machine_project(artifacts_dir)
    if not project:
        outcome.error = (
            "recovery store unavailable: no project owns the failed run's checkout; "
            "the recovery request is retained in the run artifacts for retry"
        )
        _persist_recovery_artifact(
            artifacts_dir,
            RECOVERY_OUTCOME_FILENAME,
            {
                "attempted": False,
                "error": outcome.error,
                "request": request,
                "failure_code": failure_code,
                "snapshot_locations": snapshot_locations,
                "snapshot_errors": snapshot_errors,
            },
        )
        _record_recovery_journal(
            artifacts_dir,
            {
                "error": outcome.error,
                "failure_code": failure_code,
                "snapshot_locations": snapshot_locations,
                "snapshot_errors": snapshot_errors,
            },
        )
        return outcome
    outcome.attempted = True
    try:
        report, committed, publication_error = _run_machine_lane_recovery(
            project, request, run_id=run_id
        )
    except Exception as exc:  # noqa: BLE001 - retain the request for retry.
        outcome.error = (
            f"recovery storage failed: {str(exc) or type(exc).__name__}; "
            "the recovery request is retained in the run artifacts for retry"
        )
        _persist_recovery_artifact(
            artifacts_dir,
            RECOVERY_OUTCOME_FILENAME,
            {
                "attempted": True,
                "recovered": [],
                "already_applied": [],
                "skipped": [],
                "committed": False,
                "published": False,
                "publication_error": "",
                "error": outcome.error,
                "request": request,
                "failure_code": failure_code,
                "snapshot_locations": snapshot_locations,
                "snapshot_errors": snapshot_errors,
            },
        )
        _record_recovery_journal(
            artifacts_dir,
            {
                "error": outcome.error,
                "failure_code": failure_code,
                "snapshot_locations": snapshot_locations,
                "snapshot_errors": snapshot_errors,
            },
        )
        return outcome
    outcome.recovered = _recovered_ids(report, "recovered")
    outcome.already_applied = _recovered_ids(report, "already_applied")
    outcome.skipped = _recovered_ids(report, "skipped")
    outcome.publication_error = publication_error
    outcome.published = not publication_error
    if publication_error:
        outcome.error = (
            f"recovery publication failed: {publication_error}; "
            "the recovery request is retained in the run artifacts for retry"
        )
    _persist_recovery_artifact(
        artifacts_dir,
        RECOVERY_OUTCOME_FILENAME,
        {
            "attempted": True,
            "recovered": outcome.recovered,
            "already_applied": outcome.already_applied,
            "skipped": outcome.skipped,
            "committed": committed,
            "published": outcome.published,
            "publication_error": publication_error,
            "error": outcome.error,
            "request": request,
            "failure_code": failure_code,
            "snapshot_locations": snapshot_locations,
            "snapshot_errors": snapshot_errors,
        },
    )
    _record_recovery_journal(
        artifacts_dir,
        {
            "recovered": outcome.recovered,
            "already_applied": outcome.already_applied,
            "published": outcome.published,
            "error": outcome.error,
            "failure_code": failure_code,
            "snapshot_locations": snapshot_locations,
            "snapshot_errors": snapshot_errors,
        },
    )
    return outcome


__all__ = [
    "RECOVERY_OUTCOME_FILENAME",
    "RECOVERY_REQUEST_FILENAME",
    "coordinate_failed_close_recovery",
]
