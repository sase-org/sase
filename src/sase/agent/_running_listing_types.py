"""Types for snapshot-backed running-agent listings."""

from dataclasses import dataclass
from datetime import datetime

from sase.agent.listing_snapshot import AgentListingLoadState
from sase.core.agent_scan_wire import AgentArtifactScanWire
from sase.monitor_state import is_monitor_member_role


@dataclass
class RunningAgentInfo:
    """Summary info for an active or recently completed agent.

    ``status`` defaults to ``"RUNNING"`` for compatibility with direct
    construction in tests and integrations. Listing functions may emit
    ``"STARTING"``, ``"WAITING"``, ``"DONE"``, and ``"FAILED"`` as well.
    """

    name: str | None
    project: str
    pid: int | None
    model: str | None
    provider: str | None
    workspace_num: int | None
    duration: str
    approve: bool
    prompt: str | None = None
    status: str = "RUNNING"
    status_bucket: str | None = None
    started_at: datetime | None = None
    duration_seconds: int | None = None
    artifacts_dir: str | None = None
    # Exact scheduler occupancy from the source scan record. ``None`` preserves
    # compatibility for integrations that construct this lightweight type.
    holds_runner_slot: bool | None = None
    # Canonical clan metadata from agent_meta.json. This is intentionally not
    # inferred from the agent's dotted name because ordinary hoods are not clans.
    agent_clan: str | None = None
    agent_clan_generation: str | None = None
    clan_tribe: str | None = None
    # Effective presentation-neutral tribe. Clan declarations/context take
    # precedence; standalone assignments remain unchanged for non-clan rows.
    tribe: str | None = None
    agent_family: str | None = None
    agent_family_role: str | None = None
    role_suffix: str | None = None
    monitor_id: str | None = None
    monitor_state: str | None = None
    monitor_label: str | None = None
    monitor_command: str | None = None
    monitor_exit_code: int | None = None
    monitor_start_status: str | None = None
    monitor_stop_status: str | None = None

    @property
    def is_monitor(self) -> bool:
        """Whether this row is a monitor member rather than its starter."""
        return is_monitor_member_role(self.agent_family_role, self.role_suffix)


class RunningAgentListing(list[RunningAgentInfo]):
    """Agent rows plus the artifact snapshot used to build them.

    The list behavior preserves the long-standing public return contract while
    read-only integrations can derive related catalog entries without starting
    a second filesystem scan.
    """

    def __init__(
        self,
        values: list[RunningAgentInfo],
        *,
        artifact_snapshot: AgentArtifactScanWire,
        listing_state: AgentListingLoadState | None = None,
    ) -> None:
        super().__init__(values)
        self.artifact_snapshot = artifact_snapshot
        self.listing_state = listing_state


@dataclass
class ListingDecodeCounters:
    liveness_checks: int = 0


DONE_AGENTS_CAP_PER_PROJECT = 50


__all__ = [
    "RunningAgentInfo",
    "DONE_AGENTS_CAP_PER_PROJECT",
    "ListingDecodeCounters",
    "RunningAgentListing",
]
