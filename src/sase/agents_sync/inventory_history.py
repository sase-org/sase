"""Primary-repository history used to enrich agent inventory records."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from sase.agents_sync.git import GitRunner
from sase.agents_sync.inventory_io import (
    canonical_local_name as _canonical_local_name,
    require_owner as _require_owner,
)
from sase.agents_sync.inventory_models import InventoryLaneCommitHistory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import CommitRecord, ProjectTarget
from sase.core.agent_identity_facade import (
    AgentIdentitySnapshot,
    parse_agent_family_name,
)
from sase.core.commit_footer_facade import CommitTagValue, LinkedCommitTagValue
from sase.sase_agent import SaseAgentRef, sase_agent_ref_for_name
from sase.workflows.commit.runtime_tags import parse_trailing_commit_tag_values


@dataclass(frozen=True, slots=True)
class HistoricalAssociations:
    """Commit associations recovered from the primary repository's history."""

    run_commits: dict[str, tuple[CommitRecord, ...]]
    lane_commits: tuple[InventoryLaneCommitHistory, ...]


def historical_associations(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
    git_runner: GitRunner,
) -> HistoricalAssociations:
    """Associate tagged primary-repository commits with runs and sase agents."""

    result = git_runner(
        target.primary_checkout,
        ["log", "--format=%H%x00%ct%x00%s%x00%B%x00"],
        op="agents_sync.v2_history",
    )
    if result.returncode != 0:
        return HistoricalAssociations({}, ())
    exact_runs: dict[str, dict[str, CommitRecord]] = defaultdict(dict)
    lanes: dict[str, dict[str, CommitRecord]] = defaultdict(dict)
    family_lanes: dict[str, bool] = {}
    chunks = result.stdout.split("\x00")
    for index in range(0, len(chunks) - 3, 4):
        sha = chunks[index].lstrip("\r\n").strip().lower()
        subject = chunks[index + 2].rstrip("\r\n")
        try:
            committed_at = int(chunks[index + 1].strip())
            tags = parse_trailing_commit_tag_values(chunks[index + 3].rstrip("\r\n"))
        except (ValueError, TypeError, RuntimeError):
            continue
        value = tags.get("AGENT")
        raw_name = value.label if isinstance(value, LinkedCommitTagValue) else value
        machine_value = tags.get("MACHINE")
        footer_machine = (
            machine_value.label
            if isinstance(machine_value, LinkedCommitTagValue)
            else machine_value
        )
        if not raw_name or not _footer_is_current_owner(
            raw_name, footer_machine, identity
        ):
            continue
        try:
            local_name = _canonical_local_name(raw_name, identity)
            parsed = parse_agent_family_name(local_name)
        except (AgentsSyncFormatError, ValueError, RuntimeError):
            continue
        commit = CommitRecord(sha, subject, committed_at)
        if parsed.member_role is not None:
            # Legacy footers named the concrete family member. Preserve that
            # exact run attribution forever; only sase-agent-valued footers
            # belong to the family container.
            exact_runs[local_name][sha] = commit
            continue
        try:
            agent_ref = sase_agent_ref_for_name(local_name, identity)
        except Exception:  # noqa: BLE001 - best-effort history boundary.
            continue
        if value is None:
            continue
        is_family = _sase_agent_footer_is_family(value, agent_ref)
        lanes[agent_ref.local_name][sha] = commit
        family_lanes[agent_ref.local_name] = (
            family_lanes.get(agent_ref.local_name, False) or is_family
        )

    lane_commits = tuple(
        InventoryLaneCommitHistory(
            name,
            family_lanes[name],
            _sorted_commit_rows(rows),
        )
        for name, rows in sorted(lanes.items())
    )
    run_rows = dict(exact_runs)
    for history in lane_commits:
        if history.is_family:
            continue
        current = run_rows.setdefault(history.local_name, {})
        current.update({commit.sha: commit for commit in history.commits})
    return HistoricalAssociations(
        {
            name: tuple(
                sorted(rows.values(), key=lambda item: (item.committed_at, item.sha))
            )
            for name, rows in run_rows.items()
        },
        lane_commits,
    )


def _sorted_commit_rows(
    rows: dict[str, CommitRecord],
) -> tuple[CommitRecord, ...]:
    return tuple(sorted(rows.values(), key=lambda item: (item.committed_at, item.sha)))


def _destination_is_family_page(destination: str) -> bool:
    """Return whether a linked footer destination names a family page."""

    path = unquote(urlsplit(destination).path)
    return "families" in {part for part in path.split("/") if part}


def _sase_agent_footer_is_family(
    value: CommitTagValue, agent_ref: SaseAgentRef
) -> bool:
    """Classify an ambiguous sase-agent label from its own footer evidence first."""

    if isinstance(value, LinkedCommitTagValue):
        return _destination_is_family_page(value.destination)
    return agent_ref.is_family


def primary_remote_url(
    target: ProjectTarget,
    git_runner: GitRunner,
) -> str | None:
    """Read the primary checkout's origin without making publication fragile."""

    try:
        result = git_runner(
            target.primary_checkout,
            ["config", "--get", "remote.origin.url"],
            op="agents_sync.v2_primary_remote",
        )
    except Exception:  # noqa: BLE001 - optional local Git metadata boundary.
        return None
    remote_url = result.stdout.strip()
    return remote_url if result.returncode == 0 and remote_url else None


def _footer_is_current_owner(
    name: str,
    footer_machine: str | None,
    identity: AgentIdentitySnapshot,
) -> bool:
    owner = _require_owner(identity)
    global_prefix = f"{owner.username}.{owner.machine_name}."
    if name.startswith(global_prefix):
        return footer_machine in {None, owner.machine_name}
    parts = name.split(".")
    if len(parts) >= 3 and footer_machine and parts[1] == footer_machine:
        return False
    if footer_machine == owner.machine_name:
        return True
    # Legacy footers stored a bare name with a host that was not the configured
    # machine identity. Accept only spellings without an explicit owner prefix.
    return not (footer_machine and name.startswith(f"{footer_machine}."))
