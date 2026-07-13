"""Persisted marker files for Agents-tab commit reverts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from sase.ace.revert_agent_models import RepoRevertOutcome
from sase.core.time import local_now

_REVERT_RESULT_FILENAME = "revert_result.json"


@dataclass(frozen=True)
class PushOutcome:
    """Result of attempting to push a revert commit to ``origin``.

    Distinguishes three outcomes the old ``bool`` return collapsed: a skipped
    push (no remote/branch, ``attempted=False``), a successful push
    (``pushed=True``), and a failed push to an available remote (``error`` set).
    """

    attempted: bool
    pushed: bool
    skipped_reason: str | None = None
    error: str | None = None


def agent_is_reverted(artifacts_dir: str | None) -> bool:
    """Return True when an agent artifacts dir carries a persisted revert marker."""
    if not artifacts_dir:
        return False
    try:
        return (Path(artifacts_dir) / _REVERT_RESULT_FILENAME).is_file()
    except OSError:
        return False


def write_revert_result(
    artifacts_dir: str,
    agent_name: str,
    shas: tuple[str, ...],
    *,
    push: PushOutcome | None = None,
    repo_outcomes: tuple[RepoRevertOutcome, ...] = (),
    complete: bool | None = None,
) -> None:
    try:
        pushed = (
            push.pushed if push is not None else any(o.pushed for o in repo_outcomes)
        )
        if complete is None:
            complete = True
        payload: dict[str, object] = {
            "agent_name": agent_name,
            "reverted_shas": list(shas),
            "pushed": pushed,
            "complete": complete,
            "reverted_at": local_now().isoformat(timespec="seconds"),
        }
        if repo_outcomes:
            payload["repos"] = [
                repo_outcome_payload(outcome) for outcome in repo_outcomes
            ]
        if push is not None and push.error is not None:
            payload["push_error"] = push.error
        if push is not None and push.skipped_reason is not None:
            payload["push_skipped_reason"] = push.skipped_reason
        if push is None and len(repo_outcomes) == 1:
            outcome = repo_outcomes[0]
            if outcome.error and outcome.error.startswith("git push failed:"):
                payload["push_error"] = outcome.error.removeprefix("git push failed: ")
            if outcome.push_skipped_reason is not None:
                payload["push_skipped_reason"] = outcome.push_skipped_reason
        path = Path(artifacts_dir) / _REVERT_RESULT_FILENAME
        path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass


def repo_outcome_payload(outcome: RepoRevertOutcome) -> dict[str, object]:
    payload: dict[str, object] = {
        "repo_label": outcome.repo_label,
        "workspace_dir": outcome.workspace_dir,
        "success": outcome.success,
        "reverted_shas": list(outcome.reverted_shas),
        "pushed": outcome.pushed,
        "repo_kind": outcome.repo_kind,
        "discarded_local_changes": outcome.discarded_local_changes,
    }
    if outcome.error is not None:
        payload["error"] = outcome.error
    if outcome.skipped_reason is not None:
        payload["skipped_reason"] = outcome.skipped_reason
    if outcome.push_skipped_reason is not None:
        payload["push_skipped_reason"] = outcome.push_skipped_reason
    return payload


_PushOutcome = PushOutcome
_write_revert_result = write_revert_result
_repo_outcome_payload = repo_outcome_payload


__all__ = [
    "_REVERT_RESULT_FILENAME",
    "PushOutcome",
    "agent_is_reverted",
    "repo_outcome_payload",
    "write_revert_result",
]
