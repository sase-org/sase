"""Resume unpushed local commits for repos the worktree already reports clean."""

from __future__ import annotations

import inspect
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.finalizers.commit_declaration import (
    repository_decision_id as _repository_decision_id,
)
from sase.finalizers.commit_dispatch import peek_attempt as _peek_attempt
from sase.finalizers.commit_repair import (
    load_commit_results,
    marker_evidence,
    marker_is_unpushed,
    marker_matches_repo,
    new_commit_markers,
    record_stitch_artifacts,
    stitch_bounds_failure_message,
    stitch_failure_message,
)
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    ResumeRunner,
    StitchCommandResult,
    failed_result,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import FinalizerBudgetError, InstanceLedger
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult


def _unpushed_markers_for_repo(
    markers: Sequence[Mapping[str, Any]],
    repo: DirtyRepo,
) -> list[dict[str, Any]]:
    return [
        dict(marker)
        for marker in markers
        if marker_is_unpushed(marker) and marker_matches_repo(marker, repo)
    ]


def _consume_unpushed_resume_attempt(
    ledger: InstanceLedger | None,
    instance_id: str,
    current_result: InvokeResult,
) -> int:
    try:
        return ledger.consume_before_execute() if ledger is not None else 1
    except FinalizerBudgetError as exc:
        raise BuiltinCommitFinalizerError(
            str(exc),
            result=failed_result(
                instance_id,
                "attempt_budget_exhausted",
                str(exc),
                attempts=[
                    FinalizerAttemptWire(
                        attempt=_peek_attempt(ledger),
                        status="failed",
                        diagnostic_code="attempt_budget_exhausted",
                    )
                ],
            ),
            invoke_result=current_result,
        ) from exc


def _unpushed_resume_failure_message(
    repo: DirtyRepo,
    marker: Mapping[str, Any],
    result: StitchCommandResult,
) -> str:
    sha = marker.get("commit_sha")
    commit = sha[:12] if isinstance(sha, str) and sha else "HEAD"
    return (
        f"commit {commit} already exists locally for {repo.name}; "
        "sase stitch create --resume could not push it. "
        + stitch_failure_message(repo, result)
    )


def resume_unpushed_already_clean_repos(
    repos: Sequence[DirtyRepo],
    *,
    decisions: Mapping[str, Mapping[str, Any]],
    artifacts: Path | None,
    context: FinalizerExecutionContext,
    instance_id: str,
    resume_runner: ResumeRunner,
    ledger: InstanceLedger | None,
    current_result: InvokeResult,
) -> tuple[int | None, list[FinalizerAttemptWire], list[FinalizerOutcomeEvidenceWire]]:
    markers = load_commit_results(artifacts)
    work = [
        (repo, repo_markers[-1])
        for repo in repos
        if (repo_markers := _unpushed_markers_for_repo(markers, repo))
    ]
    if not work:
        return (None, [], [])

    attempt_id = _consume_unpushed_resume_attempt(ledger, instance_id, current_result)
    attempts = [FinalizerAttemptWire(attempt=attempt_id, status="failed")]
    evidence: list[FinalizerOutcomeEvidenceWire] = []

    for repo, marker in work:
        bead_action = _decision_bead_action(
            decisions.get(_repository_decision_id(repo), {})
        )
        evidence.append(
            FinalizerOutcomeEvidenceWire(
                kind="unpushed_commit_resume",
                value=repo.name,
            )
        )
        evidence.extend(marker_evidence(marker))
        before_markers = load_commit_results(artifacts)
        resumed = _call_resume_runner(
            resume_runner,
            repo,
            context,
            bead_action=bead_action,
        )
        record_stitch_artifacts(
            context,
            instance_id,
            attempt_id,
            resumed,
            label=f"{repo.name}-unpushed-resume",
            inputs={
                "resume_unpushed": True,
                "repo_path": repo.path,
                "commit_sha": marker.get("commit_sha"),
                "result": marker.get("result"),
            },
        )
        if resumed.timed_out or resumed.stdout_truncated or resumed.stderr_truncated:
            code = "stitch_timeout" if resumed.timed_out else "stitch_output_cap"
            message_text = stitch_bounds_failure_message(
                repo,
                resumed,
                code,
                artifacts=artifacts,
                resume=True,
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
        if resumed.returncode != 0:
            message_text = _unpushed_resume_failure_message(repo, marker, resumed)
            attempts[0] = FinalizerAttemptWire(
                attempt=attempt_id,
                status="failed",
                diagnostic_code="stitch_failed",
            )
            raise BuiltinCommitFinalizerError(
                message_text,
                result=failed_result(
                    instance_id,
                    "stitch_failed",
                    message_text,
                    attempts=attempts,
                    evidence=evidence,
                ),
                invoke_result=current_result,
            )
        resumed_markers = [
            item
            for item in new_commit_markers(
                before_markers,
                load_commit_results(artifacts),
            )
            if marker_matches_repo(item, repo)
        ]
        if resumed_markers:
            evidence.extend(marker_evidence(resumed_markers[-1]))
        else:
            latest = _latest_marker_for_repo(load_commit_results(artifacts), repo)
            if latest is not None:
                evidence.extend(marker_evidence(latest))

    attempts[0] = FinalizerAttemptWire(attempt=attempt_id, status="success")
    return (attempt_id, attempts, evidence)


def _latest_marker_for_repo(
    markers: Sequence[Mapping[str, Any]],
    repo: DirtyRepo,
) -> Mapping[str, Any] | None:
    for marker in reversed(markers):
        if marker_matches_repo(marker, repo):
            return marker
    return None


def _decision_bead_action(decision: Mapping[str, Any]) -> str | None:
    value = decision.get("bead_action")
    return value if value in {"close", "keep"} else None


def _call_resume_runner(
    resume_runner: ResumeRunner,
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
    *,
    bead_action: str | None,
) -> StitchCommandResult:
    if _callable_accepts_keyword(resume_runner, "bead_action"):
        runner = cast(Callable[..., StitchCommandResult], resume_runner)
        return runner(repo, context, bead_action=bead_action)
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
