"""Built-in ``builtin@commit`` finalizer execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.core.finalizer_facade import validate_finalizer_submission
from sase.finalizers.config import ConfiguredFinalizerInstance
from sase.finalizers import declaration as finalizer_declaration
from sase.finalizers.commit_repair import (
    load_commit_results as _load_commit_results,
    marker_evidence as _marker_evidence,
    marker_matches_repo as _marker_matches_repo,
    new_commit_markers as _new_commit_markers,
    record_stitch_artifacts as _record_stitch_artifacts,
    resolve_commit_conflict as _resolve_commit_conflict,
    run_stitch_create,
    run_stitch_resume,
    stitch_failure_message as _stitch_failure_message,
)
from sase.finalizers.commit_types import (
    BuiltinCommitExecution,
    BuiltinCommitFinalizerError,
    ResumeRunner,
    StitchCommandResult,
    StitchRunner,
    failed_result as _failed_result,
    refused_result as _refused_result,
    success_result as _success_result,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.reconciliation import (
    PreparedCommitDirtyState,
    prepare_commit_dirty_state,
)
from sase.llm_provider.commit_finalizer_artifacts import artifact_root
from sase.llm_provider.commit_finalizer_baseline import (
    BASELINE_FILENAME,
    FINALIZER_BASELINE_FILENAME,
)
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.commit_finalizer_git import (
    discarded_dirty_work_evidence,
    discarded_dirty_work_message,
    git_changed_files,
    normalize_path,
    split_pre_existing_changed_files,
)
from sase.llm_provider.commit_finalizer_prompting import failure_message
from sase.llm_provider.commit_finalizer_types import DirtyRepo, DirtyState
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions, ModelTier
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

_COMMIT_PROVIDER_REF = "builtin@commit"


def execute_commit_finalizer(
    instance: ConfiguredFinalizerInstance,
    context: FinalizerExecutionContext,
    *,
    provider: Any,
    invoke_result: InvokeResult,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    options: LLMInvocationOptions | None = None,
    stitch_runner: StitchRunner | None = None,
    resume_runner: ResumeRunner | None = None,
) -> BuiltinCommitExecution:
    """Execute accepted ``commit`` declarations through ``sase stitch create``."""

    if instance.provider_ref != _COMMIT_PROVIDER_REF:
        raise BuiltinCommitFinalizerError(
            f"commit executor received provider {instance.provider_ref!r}",
            result=_failed_result(
                instance.instance_id,
                "invalid_provider",
                f"commit executor received provider {instance.provider_ref!r}",
            ),
            invoke_result=invoke_result,
        )

    artifacts = artifact_root(context.artifacts_dir)
    project_dir = resolve_finalizer_project_dir()
    state = prepare_commit_dirty_state(project_dir, artifacts)
    if state.dirty_state.is_clean:
        _raise_if_unpublished_bead_state(
            state,
            instance_id=instance.instance_id,
            invoke_result=invoke_result,
        )
        return BuiltinCommitExecution(
            invoke_result=invoke_result,
            result=_success_result(
                instance.instance_id,
                attempts=(),
                evidence=(),
            ),
        )

    dirty_before_decisions = state.dirty_state
    try:
        root = finalizer_declaration.require_artifacts_dir(
            context.artifacts_dir,
            "finalizer declaration load",
        )
        accepted_context = finalizer_declaration.load_latest_finalizer_context(root)
        envelope = _load_current_final_submission(context.artifacts_dir)
    except Exception as exc:
        result = _failed_result(
            instance.instance_id,
            "missing_commit_declaration",
            f"commit finalizer requires a current accepted declaration: {exc}",
        )
        raise BuiltinCommitFinalizerError(
            result.diagnostics[0].message,
            result=result,
            invoke_result=invoke_result,
        ) from exc

    obligation_by_id = {
        obligation.obligation_id: obligation
        for obligation in accepted_context.obligations
        if obligation.kind == "repository"
    }
    decisions = _commit_decisions_for_instance(envelope, instance.instance_id)
    current_result = invoke_result
    attempts: list[FinalizerAttemptWire] = []
    evidence: list[FinalizerOutcomeEvidenceWire] = []
    runner = stitch_runner or run_stitch_create
    resume = resume_runner or run_stitch_resume
    ledger_before_all = _load_commit_results(artifacts)

    for repo in _dirty_repos_in_context_order(state.dirty_state, decisions):
        _reject_stale_repository_obligation(
            repo, obligation_by_id, instance.instance_id
        )
        decision = decisions[_repository_decision_id(repo)]
        action = str(decision.get("action"))
        if action == "refuse":
            reason = str(decision.get("reason", "")).strip()
            result = _refused_result(instance.instance_id, reason)
            raise BuiltinCommitFinalizerError(
                f"commit finalizer refused dirty repository {repo.name}: {reason}",
                result=result,
                invoke_result=current_result,
            )

        message = str(decision.get("message", "")).strip()
        protected = _protected_baseline_paths(artifacts, repo.path)
        before_markers = _load_commit_results(artifacts)
        stitch = runner(repo, message, protected, context)
        attempts.append(
            FinalizerAttemptWire(
                attempt=len(attempts) + 1,
                status="success" if stitch.returncode == 0 else "failed",
                diagnostic_code=None
                if stitch.returncode == 0
                else (
                    "commit_conflict"
                    if stitch.returncode == EXIT_CODE_CONFLICT
                    else "stitch_failed"
                ),
            )
        )
        _record_stitch_artifacts(
            context,
            instance.instance_id,
            len(attempts),
            stitch,
        )
        if stitch.returncode == EXIT_CODE_CONFLICT:
            current_result = _resolve_commit_conflict(
                repo,
                context,
                provider=provider,
                invoke_result=current_result,
                model_tier=model_tier,
                suppress_output=suppress_output,
                model_override=model_override,
                options=options,
                resume_runner=resume,
                attempts=attempts,
                evidence=evidence,
                before_markers=before_markers,
            )
        elif stitch.returncode != 0:
            message_text = _stitch_failure_message(repo, stitch)
            result = _failed_result(
                instance.instance_id,
                "stitch_failed",
                message_text,
                attempts=attempts,
                evidence=evidence,
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=result,
                invoke_result=current_result,
            )

        markers = _new_commit_markers(before_markers, _load_commit_results(artifacts))
        repo_markers = [
            marker for marker in markers if _marker_matches_repo(marker, repo)
        ]
        if not repo_markers:
            message_text = (
                f"sase stitch create completed for {repo.name}, but no "
                "commit_results.json entry was recorded"
            )
            result = _failed_result(
                instance.instance_id,
                "missing_commit_result",
                message_text,
                attempts=attempts,
                evidence=evidence,
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=result,
                invoke_result=current_result,
            )
        evidence.extend(_marker_evidence(repo_markers[-1]))

        remaining = _unexpected_remaining_paths(repo.path, protected)
        if remaining:
            message_text = (
                f"sase stitch create left uncommitted attributable paths in "
                f"{repo.name}: " + ", ".join(remaining)
            )
            result = _failed_result(
                instance.instance_id,
                "dirty_after_stitch",
                message_text,
                attempts=attempts,
                evidence=evidence,
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=result,
                invoke_result=current_result,
            )

        state = prepare_commit_dirty_state(project_dir, artifacts)

    _reject_discarded_dirty_work(
        dirty_before_decisions,
        state.dirty_state,
        artifacts=artifacts,
        project_dir=project_dir,
        instance_id=instance.instance_id,
        attempts=attempts,
        evidence=evidence,
        invoke_result=current_result,
        ledger_before=ledger_before_all,
    )

    if not state.dirty_state.is_clean:
        message_text = failure_message(
            state.dirty_state,
            max_passes=1,
            no_progress_passes=0,
        )
        result = _failed_result(
            instance.instance_id,
            "dirty_after_commit_decisions",
            message_text,
            attempts=attempts,
            evidence=evidence,
        )
        raise BuiltinCommitFinalizerError(
            message_text,
            result=result,
            invoke_result=current_result,
        )

    _raise_if_unpublished_bead_state(
        state,
        instance_id=instance.instance_id,
        invoke_result=current_result,
        attempts=attempts,
        evidence=evidence,
    )
    return BuiltinCommitExecution(
        invoke_result=current_result,
        result=_success_result(
            instance.instance_id,
            attempts=attempts,
            evidence=evidence,
        ),
    )


def _raise_if_unpublished_bead_state(
    state: PreparedCommitDirtyState,
    *,
    instance_id: str,
    invoke_result: InvokeResult,
    attempts: Sequence[FinalizerAttemptWire] = (),
    evidence: Sequence[FinalizerOutcomeEvidenceWire] = (),
) -> None:
    if state.bead_publication_error is None:
        return
    result = _failed_result(
        instance_id,
        "bead_state_unpublished",
        state.bead_publication_error,
        attempts=attempts,
        evidence=evidence,
    )
    raise BuiltinCommitFinalizerError(
        state.bead_publication_error,
        result=result,
        invoke_result=invoke_result,
    )


def _commit_decisions_for_instance(
    envelope: Mapping[str, Any],
    instance_id: str,
) -> dict[str, Mapping[str, Any]]:
    payloads = envelope.get("payloads")
    if not isinstance(payloads, list):
        return {}
    for item in payloads:
        if not isinstance(item, Mapping) or item.get("instance_id") != instance_id:
            continue
        payload = item.get("payload")
        if not isinstance(payload, Mapping):
            return {}
        repositories = payload.get("repositories")
        if not isinstance(repositories, list):
            return {}
        decisions: dict[str, Mapping[str, Any]] = {}
        for decision in repositories:
            if not isinstance(decision, Mapping):
                continue
            repo_id = decision.get("repo_id")
            if isinstance(repo_id, str):
                decisions[repo_id] = decision
        return decisions
    return {}


def _load_current_final_submission(artifacts_dir: str | None) -> dict[str, Any]:
    root = finalizer_declaration.require_artifacts_dir(
        artifacts_dir,
        "finalizer declaration load",
    )
    plan = finalizer_declaration.load_finalizer_plan(root)
    context = finalizer_declaration.load_latest_finalizer_context(root)
    submission = finalizer_declaration.load_latest_finalizer_submission(root)
    envelope = finalizer_declaration.normalize_submission_envelope(
        submission["submission"]
    )
    validate_finalizer_submission(plan, context, envelope)
    finalizer_declaration.validate_provider_payloads(plan, context, envelope)
    return envelope


def _dirty_repos_in_context_order(
    dirty_state: DirtyState,
    decisions: Mapping[str, Mapping[str, Any]],
) -> list[DirtyRepo]:
    repos_by_id = {_repository_decision_id(repo): repo for repo in dirty_state.repos}
    ordered: list[DirtyRepo] = []
    for repo_id in decisions:
        repo = repos_by_id.get(repo_id)
        if repo is not None:
            ordered.append(repo)
    missing = sorted(set(repos_by_id) - set(decisions))
    if missing:
        raise BuiltinCommitFinalizerError(
            "commit declaration is stale; missing decision(s): " + ", ".join(missing),
            result=_failed_result(
                "commit",
                "stale_commit_declaration",
                "commit declaration is stale; missing decision(s): "
                + ", ".join(missing),
            ),
        )
    return ordered


def _repository_decision_id(repo: DirtyRepo) -> str:
    from sase.finalizers.declaration import repository_obligation_id

    return repository_obligation_id(repo)


def _protected_baseline_paths(
    artifacts: Path | None, repo_path: str
) -> tuple[str, ...]:
    if artifacts is None:
        return ()
    baseline = _load_baseline_fingerprints(artifacts, repo_path)
    if not baseline:
        return ()
    changed = git_changed_files(repo_path)
    _still, pre_existing = split_pre_existing_changed_files(
        repo_path,
        changed,
        baseline,
    )
    return tuple(sorted(pre_existing))


def _load_baseline_fingerprints(
    artifacts: Path,
    repo_path: str,
) -> dict[str, tuple[str, str | None]]:
    normalized_repo = normalize_path(repo_path)
    records = _read_finalizer_baseline_records(artifacts)
    if records is None:
        return _read_legacy_baseline(artifacts, normalized_repo)
    for record in records:
        if normalize_path(str(record.get("path", ""))) != normalized_repo:
            continue
        raw = record.get("fingerprints")
        if isinstance(raw, Mapping):
            return _normalize_fingerprints(raw)
    return {}


def _read_finalizer_baseline_records(
    artifacts: Path,
) -> list[Mapping[str, Any]] | None:
    try:
        payload = json.loads(
            (artifacts / FINALIZER_BASELINE_FILENAME).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
        return None
    records = payload.get("repositories")
    if not isinstance(records, list):
        return None
    return [item for item in records if isinstance(item, Mapping)]


def _read_legacy_baseline(
    artifacts: Path,
    normalized_repo: str,
) -> dict[str, tuple[str, str | None]]:
    try:
        payload = json.loads(
            (artifacts / BASELINE_FILENAME).read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, Mapping):
        return {}
    raw = payload.get(normalized_repo)
    return _normalize_fingerprints(raw) if isinstance(raw, Mapping) else {}


def _normalize_fingerprints(
    raw: Mapping[str, Any],
) -> dict[str, tuple[str, str | None]]:
    normalized: dict[str, tuple[str, str | None]] = {}
    for path, value in raw.items():
        if (
            isinstance(path, str)
            and isinstance(value, list)
            and len(value) == 2
            and isinstance(value[0], str)
            and (value[1] is None or isinstance(value[1], str))
        ):
            normalized[path] = (value[0], value[1])
    return normalized


def _unexpected_remaining_paths(repo_path: str, protected: Sequence[str]) -> list[str]:
    protected_set = set(protected)
    return [path for path in git_changed_files(repo_path) if path not in protected_set]


def _reject_stale_repository_obligation(
    repo: DirtyRepo,
    obligation_by_id: Mapping[str, Any],
    instance_id: str,
) -> None:
    repo_id = _repository_decision_id(repo)
    obligation = obligation_by_id.get(repo_id)
    if obligation is None:
        raise BuiltinCommitFinalizerError(
            f"commit declaration is stale; repository {repo.name} is not in "
            "the accepted context",
            result=_failed_result(
                instance_id,
                "stale_commit_declaration",
                f"commit declaration is stale; repository {repo.name} is not "
                "in the accepted context",
            ),
        )
    expected = getattr(obligation, "digest", None)
    if not isinstance(expected, str) or not expected:
        return
    current = finalizer_declaration.repository_state_digest(
        repo_id,
        repo,
        list(repo.changed_files),
    )
    if current != expected:
        raise BuiltinCommitFinalizerError(
            f"commit declaration is stale; repository {repo.name} changed after submit",
            result=_failed_result(
                instance_id,
                "stale_commit_declaration",
                f"commit declaration is stale; repository {repo.name} changed "
                "after submit",
            ),
        )


def _reject_discarded_dirty_work(
    before: DirtyState,
    after: DirtyState,
    *,
    artifacts: Path | None,
    project_dir: str,
    instance_id: str,
    attempts: Sequence[FinalizerAttemptWire],
    evidence: Sequence[FinalizerOutcomeEvidenceWire],
    invoke_result: InvokeResult,
    ledger_before: Sequence[Mapping[str, Any]],
) -> None:
    discarded = discarded_dirty_work_evidence(
        before,
        after,
        artifacts_dir=str(artifacts) if artifacts is not None else None,
    )
    proven = {
        normalize_path(str(marker.get("cwd", "")))
        for marker in _new_commit_markers(
            ledger_before, _load_commit_results(artifacts)
        )
        if marker.get("cwd")
    }
    remaining = tuple(
        item for item in discarded if normalize_path(item.repo_path) not in proven
    )
    if not remaining:
        return
    message_text = discarded_dirty_work_message(remaining)
    result = _failed_result(
        instance_id,
        "dirty_work_discarded",
        message_text,
        attempts=attempts,
        evidence=evidence,
    )
    raise BuiltinCommitFinalizerError(
        message_text,
        result=result,
        invoke_result=invoke_result,
    )


__all__ = [
    "BuiltinCommitExecution",
    "BuiltinCommitFinalizerError",
    "StitchCommandResult",
    "execute_commit_finalizer",
    "run_stitch_create",
    "run_stitch_resume",
]
