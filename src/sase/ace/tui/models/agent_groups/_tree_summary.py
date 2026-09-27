"""Banner summaries, labels, and ancestor lookup for the agent tree."""

from __future__ import annotations

from dataclasses import dataclass

from sase.project_display_names import humanize_cl_name

from ..agent import Agent, format_compact_duration
from .._agent_clan import sase_agent_status_counts
from .._agent_tree import agent_is_tree_child
from ._buckets import NO_PATCH_LABEL, GroupingMode
from ._tree_rows import GroupRow, TreeEntry


@dataclass(frozen=True)
class _BannerSummary:
    """Aggregate counts shown next to a group banner."""

    count: int
    running: int
    failed: int
    awaiting: int
    done: int = 0
    # Set for a remote-machine L0 banner sourced from the host's
    # authoritative counts rather than a recount of loaded rows. ``unknown``
    # is only displayed when the host supplied an explicit unknown count;
    # it is never inferred as ``total - running`` because queued, waiting,
    # failed, and done rows are known non-running states.
    unknown: int = 0
    authoritative: bool = False
    # Ready-to-render suffix for a degraded remote-machine feed (e.g.
    # ``"feed invalid"`` or ``"stale · cached 5h ago"``). Set only for an
    # authoritative BY_MACHINE banner whose host reports an invalid or
    # stale-cached snapshot; see ``_host_feed_status_label``.
    status_label: str | None = None


def compute_banner_summary(
    group: GroupRow,
    agents: list[Agent],
    *,
    mode: GroupingMode = GroupingMode.STANDARD,
) -> _BannerSummary:
    """Aggregate status counts for the agents referenced by *group*.

    Only non-workflow-child agents are counted so the summary mirrors
    the user's mental model of "agents in this group".  Counts are
    derived from the shared concrete-agent projection so agent session handoffs and
    container counts agree with the other summary surfaces, *except* for a
    remote-machine L0 banner in ``BY_MACHINE`` mode: that banner sources its
    counts from the host's own authoritative counts instead, so a bounded or
    partially-stale page of rows can never under/over-count a remote
    machine's real running total. The local ("here") machine banner keeps
    the recount path unchanged.
    """
    roots: list[Agent] = []
    for idx in group.agent_indices:
        if idx < 0 or idx >= len(agents):
            continue
        agent = agents[idx]
        if agent_is_tree_child(agent):
            continue
        roots.append(agent)

    if group.level == 0 and mode is GroupingMode.BY_MACHINE:
        authoritative = _authoritative_machine_summary(roots)
        if authoritative is not None:
            return authoritative

    projected = sase_agent_status_counts(roots, ())
    return _BannerSummary(
        count=projected.total,
        running=projected.running,
        failed=projected.failed,
        awaiting=projected.stopped,
    )


def _authoritative_machine_summary(roots: list[Agent]) -> _BannerSummary | None:
    """Authoritative running/unknown summary for a remote-machine L0 banner.

    Returns ``None`` for the local ("here") group, or when no row in the
    group yet carries host counts, so the caller falls back to the ordinary
    recount.
    """
    for agent in roots:
        if not agent.fleet_origin_alias:
            return None
        total = agent.fleet_host_total_count
        running = agent.fleet_host_running_count
        if total is None or running is None:
            continue
        return _BannerSummary(
            count=total,
            running=running,
            failed=agent.fleet_host_failed_count or 0,
            awaiting=agent.fleet_host_waiting_count or 0,
            done=agent.fleet_host_done_count or 0,
            unknown=agent.fleet_host_unknown_count or 0,
            authoritative=True,
            status_label=_host_feed_status_label(agent),
        )
    return None


def _host_feed_status_label(agent: Agent) -> str | None:
    """Honest feed-health suffix for a remote-machine banner.

    Every row from the same host carries the same
    ``fleet_host_status``/``fleet_freshness``/``fleet_host_cache_age_seconds``
    values (see ``_fleet_agents_rows``), so the representative row this
    banner sourced its counts from also tells the whole host's feed health
    -- a healthy count must never be shown next to a feed that is actually
    invalid or serving a stale cache.
    """
    if agent.fleet_host_status == "invalid" or agent.fleet_host_feed_error:
        return "feed invalid"
    if agent.fleet_freshness == "stale":
        if agent.fleet_host_cache_age_seconds is not None:
            age = format_compact_duration(agent.fleet_host_cache_age_seconds)
            return f"stale · cached {age} ago"
        return "stale"
    return None


def banner_label_for_group_key(group_key: tuple[str, ...]) -> str:
    """Compose the human-readable banner label for *group_key*.

    * Level 0 (1-tuple ``(project,)``) → project name or ``"(no project)"``.
    * Level 1, 3-level mode (2-tuple ``(project, patch)``) → the
      Patch name or the synthetic ``"(no Patch)"`` bucket.
    * Level 1, 2-level mode (2-tuple ``(project, name_root)``) → the
      bare name-root (always non-empty for a real banner).
    * Level 1, BY_DATE mode (2-tuple ``(date_bucket, subgroup)``) → the
      bare subgroup label (1-hour ``HH:00``, calendar day, or week range).
    * Level 2+ dotted-name prefix or name-root descendants use their
      bare suffix.

    All non-L0 banners use the ``group_key[-1]`` suffix as their label.
    """
    if len(group_key) == 1:
        proj = group_key[0]
        return proj if proj else "(no project)"
    suffix = group_key[-1]
    if suffix:
        return humanize_cl_name(suffix)
    return NO_PATCH_LABEL


def banner_label(group: GroupRow) -> str:
    """Compose the human-readable banner label for *group*."""
    return banner_label_for_group_key(group.group_key)


def banner_summary_text(summary: _BannerSummary) -> str:
    """Compact ``"N agents · 2 running · 1 failed"``-style label.

    An authoritative remote-machine summary uses only explicit host count
    evidence. It never renders ``unknown`` from a remainder because known
    non-running states are not unknown.

    Returns an empty string when the summary is empty (count == 0).
    """
    if summary.count <= 0:
        return ""
    plural = "s" if summary.count != 1 else ""
    parts = [f"{summary.count} agent{plural}"]
    if summary.authoritative:
        if summary.running:
            parts.append(f"{summary.running} running")
        if summary.awaiting:
            parts.append(f"{summary.awaiting} awaiting")
        if summary.failed:
            parts.append(f"{summary.failed} failed")
        if summary.done:
            parts.append(f"{summary.done} done")
        if summary.unknown:
            parts.append(f"{summary.unknown} unknown")
    else:
        if summary.running:
            parts.append(f"{summary.running} running")
        if summary.failed:
            parts.append(f"{summary.failed} failed")
        if summary.awaiting:
            parts.append(f"{summary.awaiting} awaiting")
    if summary.status_label:
        parts.append(summary.status_label)
    return " · ".join(parts)


def find_visible_ancestor_banner(
    entries: list[TreeEntry], target_agent_idx: int
) -> GroupRow | None:
    """Return the closest ancestor banner of *target_agent_idx* in *entries*.

    Picks the deepest banner whose ``agent_indices`` contains
    *target_agent_idx*; falls back to the first banner that contains
    it, or ``None``.
    """
    best: GroupRow | None = None
    for entry in entries:
        if entry.kind != "group" or entry.group is None:
            continue
        if target_agent_idx in entry.group.agent_indices:
            if best is None or entry.group.level > best.level:
                best = entry.group
    return best
