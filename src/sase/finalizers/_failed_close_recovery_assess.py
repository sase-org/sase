"""Landing-proof assessment and recovery-note rendering for failed closes."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.pending_handoff import has_pending_handoff
from sase.bead.close_provenance import (
    RECOVERY_RUN_ID_ENV_VAR,
    RUN_ID_ENV_VAR,
    host_run_close_provenance,
)
from sase.core.finalizer_wire import (
    LandingAttemptFactWire,
    LandingMarkerFactWire,
    RepositoryLandingProofRequestWire,
)
from sase.finalizers.commit_repair_markers import load_commit_results
from sase.procs.text_bounding import bound_and_redact_text

STITCH_FAILED_NOTE_PREFIX = "STITCH FAILED:"
_DIAGNOSTIC_MAX_CHARS = 4000


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


def run_provenance(env: Mapping[str, str] | None = None) -> dict[str, Any] | None:
    """Return the host-run close provenance used to attribute recovery."""
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


def _redact_diagnostic(text: str) -> str:
    """Redact secrets and keep the bounded tail of one diagnostic string."""
    return bound_and_redact_text(text, _DIAGNOSTIC_MAX_CHARS) or ""


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _landing_marker_fact(marker: Mapping[str, Any]) -> LandingMarkerFactWire | None:
    from sase.llm_provider.commit_finalizer_git import normalize_path

    cwd = marker.get("cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        return None
    pushed = marker.get("pushed")
    return LandingMarkerFactWire(
        cwd=normalize_path(cwd),
        run_id=str(marker.get("run_id") or ""),
        operation_id=_optional_text(marker.get("operation_id")),
        commit_sha=_optional_text(marker.get("commit_sha")),
        pushed=pushed if isinstance(pushed, bool) else None,
        settled=bool(marker.get("settled")),
        superseded_by=_optional_text(marker.get("superseded_by")),
        head=_optional_text(marker.get("head")),
        dirty_fingerprint=_optional_text(marker.get("dirty_fingerprint")),
        message_digest=_optional_text(marker.get("message_digest")),
    )


def _landing_proof(
    repo: _ObligatedRepository,
    run_id: str,
    markers: Sequence[Mapping[str, Any]],
    *,
    artifacts_dir: str,
) -> _RepositorySettlement:
    """Decide whether current attempt evidence proves this repo landed."""
    from sase.core.finalizer_facade import assess_repository_landing_proof
    from sase.llm_provider.commit_finalizer_git import normalize_path

    want = normalize_path(repo.path)
    marker_facts = [
        fact
        for marker in markers
        if isinstance(marker, Mapping)
        for fact in [_landing_marker_fact(marker)]
        if fact is not None
    ]
    source_run_id = (os.environ.get(RECOVERY_RUN_ID_ENV_VAR) or "").strip()
    executor_run_id = (os.environ.get(RUN_ID_ENV_VAR) or "").strip()
    request = RepositoryLandingProofRequestWire(
        run_id=run_id,
        repo_path=want,
        markers=marker_facts,
        attempts=_attempt_facts_for_repo(artifacts_dir, want),
        source_run_id=source_run_id or None,
        executor_run_id=executor_run_id or None,
    )
    proof = assess_repository_landing_proof(request)
    return _RepositorySettlement(repo=repo, landed=proof.landed, detail=proof.detail)


def _attempt_input_files(artifacts_dir: str) -> list[Path]:
    found: list[Path] = []
    for root_name in ("finalizers", "finalizer_runs"):
        root = Path(artifacts_dir) / root_name
        try:
            found.extend(sorted(root.glob("*/attempt-*.inputs.json")))
        except OSError:
            continue
    return found


def _attempt_facts_for_repo(
    artifacts_dir: str, repo_path: str
) -> list[LandingAttemptFactWire]:
    """Return recorded stitch attempt facts touching *repo_path*, if any."""
    from sase.llm_provider.commit_finalizer_git import normalize_path

    want = normalize_path(repo_path)
    matches: list[LandingAttemptFactWire] = []
    for candidate in _attempt_input_files(artifacts_dir):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        recorded = payload.get("repo_path")
        if not isinstance(recorded, str) or normalize_path(recorded) != want:
            continue
        fingerprints = payload.get("dirty_fingerprints")
        dirty_fingerprint = None
        if fingerprints:
            canonical = json.dumps(fingerprints, sort_keys=True)
            dirty_fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        matches.append(
            LandingAttemptFactWire(
                repo_path=want,
                operation_id=_optional_text(payload.get("operation_id")),
                head=_optional_text(payload.get("head")),
                dirty_fingerprint=dirty_fingerprint,
                message_digest=_optional_text(payload.get("message_digest")),
                message_file=_optional_text(payload.get("message_file")),
            )
        )
    return matches


def _message_files_from_attempts(
    attempts: Sequence[LandingAttemptFactWire],
) -> list[str]:
    """Return commit-message paths recorded on this run's attempts."""
    files = [
        attempt.message_file.strip()
        for attempt in attempts
        if attempt.message_file and attempt.message_file.strip()
    ]
    return sorted(set(files))


