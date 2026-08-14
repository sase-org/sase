"""Identifiers, constants, and immutable records for Artifacts tabs.

Split out of :mod:`sase.ace.tui.artifact_tabs` so descriptor construction and
provider discovery can share one vocabulary without importing each other.  Like
that module this one has no Textual widget dependencies.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.sidecar_ref_config import SidecarRefPolicy


ArtifactsSubTab = str
FilesSubTab = str
ArtifactsPaneKey = str

DEFAULT_ARTIFACTS_SUBTAB: ArtifactsSubTab = "stitches"
FIXED_ARTIFACTS_SUBTAB_ORDER: tuple[ArtifactsSubTab, ...] = (
    "stitches",
    "patches",
    "beads",
    "files",
)
FIXED_ARTIFACTS_PANE_IDS: dict[ArtifactsSubTab, str] = {
    "patches": "artifacts-patches-pane",
    "stitches": "artifacts-stitches-pane",
    "beads": "artifacts-beads-pane",
    "files": "artifacts-files-pane",
}

LEGACY_ARTIFACTS_SUBTABS: dict[str, ArtifactsSubTab] = {
    "prs": "patches",
    "bugs": "beads",
    "plans": "ref:plan",
    "other": "files",
    # The standalone Chats pane has been retired. Transcript access remains
    # available from agent detail and artifact flows.
    "chats": DEFAULT_ARTIFACTS_SUBTAB,
}

EXTERNAL_ACCENT = "#FF5F5F"
ARTIFACTS_ACCENTS: dict[str, str] = {
    "patches": "#00D7AF",
    "stitches": "#FFD700",
    "beads": "#D787FF",
    "files": "#FFAF5F",
    "ref:plan": "#AF87FF",
    # Compatibility aliases for older modules/tests while the provider pane
    # keeps the old plans action surface.
    "plans": "#AF87FF",
    "other": "#FFAF5F",
}
ARTIFACTS_ICONS: dict[str, str] = {
    "stitches": "◉",
    "patches": "⎇",
    "beads": "◈",
    "files": "▤",
}


@dataclass(frozen=True, slots=True)
class ArtifactsTabDescriptor:
    """Immutable runtime descriptor for one top-level Artifacts pane."""

    id: ArtifactsSubTab
    label: str
    accent: str
    pane_id: str
    icon: str = ""
    provider_kind: str | None = None
    provider_spec_digest: str | None = None
    provider_spec: Mapping[str, Any] | None = None
    digit_shortcut: str | None = None
    error: str | None = None
    error_code: str | None = None
    error_source: str | None = None

    @property
    def is_provider(self) -> bool:
        return self.provider_kind is not None

    @property
    def is_degraded(self) -> bool:
        return self.error is not None


@dataclass(frozen=True, slots=True)
class DocumentProviderProjectRoot:
    """One project/root contributing rows to a document-provider pane."""

    project: str
    display_name: str
    workspace_dir: str | None
    role: str
    root: Path
    policy: SidecarRefPolicy


@dataclass(frozen=True, slots=True)
class ProjectProviderRecord:
    """One discovered document-provider root, before it becomes a tab."""

    project: str
    display_name: str
    workspace_dir: str | None
    role: str
    root: Path
    policy: SidecarRefPolicy


@dataclass(frozen=True, slots=True)
class ProviderDiscoveryIssue:
    """A provider-discovery failure that must stay visible on a tab."""

    message: str
    code: str
    kind: str | None = None
    role: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderLoadResult:
    """Everything one discovery pass learned: healthy roots plus failures."""

    records: tuple[ProjectProviderRecord, ...]
    issues: tuple[ProviderDiscoveryIssue, ...]
