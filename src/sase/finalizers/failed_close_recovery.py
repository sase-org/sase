"""Recover run-owned bead closes after terminal host-finalization failure.

A provider may close its beads during its turn. When host finalization then
fails terminally — a commit that never landed, or a declaration recovery that
never produced a submission — every still-current ``done`` close attributable
to that run is undone through the canonical Rust bead mutation engine, with
close history archived, closed ancestors reopened, and one ``STITCH FAILED:``
note appended per affected close episode.

The coordinator runs at the terminal controller failure boundary inside
:func:`sase.finalizers.controller.run_finalizers`, so both the provider-turn
path and the monitor/prepared-completion path funnel through it. It never
raises and never turns the failed finalizer into a success: on recovery
storage or publication failure it retains the original finalizer error plus
an actionable diagnostic in the run artifacts, and the controller still raises
the original failure.

Eligibility (all must hold before any mutation):

- a stable host-run identity is available (never guessed from assignees or
  timestamps; human closes stay unattributed and are never recovered);
- no authentic handoff is pending;
- the run has repository obligations (clean/no-code completion skips);
- at least one obligated repository has no landing proof: no commit marker
  that matches the repository path *and* this run *and* carries a commit SHA
  with push not refused, and no accepted typed deferral covering it.

Landing proofs come from the existing finalizer ledger
(``commit_results.json``) and reconciliation code: never exit codes, never a
clean tree alone, and never a marker from another repository or attempt.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.agent.pending_handoff import has_pending_handoff
from sase.bead.close_provenance import host_run_close_provenance
from sase.finalizers.artifacts import write_json_atomic
from sase.finalizers.commit_repair_common import bound_stream
from sase.finalizers.commit_repair_markers import load_commit_results

STITCH_FAILED_NOTE_PREFIX = "STITCH FAILED:"
RECOVERY_REQUEST_FILENAME = "failed_close_recovery_request.json"
RECOVERY_OUTCOME_FILENAME = "failed_close_recovery_outcome.json"
_RECOVERY_JOURNAL_EVENT = "failed_close_recovery"
_MACHINE_WORKFLOW = "failed_close_recovery"


@dataclass(frozen=True)
class _ObligatedRepository:
    """One repository obligation the failed run was expected to land."""

    obligation_id: str
    name: str
    path: str


@dataclass(frozen=True)
class _RepositorySettlement:
    """Whether one obligated repository provably landed."""

    repo: _ObligatedRepository
    landed: bool
    detail: str
    deferred: bool = False


@dataclass(frozen=True)
class _RecoveryAssessment:
    """The read-only verdict a terminal failure was assessed against."""

    should_recover: bool
    reason: str
    repositories: tuple[_RepositorySettlement, ...] = ()
    stitch_attempted: bool = False
    failure_code: str = ""
    failure_message: str = ""


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


def _utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _failure_code_and_message(failure: BaseException) -> tuple[str, str]:
    """Derive a stable failure code and message from a terminal exception."""
    from sase.finalizers.commit_types import BuiltinCommitFinalizerError
    from sase.finalizers.controller_context import FinalizerControllerError

    message = str(failure).strip() or type(failure).__name__
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


def _run_provenance(env: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    return host_run_close_provenance(env)


@contextmanager
def source_identity_scope(
    intent: Mapping[str, Any] | None,
    intent_root: str | None,
) -> Iterator[None]:
    """Publish the prepared intent's source identity for recovery attribution.

    The monitor runs finalizers under its own artifacts directory and may
    mint a new turn nonce, so the ambient ``SASE_AGENT_TIMESTAMP`` would
    attribute the prepared run's closes to the monitor. The scope redirects
    close-recovery attribution (only) to the intent creator's run identity
    for the wrapped call and restores the ambient environment after.
    """
    from sase.bead.close_provenance import (
        RECOVERY_AGENT_NAME_ENV_VAR,
        RECOVERY_ARTIFACTS_DIR_ENV_VAR,
        RECOVERY_RUN_ID_ENV_VAR,
    )

    creator = intent.get("creator") if isinstance(intent, Mapping) else None
    overrides: dict[str, str] = {}
    if isinstance(creator, Mapping):
        run_id = str(creator.get("run_id", "") or "").strip()
        agent_name = str(creator.get("agent_name", "") or "").strip()
        if run_id and agent_name and intent_root:
            overrides = {
                RECOVERY_RUN_ID_ENV_VAR: run_id,
                RECOVERY_AGENT_NAME_ENV_VAR: agent_name,
                RECOVERY_ARTIFACTS_DIR_ENV_VAR: intent_root,
            }
    previous = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _context_obligations(
    artifacts_dir: str,
) -> tuple[tuple[_ObligatedRepository, ...], set[str], tuple[Mapping[str, Any], ...]]:
    """Return (repository obligations, deferred repo ids, raw markers).

    Prefers the accepted declaration's obligations (they survived submit-time
    adjudication); falls back to the latest published context when no
    declaration was accepted, which is exactly the declaration-recovery
    failure case. Returns empty obligations when neither exists: without
    trustworthy obligation evidence there is nothing to assess.
    """
    markers = _load_markers(artifacts_dir)
    try:
        from sase.finalizers.commit_declaration import (
            accepted_repos_from_host,
            load_accepted_commit_declaration,
        )

        envelope, accepted_context, host_records, accepted_deferrals_raw = (
            load_accepted_commit_declaration(artifacts_dir)
        )
        accepted_repos = accepted_repos_from_host(
            accepted_context,
            host_records,
            instance_id="coordinator",
        )
        deferred = {
            str(item.get("repo_id", ""))
            for item in accepted_deferrals_raw
            if isinstance(item, Mapping) and str(item.get("repo_id", ""))
        }
        obligated: list[_ObligatedRepository] = []
        for repo in accepted_repos:
            for obligation in accepted_context.obligations:
                if obligation.kind != "repository":
                    continue
                obligation_id = str(getattr(obligation, "obligation_id", "") or "")
                if not obligation_id:
                    continue
                if not _obligation_matches_repo(obligation, repo):
                    continue
                obligated.append(
                    _ObligatedRepository(
                        obligation_id=obligation_id,
                        name=repo.name,
                        path=repo.path,
                    )
                )
        return tuple(obligated), deferred, markers
    except Exception:
        pass
    try:
        from sase.finalizers import declaration as declaration_module
        from sase.finalizers.declaration_store import load_accepted_host_repositories

        root = declaration_module.require_artifacts_dir(
            artifacts_dir,
            "failed close recovery assessment",
        )
        context = declaration_module.load_latest_finalizer_context(root)
        host_records = load_accepted_host_repositories(root)
        path_by_id = {
            record.obligation_id: (record.name, record.path) for record in host_records
        }
        fallback: list[_ObligatedRepository] = []
        for obligation in context.obligations:
            if obligation.kind != "repository":
                continue
            if obligation.obligation_id not in path_by_id:
                continue
            name, path = path_by_id[obligation.obligation_id]
            fallback.append(
                _ObligatedRepository(
                    obligation_id=obligation.obligation_id,
                    name=name or obligation.obligation_id,
                    path=path,
                )
            )
        return tuple(fallback), set(), markers
    except Exception:
        return (), set(), markers


def _obligation_matches_repo(obligation: Any, repo: Any) -> bool:
    from sase.finalizers.declaration_store import repository_obligation_id

    try:
        return bool(obligation.obligation_id == repository_obligation_id(repo))
    except Exception:
        return False


def _load_markers(artifacts_dir: str) -> tuple[Mapping[str, Any], ...]:
    try:
        return tuple(load_commit_results(Path(artifacts_dir)))
    except Exception:
        return ()


def _landing_proof(
    repo: _ObligatedRepository,
    run_id: str,
    markers: Sequence[Mapping[str, Any]],
) -> _RepositorySettlement:
    """Decide whether one exact marker proves this repo landed for this run."""
    from sase.llm_provider.commit_finalizer_git import normalize_path

    want = normalize_path(repo.path)
    for marker in markers:
        if not isinstance(marker, Mapping):
            continue
        cwd = marker.get("cwd")
        if not isinstance(cwd, str) or normalize_path(cwd) != want:
            continue
        if str(marker.get("run_id") or "") != run_id:
            continue
        if marker.get("settled") or marker.get("superseded_by"):
            continue
        commit_sha = marker.get("commit_sha")
        if not isinstance(commit_sha, str) or not commit_sha.strip():
            continue
        if marker.get("pushed") is False:
            return _RepositorySettlement(
                repo=repo,
                landed=False,
                detail=f"commit {commit_sha[:12]} is unpushed",
            )
        return _RepositorySettlement(
            repo=repo,
            landed=True,
            detail=f"commit {commit_sha[:12]}",
        )
    return _RepositorySettlement(repo=repo, landed=False, detail="no landing marker")


def _attempt_inputs_for_repo(
    artifacts_dir: str,
    repo_path: str,
) -> list[dict[str, Any]]:
    """Return recorded stitch attempt inputs touching *repo_path*, if any."""
    from sase.llm_provider.commit_finalizer_git import normalize_path

    runs_dir = Path(artifacts_dir) / "finalizer_runs"
    try:
        candidates = sorted(runs_dir.glob("*/attempt-*.inputs.json"))
    except OSError:
        return []
    want = normalize_path(repo_path)
    matches: list[dict[str, Any]] = []
    for candidate in candidates:
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        recorded = payload.get("repo_path")
        if isinstance(recorded, str) and normalize_path(recorded) == want:
            matches.append(payload)
    return matches


def _message_files_for_repo(repo_path: str) -> list[str]:
    """Return preserved commit-message paths under one repository."""
    root = Path(repo_path) / ".sase" / "finalizers"
    try:
        candidates = sorted(root.glob("commit-message-*.txt"))
    except OSError:
        return []
    return [str(candidate) for candidate in candidates if candidate.is_file()]


def _hook_tail_for_repo(artifacts_dir: str, repo_path: str) -> str:
    """Return the bounded hook-output tail for one repository, if any."""
    try:
        from sase.workflows.commit.command_hooks import (
            hook_output_tail_from_metadata,
            load_latest_commit_hook_metadata,
        )

        hook = load_latest_commit_hook_metadata(artifacts_dir, repo_path)
        if hook is None:
            return ""
        return bound_stream(hook_output_tail_from_metadata(hook))
    except Exception:
        return ""


def _declaration_evidence_path(artifacts_dir: str) -> str | None:
    """Return the declaration-recovery evidence file, when one was written."""
    from sase.finalizers.declaration_recovery import (
        FINAL_DECLARATION_RECOVERY_EVIDENCE_FILENAME,
    )

    candidate = Path(artifacts_dir) / FINAL_DECLARATION_RECOVERY_EVIDENCE_FILENAME
    try:
        if candidate.is_file():
            return str(candidate)
    except OSError:
        return None
    return None


def _assess_terminal_failure(
    artifacts_dir: str | None,
    *,
    failure_code: str,
    failure_message: str,
    provenance: Mapping[str, Any] | None = None,
) -> _RecoveryAssessment:
    """Decide whether a terminal failure warrants failed-close recovery."""
    if not artifacts_dir:
        return _RecoveryAssessment(
            should_recover=False,
            reason="no_artifacts_dir",
            failure_code=failure_code,
            failure_message=failure_message,
        )
    proven = provenance if provenance is not None else _run_provenance()
    if proven is None:
        return _RecoveryAssessment(
            should_recover=False,
            reason="no_run_provenance",
            failure_code=failure_code,
            failure_message=failure_message,
        )
    run_id = str(proven.get("run_id", ""))
    try:
        if has_pending_handoff(artifacts_dir):
            return _RecoveryAssessment(
                should_recover=False,
                reason="pending_handoff",
                failure_code=failure_code,
                failure_message=failure_message,
            )
    except Exception:
        pass
    obligations, deferred_ids, markers = _context_obligations(artifacts_dir)
    if not obligations:
        return _RecoveryAssessment(
            should_recover=False,
            reason="no_repository_obligations",
            failure_code=failure_code,
            failure_message=failure_message,
        )
    settlements: list[_RepositorySettlement] = []
    for repo in obligations:
        if repo.obligation_id in deferred_ids:
            settlements.append(
                _RepositorySettlement(
                    repo=repo, landed=True, detail="accepted deferral", deferred=True
                )
            )
            continue
        settlements.append(_landing_proof(repo, run_id, markers))
    unlanded = [item for item in settlements if not item.landed]
    if not unlanded:
        return _RecoveryAssessment(
            should_recover=False,
            reason="all_repositories_landed",
            repositories=tuple(settlements),
            stitch_attempted=_stitch_attempted(
                artifacts_dir, obligations, markers, run_id
            ),
            failure_code=failure_code,
            failure_message=failure_message,
        )
    return _RecoveryAssessment(
        should_recover=True,
        reason="unlanded_repository_obligations",
        repositories=tuple(settlements),
        stitch_attempted=_stitch_attempted(artifacts_dir, obligations, markers, run_id),
        failure_code=failure_code,
        failure_message=failure_message,
    )


def _stitch_attempted(
    artifacts_dir: str,
    obligations: tuple[_ObligatedRepository, ...],
    markers: Sequence[Mapping[str, Any]],
    run_id: str,
) -> bool:
    """Return whether any stitch output exists for this run's obligations."""
    for marker in markers:
        if isinstance(marker, Mapping) and str(marker.get("run_id") or "") == run_id:
            return True
    for repo in obligations:
        if _attempt_inputs_for_repo(artifacts_dir, repo.path):
            return True
        if _message_files_for_repo(repo.path):
            return True
    return False


