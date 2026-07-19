"""Shared state types for prompt-panel display workers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ...models._agent_clan_sections import ClanDiskSection, ClanInMemorySnapshot
from ...models.agent import Agent
from ...models.agent_tribe_summary import TribePanelIdentity
from ._agent_tribe_aggregation import TribeEnrichmentSection, TribeUnitSource


@dataclass(frozen=True)
class AgentDetailRenderContext:
    """Current AgentDetail state needed by async prompt-panel workers."""

    generation: int
    attempt_view_mode: str
    attempt_pinned_number: int | None
    is_current: Callable[[tuple[Any, ...], int, str, int | None], bool]


@dataclass(frozen=True)
class BeadDisplayResolveRequest:
    """State captured when an async bead display resolve is started."""

    agent: Agent
    agent_identity: tuple[Any, ...]
    generation: int
    attempt_view_mode: str
    attempt_pinned_number: int | None
    is_current: Callable[[tuple[Any, ...], int, str, int | None], bool]


@dataclass(frozen=True)
class LinkedDeltaResolveRequest:
    """State captured when an async linked-deltas refresh is started."""

    agent: Agent
    agent_identity: tuple[Any, ...]
    generation: int
    attempt_view_mode: str
    attempt_pinned_number: int | None
    is_current: Callable[[tuple[Any, ...], int, str, int | None], bool]


@dataclass(frozen=True)
class DetailHeaderEnrichmentRequest:
    """State captured when async detail-header enrichment is started."""

    agent: Agent
    agent_identity: tuple[Any, ...]
    generation: int
    attempt_view_mode: str
    attempt_pinned_number: int | None
    is_current: Callable[[tuple[Any, ...], int, str, int | None], bool]


@dataclass(frozen=True)
class ClanSectionEnrichmentRequest:
    """State captured when clan disk-section loading starts."""

    agent: Agent
    agent_identity: tuple[Any, ...]
    in_memory: ClanInMemorySnapshot
    sections: frozenset[ClanDiskSection]
    slow_tool_threshold_ms: int
    generation: int
    attempt_view_mode: str
    attempt_pinned_number: int | None
    is_current: Callable[[tuple[Any, ...], int, str, int | None], bool]


@dataclass(frozen=True)
class TribeSectionEnrichmentRequest:
    """State captured when tribe disk/statistics enrichment starts."""

    panel_identity: TribePanelIdentity
    sources: tuple[TribeUnitSource, ...]
    sections: frozenset[TribeEnrichmentSection]
    slow_tool_threshold_ms: int
