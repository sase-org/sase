"""Single-pass primary commit-history association discovery."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
import re

from sase.agents_sync.git import GitRunner
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.commit_footer_facade import parse_commit_footer

from ._agent_names import commit_tag_label, global_agent_name
from .models import BeadCommitRepository

_LOG_FORMAT = "--format=%H%x00%ct%x00%s%x00%B%x00"
_LEGACY_BEAD_SUBJECT_RE = re.compile(r" \(([^()\s]+)\)$")


@dataclass(frozen=True, slots=True)
class HistoricalBeadCommit:
    """Commit metadata retained for bead-page rendering."""

    sha: str
    committed_at: int
    subject: str
    repository: BeadCommitRepository


@dataclass(frozen=True, slots=True)
class _HistoryAssociations:
    """Direct associations derived from one primary ``git log`` walk."""

    agents: dict[str, set[str]]
    agent_commits: dict[str, dict[str, set[tuple[str, str]]]]
    commits: dict[str, dict[tuple[str, str], HistoricalBeadCommit]]
    diagnostics: tuple[str, ...] = ()


def read_history_associations(
    repository: BeadCommitRepository,
    known_bead_ids: frozenset[str],
    identity: AgentIdentitySnapshot,
    git_runner: GitRunner,
) -> _HistoryAssociations:
    """Walk one repository's history and group footer tags by known bead."""

    try:
        result = git_runner(
            repository.root,
            ["log", _LOG_FORMAT],
            op="bead_pages.associations.history",
        )
    except Exception as exc:  # noqa: BLE001 - best-effort local history boundary.
        return _HistoryAssociations(
            {},
            {},
            {},
            (_history_diagnostic(repository, str(exc)),),
        )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"git exited {result.returncode}"
        return _HistoryAssociations(
            {},
            {},
            {},
            (_history_diagnostic(repository, detail),),
        )

    agents: defaultdict[str, set[str]] = defaultdict(set)
    agent_commits: defaultdict[str, dict[str, set[tuple[str, str]]]] = defaultdict(dict)
    commits: defaultdict[str, dict[tuple[str, str], HistoricalBeadCommit]] = (
        defaultdict(dict)
    )
    chunks = result.stdout.split("\x00")
    for index in range(0, len(chunks) - 3, 4):
        _index_history_entry(
            chunks[index : index + 4],
            repository,
            known_bead_ids,
            identity,
            agents,
            agent_commits,
            commits,
        )
    return _HistoryAssociations(
        dict(agents),
        dict(agent_commits),
        dict(commits),
    )


def _index_history_entry(
    chunks: list[str],
    repository: BeadCommitRepository,
    known_bead_ids: frozenset[str],
    identity: AgentIdentitySnapshot,
    agents: defaultdict[str, set[str]],
    agent_commits: defaultdict[str, dict[str, set[tuple[str, str]]]],
    commits: defaultdict[str, dict[tuple[str, str], HistoricalBeadCommit]],
) -> None:
    sha = chunks[0].lstrip("\r\n").strip().casefold()
    subject = chunks[2].rstrip("\r\n")
    try:
        committed_at = int(chunks[1].strip())
        footer = parse_commit_footer(chunks[3].rstrip("\r\n"))
    except (ImportError, RuntimeError, TypeError, ValueError):
        return
    tags = {tag.key: tag.value for tag in footer.tags}
    tagged_bead = commit_tag_label(tags.get("BEAD"))
    bead_id = _associated_bead_id(tagged_bead, subject, known_bead_ids)
    if bead_id is None:
        return

    commit_key = (repository.name, sha)
    commits[bead_id][commit_key] = HistoricalBeadCommit(
        sha,
        committed_at,
        subject,
        repository,
    )
    agent_name = global_agent_name(commit_tag_label(tags.get("AGENT")), identity)
    if agent_name is None:
        return
    agents[bead_id].add(agent_name)
    agent_commits[bead_id].setdefault(agent_name, set()).add(commit_key)


def _history_diagnostic(
    repository: BeadCommitRepository,
    detail: str,
) -> str:
    return (
        f"could not read git history for {repository.name} "
        f"({repository.root}): {detail}"
    )


def _associated_bead_id(
    tagged_bead: str | None,
    subject: str,
    known_bead_ids: frozenset[str],
) -> str | None:
    if tagged_bead is not None:
        return tagged_bead if tagged_bead in known_bead_ids else None
    legacy = _LEGACY_BEAD_SUBJECT_RE.search(subject)
    if legacy is None:
        return None
    candidate = legacy.group(1)
    return candidate if candidate in known_bead_ids else None


__all__ = [
    "HistoricalBeadCommit",
    "read_history_associations",
]
