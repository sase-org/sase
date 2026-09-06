"""Stitch dispatch and conflict-repair helpers for builtin@commit."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.artifacts import instance_artifact_dir, write_text_artifact
from sase.finalizers.bounded_subprocess import (
    HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS,
    run_bounded_subprocess,
)
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    ResumeRunner,
    StitchCommandResult,
    failed_result,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.llm_provider.commit_finalizer_artifacts import artifact_root
from sase.llm_provider.commit_finalizer_git import (
    dirty_path_fingerprints,
    git_changed_files,
    normalize_path,
)
from sase.llm_provider.commit_finalizer_git_status import git_head_commit_id
from sase.llm_provider.commit_finalizer_prompting import append_response, merge_usage
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions, ModelTier
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

_CONFLICT_PROMPT_FILENAME = "conflict_repair_prompt.md"
_CONFLICT_RESPONSE_FILENAME = "conflict_repair_response.md"
_ARTIFACT_LABEL_RE = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_STREAM_CHARS = 4000


@dataclass(frozen=True)
class _ConflictRepairResult:
    """Outcome from one conflict repair and resume attempt."""

    invoke_result: InvokeResult
    resolved_without_commit: bool = False


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
    result = _run_stitch_argv(argv, repo, context)
    return replace(result, argv=tuple(argv), message_file=str(message_file))


def run_stitch_resume(
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
) -> StitchCommandResult:
    """Resume the checkpointed stitch for one repository."""

    argv = [sys.executable, "-m", "sase", "stitch", "create", "--resume"]
    result = _run_stitch_argv(argv, repo, context)
    return replace(result, argv=tuple(argv))


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
    attempt_id: int,
) -> _ConflictRepairResult:
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
    repaired_markers = [
        marker
        for marker in new_commit_markers(
            before_markers,
            load_commit_results(artifact_root(context.artifacts_dir)),
        )
        if marker_matches_repo(marker, repo)
    ]
    if repaired_markers:
        evidence.append(
            FinalizerOutcomeEvidenceWire(kind="conflict_repair", value="success")
        )
        evidence.extend(marker_evidence(repaired_markers[-1]))
        return _ConflictRepairResult(invoke_result=current_result)
    resumed = resume_runner(repo, context)
    record_stitch_artifacts(
        context, "commit", attempt_id, resumed, label="conflict-repair"
    )
    if resumed.timed_out or resumed.stdout_truncated or resumed.stderr_truncated:
        code = "stitch_timeout" if resumed.timed_out else "stitch_output_cap"
        message_text = f"sase stitch create --resume {code} for {repo.name}"
        raise BuiltinCommitFinalizerError(
            message_text,
            result=failed_result(
                "commit",
                code,
                message_text,
                attempts=attempts,
                evidence=evidence,
            ),
            invoke_result=current_result,
        )
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
    resumed_markers = [
        marker
        for marker in new_commit_markers(
            before_markers,
            load_commit_results(artifact_root(context.artifacts_dir)),
        )
        if marker_matches_repo(marker, repo)
    ]
    if resumed_markers:
        evidence.append(
            FinalizerOutcomeEvidenceWire(kind="conflict_repair", value="success")
        )
        return _ConflictRepairResult(invoke_result=current_result)
    if _repo_is_settled_after_repair(repo, provider=provider):
        evidence.append(
            FinalizerOutcomeEvidenceWire(
                kind="conflict_repair", value="resolved_without_commit"
            )
        )
        evidence.append(
            FinalizerOutcomeEvidenceWire(
                kind="head_sha", value=git_head_commit_id(repo.path)
            )
        )
        return _ConflictRepairResult(
            invoke_result=current_result,
            resolved_without_commit=True,
        )
    message_text = (
        f"sase stitch create --resume completed for {repo.name}, but no "
        "commit_results.json entry was recorded and the repository is not clean"
    )
    raise BuiltinCommitFinalizerError(
        message_text,
        result=failed_result(
            "commit",
            "missing_commit_result",
            message_text,
            attempts=attempts,
            evidence=evidence,
        ),
        invoke_result=current_result,
    )


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


def _repo_is_settled_after_repair(
    repo: DirtyRepo,
    *,
    provider: Any,
) -> bool:
    try:
        if provider.is_sync_in_progress(repo.path):  # type: ignore[attr-defined]
            return False
    except NotImplementedError:
        pass
    except Exception:
        return False
    try:
        if provider.get_conflicted_files(repo.path):  # type: ignore[attr-defined]
            return False
    except NotImplementedError:
        pass
    except Exception:
        return False
    return not git_changed_files(repo.path)


def record_stitch_artifacts(
    context: FinalizerExecutionContext,
    instance_id: str,
    attempt: int,
    result: StitchCommandResult,
    *,
    label: str = "stitch",
    inputs: Mapping[str, Any] | None = None,
) -> None:
    artifact_dir = instance_artifact_dir(context.artifacts_dir, instance_id)
    if artifact_dir is None:
        return
    safe_label = _ARTIFACT_LABEL_RE.sub("_", label).strip("._") or "stitch"
    prefix = f"attempt-{attempt}.{safe_label}"
    try:
        write_text_artifact(
            artifact_dir / f"{prefix}.stdout",
            result.stdout,
            exclusive=True,
        )
        write_text_artifact(
            artifact_dir / f"{prefix}.stderr",
            result.stderr,
            exclusive=True,
        )
        if inputs is not None:
            payload = {
                **inputs,
                "argv": list(result.argv),
                "message_file": result.message_file,
            }
            write_text_artifact(
                artifact_dir / f"{prefix}.inputs.json",
                json.dumps(payload, indent=2, sort_keys=True),
                exclusive=True,
            )
    except FileExistsError as exc:
        raise BuiltinCommitFinalizerError(
            str(exc),
            result=failed_result(
                instance_id,
                "immutable_attempt_artifact",
                str(exc),
            ),
        ) from exc


def stitch_failure_message(repo: DirtyRepo, result: StitchCommandResult) -> str:
    """Render the VCS provider's real reason, whichever stream carried it.

    ``sase stitch create`` sometimes writes the actual failure reason to
    stdout while stderr carries only boilerplate (or the reverse); returning
    only one stream silently discarded the reason a past incident needed.
    """
    parts = []
    stdout = result.stdout.strip()
    stderr = result.stderr.strip()
    if stdout:
        parts.append(f"stdout: {_bound_stream(stdout)}")
    if stderr:
        parts.append(f"stderr: {_bound_stream(stderr)}")
    if not parts:
        return (
            f"sase stitch create failed for {repo.name} with exit {result.returncode}"
        )
    return f"sase stitch create failed for {repo.name}: " + " | ".join(parts)


def _bound_stream(text: str) -> str:
    if len(text) <= _MAX_STREAM_CHARS:
        return text
    omitted = len(text) - _MAX_STREAM_CHARS
    return f"{text[:_MAX_STREAM_CHARS]}... [{omitted} more chars truncated]"


def stitch_attempt_input_fields(
    repo: DirtyRepo,
    message: str,
    excludes: Sequence[str],
) -> dict[str, Any]:
    """Capture everything that determines whether a stitch attempt can succeed.

    Two attempts whose fields are identical are guaranteed to fail the same
    way, so :func:`stitch_attempt_fingerprint` of these fields is what the
    host uses to refuse to waste a second mutating attempt on a foregone
    conclusion.
    """
    return {
        "repo_path": normalize_path(repo.path),
        "head": git_head_commit_id(repo.path),
        "dirty_fingerprints": sorted(dirty_path_fingerprints(repo.path).items()),
        "excludes": sorted(excludes),
        "message_digest": hashlib.sha256(message.encode("utf-8")).hexdigest(),
    }


def stitch_attempt_fingerprint(fields: Mapping[str, Any]) -> str:
    """Hash *fields* (from :func:`stitch_attempt_input_fields`) into one token."""

    canonical = json.dumps(fields, sort_keys=True).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class _PriorStitchAttempt:
    """One earlier stitch attempt's recorded inputs and captured output."""

    attempt: int
    inputs: Mapping[str, Any]
    stdout: str
    stderr: str