def _build_recovery_note(
    assessment: _RecoveryAssessment,
    provenance: Mapping[str, Any],
    *,
    artifacts_dir: str,
    evidence_locations: Sequence[str],
) -> str:
    """Render the ``STITCH FAILED:`` note recorded on every recovered bead."""
    run_id = str(provenance.get("run_id", ""))
    agent_name = str(provenance.get("agent_name", ""))
    lines = [
        f"{STITCH_FAILED_NOTE_PREFIX} host finalization failed "
        f"({assessment.failure_code}) for run {run_id} ({agent_name}); "
        "reopening this run's still-current done closes.",
    ]
    unlanded = [item for item in assessment.repositories if not item.landed]
    if unlanded:
        lines.append(
            "Repositories without landing proof: "
            + "; ".join(
                f"{item.repo.name} ({item.repo.path}; {item.detail})"
                for item in unlanded
            )
            + "."
        )
    else:
        lines.append("No repository obligation is missing a landing proof.")
    landed = [item for item in assessment.repositories if item.landed]
    if landed:
        lines.append(
            "Repositories landed or discharged: "
            + "; ".join(f"{item.repo.name} ({item.detail})" for item in landed)
            + "."
        )
    if assessment.stitch_attempted:
        message_files: list[str] = []
        for item in assessment.repositories:
            message_files.extend(_message_files_for_repo(item.repo.path))
            for attempt in _attempt_inputs_for_repo(artifacts_dir, item.repo.path):
                recorded = attempt.get("message_file")
                if isinstance(recorded, str) and recorded.strip():
                    message_files.append(recorded.strip())
        unique_files = sorted(set(message_files))
        if unique_files:
            lines.append(
                "Preserved commit-message paths: " + "; ".join(unique_files) + "."
            )
        else:
            lines.append("No commit-message file was preserved by the failed attempts.")
        lines.append(
            "Failure evidence: " + bound_stream(assessment.failure_message) + "."
        )
        tails = [
            _hook_tail_for_repo(artifacts_dir, item.repo.path)
            for item in assessment.repositories
        ]
        tails = [tail for tail in tails if tail]
        if tails:
            lines.append("Hook output tail: " + " | ".join(tails) + ".")
    else:
        lines.append(
            "No stitch/message file was created: declaration recovery failed "
            "before a stitch ran. Declaration diagnostic: "
            + bound_stream(assessment.failure_message)
            + "."
        )
        declaration_evidence = _declaration_evidence_path(artifacts_dir)
        if declaration_evidence is not None:
            lines.append("Declaration recovery evidence: " + declaration_evidence + ".")
    if evidence_locations:
        lines.append("Evidence locations: " + "; ".join(evidence_locations) + ".")
    return "\n".join(lines)


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


