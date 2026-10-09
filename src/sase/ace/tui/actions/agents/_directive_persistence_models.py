"""Patch and spec types for worker-safe agent directive persistence."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AgentMetaPatch:
    """Patch to apply to ``agent_meta.json``."""

    set_values: Mapping[str, object] = field(default_factory=dict)
    remove_keys: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentTribeStorePatch:
    """Patch to apply to the persistent Agents-tab tribe store."""

    identity: tuple[Any, str, str | None]
    tribe: str | None


@dataclass(frozen=True)
class WaitingMarkerPatch:
    """Replacement contents for ``waiting.json``."""

    waiting_for: tuple[str, ...] = ()
    wait_for_epics_of: tuple[str, ...] = ()
    wait_for_beads: tuple[str, ...] = ()
    wait_for_hoods: tuple[str, ...] = ()
    wait_duration: float | None = None
    wait_until: str | None = None
    update_wait_runners: bool = False
    wait_runners: int | None = None
    queue_capacity_multiplier: float | None = None
    update_wait_priority: bool = False
    wait_priority: int | None = None
    update_queue_weight: bool = False
    queue_weight: float | None = None
    queue_weight_explicit: bool = False


@dataclass(frozen=True)
class ReadyMarkerPatch:
    """Replacement contents for ``ready.json``."""

    resolved_deps: tuple[str, ...] = ()
    unwait: bool = False


@dataclass(frozen=True)
class AgentDirectivePersistenceSpec:
    """All disk mutations for one macro directive-backed property edit."""

    artifacts_dir: str | Path | None
    prompt_mutator: Callable[[str], str] | None = None
    meta_patch: AgentMetaPatch | None = None
    tribe_patch: AgentTribeStorePatch | None = None
    waiting_marker: WaitingMarkerPatch | None = None
    ready_marker: ReadyMarkerPatch | None = None


@dataclass(frozen=True)
class AgentDirectivePersistenceResult:
    """Summary of worker-side persistence effects."""

    raw_prompt_updated: bool = False
    submitted_prompt_updated: bool = False
    history_rewrites: int = 0
    stash_rewrites: int = 0
    meta_updated: bool = False
    waiting_updated: bool = False
    ready_updated: bool = False
    tribe_updated: bool = False


#: Public alias for the worker-side persistence result, for non-TUI callers
#: (e.g. the ``sase agent persist-directive`` operation) that report on an
#: autonomy mutation without reaching into the worker result type.
DirectivePersistenceResult = AgentDirectivePersistenceResult


__all__ = [
    "AgentDirectivePersistenceResult",
    "AgentDirectivePersistenceSpec",
    "AgentMetaPatch",
    "AgentTribeStorePatch",
    "DirectivePersistenceResult",
    "ReadyMarkerPatch",
    "WaitingMarkerPatch",
]
