"""Built-in ``builtin@commit`` finalizer execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDiagnosticWire,
    FinalizerInstanceResultWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.core.finalizer_facade import validate_finalizer_submission
from sase.finalizers.artifacts import instance_artifact_dir, write_text_artifact
from sase.finalizers.config import ConfiguredFinalizerInstance
from sase.finalizers import declaration as finalizer_declaration
from sase.finalizers.executor import FinalizerExecutionContext
from sase.llm_provider import commit_finalizer as legacy_commit
from sase.llm_provider.commit_finalizer_artifacts import artifact_root, write_result
from sase.llm_provider.commit_finalizer_baseline import (
    BASELINE_FILENAME,
    FINALIZER_BASELINE_FILENAME,
)
from sase.llm_provider.commit_finalizer_config import resolve_finalizer_project_dir
from sase.llm_provider.commit_finalizer_git import (
    git_changed_files,
    normalize_path,
    split_pre_existing_changed_files,
)
from sase.llm_provider.commit_finalizer_prompting import append_response, merge_usage
from sase.llm_provider.commit_finalizer_state import collect_dirty_state
from sase.llm_provider.commit_finalizer_types import (
    CommitFinalizerResult,
    DirtyRepo,
    DirtyState,
)
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions, ModelTier
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

_COMMIT_PROVIDER_REF = "builtin@commit"
_CONFLICT_PROMPT_FILENAME = "conflict_repair_prompt.md"
_CONFLICT_RESPONSE_FILENAME = "conflict_repair_response.md"


class BuiltinCommitFinalizerError(RuntimeError):
    """Raised when the built-in commit finalizer cannot prove completion."""

    def __init__(
        self,
        message: str,
        *,
        result: FinalizerInstanceResultWire,
        invoke_result: InvokeResult | None = None,
    ) -> None:
        super().__init__(message)
        self.result = result
        self.invoke_result = invoke_result


@dataclass(frozen=True)
class BuiltinCommitExecution:
    """Commit finalizer execution output."""

    invoke_result: InvokeResult
    result: FinalizerInstanceResultWire


@dataclass(frozen=True)
class StitchCommandResult:
    """Result from one ``sase stitch create`` subprocess."""

    returncode: int
    stdout: str = ""
    stderr: str = ""
    duration_seconds: float = 0.0


StitchRunner = Callable[
    [DirtyRepo, str, Sequence[str], FinalizerExecutionContext],
    StitchCommandResult,
]


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
    state = _prepare_dirty_state(project_dir, artifacts)
    if state.dirty_state.is_clean:
        _write_clean_compat_result(
            artifacts,
            project_dir=project_dir,
            state=state,
            passes=0,
        )
        return BuiltinCommitExecution(
            invoke_result=invoke_result,
            result=_success_result(
                instance.instance_id,
                attempts=(),
                evidence=(),
            ),
        )

    try:
        envelope = _load_current_final_submission(context.artifacts_dir)
    except Exception as exc:
        result = _failed_result(
            instance.instance_id,
            "missing_commit_declaration",
            f"commit finalizer requires a current accepted declaration: {exc}",
        )
        _write_failed_compat_result(
            artifacts,
            project_dir=project_dir,
            dirty_state=state.dirty_state,
            reason="missing_declaration",
            error=result.diagnostics[0].message,
            passes=0,
        )
        raise BuiltinCommitFinalizerError(
            result.diagnostics[0].message,
            result=result,
            invoke_result=invoke_result,
        ) from exc

    decisions = _commit_decisions_for_instance(envelope, instance.instance_id)
    current_result = invoke_result
    attempts: list[FinalizerAttemptWire] = []
    evidence: list[FinalizerOutcomeEvidenceWire] = []
    runner = stitch_runner or run_stitch_create

    for repo in _dirty_repos_in_context_order(state.dirty_state, decisions):
        decision = decisions[_repository_decision_id(repo)]
        action = str(decision.get("action"))
        if action == "refuse":
            reason = str(decision.get("reason", "")).strip()
            result = _refused_result(instance.instance_id, reason)
            _write_failed_compat_result(
                artifacts,
                project_dir=project_dir,
                dirty_state=state.dirty_state,
                reason="refused",
                error=reason,
                passes=len(attempts),
            )
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
            current_result = _run_conflict_repair_turn(
                provider=provider,
                invoke_result=current_result,
                model_tier=model_tier,
                suppress_output=suppress_output,
                model_override=model_override,
                artifacts_dir=context.artifacts_dir,
                options=options,
                repo=repo,
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
            _write_failed_compat_result(
                artifacts,
                project_dir=project_dir,
                dirty_state=state.dirty_state,
                reason="stitch_failed",
                error=message_text,
                passes=len(attempts),
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
            _write_failed_compat_result(
                artifacts,
                project_dir=project_dir,
                dirty_state=state.dirty_state,
                reason="missing_commit_result",
                error=message_text,
                passes=len(attempts),
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
            _write_failed_compat_result(
                artifacts,
                project_dir=project_dir,
                dirty_state=_collect_dirty_state(project_dir, artifacts),
                reason="dirty_after_stitch",
                error=message_text,
                passes=len(attempts),
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=result,
                invoke_result=current_result,
            )

        state = _prepare_dirty_state(project_dir, artifacts)

    if not state.dirty_state.is_clean:
        message_text = legacy_commit.failure_message(
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
        _write_failed_compat_result(
            artifacts,
            project_dir=project_dir,
            dirty_state=state.dirty_state,
            reason="dirty_after_commit_decisions",
            error=message_text,
            passes=len(attempts),
        )
        raise BuiltinCommitFinalizerError(
            message_text,
            result=result,
            invoke_result=current_result,
        )

    legacy_commit._fail_on_unpublished_bead_state(
        state.bead_publication_error,
        artifact_root=artifacts,
        project_dir=project_dir,
        passes=len(attempts),
    )
    _write_clean_compat_result(
        artifacts,
        project_dir=project_dir,
        state=state,
        passes=len(attempts),
    )
    return BuiltinCommitExecution(
        invoke_result=current_result,
        result=_success_result(
            instance.instance_id,
            attempts=attempts,
            evidence=evidence,
        ),
    )


def run_stitch_create(
    repo: DirtyRepo,
    message: str,
    excludes: Sequence[str],
    context: FinalizerExecutionContext,
) -> StitchCommandResult:
    """Run ``sase stitch create`` for one repository."""

    message_file = _write_message_file(repo.path, message)
    argv = [
        sys.executable,
        "-m",
        "sase",
        "stitch",
        "create",
        "-M",
        str(message_file),
    ]
    for path in excludes:
        argv.extend(["-x", path])
    env = dict(os.environ)
    if context.artifacts_dir:
        env["SASE_ARTIFACTS_DIR"] = context.artifacts_dir
    started = time.monotonic()
    completed = subprocess.run(
        argv,
        cwd=repo.path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return StitchCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        duration_seconds=time.monotonic() - started,
    )


@dataclass(frozen=True)
class _PreparedDirtyState:
    dirty_state: DirtyState
    done_plan_auto_committed: bool = False
    sdd_prompt_qa_auto_committed: bool = False
    sdd_store_auto_committed: bool = False
    bead_publication_error: str | None = None


def _prepare_dirty_state(
    project_dir: str,
    artifacts: Path | None,
) -> _PreparedDirtyState:
    bead_sync = legacy_commit._auto_commit_separate_sdd_store_if_possible(
        project_dir,
        artifacts,
    )
    dirty_state = _collect_dirty_state(project_dir, artifacts)
    dirty_state, qa_auto_committed = (
        legacy_commit._auto_commit_external_sdd_prompt_qa_if_possible(
            project_dir,
            dirty_state,
            artifacts,
        )
    )
    dirty_state, done_auto_committed = (
        legacy_commit._auto_commit_done_plan_status_if_possible(
            project_dir,
            dirty_state,
            artifacts,
        )
    )
    return _PreparedDirtyState(
        dirty_state=dirty_state,
        done_plan_auto_committed=done_auto_committed,
        sdd_prompt_qa_auto_committed=qa_auto_committed,
        sdd_store_auto_committed=bead_sync.committed,
        bead_publication_error=bead_sync.publication_error,
    )


def _collect_dirty_state(project_dir: str, artifacts: Path | None) -> DirtyState:
    return collect_dirty_state(project_dir, artifact_root=artifacts)


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
    root = finalizer_declaration._require_artifacts_dir(
        artifacts_dir,
        "finalizer declaration load",
    )
    plan = finalizer_declaration._load_plan(root)
    context = finalizer_declaration._load_latest_context(root)
    submission = finalizer_declaration._load_latest_submission(root)
    envelope = finalizer_declaration._normalize_submission_envelope(
        submission["submission"]
    )
    validate_finalizer_submission(plan, context, envelope)
    finalizer_declaration._validate_provider_payloads(plan, context, envelope)
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
    from sase.finalizers.declaration import _repository_obligation_id

    return _repository_obligation_id(repo)


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


def _write_message_file(repo_path: str, message: str) -> Path:
    root = Path(repo_path) / ".sase" / "finalizers"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"commit-message-{os.getpid()}-{time.time_ns()}.txt"
    path.write_text(message.rstrip() + "\n", encoding="utf-8")
    return path


def _load_commit_results(artifacts: Path | None) -> list[dict[str, Any]]:
    if artifacts is None:
        return []
    try:
        payload = json.loads(
            (artifacts / "commit_results.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _new_commit_markers(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    before_keys = {_marker_key(item) for item in before}
    return [dict(item) for item in after if _marker_key(item) not in before_keys]


def _marker_key(marker: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        marker.get("cwd"),
        marker.get("result"),
        marker.get("commit_sha"),
        marker.get("commit_tree"),
        marker.get("entry_id"),
    )


def _marker_matches_repo(marker: Mapping[str, Any], repo: DirtyRepo) -> bool:
    cwd = marker.get("cwd")
    return isinstance(cwd, str) and normalize_path(cwd) == normalize_path(repo.path)


def _marker_evidence(
    marker: Mapping[str, Any],
) -> list[FinalizerOutcomeEvidenceWire]:
    evidence: list[FinalizerOutcomeEvidenceWire] = []
    for key in ("cwd", "result", "commit_sha", "commit_tree", "entry_id"):
        value = marker.get(key)
        if isinstance(value, str) and value:
            evidence.append(FinalizerOutcomeEvidenceWire(kind=key, value=value))
    if not any(item.kind == "commit_sha" for item in evidence):
        evidence.append(
            FinalizerOutcomeEvidenceWire(
                kind="warning",
                value="commit_results entry omitted commit_sha",
            )
        )
    if not any(item.kind == "commit_tree" for item in evidence):
        evidence.append(
            FinalizerOutcomeEvidenceWire(
                kind="warning",
                value="commit_results entry omitted commit_tree",
            )
        )
    return evidence


def _unexpected_remaining_paths(repo_path: str, protected: Sequence[str]) -> list[str]:
    protected_set = set(protected)
    return [path for path in git_changed_files(repo_path) if path not in protected_set]


def _run_conflict_repair_turn(
    *,
    provider: Any,
    invoke_result: InvokeResult,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    artifacts_dir: str | None,
    options: LLMInvocationOptions | None,
    repo: DirtyRepo,
) -> InvokeResult:
    prompt = _conflict_repair_prompt(repo)
    artifact_dir = instance_artifact_dir(artifacts_dir, "commit")
    if artifact_dir is not None:
        write_text_artifact(artifact_dir / _CONFLICT_PROMPT_FILENAME, prompt)
    follow_up = provider.invoke(
        prompt,
        model_tier=model_tier,
        suppress_output=suppress_output,
        model_override=model_override,
        options=options,
    )
    if artifact_dir is not None:
        write_text_artifact(
            artifact_dir / _CONFLICT_RESPONSE_FILENAME,
            follow_up.content,
        )
    return InvokeResult(
        content=append_response(invoke_result.content, follow_up.content),
        usage=merge_usage(invoke_result.usage, follow_up.usage),
    )


def _conflict_repair_prompt(repo: DirtyRepo) -> str:
    return (
        "The built-in SASE commit finalizer hit a merge/rebase conflict while "
        f"committing repository {repo.name}.\n\n"
        "This is the single conflict-repair turn. Inspect the unmerged files, "
        "resolve every conflict marker, stage the resolved files, continue the "
        "paused VCS operation, then run `sase stitch create --resume`. Do not "
        "start a new stitch, skip, abort, stash, or create a second commit. "
        "Return briefly after the resume command succeeds."
    )


def _record_stitch_artifacts(
    context: FinalizerExecutionContext,
    instance_id: str,
    attempt: int,
    result: StitchCommandResult,
) -> None:
    artifact_dir = instance_artifact_dir(context.artifacts_dir, instance_id)
    if artifact_dir is None:
        return
    write_text_artifact(artifact_dir / f"attempt-{attempt}.stdout", result.stdout)
    write_text_artifact(artifact_dir / f"attempt-{attempt}.stderr", result.stderr)


def _write_clean_compat_result(
    artifacts: Path | None,
    *,
    project_dir: str,
    state: _PreparedDirtyState,
    passes: int,
) -> None:
    finalized = (
        passes > 0
        or state.done_plan_auto_committed
        or state.sdd_prompt_qa_auto_committed
        or state.sdd_store_auto_committed
    )
    write_result(
        artifacts,
        CommitFinalizerResult(
            status="finalized" if finalized else "clean",
            reason=legacy_commit._clean_result_reason(
                done_plan_auto_committed=state.done_plan_auto_committed,
                sdd_prompt_qa_auto_committed=state.sdd_prompt_qa_auto_committed,
                sdd_store_auto_committed=state.sdd_store_auto_committed,
            )
            if finalized and passes == 0
            else ("clean_after_pass" if finalized else "clean"),
            project_dir=project_dir,
            passes=passes,
            changed_files=[],
        ),
    )


def _write_failed_compat_result(
    artifacts: Path | None,
    *,
    project_dir: str,
    dirty_state: DirtyState,
    reason: str,
    error: str,
    passes: int,
) -> None:
    write_result(
        artifacts,
        CommitFinalizerResult(
            status="failed",
            reason=reason,
            project_dir=project_dir,
            passes=passes,
            changed_files=legacy_commit._result_changed_files(dirty_state),
            error=error,
        ),
    )


def _success_result(
    instance_id: str,
    *,
    attempts: Sequence[FinalizerAttemptWire],
    evidence: Sequence[FinalizerOutcomeEvidenceWire],
) -> FinalizerInstanceResultWire:
    return FinalizerInstanceResultWire(
        instance_id=instance_id,
        status="success",
        attempts=list(attempts),
        evidence=list(evidence),
    )


def _refused_result(instance_id: str, reason: str) -> FinalizerInstanceResultWire:
    return FinalizerInstanceResultWire(
        instance_id=instance_id,
        status="refused",
        refusal_reason=reason,
        attempts=[
            FinalizerAttemptWire(
                attempt=1,
                status="refused",
                diagnostic_code="commit_refused",
            )
        ],
        diagnostics=[
            FinalizerDiagnosticWire(
                code="commit_refused",
                severity="error",
                message=reason,
                instance_id=instance_id,
            )
        ],
    )


def _failed_result(
    instance_id: str,
    code: str,
    message: str,
    *,
    attempts: Sequence[FinalizerAttemptWire] = (),
    evidence: Sequence[FinalizerOutcomeEvidenceWire] = (),
) -> FinalizerInstanceResultWire:
    return FinalizerInstanceResultWire(
        instance_id=instance_id,
        status="failed",
        attempts=list(attempts)
        or [
            FinalizerAttemptWire(
                attempt=1,
                status="failed",
                diagnostic_code=code,
            )
        ],
        evidence=list(evidence),
        diagnostics=[
            FinalizerDiagnosticWire(
                code=code,
                severity="error",
                message=message,
                instance_id=instance_id,
            )
        ],
    )


def _stitch_failure_message(repo: DirtyRepo, result: StitchCommandResult) -> str:
    detail = (result.stderr or result.stdout).strip()
    if detail:
        return f"sase stitch create failed for {repo.name}: {detail}"
    return f"sase stitch create failed for {repo.name} with exit {result.returncode}"


__all__ = [
    "BuiltinCommitExecution",
    "BuiltinCommitFinalizerError",
    "StitchCommandResult",
    "execute_commit_finalizer",
    "run_stitch_create",
]
