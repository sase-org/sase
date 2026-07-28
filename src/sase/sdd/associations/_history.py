"""Single-pass primary commit-history association discovery."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from sase.agents_sync.git import GitRunner
from sase.core.agent_identity_facade import AgentIdentitySnapshot
from sase.core.commit_footer_facade import LinkedCommitTagValue, parse_commit_footer

from ._normalization import PlanReferenceNormalizer, global_agent_name

_LOG_FORMAT = "--format=%H%x00%ct%x00%s%x00%B%x00"


@dataclass(frozen=True, slots=True)
class HistoricalCommit:
    """Commit metadata retained for plan-header rendering."""

    sha: str
    committed_at: int
    subject: str


@dataclass(frozen=True, slots=True)
class _HistoryAssociations:
    """Direct associations derived from one primary ``git log`` walk."""

    agents: dict[str, set[str]]
    commits: dict[str, dict[str, HistoricalCommit]]
    diagnostics: tuple[str, ...] = ()


def read_history_associations(
    primary_root: Path,
    normalizer: PlanReferenceNormalizer,
    identity: AgentIdentitySnapshot,
    git_runner: GitRunner,
) -> _HistoryAssociations:
    """Walk primary history once and group footer tags by plan."""

    try:
        result = git_runner(
            primary_root,
            ["log", _LOG_FORMAT],
            op="sdd.plan_associations.history",
        )
    except Exception as exc:  # noqa: BLE001 - best-effort local history boundary.
        return _HistoryAssociations({}, {}, (f"could not read git history: {exc}",))
    if result.returncode != 0:
        detail = result.stderr.strip() or f"git exited {result.returncode}"
        return _HistoryAssociations({}, {}, (f"could not read git history: {detail}",))

    agents: defaultdict[str, set[str]] = defaultdict(set)
    commits: defaultdict[str, dict[str, HistoricalCommit]] = defaultdict(dict)
    chunks = result.stdout.split("\x00")
    for index in range(0, len(chunks) - 3, 4):
        sha = chunks[index].lstrip("\r\n").strip().casefold()
        subject = chunks[index + 2].rstrip("\r\n")
        try:
            committed_at = int(chunks[index + 1].strip())
            footer = parse_commit_footer(chunks[index + 3].rstrip("\r\n"))
        except (ImportError, RuntimeError, TypeError, ValueError):
            continue
        tags = {tag.key: tag.value for tag in footer.tags}
        plan_ref = normalizer.normalize(_tag_label(tags.get("PLAN")))
        if plan_ref is None:
            continue
        commits[plan_ref][sha] = HistoricalCommit(sha, committed_at, subject)
        agent = global_agent_name(_tag_label(tags.get("AGENT")), identity)
        if agent is not None:
            agents[plan_ref].add(agent)
    return _HistoryAssociations(dict(agents), dict(commits))


def _tag_label(value: object) -> str | None:
    if isinstance(value, LinkedCommitTagValue):
        return value.label
    return value if isinstance(value, str) else None


__all__ = ["HistoricalCommit", "read_history_associations"]
