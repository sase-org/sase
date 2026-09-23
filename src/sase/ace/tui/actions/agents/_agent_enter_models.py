"""Shared data shapes for context-aware Enter targets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from ...models import Agent
    from sase.notifications import Notification

EnterTargetKind = Literal["gate", "patch"]
EnterTargetSource = Literal[
    "gate_row",
    "notification",
    "question_marker",
    "workflow_hitl",
    "remote_attention",
    "patch",
]

#: Message when Enter lands on a clan container row.
CLAN_EMPTY_MESSAGE = "Select an agent inside this clan"

#: Message when Enter finds neither a pending gate nor a Patch.
NO_TARGET_EMPTY_MESSAGE = "No pending gate or Patch for this agent"


@dataclass(frozen=True, slots=True)
class PatchSummary:
    """In-memory Patch badge data for one Patch name."""

    status: str | None = None
    pr_label: str | None = None


@dataclass(frozen=True, slots=True)
class AgentEnterTarget:
    """One actionable Enter target for the selected agent row."""

    kind: EnterTargetKind
    source: EnterTargetSource
    key: str
    label: str
    detail: str | None = None
    badge: str | None = None
    badge_style: str | None = None
    age_seconds: float | None = None
    notification_id: str | None = None
    bundle_path: str | None = None
    gate_id: str | None = None
    row_identity: tuple[object, ...] | None = None
    patch_name: str | None = None
    project_file: str | None = None


@dataclass(frozen=True, slots=True)
class AgentEnterResolution:
    """Ordered Enter targets for one selected row."""

    targets: tuple[AgentEnterTarget, ...] = ()
    scope_title: str = ""
    empty_message: str | None = None

    @property
    def primary(self) -> AgentEnterTarget | None:
        """Return the first target (gates first, newest first, Patch last)."""
        return self.targets[0] if self.targets else None


@dataclass
class GateNotificationIndex:
    """Prefiltered gate-notification lookup for one snapshot object."""

    by_id: dict[str, Notification] = field(default_factory=dict)
    by_bundle_path: dict[str, Notification] = field(default_factory=dict)
    by_raw_suffix: dict[str, list[Notification]] = field(default_factory=dict)
    by_request_id: dict[str, Notification] = field(default_factory=dict)
    gate_notifications: tuple[Notification, ...] = ()


def identity_of(agent: Agent) -> tuple[object, ...] | None:
    try:
        identity = agent.identity
    except Exception:
        return None
    if isinstance(identity, tuple):
        return tuple(identity)
    return None


__all__ = [
    "AgentEnterResolution",
    "AgentEnterTarget",
    "CLAN_EMPTY_MESSAGE",
    "GateNotificationIndex",
    "NO_TARGET_EMPTY_MESSAGE",
    "PatchSummary",
    "identity_of",
]
