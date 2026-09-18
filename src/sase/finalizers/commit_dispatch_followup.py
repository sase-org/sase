"""Post-repair stitch handling for built-in commit dispatch."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
import inspect
from pathlib import Path
from typing import Any, cast

from sase.core.finalizer_facade import (
    RemainingCommitWorkError,
    select_remaining_commit_obligations,
)
from sase.core.finalizer_wire import (
    ExecutedCommitObligationFactWire,
    FinalizerAttemptWire,
    FinalizerDiagnosticWire,
    FinalizerOutcomeEvidenceWire,
    RemainingCommitObligationFactWire,
    RemainingCommitWorkRequestWire,
)
from sase.finalizers import declaration as finalizer_declaration
from sase.finalizers.commit_declaration import (
    accepted_deferrals_for_instance,
    accepted_repos_from_host,
    commit_decisions_for_instance,
    load_accepted_commit_declaration,
    repository_decision_id,
)
from sase.finalizers.commit_dispatch_types import (
    PostRepairFollowUpResult,
    PrepareDirtyState,
    RepairRemainingHandoff,
    UnexpectedPathResolver,
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

_DeclarationLoader = Callable[[str | None], tuple[Mapping[str, Any], Any, Any, Any]]

_NO_FOLLOW_UP_DECLARATION = (
    "the conflict-repair turn submitted no commit declaration for this repository"
)
_FOLLOW_UP_LOAD_FAILED = "the declaration could not be loaded"
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
    declaration_loader: _DeclarationLoader | None = None,
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


def post_repair_declared_message(
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
    instance_id: str,
    *,
    declaration_loader: _DeclarationLoader | None = None,
) -> tuple[str | None, str | None]:
    try:
        loader = declaration_loader or load_accepted_commit_declaration
        envelope, _accepted_context, _host_records, _accepted_deferrals = loader(
            context.artifacts_dir
        )
    except Exception as exc:
        return None, f"{_FOLLOW_UP_LOAD_FAILED}: {exc}"
    decision = commit_decisions_for_instance(envelope, instance_id).get(
        repository_decision_id(repo)
    )
    if not isinstance(decision, Mapping):
        return None, _NO_FOLLOW_UP_DECLARATION
    if str(decision.get("action")) != "commit":
        return None, _NO_FOLLOW_UP_DECLARATION
    message = str(decision.get("message", "")).strip()
    if not message:
        return None, _NO_FOLLOW_UP_DECLARATION
    return message, None


def conflict_repair_dirty_after_stitch_message(
    repo: DirtyRepo,
    remaining: Sequence[str],
    *,
    primary_marker: Mapping[str, Any],
    failure_reason: str,
) -> str:
    base = (
        f"sase stitch create left uncommitted attributable paths in "
        f"{repo.name}: " + ", ".join(remaining)
    )
    sha = primary_marker.get("commit_sha")
    landed = (
        f"The primary commit for {repo.name} already landed as {sha}."
        if isinstance(sha, str) and sha
        else (
            f"The primary commit for {repo.name} already landed, but "
            "commit_results.json did not include its commit sha."
        )
    )
    return f"{base}. {landed} Follow-up commit status: {failure_reason}."


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


def format_repair_handoff_failure(
    reason: str,
    *,
    landed: Sequence[tuple[str, str]],
    remaining: Sequence[DirtyRepo],
    continuation_bound: bool = False,
) -> str:
    """Describe a repair-handoff failure without implying a replay of landed work."""

    parts = [reason.rstrip(".") + "."]
    if landed:
        parts.append(
            "Already landed: "
            + ", ".join(f"{name} {sha}" for name, sha in landed)
            + "."
        )
    if remaining:
        described = []
        for repo in remaining:
            paths = ", ".join(repo.changed_files)
            described.append(f"{repo.name} ({paths})" if paths else repo.name)
        parts.append("Remaining: " + ", ".join(described) + ".")
    if continuation_bound:
        parts.append(
            "The conflict-repair continuation bound forbids another repair turn."
        )
    return " ".join(parts)


def collect_repair_remaining_handoff(
    *,
    context: FinalizerExecutionContext,
    instance_id: str,
    project_dir: str,
    artifacts: Path | None,
    prepare_dirty_state: PrepareDirtyState,
    executed: Sequence[ExecutedCommitObligationFactWire],
    landed: Sequence[tuple[str, str]],
    current_result: InvokeResult,
    attempts: Sequence[FinalizerAttemptWire],
    evidence: Sequence[FinalizerOutcomeEvidenceWire],
    declaration_loader: _DeclarationLoader | None = None,
) -> RepairRemainingHandoff | None:
    """Load the repair declaration and select remaining host-ordered work."""

    state = prepare_dirty_state(project_dir, artifacts)
    completed_ids = {item.obligation_id for item in executed if item.completed}
    remaining_dirty = tuple(
        repo
        for repo in state.dirty_state.repos
        if repository_decision_id(repo) not in completed_ids
    )
    if not remaining_dirty:
        return None
    try:
        loader = declaration_loader or load_accepted_commit_declaration
        envelope, accepted_context, host_records, accepted_deferrals_raw = loader(
            context.artifacts_dir
        )
        if accepted_context is None:
            raise RuntimeError("accepted repair context is missing")
    except Exception as exc:
        message_text = format_repair_handoff_failure(
            f"commit finalizer requires a current accepted declaration: {exc}",
            landed=landed,
            remaining=remaining_dirty,
        )
        raise BuiltinCommitFinalizerError(
            message_text,
            result=failed_result(
                instance_id,
                "missing_commit_declaration",
                message_text,
                attempts=attempts,
                evidence=evidence,
            ),
            invoke_result=current_result,
        ) from exc

    decisions = commit_decisions_for_instance(envelope, instance_id)
    accepted_deferrals = accepted_deferrals_for_instance(
        accepted_deferrals_raw, instance_id
    )
    obligation_by_id = {
        obligation.obligation_id: obligation
        for obligation in accepted_context.obligations
        if obligation.kind == "repository"
    }
    current_by_id = {repository_decision_id(repo): repo for repo in remaining_dirty}
    extra_dirty = sorted(set(current_by_id) - set(obligation_by_id))
    if extra_dirty:
        extra_repos = tuple(current_by_id[repo_id] for repo_id in extra_dirty)
        message_text = format_repair_handoff_failure(
            "commit declaration is stale; unexpected dirty repository "
            "obligation(s): " + ", ".join(extra_dirty),
            landed=landed,
            remaining=extra_repos,
        )
        raise BuiltinCommitFinalizerError(
            message_text,
            result=failed_result(
                instance_id,
                "stale_commit_declaration",
                message_text,
                attempts=attempts,
                evidence=evidence,
            ),
            invoke_result=current_result,
        )

    host_by_id = {record.obligation_id: record for record in host_records}
    facts: list[RemainingCommitObligationFactWire] = []
    for obligation in accepted_context.obligations:
        if obligation.kind != "repository":
            continue
        repo = current_by_id.get(obligation.obligation_id)
        if repo is None:
            continue
        record = host_by_id.get(obligation.obligation_id)
        current_digest = finalizer_declaration.repository_state_digest(
            obligation.obligation_id,
            repo,
            list(repo.changed_files),
        )
        facts.append(
            RemainingCommitObligationFactWire(
                obligation_id=obligation.obligation_id,
                kind="repository",
                current_digest=current_digest,
                submitted_digest=obligation.digest,
                has_host_identity=record is not None,
                host_identity_matches=_host_identity_matches(record, repo),
                has_valid_decision=_has_valid_current_decision(
                    obligation.obligation_id,
                    decisions,
                    accepted_deferrals,
                ),
            )
        )

    request = RemainingCommitWorkRequestWire(
        current_run_id=str(context.run_id or ""),
        current_agent_id=str(context.agent_id or ""),
        current_turn_nonce=str(context.turn_nonce or ""),
        current_plan_digest=str(context.plan_digest or ""),
        declaration_run_id=accepted_context.run_id,
        declaration_agent_id=accepted_context.agent_id,
        declaration_turn_nonce=accepted_context.turn_nonce,
        declaration_plan_digest=accepted_context.plan_digest,
        current_obligations=facts,
        executed_obligations=list(executed),
    )
    try:
        outcome = select_remaining_commit_obligations(request)
    except RemainingCommitWorkError as exc:
        remaining_repos = tuple(
            current_by_id[item.obligation_id]
            for item in facts
            if item.obligation_id in current_by_id
        )
        message_text = format_repair_handoff_failure(
            str(exc),
            landed=landed,
            remaining=remaining_repos,
        )
        raise BuiltinCommitFinalizerError(
            message_text,
            result=failed_result(
                instance_id,
                exc.code,
                message_text,
                attempts=attempts,
                evidence=evidence,
            ),
            invoke_result=current_result,
        ) from exc

    remaining_repos = tuple(
        current_by_id[repo_id]
        for repo_id in outcome.obligation_ids
        if repo_id in current_by_id
    )
    if not remaining_repos:
        return None
    accepted_repos_from_host(
        accepted_context,
        host_records,
        instance_id=instance_id,
    )
    stitch_context = replace(
        context,
        assigned_bead_id=(
            accepted_context.assigned_bead.bead_id
            if accepted_context.assigned_bead is not None
            else None
        ),
        assigned_bead_primary_repo_id=(
            accepted_context.assigned_bead.primary_repo_obligation_id
            if accepted_context.assigned_bead is not None
            else None
        ),
        run_id=accepted_context.run_id,
        agent_id=accepted_context.agent_id,
        turn_nonce=accepted_context.turn_nonce,
        plan_digest=accepted_context.plan_digest,
        context_digest=accepted_context.context_digest,
    )
    return RepairRemainingHandoff(
        repos=remaining_repos,
        decisions=decisions,
        accepted_deferrals=accepted_deferrals,
        state=state,
        context=stitch_context,
    )


def _host_identity_matches(record: Any, repo: DirtyRepo) -> bool:
    if record is None:
        return False
    return (
        record.kind == repo.kind
        and record.name == repo.name
        and record.path == repo.path
    )


def _has_valid_current_decision(
    repo_id: str,
    decisions: Mapping[str, Mapping[str, Any]],
    accepted_deferrals: Mapping[str, Any],
) -> bool:
    if repo_id in accepted_deferrals:
        return True
    decision = decisions.get(repo_id)
    if not isinstance(decision, Mapping):
        return False
    if str(decision.get("action")) != "commit":
        return False
    return bool(str(decision.get("message", "")).strip())


__all__ = [
    "attempt_post_repair_follow_up",
    "collect_repair_remaining_handoff",
    "conflict_repair_dirty_after_stitch_message",
    "format_repair_handoff_failure",
    "post_repair_declared_message",
    "rescue_landed_commit_after_bounds_failure",
    "stitch_bounds_failure_code",
]
