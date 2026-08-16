"""Data models for deterministic bead-work owner cleanup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


type CleanupAction = Literal["PRESERVE", "KILL", "REMOVE", "RELEASE"]


@dataclass(frozen=True)
class BeadWorkSlot:
    """One logical bead-work owner name that may block a relaunch segment."""

    slot_id: str
    owner_name: str
    expected_bead_id: str
    launch_name: str | None
    allow_populated_clan_skip: bool = False


@dataclass(frozen=True)
class CleanupTarget:
    """One existing owner or reservation affected by forced name reuse."""

    name: str
    action: CleanupAction
    current_state: str
    detail: str
    expected_bead_id: str = ""
    slot_id: str = ""
    artifacts_dir: str = ""
    generation: str = ""

    @property
    def destructive(self) -> bool:
        return self.action in {"KILL", "REMOVE", "RELEASE"}

    @property
    def preserved(self) -> bool:
        return self.action == "PRESERVE"


@dataclass(frozen=True)
class BeadWorkLaunchSelection:
    """Immutable cleanup and replacement decision for one bead-work retry."""

    slots: tuple[BeadWorkSlot, ...]
    targets: tuple[CleanupTarget, ...]
    launch_names: frozenset[str]

    @property
    def destructive_targets(self) -> tuple[CleanupTarget, ...]:
        return tuple(target for target in self.targets if target.destructive)

    @property
    def preserved_names(self) -> tuple[str, ...]:
        return tuple(target.name for target in self.targets if target.preserved)

    @property
    def has_launches(self) -> bool:
        return bool(self.launch_names)


@dataclass(frozen=True)
class CleanupPreview:
    """Read-only preview of destructive forced-reuse cleanup."""

    targets: tuple[CleanupTarget, ...]
    selection: BeadWorkLaunchSelection | None = None

    @property
    def has_destructive_targets(self) -> bool:
        return any(target.destructive for target in self.targets)
