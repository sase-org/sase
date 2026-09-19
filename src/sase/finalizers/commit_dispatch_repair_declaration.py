"""Declaration lookups and messages used by conflict-repair follow-up work."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sase.finalizers.commit_declaration import (
    commit_decisions_for_instance,
    load_accepted_commit_declaration,
    repository_decision_id,
)
from sase.finalizers.executor import FinalizerExecutionContext
from sase.llm_provider.commit_finalizer_types import DirtyRepo

_NO_FOLLOW_UP_DECLARATION = (
    "the conflict-repair turn submitted no commit declaration for this repository"
)
_FOLLOW_UP_LOAD_FAILED = "the declaration could not be loaded"


def post_repair_declared_message(
    repo: DirtyRepo,
    context: FinalizerExecutionContext,
    instance_id: str,
    *,
    declaration_loader: Any | None = None,
) -> tuple[str | None, str | None]:
    """Return the follow-up commit message declared for a repaired repository."""
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
    """Explain why a landed primary commit still requires repair attention."""
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