def load_latest_stitch_attempt(
    context: FinalizerExecutionContext,
    instance_id: str,
    label: str,
) -> _PriorStitchAttempt | None:
    """Return the most recently recorded stitch attempt for *label*, if any."""

    artifact_dir = instance_artifact_dir(context.artifacts_dir, instance_id)
    if artifact_dir is None:
        return None
    safe_label = _ARTIFACT_LABEL_RE.sub("_", label).strip("._") or "stitch"
    pattern = re.compile(rf"^attempt-(\d+)\.{re.escape(safe_label)}\.inputs\.json$")
    best_attempt = -1
    best_path: Path | None = None
    try:
        entries = list(artifact_dir.iterdir())
    except OSError:
        return None
    for entry in entries:
        match = pattern.match(entry.name)
        if not match:
            continue
        attempt_num = int(match.group(1))
        if attempt_num > best_attempt:
            best_attempt = attempt_num
            best_path = entry
    if best_path is None:
        return None
    try:
        inputs = json.loads(best_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(inputs, dict):
        return None
    prefix = f"attempt-{best_attempt}.{safe_label}"
    return _PriorStitchAttempt(
        attempt=best_attempt,
        inputs=inputs,
        stdout=_read_optional_artifact(artifact_dir / f"{prefix}.stdout"),
        stderr=_read_optional_artifact(artifact_dir / f"{prefix}.stderr"),
    )


def _read_optional_artifact(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _run_stitch_argv(
    argv: list[str],
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
) -> StitchCommandResult:
    env = dict(os.environ)
    if context.artifacts_dir:
        env["SASE_ARTIFACTS_DIR"] = context.artifacts_dir
    completed = run_bounded_subprocess(
        argv,
        cwd=repo.path,
        env=env,
        input_bytes=None,
        timeout=HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS,
    )
    return StitchCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout.decode("utf-8", errors="replace"),
        stderr=completed.stderr.decode("utf-8", errors="replace"),
        duration_seconds=completed.duration_seconds,
        timed_out=completed.timed_out,
        stdout_truncated=completed.stdout_truncated,
        stderr_truncated=completed.stderr_truncated,
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
        f"committing repository {repo.name}. This is an automated host instruction, "
        "not a message from the user.\n\n"
        "This is the single conflict-repair turn. Inspect the unmerged files, "
        "resolve every conflict marker, and stage the resolved files. Before "
        "continuing the paused VCS operation, run the project's verification "
        "gate and fold every resulting fix into the staged resolution. Then "
        "continue the paused VCS operation and run `sase stitch create --resume`.\n\n"
        "A clean conflict-marker resolution does not prove the merge is "
        "semantically correct. When both sides add an entry to the same list, "
        "dict, tuple, or enum, git can merge both entries and leave a duplicate "
        "that only lint or tests will catch.\n\n"
        f"Scope: these restrictions apply only to the paused operation in {repo.name}. "
        "Do not start a new stitch, skip, abort, or stash it, and do not create a "
        f"fresh commit in {repo.name} to work around the conflict; repair and resume "
        "the paused one instead.\n\n"
        "This does not change what you owe elsewhere. Your standing obligation to "
        "declare and commit every repository you changed this turn is unaffected: "
        "after the resume succeeds, finish the turn through `/sase_final` as usual. "
        "If this repository is still dirty after the resume, the declaration's "
        "commit decision for it will be executed as a single follow-up commit, "
        "so the message you declare there is the message that lands. Include any "
        "other repository that is still dirty."
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
    "load_latest_stitch_attempt",
    "marker_evidence",
    "marker_matches_repo",
    "new_commit_markers",
    "record_stitch_artifacts",
    "resolve_commit_conflict",
    "run_stitch_create",
    "run_stitch_resume",
    "stitch_attempt_fingerprint",
    "stitch_attempt_input_fields",
    "stitch_failure_message",
]
