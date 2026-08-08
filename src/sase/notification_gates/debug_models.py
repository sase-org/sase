"""Data models shared by notification gate debug modules."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from sase.notifications.models import Notification

ArtifactStatus = Literal["ok", "missing", "error"]
GateDebugStatus = Literal[
    "PENDING",
    "ANSWERED",
    "CANCELLED",
    "TIMED OUT",
    "OVERDUE",
    "UNKNOWN",
]


@dataclass(frozen=True)
class GateDebugContext:
    """Stable in-hand input used to open a gate debug surface immediately."""

    notification: Notification
    action_data: Mapping[str, str]


@dataclass(frozen=True)
class GateDebugArtifact:
    """One bounded artifact rendered by a debug tab."""

    status: ArtifactStatus
    body: str
    raw_text: str
    path: Path | None = None
    error: str | None = None
    truncated: bool = False


@dataclass(frozen=True)
class GateDebugResource:
    """Live integrity result for one reviewed bundle resource."""

    path: str
    role: str
    executable: bool
    size: int | None
    integrity: Literal["ok", "mismatch", "missing", "error"]
    detail: str


@dataclass(frozen=True)
class GateDebugError:
    """One execution-error record from the bundle's errors directory."""

    path: Path
    code: str
    message: str
    source: str
    returncode: int | None
    stdout: str | None
    stderr: str | None
    body: str


@dataclass(frozen=True)
class GateDebugSnapshot:
    """Complete, immutable debug projection for a notification gate."""

    kind: str
    request_id: str
    notification_id: str
    icon: str
    status: GateDebugStatus
    created_at: str | None
    age: str
    bundle_path: Path | None
    overview: GateDebugArtifact
    request: GateDebugArtifact
    response: GateDebugArtifact
    journal: GateDebugArtifact
    errors: tuple[GateDebugError, ...]
    error_count: int
    errors_artifact: GateDebugArtifact
    row: GateDebugArtifact
    resources: tuple[GateDebugResource, ...]


@dataclass(frozen=True)
class GateDebugBundlePaths:
    root: Path
    request: Path
    response: Path
    cancellation: Path
    legacy: bool
