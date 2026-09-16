"""Shared model types for workspace Git object sharing."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AlternateStatus = Literal[
    "absent", "expected", "stale", "broken", "unexpected", "preserved"
]

_CONFIG_ENABLED = "sase.workspaceGitObjects"
_CONFIG_PRIMARY_OBJECTS = "sase.workspaceGitObjectsPrimary"
_CONFIG_PRIMARY_CHECKOUT = "sase.workspaceGitObjectsPrimaryCheckout"
_CONFIG_SOURCE = "sase.workspaceGitObjectsSource"
_BORROWER_CONFIG_KEYS = (
    _CONFIG_ENABLED,
    _CONFIG_PRIMARY_OBJECTS,
    _CONFIG_PRIMARY_CHECKOUT,
    "gc.auto",
    "maintenance.auto",
)


class GitObjectSharingError(RuntimeError):
    """Raised when Git object sharing cannot be proven safe."""


@dataclass(frozen=True)
class AlternateState:
    """Classified ``objects/info/alternates`` state for one checkout."""

    status: AlternateStatus
    checkout_dir: str
    object_dir: str
    alternates_file: str
    expected_object_dir: str
    alternates: tuple[str, ...] = ()
    sase_owned: bool = False
    detail: str = ""


@dataclass(frozen=True)
class ObjectSharingResult:
    """Result of a compact or repair operation."""

    checkout_dir: str
    before_bytes: int
    after_bytes: int
    status: str
    detail: str = ""

    @property
    def reclaimed_bytes(self) -> int:
        return max(0, self.before_bytes - self.after_bytes)


@dataclass(frozen=True)
class AlternateSnapshot:
    """Borrower-local alternates/config state for rollback."""

    alternates_file: Path
    alternates_content: str | None
    config_values: Mapping[str, str | None]
