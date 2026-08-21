"""Stitch dispatch and conflict-repair helpers for builtin@commit."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.artifacts import instance_artifact_dir, write_text_artifact
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    ResumeRunner,
    StitchCommandResult,
    failed_result,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.llm_provider.commit_finalizer_artifacts import artifact_root
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_prompting import append_response, merge_usage
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions, ModelTier
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

_CONFLICT_PROMPT_FILENAME = "conflict_repair_prompt.md"
_CONFLICT_RESPONSE_FILENAME = "conflict_repair_response.md"


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
    return _run_stitch_argv(argv, repo, context)


def run_stitch_resume(
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
) -> StitchCommandResult:
    """Resume the checkpointed stitch for one repository."""

    argv = [sys.executable, "-m", "sase", "stitch", "create", "--resume"]
    return _run_stitch_argv(argv, repo, context)


def resolve_commit_conflict(
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
    *,
    provider: Any,
    invoke_result: InvokeResult,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    options: LLMInvocationOptions | None,
    resume_runner: ResumeRunner,
    attempts: list[FinalizerAttemptWire],
    evidence: list[FinalizerOutcomeEvidenceWire],
    before_markers: Sequence[Mapping[str, Any]],
) -> InvokeResult:
    """Run the one-shot conflict-repair turn and resume the same stitch."""

    if _conflict_repair_spent(context.artifacts_dir):
        raise BuiltinCommitFinalizerError(
            f"commit finalizer hit a second unresolved conflict in {repo.name}",
            result=failed_result(
                "commit",
                "second_unresolved_conflict",
                f"commit finalizer hit a second unresolved conflict in {repo.name}",
                attempts=attempts,
                evidence=evidence,
            ),
            invoke_result=invoke_result,
        )
    current_result = _run_conflict_repair_turn(
        provider=provider,
        invoke_result=invoke_result,
        model_tier=model_tier,
        suppress_output=suppress_output,
        model_override=model_override,
        artifacts_dir=context.artifacts_dir,
        options=options,
        repo=repo,
    )
    if any(
        marker_matches_repo(marker, repo)
        for marker in new_commit_markers(
            before_markers,
            load_commit_results(artifact_root(context.artifacts_dir)),
        )
    ):
        return current_result
    resumed = resume_runner(repo, context)
    attempts.append(
        FinalizerAttemptWire(
            attempt=len(attempts) + 1,
            status="success" if resumed.returncode == 0 else "failed",
            diagnostic_code=None
            if resumed.returncode == 0
            else (
                "second_unresolved_conflict"
                if resumed.returncode == EXIT_CODE_CONFLICT
                else "stale_conflict_checkpoint"
            ),
        )
    )
    record_stitch_artifacts(context, "commit", len(attempts), resumed)
    if resumed.returncode == EXIT_CODE_CONFLICT:
        raise BuiltinCommitFinalizerError(
            f"commit finalizer hit a second unresolved conflict in {repo.name}",
            result=failed_result(
                "commit",
                "second_unresolved_conflict",
                f"commit finalizer hit a second unresolved conflict in {repo.name}",
                attempts=attempts,
                evidence=evidence,
            ),
            invoke_result=current_result,
        )
    if resumed.returncode != 0:
        message_text = f"sase stitch create --resume failed for {repo.name}: " + (
            (resumed.stderr or resumed.stdout).strip() or "stale checkpoint"
        )
        raise BuiltinCommitFinalizerError(
            message_text,
            result=failed_result(
                "commit",
                "stale_conflict_checkpoint",
                message_text,
                attempts=attempts,
                evidence=evidence,
            ),
            invoke_result=current_result,
        )
    return current_result


def load_commit_results(artifacts: Path | None) -> list[dict[str, Any]]:
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


def new_commit_markers(
    before: Sequence[Mapping[str, Any]],
    after: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    before_keys = {_marker_key(item) for item in before}
    return [dict(item) for item in after if _marker_key(item) not in before_keys]


def marker_matches_repo(marker: Mapping[str, Any], repo: DirtyRepo) -> bool:
    cwd = marker.get("cwd")
    return isinstance(cwd, str) and normalize_path(cwd) == normalize_path(repo.path)


def marker_evidence(
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


def record_stitch_artifacts(
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


def stitch_failure_message(repo: DirtyRepo, result: StitchCommandResult) -> str:
    detail = (result.stderr or result.stdout).strip()
    if detail:
        return f"sase stitch create failed for {repo.name}: {detail}"
    return f"sase stitch create failed for {repo.name} with exit {result.returncode}"


def _run_stitch_argv(
    argv: list[str],
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
) -> StitchCommandResult:
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


def _write_message_file(repo_path: str, message: str) -> Path:
    root = Path(repo_path) / ".sase" / "finalizers"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"commit-message-{os.getpid()}-{time.time_ns()}.txt"
    path.write_text(message.rstrip() + "\n", encoding="utf-8")
    return path


def _conflict_repair_spent(artifacts_dir: str | None) -> bool:
    artifact_dir = instance_artifact_dir(artifacts_dir, "commit")
    if artifact_dir is None:
        return False
    return (artifact_dir / _CONFLICT_PROMPT_FILENAME).is_file()


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
    prompt = (
        "The built-in SASE commit finalizer hit a merge/rebase conflict while "
        f"committing repository {repo.name}.\n\n"
        "This is the single conflict-repair turn. Inspect the unmerged files, "
        "resolve every conflict marker, stage the resolved files, continue the "
        "paused VCS operation, then run `sase stitch create --resume`. Do not "
        "start a new stitch, skip, abort, stash, or create a second commit. "
        "Return briefly after the resume command succeeds."
    )
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


def _marker_key(marker: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        marker.get("cwd"),
        marker.get("result"),
        marker.get("commit_sha"),
        marker.get("commit_tree"),
        marker.get("entry_id"),
    )


__all__ = [
    "load_commit_results",
    "marker_evidence",
    "marker_matches_repo",
    "new_commit_markers",
    "record_stitch_artifacts",
    "resolve_commit_conflict",
    "run_stitch_create",
    "run_stitch_resume",
    "stitch_failure_message",
]
