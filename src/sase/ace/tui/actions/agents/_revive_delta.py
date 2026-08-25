"""Structured completion delta for agent revival."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models import Agent
    from ...models.agent import AgentType

AgentIdentity = tuple["AgentType", str, str | None]


@dataclass(frozen=True, slots=True)
class _AgentReviveRecord:
    """One agent identity successfully revived by the mutation path."""

    identity: AgentIdentity
    agent_name: str | None
    raw_suffix: str | None
    artifact_dir: str | None


@dataclass(frozen=True, slots=True)
class _AgentReviveFailure:
    """One requested revive that did not complete."""

    identity: AgentIdentity | None
    agent_name: str | None
    raw_suffix: str | None
    stage: str
    message: str


@dataclass(frozen=True, slots=True)
class AgentReviveDelta:
    """Summary returned by ``_do_revive_agent(s)`` for UI consumers."""

    revived: tuple[_AgentReviveRecord, ...] = ()
    failed: tuple[_AgentReviveFailure, ...] = ()
    dismiss_revive_epoch_before: int = 0
    dismiss_revive_epoch_after: int = 0
    dismissed_count_before: int = 0
    dismissed_count_after: int = 0
    dismissed_index_synced: bool = False

    @property
    def revived_identities(self) -> tuple[AgentIdentity, ...]:
        return tuple(item.identity for item in self.revived)

    @property
    def revived_artifact_dirs(self) -> tuple[str, ...]:
        return tuple(
            item.artifact_dir for item in self.revived if item.artifact_dir is not None
        )

    @property
    def generation_changed(self) -> bool:
        return self.dismiss_revive_epoch_after != self.dismiss_revive_epoch_before

    @property
    def has_changes(self) -> bool:
        return bool(self.revived)


def revive_record_for_agent(
    agent: Agent,
    *,
    artifact_dir: str | None,
) -> _AgentReviveRecord:
    """Build a stable success record from a revived Agent object."""

    return _AgentReviveRecord(
        identity=agent.identity,
        agent_name=agent.agent_name,
        raw_suffix=agent.raw_suffix,
        artifact_dir=artifact_dir,
    )


def revive_failure_for_agent(
    agent: Agent | None,
    *,
    stage: str,
    message: str,
) -> _AgentReviveFailure:
    """Build a stable failure record from a requested Agent object."""

    return _AgentReviveFailure(
        identity=None if agent is None else agent.identity,
        agent_name=None if agent is None else agent.agent_name,
        raw_suffix=None if agent is None else agent.raw_suffix,
        stage=stage,
        message=message,
    )


__all__ = [
    "AgentReviveDelta",
    "revive_failure_for_agent",
    "revive_record_for_agent",
]
