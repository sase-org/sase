"""Shared dependency entrypoints used by publication enqueue and drain flows."""

from __future__ import annotations

from sase import config
from sase.agents_sync import targets
from sase.agents_sync.models import TargetSelection
from sase.core.agent_identity_facade import AgentOwnerIdentity


def resolve_sync_targets(projects: tuple[str, ...]) -> TargetSelection:
    return targets.resolve_sync_targets(projects)


def require_agent_owner_identity() -> AgentOwnerIdentity:
    return config.require_agent_owner_identity()