def _run_machine_lane_recovery(
    project: str,
    request: Mapping[str, Any],
    *,
    run_id: str,
) -> tuple[dict[str, Any], bool, str]:
    """Apply the recovery mutation through the machine write lane.

    Returns ``(report, committed, publication_error)``. ``committed`` is
    false when the mutation changed nothing (idempotent retry) or when the
    commit itself failed; ``publication_error`` names a commit or push
    failure. The failed product hook is never invoked to commit the note,
    and the user-owned primary snapshot is never touched: the store comes
    from the machine lane and converges through sidecar auto-sync.
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
            committed = False
            if changed:
                committed = _commit_recovery_mutation(
                    beads_dir,
                    run_id,
                    already_locked=already_locked,
                    operation_context=store.context,
                )
                if not committed:
                    return (
                        dict(report),
                        False,
                        "recovery mutation was not committed to the bead store",
                    )
        if not changed and not report.get("already_applied"):
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
        if changed or report.get("already_applied"):
            try:
                schedule_beads_sidecar_convergence(store.project)
            except Exception:
                pass
        return dict(report), committed if changed else True, push_error


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
        outcome.error = str(exc) or type(exc).__name__
        return outcome


def _coordinate_failed_close_recovery(
    artifacts_dir: str | None,
    failure: BaseException,
    outcome: _RecoveryOutcome,
) -> _RecoveryOutcome:
    failure_code, failure_message = _failure_code_and_message(failure)
    provenance = _run_provenance()
    assessment = _assess_terminal_failure(
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
    evidence_locations = [
        str(location)
        for location in [
            artifacts_dir,
            artifact_dir,
            _declaration_evidence_path(artifacts_dir),
        ]
        if location
    ]
    note = _build_recovery_note(
        assessment,
        provenance,
        artifacts_dir=artifacts_dir,
        evidence_locations=evidence_locations,
    )
    request = {
        "run_id": run_id,
        "failed_at": _utc_now(),
        "failure_code": failure_code,
        "evidence_locations": evidence_locations,
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
            },
        )
        _record_recovery_journal(
            artifacts_dir,
            {"error": outcome.error, "failure_code": failure_code},
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
            },
        )
        _record_recovery_journal(
            artifacts_dir,
            {"error": outcome.error, "failure_code": failure_code},
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
        },
    )
    return outcome


__all__ = [
    "RECOVERY_OUTCOME_FILENAME",
    "RECOVERY_REQUEST_FILENAME",
    "STITCH_FAILED_NOTE_PREFIX",
    "coordinate_failed_close_recovery",
    "source_identity_scope",
]
