"""Detection of finalization progress and of discarded dirty work."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from sase.agents_sync.git_sync_ops import AGENTS_SYNC_AUTO_COMMIT_TYPE

from .commit_finalizer_git_paths import normalize_path
from .commit_finalizer_git_status import (
    UNKNOWN_HEAD_SENTINEL,
    git_head_commit_id,
    git_log_commit_records,
    git_upstream_ahead_count,
)

if TYPE_CHECKING:
    from .commit_finalizer_types import DirtyRepo, DirtyState

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _LedgerEntry:
    cwd: str
    commit_sha: str
    commit_tree: str


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
    artifacts_dir: str | None = None,
) -> tuple[_DiscardedDirtyWorkEvidence, ...]:
    """Return repos that became clean without an attributable commit."""

    ledger = _load_run_owned_commit_ledger(artifacts_dir)
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
        if agent_name and not _new_commits_are_attributable(
            repo.path,
            before_head,
            after_head,
            agent_name,
            ledger,
        ):
            if _published_store_state_is_exempt(repo, before_head, after_head):
                continue
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


def _published_store_state_is_exempt(
    repo: DirtyRepo,
    before_head: str,
    after_head: str,
) -> bool:
    """Whether *repo* is machine-managed store state a sync rebase absorbed.

    A sidecar that went clean with no locally-attributed commit is only
    exempt from the discarded-work guard when it is machine-managed
    (``kind == "sdd"``) and its clone is not ahead of its configured
    upstream — i.e. the store's content is already published and the clone
    matches the canonical remote, rather than a local discard of unpublished
    work.
    """
    if repo.kind != "sdd":
        return False
    ahead = git_upstream_ahead_count(repo.path)
    if ahead != 0:
        return False
    _logger.warning(
        "commit finalizer: treating %s (%s) as published rather than "
        "discarded — HEAD moved %s -> %s with no locally-attributed commit, "
        "but the clone is not ahead of its upstream; changed files: %s",
        repo.name,
        repo.path,
        before_head,
        after_head,
        ", ".join(repo.changed_files),
    )
    return True


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


def _new_commits_are_attributable(
    repo_dir: str,
    before_head: str,
    after_head: str,
    agent_name: str,
    ledger: tuple[_LedgerEntry, ...],
) -> bool:
    for sha, tree, message in _new_commit_records(repo_dir, before_head, after_head):
        from sase.workflows.commit.runtime_tags import parse_trailing_commit_tags

        tags = parse_trailing_commit_tags(message)
        if _agent_provenance_matches(tags.get("AGENT"), agent_name):
            return True
        if tags.get("TYPE") == AGENTS_SYNC_AUTO_COMMIT_TYPE:
            return True
        if _ledger_matches_commit(ledger, repo_dir, sha, tree):
            return True
    return False


def _new_commit_records(
    repo_dir: str,
    before_head: str,
    after_head: str,
) -> tuple[tuple[str, str, str], ...]:
    revision = (
        after_head
        if before_head == UNKNOWN_HEAD_SENTINEL
        else f"{before_head}..{after_head}"
    )
    return git_log_commit_records(repo_dir, revision)


def _load_run_owned_commit_ledger(
    artifacts_dir: str | None,
) -> tuple[_LedgerEntry, ...]:
    """Load this run's commit ledger, degrading to empty on any read failure.

    The ledger (``commit_results.json`` in the agent artifacts directory) is
    a bonus attribution signal, not a requirement: a missing, empty, or
    malformed file must fall back to today's footer-only behavior rather
    than raising and turning a read failure into a new way to fail an agent.
    """
    if not artifacts_dir:
        return ()
    try:
        raw = (Path(artifacts_dir) / "commit_results.json").read_text(encoding="utf-8")
        data = json.loads(raw)
    except (OSError, ValueError):
        return ()
    if not isinstance(data, list):
        return ()
    entries: list[_LedgerEntry] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cwd = item.get("cwd")
        sha = item.get("commit_sha")
        if not isinstance(cwd, str) or not cwd or not isinstance(sha, str) or not sha:
            continue
        tree = item.get("commit_tree")
        entries.append(
            _LedgerEntry(
                cwd=cwd,
                commit_sha=sha,
                commit_tree=tree if isinstance(tree, str) else "",
            )
        )
    return tuple(entries)


def _ledger_matches_commit(
    ledger: tuple[_LedgerEntry, ...],
    repo_dir: str,
    commit_sha: str,
    commit_tree: str,
) -> bool:
    """Whether the ledger proves *repo_dir* provably owns this commit.

    Matches on the recorded SHA first; a rebase performed after the ledger
    entry was written can move the commit, so a content match against the
    recorded tree is the fallback rather than giving up.
    """
    if not commit_sha:
        return False
    normalized_repo = normalize_path(repo_dir)
    same_repo = tuple(
        entry for entry in ledger if normalize_path(entry.cwd) == normalized_repo
    )
    if any(entry.commit_sha == commit_sha for entry in same_repo):
        return True
    if not commit_tree:
        return False
    return any(
        entry.commit_tree and entry.commit_tree == commit_tree for entry in same_repo
    )


def _agent_provenance_matches(recorded_agent: str | None, agent_name: str) -> bool:
    if not recorded_agent:
        return False
    if _names_match(recorded_agent, agent_name):
        return True
    return _names_match(_sase_agent_of(recorded_agent), _sase_agent_of(agent_name))


def _names_match(recorded_agent: str, agent_name: str) -> bool:
    return recorded_agent == agent_name or recorded_agent.startswith(
        (f"{agent_name}.", f"{agent_name}--")
    )


def _sase_agent_of(name: str) -> str:
    try:
        from sase.core.agent_identity_facade import AgentIdentitySnapshot
        from sase.sase_agent import sase_agent_ref_for_shell

        return sase_agent_ref_for_shell(
            name, AgentIdentitySnapshot.current()
        ).local_name
    except Exception:
        return name