def _hook_tail_for_repo(artifacts_dir: str, repo_path: str) -> str:
    """Return the redacted hook-output tail for one repository, if any."""
    try:
        from sase.workflows.commit.command_hooks import (
            hook_output_tail_from_metadata,
            load_latest_commit_hook_metadata,
        )

        hook = load_latest_commit_hook_metadata(artifacts_dir, repo_path)
        if hook is None:
            return ""
        return _redact_diagnostic(hook_output_tail_from_metadata(hook))
    except Exception:
        return ""


def declaration_evidence_path(artifacts_dir: str) -> str | None:
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


def assess_terminal_failure(
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
    proven = provenance if provenance is not None else run_provenance()
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
        settlements.append(
            _landing_proof(repo, run_id, markers, artifacts_dir=artifacts_dir)
        )
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
        if _attempt_facts_for_repo(artifacts_dir, repo.path):
            return True
    return False


def build_recovery_note(
    assessment: _RecoveryAssessment,
    provenance: Mapping[str, Any],
    *,
    artifacts_dir: str,
    evidence_locations: Sequence[str],
    snapshot_errors: Sequence[Mapping[str, str]] = (),
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
            message_files.extend(
                _message_files_from_attempts(
                    _attempt_facts_for_repo(artifacts_dir, item.repo.path)
                )
            )
        unique_files = sorted(set(message_files))
        if unique_files:
            lines.append(
                "Preserved commit-message paths: " + "; ".join(unique_files) + "."
            )
        else:
            lines.append("No commit-message file was preserved by the failed attempts.")
        lines.append(
            "Failure evidence: " + _redact_diagnostic(assessment.failure_message) + "."
        )
        tails = [
            _hook_tail_for_repo(artifacts_dir, item.repo.path)
            for item in assessment.repositories
        ]
        tails = [tail for tail in tails if tail]
        if tails:
            combined = _redact_diagnostic(" | ".join(tails))
            lines.append("Hook output tail: " + combined + ".")
    else:
        lines.append(
            "No stitch/message file was created: declaration recovery failed "
            "before a stitch ran. Declaration diagnostic: "
            + _redact_diagnostic(assessment.failure_message)
            + "."
        )
        declaration_evidence = declaration_evidence_path(artifacts_dir)
        if declaration_evidence is not None:
            lines.append("Declaration recovery evidence: " + declaration_evidence + ".")
    if evidence_locations:
        lines.append("Evidence locations: " + "; ".join(evidence_locations) + ".")
    for error in snapshot_errors:
        name = str(error.get("repo") or error.get("repo_path") or "repository")
        detail = _redact_diagnostic(str(error.get("error", "snapshot failed")))
        lines.append(f"Verified snapshot unavailable for {name}: {detail}.")
    return "\n".join(lines)


__all__ = [
    "STITCH_FAILED_NOTE_PREFIX",
    "assess_terminal_failure",
    "build_recovery_note",
    "declaration_evidence_path",
    "run_provenance",
    "source_identity_scope",
]
