"""One-shot conflict repair support for builtin@commit."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import inspect
import time
from typing import Any, cast

from pathlib import Path

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.artifacts import instance_artifact_dir, write_text_artifact
from sase.finalizers.commit_repair_common import artifact_label
from sase.finalizers.commit_repair_markers import (
    load_commit_results,
    marker_evidence,
    marker_matches_repo,
    new_commit_markers,
)
from sase.finalizers.commit_repair_stitch import (
    record_stitch_artifacts,
    stitch_bounds_failure_message,
)
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    ResumeRunner,
    StitchCommandResult,
    failed_result,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.operation_records import OperationRecorder
from sase.finalizers.owned_turn import finalizer_owned_turn
from sase.llm_provider._instruction_boundary import invoke_with_instructions
from sase.llm_provider.commit_finalizer_artifacts import artifact_root
from sase.llm_provider.commit_finalizer_git import git_changed_files
from sase.llm_provider.commit_finalizer_git_status import (
    git_head_commit_id,
    git_unpushed_commit_records,
)
from sase.llm_provider.commit_finalizer_prompting import append_response, merge_usage
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult, LLMInvocationOptions, ModelTier
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

_CONFLICT_PROMPT_STEM = "conflict_repair_prompt"
_CONFLICT_RESPONSE_STEM = "conflict_repair_response"
_GitChangedFiles = Callable[[str], Sequence[str]]
_GitHeadCommitId = Callable[[str], str]
_GitUnpushedRecords = Callable[[str], tuple[tuple[str, str, str], ...]]

_CHECKPOINT_FILENAME = "commit_state.json"


def _default_unpushed_records(repo_path: str) -> tuple[tuple[str, str, str], ...]:
    try:
        return git_unpushed_commit_records(repo_path, fetch=True)
    except Exception:
        return ()


def _run_owned_checkpoint_path(artifacts_dir: str | None) -> Path | None:
    if not artifacts_dir:
        return None
    return Path(artifacts_dir) / _CHECKPOINT_FILENAME


@dataclass(frozen=True)
class ConflictRepairResult:
    """Outcome from one conflict repair and resume attempt."""

    invoke_result: InvokeResult
    resolved_without_commit: bool = False


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
    bead_action: str | None = None,
    instance_id: str = "commit",
    git_changed_files_fn: _GitChangedFiles = git_changed_files,
    git_head_commit_id_fn: _GitHeadCommitId = git_head_commit_id,
    git_unpushed_records_fn: _GitUnpushedRecords = _default_unpushed_records,
) -> ConflictRepairResult:
    """Run the one-shot conflict-repair turn and resume the same stitch."""

    if _conflict_repair_spent(context.artifacts_dir, repo, instance_id=instance_id):
        raise BuiltinCommitFinalizerError(
            f"commit finalizer hit a second unresolved conflict in {repo.name}",
            result=failed_result(
                instance_id,
                "second_unresolved_conflict",
                f"commit finalizer hit a second unresolved conflict in {repo.name}",
                attempts=attempts,
                evidence=evidence,
            ),
            invoke_result=invoke_result,
        )
    checkpoint_path = _run_owned_checkpoint_path(context.artifacts_dir)
    checkpoint_existed_before = bool(
        checkpoint_path is not None and checkpoint_path.is_file()
    )
    current_result = run_conflict_repair_turn(
        provider=provider,
        invoke_result=invoke_result,
        model_tier=model_tier,
        suppress_output=suppress_output,
        model_override=model_override,
        artifacts_dir=context.artifacts_dir,
        options=options,
        repo=repo,
        instance_id=instance_id,
        attempt=attempt_id,
        context=context,
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
        return ConflictRepairResult(invoke_result=current_result)
    if checkpoint_existed_before and (
        checkpoint_path is None or not checkpoint_path.is_file()
    ):
        # The repair turn already ran `sase stitch create --resume` and
        # consumed the run-owned checkpoint. Do not run the host resume
        # again; verify repository state directly.
        return _verify_settled_or_raise(
            repo,
            context,
            provider=provider,
            invoke_result=current_result,
            attempts=attempts,
            evidence=evidence,
            instance_id=instance_id,
            git_changed_files_fn=git_changed_files_fn,
            git_head_commit_id_fn=git_head_commit_id_fn,
            git_unpushed_records_fn=git_unpushed_records_fn,
        )
    resumed = _call_resume_runner(
        resume_runner,
        repo,
        context,
        bead_action=bead_action,
        instance_id=instance_id,
        attempt=attempt_id,
        label=f"{repo.name}-conflict-repair",
    )
    record_stitch_artifacts(
        context, instance_id, attempt_id, resumed, label=f"{repo.name}-conflict-repair"
    )
    if resumed.timed_out or resumed.stdout_truncated or resumed.stderr_truncated:
        code = "stitch_timeout" if resumed.timed_out else "stitch_output_cap"
        message_text = stitch_bounds_failure_message(
            repo,
            resumed,
            code,
            artifacts=artifact_root(context.artifacts_dir),
            resume=True,
        )
        raise BuiltinCommitFinalizerError(
            message_text,
            result=failed_result(
                instance_id,
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
                instance_id,
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
                instance_id,
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
        return ConflictRepairResult(invoke_result=current_result)
    return _verify_settled_or_raise(
        repo,
        context,
        provider=provider,
        invoke_result=current_result,
        attempts=attempts,
        evidence=evidence,
        instance_id=instance_id,
        git_changed_files_fn=git_changed_files_fn,
        git_head_commit_id_fn=git_head_commit_id_fn,
        git_unpushed_records_fn=git_unpushed_records_fn,
    )


def _safe_unpushed_records(
    repo_path: str,
    git_unpushed_records_fn: _GitUnpushedRecords,
) -> tuple[tuple[str, str, str], ...]:
    try:
        records = git_unpushed_records_fn(repo_path)
    except Exception:
        return ()
    return records or ()


def _format_unpushed_lines(
    records: tuple[tuple[str, str, str], ...],
) -> str:
    lines: list[str] = []
    for sha, _tree, message in records:
        subject = (message.strip().splitlines() or [""])[0].strip() or "(no subject)"
        short = sha[:12] if len(sha) >= 12 else sha
        lines.append(f"  {short} {subject}")
    return "\n".join(lines)


def _repo_is_clean_after_repair(
    repo: DirtyRepo,
    *,
    provider: Any,
    git_changed_files_fn: _GitChangedFiles,
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
    return not git_changed_files_fn(repo.path)


def _repo_is_settled_after_repair(
    repo: DirtyRepo,
    *,
    provider: Any,
    git_changed_files_fn: _GitChangedFiles = git_changed_files,
    git_unpushed_records_fn: _GitUnpushedRecords = _default_unpushed_records,
) -> bool:
    if not _repo_is_clean_after_repair(
        repo, provider=provider, git_changed_files_fn=git_changed_files_fn
    ):
        return False
    return not _safe_unpushed_records(repo.path, git_unpushed_records_fn)


def _verify_settled_or_raise(
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
    *,
    provider: Any,
    invoke_result: InvokeResult,
    attempts: list[FinalizerAttemptWire],
    evidence: list[FinalizerOutcomeEvidenceWire],
    instance_id: str,
    git_changed_files_fn: _GitChangedFiles,
    git_head_commit_id_fn: _GitHeadCommitId,
    git_unpushed_records_fn: _GitUnpushedRecords,
) -> ConflictRepairResult:
    if _repo_is_settled_after_repair(
        repo,
        provider=provider,
        git_changed_files_fn=git_changed_files_fn,
        git_unpushed_records_fn=git_unpushed_records_fn,
    ):
        evidence.append(
            FinalizerOutcomeEvidenceWire(
                kind="conflict_repair", value="resolved_without_commit"
            )
        )
        evidence.append(
            FinalizerOutcomeEvidenceWire(
                kind="head_sha", value=git_head_commit_id_fn(repo.path)
            )
        )
        return ConflictRepairResult(
            invoke_result=invoke_result,
            resolved_without_commit=True,
        )
    unpushed = _safe_unpushed_records(repo.path, git_unpushed_records_fn)
    clean = _repo_is_clean_after_repair(
        repo, provider=provider, git_changed_files_fn=git_changed_files_fn
    )
    if clean and unpushed:
        message_text = (
            f"sase stitch create --resume completed for {repo.name}, but HEAD is "
            "ahead of its upstream with unpushed commits and no "
            "commit_results.json entry was recorded:\n"
            + _format_unpushed_lines(unpushed)
            + "\nRun `sase stitch create --resume` to publish the rebased HEAD."
        )
        raise BuiltinCommitFinalizerError(
            message_text,
            result=failed_result(
                instance_id,
                "unpushed_after_repair",
                message_text,
                attempts=attempts,
                evidence=evidence,
            ),
            invoke_result=invoke_result,
        )
    message_text = (
        f"sase stitch create --resume completed for {repo.name}, but no "
        "commit_results.json entry was recorded and the repository is not clean"
    )
    raise BuiltinCommitFinalizerError(
        message_text,
        result=failed_result(
            instance_id,
            "missing_commit_result",
            message_text,
            attempts=attempts,
            evidence=evidence,
        ),
        invoke_result=invoke_result,
    )


def _call_resume_runner(
    resume_runner: ResumeRunner,
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
    *,
    bead_action: str | None,
    instance_id: str | None = None,
    attempt: int | None = None,
    label: str | None = None,
) -> StitchCommandResult:
    accepted = {
        name
        for name in ("bead_action", "instance_id", "attempt", "label")
        if _callable_accepts_keyword(resume_runner, name)
    }
    if accepted:
        offered = {
            "bead_action": bead_action,
            "instance_id": instance_id,
            "attempt": attempt,
            "label": label,
        }
        runner = cast(Callable[..., StitchCommandResult], resume_runner)
        return runner(
            repo,
            context,
            **{name: offered[name] for name in sorted(accepted)},
        )
    return resume_runner(repo, context)


def _callable_accepts_keyword(fn: Callable[..., Any], name: str) -> bool:
    try:
        signature = inspect.signature(fn)
    except (TypeError, ValueError):
        return False
    for param in signature.parameters.values():
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            return True
        if param.name == name and param.kind in {
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        }:
            return True
    return False


def _conflict_repair_filename(stem: str, repo: DirtyRepo) -> str:
    return f"{stem}.{artifact_label(repo.name)}.md"


def _conflict_repair_spent(
    artifacts_dir: str | None,
    repo: DirtyRepo,
    *,
    instance_id: str = "commit",
) -> bool:
    artifact_dir = instance_artifact_dir(artifacts_dir, instance_id)
    if artifact_dir is None:
        return False
    return (
        artifact_dir / _conflict_repair_filename(_CONFLICT_PROMPT_STEM, repo)
    ).is_file()


def run_conflict_repair_turn(
    *,
    provider: Any,
    invoke_result: InvokeResult,
    model_tier: ModelTier,
    suppress_output: bool,
    model_override: str | None,
    artifacts_dir: str | None,
    options: LLMInvocationOptions | None,
    repo: DirtyRepo,
    instance_id: str = "commit",
    attempt: int | None = None,
    context: Any | None = None,
) -> InvokeResult:
    prompt = (
        "The built-in SASE commit finalizer hit a merge/rebase conflict while "
        f"committing repository {repo.name}. This is an automated host instruction, "
        "not a message from the user.\n\n"
        f"Target repository: {repo.name}\n"
        f"Target checkout path: {repo.path}\n\n"
        "This is the single conflict-repair turn for this repository during this "
        "run. Operate from the checkout holding the paused operation; use an explicit "
        "working directory for commands instead of changing the provider process's "
        "global working directory. Use the existing `/sase_repo` access workflow when "
        "it is required for this checkout.\n\n"
        "Inspect the live unmerged files with the VCS, resolve their semantics, stage "
        "the resolved files, and review the staged result before continuing. Verify "
        "the integrated content affected by the repair, including relevant "
        "automatically merged content; do not choose checks solely from the old dirty "
        "file snapshot.\n\n"
        "Consult the target repository's applicable instructions and locally defined "
        "verification commands. Run the checks they require for these changes in the "
        "working directory those checks specify. A mandatory all-changes gate remains "
        "mandatory, including for JSON or Markdown repairs, and a failing or "
        "unavailable required gate is a verification failure, not an absent gate.\n\n"
        "Confirm that the selected command definition and working directory belong to "
        "the target repository's verification procedure. Do not substitute a parent, "
        "launch-workspace, or sibling repository's gate just because the target has "
        "none; account for task runners discovering ancestor configuration. A command "
        "outside the repository is appropriate only when applicable instructions "
        "explicitly delegate verification there and it actually checks this target "
        "content.\n\n"
        "If there is no applicable gate, validate the resolved files directly. For "
        "structured data, check parsing plus relevant schema or invariants; for JSON "
        "artifact-link indexes, preserve distinct records and counts, detect duplicate "
        "identities, and maintain required ordering. For prose, review that intended "
        "content from both sides survives. Verify that no unresolved entries or "
        "conflict markers remain. Parse success alone is insufficient, but do not "
        "invent a full test suite to repair a document.\n\n"
        "Briefly report the repository, the checks performed and their results, or why "
        "no applicable gate exists and which direct checks were used. Then continue "
        "the paused VCS operation and run `sase stitch create --resume`. If continuing "
        "reveals further conflicts, repeat the resolution and verification steps.\n\n"
        "A clean conflict-marker resolution does not prove the merge is "
        "semantically correct. When both sides add an entry to the same list, "
        "dict, tuple, or enum, git can merge both entries and leave a duplicate; "
        "semantic mistakes need checks that actually cover the merged content.\n\n"
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
        "other repository that is still dirty; after this declaration is accepted, "
        "the host executes remaining declared repository obligations once in a "
        "bounded continuation and will not start another conflict-repair turn."
    )
    recorder: OperationRecorder | None = None
    if context is not None:
        recorder = OperationRecorder.for_context(context, instance_id)
    elif artifacts_dir is not None:
        recorder = OperationRecorder(artifacts_dir, instance_id)
    op_name = f"conflict-repair-{artifact_label(repo.name)}"
    started_at: float | None = None
    wall_start = time.time()
    if recorder is not None:
        started_at = recorder.start(
            op_name,
            kind="model_turn",
            label=f"conflict repair {repo.name}"[:120],
            attempt=attempt,
        )
        wall_start = started_at
    artifact_dir = instance_artifact_dir(artifacts_dir, instance_id)
    if artifact_dir is not None:
        write_text_artifact(
            artifact_dir / _conflict_repair_filename(_CONFLICT_PROMPT_STEM, repo),
            prompt,
        )
    with finalizer_owned_turn():
        follow_up = invoke_with_instructions(
            provider,
            prompt,
            purpose="conflict_repair",
            artifacts_dir=artifacts_dir,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            options=options,
        )
    if artifact_dir is not None:
        write_text_artifact(
            artifact_dir / _conflict_repair_filename(_CONFLICT_RESPONSE_STEM, repo),
            follow_up.content,
        )
    if recorder is not None:
        try:
            recorder.finish(
                op_name,
                kind="model_turn",
                label=f"conflict repair {repo.name}"[:120],
                attempt=attempt,
                started_at=started_at or wall_start,
                duration_seconds=max(0.0, time.time() - wall_start),
                prompt=prompt,
                response=follow_up.content,
                logs={
                    "stdout": _conflict_repair_filename(_CONFLICT_RESPONSE_STEM, repo),
                },
            )
        except Exception:  # noqa: BLE001 - observability is best-effort
            pass
    return InvokeResult(
        content=append_response(invoke_result.content, follow_up.content),
        usage=merge_usage(invoke_result.usage, follow_up.usage),
    )


__all__ = [
    "ConflictRepairResult",
    "run_conflict_repair_turn",
    "resolve_commit_conflict",
]
