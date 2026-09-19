"""Post-repair stitch handling for built-in commit dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import inspect
from pathlib import Path
from typing import Any, cast

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerDiagnosticWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.commit_dispatch_types import (
    PostRepairFollowUpResult,
    UnexpectedPathResolver,
)
from sase.finalizers.commit_dispatch_repair_declaration import (
    conflict_repair_dirty_after_stitch_message,
    post_repair_declared_message,
)
from sase.finalizers.commit_dispatch_repair_handoff import (
    collect_repair_remaining_handoff,
    format_repair_handoff_failure,
)
from sase.finalizers.commit_repair import (
    load_commit_results,
    marker_evidence,
    marker_matches_repo,
    new_commit_markers,
    record_stitch_artifacts,
    stitch_attempt_fingerprint,
    stitch_attempt_input_fields,
    stitch_bounds_failure_message,
    stitch_failure_message,
)
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    StitchCommandResult,
    StitchRunner,
    failed_result,
)
from sase.finalizers.commit_validation import reconcile_commit_file_hooks
from sase.finalizers.executor import FinalizerExecutionContext
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

_FOLLOW_UP_STILL_DIRTY = "the follow-up commit still left these paths dirty"


def attempt_post_repair_follow_up(
    repo: DirtyRepo,
    protected: Sequence[str],
    context: FinalizerExecutionContext,
    instance_id: str,
    attempt_id: int,
    *,
    attempts: list[FinalizerAttemptWire],
    evidence: list[FinalizerOutcomeEvidenceWire],
    diagnostics: list[FinalizerDiagnosticWire],
    stitch_runner: StitchRunner,
    unexpected_path_resolver: UnexpectedPathResolver,
    project_dir: str,
    current_result: InvokeResult,
    declaration_loader: Callable[..., Any] | None = None,
    bead_action: str | None = None,
) -> PostRepairFollowUpResult:
    message, failure_reason = post_repair_declared_message(
        repo,
        context,
        instance_id,
        declaration_loader=declaration_loader,
    )
    if failure_reason is not None:
        return PostRepairFollowUpResult(
            remaining=unexpected_path_resolver(repo.path, protected),
            failure_reason=failure_reason,
        )
    assert message is not None

    artifacts = (
        Path(context.artifacts_dir) if context.artifacts_dir is not None else None
    )
    before_markers = load_commit_results(artifacts)
    attempt_fields = stitch_attempt_input_fields(
        repo,
        message,
        protected,
        bead_action=bead_action,
        assigned_bead_id=_context_assigned_bead_id(context),
    )
    attempt_fingerprint = stitch_attempt_fingerprint(attempt_fields)
    stitch = _call_stitch_runner(
        stitch_runner,
        repo,
        message,
        protected,
        context,
        bead_action=bead_action,
    )
    follow_up_label = f"{repo.name}.post-repair"
    record_stitch_artifacts(
        context,
        instance_id,
        attempt_id,
        stitch,
        label=follow_up_label,
        inputs={**attempt_fields, "fingerprint": attempt_fingerprint},
    )
    rescued_bounds_failure = rescue_landed_commit_after_bounds_failure(
        stitch,
        repo=repo,
        before_markers=before_markers,
        artifacts=artifacts,
        instance_id=instance_id,
        attempt_id=attempt_id,
        attempts=attempts,
        evidence=evidence,
        diagnostics=diagnostics,
        current_result=current_result,
        bead_action=bead_action,
        assigned_bead_id=_context_assigned_bead_id(context),
    )
    if not rescued_bounds_failure:
        if stitch.returncode == EXIT_CODE_CONFLICT:
            message_text = (
                f"commit finalizer hit a second unresolved conflict in {repo.name}"
            )
            result = failed_result(
                instance_id,
                "second_unresolved_conflict",
                message_text,
                attempts=attempts,
                evidence=evidence,
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=result,
                invoke_result=current_result,
            )
        if stitch.returncode != 0:
            message_text = stitch_failure_message(repo, stitch)
            attempts[0] = FinalizerAttemptWire(
                attempt=attempt_id,
                status="failed",
                diagnostic_code="stitch_failed",
            )
            result = failed_result(
                instance_id,
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

    markers = new_commit_markers(
        before_markers,
        load_commit_results(artifacts),
    )
    repo_markers = [marker for marker in markers if marker_matches_repo(marker, repo)]
    if not repo_markers:
        message_text = (
            f"sase stitch create completed for {repo.name}, but no "
            "commit_results.json entry was recorded"
        )
        result = failed_result(
            instance_id,
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
    evidence.append(
        FinalizerOutcomeEvidenceWire(kind="conflict_repair_followup", value="success")
    )
    evidence.extend(marker_evidence(repo_markers[-1]))
    reconcile_commit_file_hooks(
        repo,
        repo_markers[-1],
        workspace_dir=project_dir,
    )
    remaining = unexpected_path_resolver(repo.path, protected)
    if remaining:
        return PostRepairFollowUpResult(
            remaining=remaining,
            failure_reason=_FOLLOW_UP_STILL_DIRTY,
        )
    return PostRepairFollowUpResult(remaining=[])


def _call_stitch_runner(
    stitch_runner: StitchRunner,
    repo: DirtyRepo,
    message: str,
    protected: Sequence[str],
    context: FinalizerExecutionContext,
    *,
    bead_action: str | None,
) -> StitchCommandResult:
    if _callable_accepts_keyword(stitch_runner, "bead_action"):
        runner = cast(Callable[..., StitchCommandResult], stitch_runner)
        return runner(
            repo,
            message,
            protected,
            context,
            bead_action=bead_action,
        )
    return stitch_runner(repo, message, protected, context)


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


def stitch_bounds_failure_code(stitch: StitchCommandResult) -> str | None:
    if stitch.timed_out:
        return "stitch_timeout"
    if stitch.stdout_truncated or stitch.stderr_truncated:
        return "stitch_output_cap"
    return None


def rescue_landed_commit_after_bounds_failure(
    stitch: StitchCommandResult,
    *,
    repo: DirtyRepo,
    before_markers: Sequence[Mapping[str, Any]],
    artifacts: Path | None,
    instance_id: str,
    attempt_id: int,
    attempts: list[FinalizerAttemptWire],
    evidence: list[FinalizerOutcomeEvidenceWire],
    diagnostics: list[FinalizerDiagnosticWire],
    current_result: InvokeResult,
    bead_action: str | None = None,
    assigned_bead_id: str | None = None,
    bead_status_reader: Callable[[str, DirtyRepo], str] | None = None,
) -> bool:
    """Raise on a bounds failure with no marker; rescue when the commit landed.

    Returns True when a matching ``commit_results.json`` marker proves the
    commit already landed, so the caller should skip returncode failure
    handling and continue with the normal marker-verification path.
    """

    code = stitch_bounds_failure_code(stitch)
    if code is None:
        return False
    markers = new_commit_markers(before_markers, load_commit_results(artifacts))
    repo_markers = [marker for marker in markers if marker_matches_repo(marker, repo)]
    if not repo_markers:
        message_text = stitch_bounds_failure_message(
            repo,
            stitch,
            code,
            artifacts=artifacts,
        )
        attempts[0] = FinalizerAttemptWire(
            attempt=attempt_id,
            status="failed",
            diagnostic_code=code,
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
    if _clean_bead_action(bead_action) == "close":
        _verify_closed_assigned_bead_for_marker_rescue(
            stitch,
            repo=repo,
            code=code,
            artifacts=artifacts,
            instance_id=instance_id,
            attempt_id=attempt_id,
            attempts=attempts,
            evidence=evidence,
            current_result=current_result,
            assigned_bead_id=assigned_bead_id,
            bead_status_reader=bead_status_reader,
            marker=repo_markers[-1],
        )
    diagnostics.append(
        FinalizerDiagnosticWire(
            code=f"{code}_after_commit",
            severity="warning",
            message=(
                stitch_bounds_failure_message(
                    repo,
                    stitch,
                    code,
                    artifacts=artifacts,
                )
                + ", but the commit already landed before the process was killed"
            ),
            instance_id=instance_id,
            attempt=attempt_id,
        )
    )
    return True


def _verify_closed_assigned_bead_for_marker_rescue(
    stitch: StitchCommandResult,
    *,
    repo: DirtyRepo,
    code: str,
    artifacts: Path | None,
    instance_id: str,
    attempt_id: int,
    attempts: list[FinalizerAttemptWire],
    evidence: list[FinalizerOutcomeEvidenceWire],
    current_result: InvokeResult,
    assigned_bead_id: str | None,
    bead_status_reader: Callable[[str, DirtyRepo], str] | None,
    marker: Mapping[str, Any],
) -> None:
    bead_id = _clean_assigned_bead_id(assigned_bead_id)
    status = _assigned_bead_marker_rescue_status(
        bead_id,
        repo,
        bead_status_reader=bead_status_reader,
    )
    status_evidence = FinalizerOutcomeEvidenceWire(
        kind="assigned_bead_status",
        value=f"{bead_id or '<unbound>'}:{status}",
    )
    if status == "closed":
        evidence.append(status_evidence)
        return
    failure_evidence = [*evidence, *marker_evidence(marker), status_evidence]
    failure_code = f"{code}_bead_not_closed"
    message_text = _close_marker_rescue_failure_message(
        repo,
        stitch,
        code=code,
        artifacts=artifacts,
        bead_id=bead_id,
        status=status,
    )
    attempts[0] = FinalizerAttemptWire(
        attempt=attempt_id,
        status="failed",
        diagnostic_code=failure_code,
    )
    raise BuiltinCommitFinalizerError(
        message_text,
        result=failed_result(
            instance_id,
            failure_code,
            message_text,
            attempts=attempts,
            evidence=failure_evidence,
        ),
        invoke_result=current_result,
    )


def _assigned_bead_marker_rescue_status(
    bead_id: str | None,
    repo: DirtyRepo,
    *,
    bead_status_reader: Callable[[str, DirtyRepo], str] | None,
) -> str:
    if bead_id is None:
        return "missing"
    reader = bead_status_reader or _default_assigned_bead_status
    try:
        return str(reader(bead_id, repo))
    except Exception as exc:
        return f"unreadable ({type(exc).__name__}: {exc})"


def _close_marker_rescue_failure_message(
    repo: DirtyRepo,
    stitch: StitchCommandResult,
    *,
    code: str,
    artifacts: Path | None,
    bead_id: str | None,
    status: str,
) -> str:
    base = stitch_bounds_failure_message(repo, stitch, code, artifacts=artifacts)
    target = f"assigned bead {bead_id}" if bead_id is not None else "the assigned bead"
    return (
        f"{base}; commit marker landed, but -B close cannot be treated as complete "
        f"because {target} is {status}, not closed. "
        "Repair or complete the bead close, then retry the finalizer."
    )


def _default_assigned_bead_status(bead_id: str, repo: DirtyRepo) -> str:
    from sase.workflows.commit.bead_hooks import bead_status_fact

    return bead_status_fact(bead_id, repo.path)


def _clean_bead_action(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip().lower()
    return stripped or None


def _clean_assigned_bead_id(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _context_assigned_bead_id(context: FinalizerExecutionContext) -> str | None:
    return _clean_assigned_bead_id(getattr(context, "assigned_bead_id", None))


__all__ = [
    "attempt_post_repair_follow_up",
    "collect_repair_remaining_handoff",
    "conflict_repair_dirty_after_stitch_message",
    "format_repair_handoff_failure",
    "post_repair_declared_message",
    "rescue_landed_commit_after_bounds_failure",
    "stitch_bounds_failure_code",
]
