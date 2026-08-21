"""Detection of finalization progress and of discarded dirty work."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING
import uuid

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

SHARED_CLONE_CLASSIFICATION_EVENT = "commit_finalizer_shared_clone"
SHARED_CLONE_CLASSIFICATION_FILENAME = "shared_clone_classification.jsonl"


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
    new_commits: tuple[tuple[str, str, str | None], ...] = ()
    ledger_entry_count: int | None = None


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
            if _published_store_state_is_exempt(
                repo,
                before_head,
                after_head,
                artifacts_dir=artifacts_dir,
            ):
                continue
            evidence.append(
                _DiscardedDirtyWorkEvidence(
                    repo_name=repo.name,
                    repo_path=repo.path,
                    changed_files=tuple(repo.changed_files),
                    before_head=before_head,
                    after_head=after_head,
                    reason="missing_agent_provenance",
                    new_commits=_new_commit_summaries(
                        repo.path, before_head, after_head
                    ),
                    ledger_entry_count=(
                        len(ledger) if artifacts_dir is not None else None
                    ),
                )
            )
    return tuple(evidence)


def _published_store_state_is_exempt(
    repo: DirtyRepo,
    before_head: str,
    after_head: str,
    *,
    artifacts_dir: str | None = None,
) -> bool:
    """Whether *repo* is shared, machine-wide clone state a race absorbed.

    A repo that went clean with no locally-attributed commit is only exempt
    from the discarded-work guard when it is a machine-wide clone this run
    does not exclusively own — either machine-managed store state
    (``kind == "sdd"``) or a repo merely opened via ``/sase_repo``
    (``kind == "external"``). ``kind == "main"`` and ``kind == "sibling"``
    repos are this agent's own workspace and are never exempt: nobody else
    should be committing there, so an unattributed change is still a
    discard.
    """
    ahead = git_upstream_ahead_count(repo.path)
    foreign_agent = _foreign_agent_of_new_commits(repo.path, before_head, after_head)
    attribution_class = "foreign_agent" if foreign_agent else "unattributed"
    if repo.kind not in ("sdd", "external"):
        exempt = False
        classification = "discard"
    elif not _shared_clone_exemption_enabled():
        exempt = _legacy_published_store_state_is_exempt(repo, ahead)
        classification = "published" if exempt else "discard"
    elif foreign_agent:
        exempt = True
        classification = "race"
    else:
        exempt = True
        classification = "published"
    _record_shared_clone_classification(
        repo_kind=repo.kind,
        before_head=before_head,
        after_head=after_head,
        upstream_ahead=ahead,
        attribution_class=attribution_class,
        classification=classification,
        artifacts_dir=artifacts_dir,
    )
    return exempt


def _legacy_published_store_state_is_exempt(
    repo: DirtyRepo,
    ahead: int | None,
) -> bool:
    """Strict, pre-``commit_finalizer_shared_clone_exempt`` classification.

    Kept as the flag's kill-switch fallback: only machine-managed
    (``kind == "sdd"``) state that is not ahead of its configured upstream is
    exempt, and a foreign agent's footer is never on its own a reason to
    exempt a repo.
    """
    return repo.kind == "sdd" and ahead == 0


def _new_shared_clone_event_id() -> str:
    return uuid.uuid4().hex


def _upstream_ahead_label(ahead: int | None) -> str:
    if ahead is None:
        return "none"
    if ahead == 0:
        return "zero"
    return "positive"


def _record_shared_clone_classification(
    *,
    repo_kind: str,
    before_head: str,
    after_head: str,
    upstream_ahead: int | None,
    attribution_class: str,
    classification: str,
    artifacts_dir: str | None,
) -> str:
    """Emit a path-free structured event and counter for one classification."""

    event_id = _new_shared_clone_event_id()
    ahead_text = "none" if upstream_ahead is None else str(upstream_ahead)
    extra = {
        "sase_event": SHARED_CLONE_CLASSIFICATION_EVENT,
        "shared_clone_event_id": event_id,
        "shared_clone_repo_kind": repo_kind,
        "shared_clone_before_head": before_head,
        "shared_clone_after_head": after_head,
        "shared_clone_upstream_ahead": upstream_ahead,
        "shared_clone_attribution_class": attribution_class,
        "shared_clone_classification": classification,
    }
    _logger.warning(
        "commit finalizer shared-clone classification event_id=%s "
        "repo_kind=%s before_head=%s after_head=%s upstream_ahead=%s "
        "attribution_class=%s classification=%s",
        event_id,
        repo_kind,
        before_head,
        after_head,
        ahead_text,
        attribution_class,
        classification,
        extra=extra,
    )
    from sase.telemetry.metrics import FINALIZER_SHARED_CLONE

    FINALIZER_SHARED_CLONE.labels(
        repo_kind=repo_kind,
        attribution_class=attribution_class,
        classification=classification,
        upstream_ahead=_upstream_ahead_label(upstream_ahead),
    ).inc()
    if artifacts_dir:
        _append_shared_clone_event(
            artifacts_dir,
            {
                "event": SHARED_CLONE_CLASSIFICATION_EVENT,
                "event_id": event_id,
                "repo_kind": repo_kind,
                "before_head": before_head,
                "after_head": after_head,
                "upstream_ahead": upstream_ahead,
                "attribution_class": attribution_class,
                "classification": classification,
            },
        )
    return event_id


def _append_shared_clone_event(
    artifacts_dir: str,
    payload: dict[str, object],
) -> None:
    try:
        path = Path(artifacts_dir) / SHARED_CLONE_CLASSIFICATION_FILENAME
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    except OSError:
        return


def _shared_clone_exemption_enabled() -> bool:
    try:
        from sase.feature_flags import FeatureFlag, current_flags

        return current_flags().enabled(FeatureFlag.commit_finalizer_shared_clone_exempt)
    except Exception:
        return True


def _foreign_agent_of_new_commits(
    repo_dir: str,
    before_head: str,
    after_head: str,
) -> str | None:
    """Return the first well-formed, non-empty ``SASE_AGENT=`` value found.

    By the time this is consulted, ``_new_commits_are_attributable`` has
    already established that no commit in this range matches the current
    agent, carries the agents-sync auto-commit type, or matches the run-owned
    ledger — so any remaining well-formed agent tag names someone else.
    """
    from sase.workflows.commit.runtime_tags import parse_trailing_commit_tags

    for _, _, message in _new_commit_records(repo_dir, before_head, after_head):
        agent = parse_trailing_commit_tags(message).get("AGENT")
        if agent:
            return agent
    return None


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
        lines.append(f"  - HEAD: {item.before_head} -> {item.after_head}")
        if item.reason == "head_not_advanced":
            lines.append(
                "  - next step: no commit exists anywhere in this repo's history "
                "for the changed files below — this agent's work was reset or "
                "never committed; recover or redo the changes."
            )
        else:
            if item.new_commits:
                lines.append("  - newly reachable commits:")
                for sha, subject, agent in item.new_commits:
                    attribution = (
                        f"SASE_AGENT={agent}" if agent else "no SASE_AGENT tag"
                    )
                    lines.append(f"    - {sha} {subject!r} ({attribution})")
            else:
                lines.append("  - newly reachable commits: none")
            lines.append(
                "  - run-owned ledger: "
                + (
                    f"{item.ledger_entry_count} entrie(s) checked, no match"
                    if item.ledger_entry_count is not None
                    else "not consulted (no artifacts directory)"
                )
            )
            lines.append(
                "  - next step: if a commit above is this agent's own work, its "
                "SASE_AGENT= footer was lost or never written — resolve any "
                "conflict and re-run `sase stitch create --resume` to re-stamp "
                "provenance. If it belongs to a different agent in a shared "
                "clone, this may be a concurrent-agent race rather than a "
                "discard."
            )
        lines.append(f"  - changed files ({len(item.changed_files)}):")
        for path in item.changed_files[:20]:
            lines.append(f"    - {path}")
        if len(item.changed_files) > 20:
            lines.append(f"    - ... ({len(item.changed_files)} total)")
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


def _new_commit_summaries(
    repo_dir: str,
    before_head: str,
    after_head: str,
) -> tuple[tuple[str, str, str | None], ...]:
    """Summarize newly reachable commits for an operator-facing diagnostic.

    Each entry is ``(short_sha, subject, agent_or_none)`` — the agent is
    whatever well-formed ``SASE_AGENT=``/``AGENT=`` tag the commit carries (if
    any), independent of whether it matched the current run.
    """
    from sase.workflows.commit.runtime_tags import parse_trailing_commit_tags

    summaries: list[tuple[str, str, str | None]] = []
    for sha, _tree, message in _new_commit_records(repo_dir, before_head, after_head):
        subject_lines = message.splitlines()
        subject = subject_lines[0] if subject_lines else ""
        agent = parse_trailing_commit_tags(message).get("AGENT")
        summaries.append((sha[:12], subject, agent))
    return tuple(summaries)


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
