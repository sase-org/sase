"""Detection of finalization progress and of discarded dirty work."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .commit_finalizer_git_status import (
    UNKNOWN_HEAD_SENTINEL,
    git_head_commit_id,
    git_log_commit_messages,
)

if TYPE_CHECKING:
    from .commit_finalizer_types import DirtyState


@dataclass(frozen=True)
class _DiscardedDirtyWorkEvidence:
    repo_name: str
    repo_path: str
    changed_files: tuple[str, ...]
    before_head: str
    after_head: str
    reason: str


def progress_fingerprint(
    dirty_state: DirtyState,
) -> tuple[tuple[str, str, tuple[str, ...]], ...]:
    """Capture whether *dirty_state*'s repos were committed to or edited.

    Each entry is ``(repo_path, head_commit_id, sorted_changed_files)``. A
    changed ``head_commit_id`` means the repo received a commit; a changed
    file tuple means the working tree changed even without a commit. A repo
    whose HEAD cannot be read contributes a sentinel instead of raising, so a
    single unreadable repo does not break progress detection for the rest.
    """
    return tuple(
        (
            repo.path,
            git_head_commit_id(repo.path),
            tuple(sorted(repo.changed_files)),
        )
        for repo in dirty_state.repos
    )


def discarded_dirty_work_evidence(
    before: DirtyState,
    after: DirtyState,
    *,
    fingerprint_before: tuple[tuple[str, str, tuple[str, ...]], ...] | None = None,
) -> tuple[_DiscardedDirtyWorkEvidence, ...]:
    """Return repos that became clean without an attributable commit."""

    before_heads = {
        repo_path: head
        for repo_path, head, _changed_files in (
            fingerprint_before
            if fingerprint_before is not None
            else progress_fingerprint(before)
        )
    }
    remaining_paths = {repo.path for repo in after.repos}
    evidence: list[_DiscardedDirtyWorkEvidence] = []
    for repo in before.repos:
        if repo.path in remaining_paths:
            continue
        before_head = before_heads.get(repo.path, UNKNOWN_HEAD_SENTINEL)
        after_head = git_head_commit_id(repo.path)
        if before_head == after_head or after_head == UNKNOWN_HEAD_SENTINEL:
            evidence.append(
                _DiscardedDirtyWorkEvidence(
                    repo_name=repo.name,
                    repo_path=repo.path,
                    changed_files=tuple(repo.changed_files),
                    before_head=before_head,
                    after_head=after_head,
                    reason="head_not_advanced",
                )
            )
            continue
        agent_name = _current_agent_name()
        if agent_name and not _new_commits_include_agent(
            repo.path,
            before_head,
            after_head,
            agent_name,
        ):
            evidence.append(
                _DiscardedDirtyWorkEvidence(
                    repo_name=repo.name,
                    repo_path=repo.path,
                    changed_files=tuple(repo.changed_files),
                    before_head=before_head,
                    after_head=after_head,
                    reason="missing_agent_provenance",
                )
            )
    return tuple(evidence)


def discarded_dirty_work_message(
    evidence: Iterable[_DiscardedDirtyWorkEvidence],
) -> str:
    items = tuple(evidence)
    if not items:
        return "Commit finalizer failed: dirty work vanished without a commit."
    lines = [
        "Commit finalizer failed: dirty work vanished without an attributable "
        "commit. The finalizer will not treat discarded, reset, or foreign-agent "
        "work as successful finalization."
    ]
    for item in items:
        reason = (
            "HEAD did not advance"
            if item.reason == "head_not_advanced"
            else "no newly reachable commit was attributed to this agent"
        )
        lines.append(f"- {item.repo_name}: {item.repo_path} ({reason})")
        for path in item.changed_files[:20]:
            lines.append(f"  - {path}")
        if len(item.changed_files) > 20:
            lines.append(f"  - ... ({len(item.changed_files)} total)")
    return "\n".join(lines)


def _current_agent_name() -> str | None:
    try:
        from sase.workflows.commit.runtime_tags import resolve_local_agent_name

        return resolve_local_agent_name()
    except Exception:
        return None


def _new_commits_include_agent(
    repo_dir: str,
    before_head: str,
    after_head: str,
    agent_name: str,
) -> bool:
    for message in _new_commit_messages(repo_dir, before_head, after_head):
        from sase.workflows.commit.runtime_tags import parse_trailing_commit_tags

        tags = parse_trailing_commit_tags(message)
        if _agent_provenance_matches(tags.get("AGENT"), agent_name):
            return True
    return False


def _new_commit_messages(
    repo_dir: str,
    before_head: str,
    after_head: str,
) -> tuple[str, ...]:
    revision = (
        after_head
        if before_head == UNKNOWN_HEAD_SENTINEL
        else f"{before_head}..{after_head}"
    )
    return git_log_commit_messages(repo_dir, revision)


def _agent_provenance_matches(recorded_agent: str | None, agent_name: str) -> bool:
    if not recorded_agent:
        return False
    if _names_match(recorded_agent, agent_name):
        return True
    return _names_match(_lane_of(recorded_agent), _lane_of(agent_name))


def _names_match(recorded_agent: str, agent_name: str) -> bool:
    return recorded_agent == agent_name or recorded_agent.startswith(
        (f"{agent_name}.", f"{agent_name}--")
    )


def _lane_of(name: str) -> str:
    try:
        from sase.agent_lanes import lane_ref_for_agent
        from sase.core.agent_identity_facade import AgentIdentitySnapshot

        return lane_ref_for_agent(name, AgentIdentitySnapshot.current()).local_name
    except Exception:
        return name
