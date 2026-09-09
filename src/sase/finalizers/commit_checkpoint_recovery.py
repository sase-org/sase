"""Resume a run-owned pending commit checkpoint before a new stitch."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from sase.core.finalizer_wire import (
    FinalizerAttemptWire,
    FinalizerOutcomeEvidenceWire,
)
from sase.core.pending_commit_checkpoint import (
    decide_pending_commit_checkpoint_recovery,
)
from sase.finalizers.commit_repair import (
    marker_evidence,
    record_stitch_artifacts,
)
from sase.finalizers.commit_types import (
    BuiltinCommitFinalizerError,
    ResumeRunner,
    failed_result,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.finalizers.ledger import FinalizerBudgetError, InstanceLedger
from sase.llm_provider.commit_finalizer_git import normalize_path
from sase.llm_provider.commit_finalizer_types import DirtyRepo
from sase.llm_provider.types import InvokeResult
from sase.workflows.commit.checkpoint import checkpoint_load
from sase.workflows.commit.runtime_tags import (
    RUN_OWNED_COMMIT_TAG_KEYS,
    update_trailing_commit_tags,
)
from sase.workflows.commit.workflow_types import EXIT_CODE_CONFLICT

_CHECKPOINT_FILENAME = "commit_state.json"


def resume_owned_pending_checkpoint(
    accepted_repos: Sequence[DirtyRepo],
    *,
    decisions: Mapping[str, Mapping[str, Any]],
    artifacts: Path | None,
    context: FinalizerExecutionContext,
    instance_id: str,
    resume_runner: ResumeRunner,
    ledger: InstanceLedger | None,
    current_result: InvokeResult,
    repository_decision_id: Any,
    peek_attempt: Any,
) -> (
    tuple[int | None, list[FinalizerAttemptWire], list[FinalizerOutcomeEvidenceWire]]
    | None
):
    """Resume one matching pending checkpoint before clean acceptance or create.

    Returns ``None`` when no recovery is required. A fail-closed decision
    raises :class:`BuiltinCommitFinalizerError`.
    """
    checkpoint, malformed, unknown_version = _load_checkpoint(artifacts)
    matching = _matching_repo(checkpoint, accepted_repos) if checkpoint else None
    decision_payload = (
        decisions.get(repository_decision_id(matching), {})
        if matching is not None
        else {}
    )
    request = _recovery_request(
        checkpoint,
        matching_repo=matching,
        decision=decision_payload,
        context=context,
        malformed=malformed,
        unknown_version=unknown_version,
    )
    verdict = decide_pending_commit_checkpoint_recovery(request)
    action = str(verdict.get("action") or "")
    reason = str(verdict.get("reason") or "commit checkpoint recovery refused")
    diagnostics = [str(item) for item in verdict.get("diagnostics") or () if str(item)]
    if action == "fail":
        raise BuiltinCommitFinalizerError(
            reason,
            result=failed_result(
                instance_id,
                "pending_checkpoint_refused",
                reason,
                attempts=[
                    FinalizerAttemptWire(
                        attempt=peek_attempt(ledger),
                        status="failed",
                        diagnostic_code="pending_checkpoint_refused",
                    )
                ],
                evidence=[
                    FinalizerOutcomeEvidenceWire(kind="checkpoint_recovery", value=item)
                    for item in diagnostics
                ],
            ),
            invoke_result=current_result,
        )
    if action != "resume" or matching is None:
        return None

    try:
        attempt_id = ledger.consume_before_execute() if ledger is not None else 1
    except FinalizerBudgetError as exc:
        raise BuiltinCommitFinalizerError(
            str(exc),
            result=failed_result(
                instance_id,
                "attempt_budget_exhausted",
                str(exc),
                attempts=[
                    FinalizerAttemptWire(
                        attempt=peek_attempt(ledger),
                        status="failed",
                        diagnostic_code="attempt_budget_exhausted",
                    )
                ],
            ),
            invoke_result=current_result,
        ) from exc

    attempts = [FinalizerAttemptWire(attempt=attempt_id, status="failed")]
    evidence = [
        FinalizerOutcomeEvidenceWire(
            kind="pending_checkpoint_resume", value=matching.name
        ),
        *[
            FinalizerOutcomeEvidenceWire(kind="checkpoint_recovery", value=item)
            for item in diagnostics
        ],
    ]
    resumed = resume_runner(matching, context)
    record_stitch_artifacts(
        context,
        instance_id,
        attempt_id,
        resumed,
        label=f"{matching.name}-checkpoint-resume",
        inputs={
            "resume_checkpoint": True,
            "repo_path": matching.path,
            "operation_id": getattr(checkpoint, "operation_id", None),
            "commit_sha": getattr(checkpoint, "commit_sha", None),
        },
    )
    if resumed.timed_out or resumed.stdout_truncated or resumed.stderr_truncated:
        code = "stitch_timeout" if resumed.timed_out else "stitch_output_cap"
        message_text = f"sase stitch create --resume {code} for {matching.name}"
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
    if resumed.returncode == EXIT_CODE_CONFLICT:
        raise BuiltinCommitFinalizerError(
            f"commit finalizer hit a second unresolved conflict in {matching.name}",
            result=failed_result(
                instance_id,
                "second_unresolved_conflict",
                f"commit finalizer hit a second unresolved conflict in {matching.name}",
                attempts=attempts,
                evidence=evidence,
            ),
            invoke_result=current_result,
        )
    if resumed.returncode != 0:
        message_text = f"sase stitch create --resume failed for {matching.name}: " + (
            (resumed.stderr or resumed.stdout).strip() or reason
        )
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
    if checkpoint is not None and checkpoint.commit_sha:
        evidence.extend(
            marker_evidence(
                {
                    "cwd": matching.path,
                    "result": checkpoint.commit_sha,
                    "commit_sha": checkpoint.commit_sha,
                    "commit_tree": checkpoint.commit_tree,
                    "pushed": checkpoint.pushed,
                }
            )
        )
    attempts[0] = FinalizerAttemptWire(attempt=attempt_id, status="success")
    return (attempt_id, attempts, evidence)


def _load_checkpoint(
    artifacts: Path | None,
) -> tuple[Any, bool, bool]:
    if artifacts is None:
        return (None, False, False)
    path = artifacts / _CHECKPOINT_FILENAME
    if not path.is_file():
        return (None, False, False)
    try:
        payload = path.read_text(encoding="utf-8")
    except OSError:
        return (None, True, False)
    if not payload.strip():
        return (None, True, False)
    loaded = checkpoint_load(str(path))
    if loaded is not None:
        return (loaded, False, False)
    try:
        data = json.loads(payload)
    except (OSError, json.JSONDecodeError, TypeError):
        return (None, True, False)
    if not isinstance(data, dict):
        return (None, True, False)
    version = data.get("version")
    if version not in (None, 1):
        return (None, False, True)
    return (None, True, False)


def _matching_repo(
    checkpoint: Any,
    accepted_repos: Sequence[DirtyRepo],
) -> DirtyRepo | None:
    cwd = getattr(checkpoint, "cwd", None)
    if not isinstance(cwd, str) or not cwd:
        return None
    expected = normalize_path(cwd)
    for repo in accepted_repos:
        if normalize_path(repo.path) == expected:
            return repo
    return None


def _recovery_request(
    checkpoint: Any,
    *,
    matching_repo: DirtyRepo | None,
    decision: Mapping[str, Any],
    context: FinalizerExecutionContext,
    malformed: bool,
    unknown_version: bool,
) -> dict[str, Any]:
    if checkpoint is None:
        return {
            "checkpoint_present": malformed or unknown_version,
            "malformed": malformed,
            "unknown_version": unknown_version,
            "current_run_id": _clean_text(context.run_id),
            "current_agent_id": _clean_text(context.agent_id),
        }
    payload = checkpoint.payload if isinstance(checkpoint.payload, dict) else {}
    expected_message = _normalized_commit_message(payload.get("message"))
    accepted_message = _normalized_commit_message(decision.get("message"))
    expected_subject = _first_line(expected_message)
    accepted_subject = _first_line(accepted_message)
    method = checkpoint.method
    accepted_action = decision.get("action")
    subject_matches = bool(expected_subject) and expected_subject == accepted_subject
    steps = list(checkpoint.completed_steps or [])
    pending_tracking = _pending_tracking(method, steps)
    return {
        "checkpoint_present": True,
        "malformed": malformed,
        "unknown_version": unknown_version,
        "repository_matches": matching_repo is not None,
        "checkpoint_method": _clean_text(method),
        "accepted_action": _clean_text(accepted_action),
        "checkpoint_payload_identity": expected_message,
        "accepted_payload_identity": accepted_message,
        "checkpoint_run_id": _clean_text(getattr(checkpoint, "run_id", None)),
        "current_run_id": _clean_text(context.run_id),
        "checkpoint_agent_id": _clean_text(
            getattr(checkpoint, "publication_agent", None)
        ),
        "current_agent_id": _clean_text(context.agent_id),
        "subject_matches": subject_matches,
        "payload_matches": expected_message == accepted_message,
        "has_operation_id": bool(checkpoint.operation_id),
        "independent_ownership_evidence": False,
        "dispatch_completed": "dispatch" in steps,
        "pending_after_hook": method in {"create_commit", "create_pull_request"}
        and "after_hook" not in steps,
        "pending_tracking": pending_tracking,
        "unpushed": checkpoint.pushed is False,
        "commit_sha_present": bool(checkpoint.commit_sha),
    }


def _pending_tracking(method: str, steps: Sequence[str]) -> bool:
    if method in {"create_commit", "create_proposal"}:
        return "write_result_marker" not in steps or "append_commits_entry" not in steps
    if method == "create_pull_request":
        return "create_patch" not in steps
    return False


def _first_line(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return (value.splitlines() or [""])[0].strip()


def _normalized_commit_message(value: object) -> str:
    if not isinstance(value, str):
        return ""
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = update_trailing_commit_tags(
        text,
        {},
        remove_keys=RUN_OWNED_COMMIT_TAG_KEYS,
    )
    return "\n".join(line.rstrip() for line in text.split("\n")).strip()


def _clean_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = ["resume_owned_pending_checkpoint"]
