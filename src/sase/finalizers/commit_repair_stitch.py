"""Stitch subprocess, attempt, and artifact helpers for builtin@commit."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

from sase.finalizers.artifacts import (
    instance_artifact_dir,
    write_json_atomic,
    write_text_artifact,
)
from sase.finalizers.bounded_subprocess import (
    HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS,
    run_bounded_subprocess,
)
from sase.finalizers.commit_repair_common import _artifact_label, _bound_stream
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
    failed_result,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.llm_provider.commit_finalizer_git import (
    dirty_path_fingerprints,
    normalize_path,
)
from sase.llm_provider.commit_finalizer_git_status import git_head_commit_id
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.workflows.commit.command_hooks import (
    hook_output_tail_from_metadata,
    load_latest_commit_hook_metadata,
)

_SubprocessRunner = Callable[..., Any]
_DirtyPathFingerprints = Callable[[str], Mapping[str, Any]]
_GitHeadCommitId = Callable[[str], str]


def run_stitch_create(
    repo: DirtyRepo,
    message: str,
    excludes: Sequence[str],
    context: FinalizerExecutionContext,
    *,
    bead_action: str | None = None,
    subprocess_runner: _SubprocessRunner = run_bounded_subprocess,
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
    if bead_action is not None:
        argv.extend(["-B", bead_action])
    for path in excludes:
        argv.extend(["-x", path])
    result = _run_stitch_argv(
        argv,
        repo,
        context,
        subprocess_runner=subprocess_runner,
    )
    return replace(result, argv=tuple(argv), message_file=str(message_file))


def run_stitch_resume(
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
    *,
    bead_action: str | None = None,
    subprocess_runner: _SubprocessRunner = run_bounded_subprocess,
) -> StitchCommandResult:
    """Resume the checkpointed stitch for one repository."""

    argv = [sys.executable, "-m", "sase", "stitch", "create", "--resume"]
    if bead_action is not None:
        argv.extend(["-B", bead_action])
    result = _run_stitch_argv(
        argv,
        repo,
        context,
        subprocess_runner=subprocess_runner,
    )
    return replace(result, argv=tuple(argv))


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
    safe_label = _artifact_label(label)
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
        write_json_atomic(
            artifact_dir / f"{prefix}.outcome.json",
            {
                "returncode": result.returncode,
                "duration_seconds": result.duration_seconds,
                "timed_out": result.timed_out,
                "stdout_truncated": result.stdout_truncated,
                "stderr_truncated": result.stderr_truncated,
                "argv": list(result.argv),
                "message_file": result.message_file,
            },
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


def stitch_bounds_failure_message(
    repo: DirtyRepo,
    result: StitchCommandResult,
    code: str,
    *,
    artifacts: Path | None,
    resume: bool = False,
) -> str:
    command = "sase stitch create --resume" if resume else "sase stitch create"
    parts = [f"{command} {code} for {repo.name}"]
    if result.duration_seconds > 0:
        parts.append(
            "elapsed "
            f"{result.duration_seconds:.1f}s of "
            f"{HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS:.0f}s allowed"
        )
    elif result.timed_out:
        parts.append(f"allowed time was {HARD_MAX_SUBPROCESS_TIMEOUT_SECONDS:.0f}s")

    hook = load_latest_commit_hook_metadata(artifacts, repo.path)
    if hook is not None:
        parts.append(_hook_context_summary(hook))
        hook_tail = hook_output_tail_from_metadata(hook)
        if hook_tail:
            parts.append("hook output tail: " + _bound_stream(hook_tail))
    else:
        parts.append("last stage unknown; no matching commit-hook record was found")
        tail = _commit_hook_tail_from_result(result)
        if tail:
            parts.append("stitch output tail: " + _bound_stream(tail))
    return "; ".join(parts)


def _hook_context_summary(hook: Mapping[str, Any]) -> str:
    phase = str(hook.get("phase") or "unknown")
    command = str(hook.get("command") or "")
    status = str(hook.get("status") or "unknown")
    summary = f"last hook {phase}"
    if command:
        summary += f" `{command}`"
    summary += f" status={status}"
    duration = hook.get("duration_seconds")
    if isinstance(duration, (int, float)) and duration >= 0:
        summary += f" duration={float(duration):.1f}s"
    metadata_path = hook.get("metadata_path")
    if isinstance(metadata_path, str) and metadata_path:
        summary += f" evidence={metadata_path}"
    paths = hook.get("paths")
    if isinstance(paths, Mapping):
        log_paths = [
            str(value)
            for key, value in paths.items()
            if key in {"stdout", "stderr", "stdout_tail", "stderr_tail"}
            and isinstance(value, str)
            and value
        ]
        if log_paths:
            summary += " logs=" + ", ".join(log_paths)
    return summary


def _commit_hook_tail_from_result(result: StitchCommandResult) -> str:
    lines: list[str] = []
    if result.stdout:
        lines.append("[stdout]")
        lines.extend(result.stdout.rstrip().splitlines()[-25:])
    if result.stderr:
        lines.append("[stderr]")
        lines.extend(result.stderr.rstrip().splitlines()[-25:])
    return "\n".join(lines)


def stitch_attempt_input_fields(
    repo: DirtyRepo,
    message: str,
    excludes: Sequence[str],
    *,
    bead_action: str | None = None,
    assigned_bead_id: str | None = None,
    dirty_path_fingerprints_fn: _DirtyPathFingerprints = dirty_path_fingerprints,
    git_head_commit_id_fn: _GitHeadCommitId = git_head_commit_id,
) -> dict[str, Any]:
    """Capture everything that determines whether a stitch attempt can succeed.

    Two attempts whose fields are identical are guaranteed to fail the same
    way, so :func:`stitch_attempt_fingerprint` of these fields is what the
    host uses to refuse to waste a second mutating attempt on a foregone
    conclusion.
    """
    return {
        "repo_path": normalize_path(repo.path),
        "head": git_head_commit_id_fn(repo.path),
        "dirty_fingerprints": sorted(dirty_path_fingerprints_fn(repo.path).items()),
        "excludes": sorted(excludes),
        "message_digest": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        "bead_action": bead_action,
        "assigned_bead_id": _clean_assigned_bead_id(assigned_bead_id),
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
    outcome: Mapping[str, Any] | None = None


def load_latest_stitch_attempt(
    context: FinalizerExecutionContext,
    instance_id: str,
    label: str,
) -> _PriorStitchAttempt | None:
    """Return the most recently recorded stitch attempt for *label*, if any."""

    artifact_dir = instance_artifact_dir(context.artifacts_dir, instance_id)
    if artifact_dir is None:
        return None
    safe_label = _artifact_label(label)
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
        outcome=_read_optional_json_artifact(artifact_dir / f"{prefix}.outcome.json"),
    )


def _read_optional_artifact(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _read_optional_json_artifact(path: Path) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _run_stitch_argv(
    argv: list[str],
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
    *,
    subprocess_runner: _SubprocessRunner,
) -> StitchCommandResult:
    env = dict(os.environ)
    if context.artifacts_dir:
        env["SASE_ARTIFACTS_DIR"] = context.artifacts_dir
    _bind_assigned_bead_env(env, context)
    completed = subprocess_runner(
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


def _bind_assigned_bead_env(
    env: dict[str, str],
    context: FinalizerExecutionContext,
) -> None:
    bead_id = _clean_assigned_bead_id(getattr(context, "assigned_bead_id", None))
    if bead_id is None:
        env.pop("SASE_BEAD_ID", None)
        return
    env["SASE_BEAD_ID"] = bead_id


def _clean_assigned_bead_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _write_message_file(repo_path: str, message: str) -> Path:
    root = Path(repo_path) / ".sase" / "finalizers"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"commit-message-{os.getpid()}-{time.time_ns()}.txt"
    path.write_text(message.rstrip() + "\n", encoding="utf-8")
    return path


__all__ = [
    "load_latest_stitch_attempt",
    "record_stitch_artifacts",
    "run_stitch_create",
    "run_stitch_resume",
    "stitch_attempt_fingerprint",
    "stitch_attempt_input_fields",
    "stitch_bounds_failure_message",
    "stitch_failure_message",
]
