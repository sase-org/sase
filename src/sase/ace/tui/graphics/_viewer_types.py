"""Shared artifact viewer types."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

ArtifactViewMode = Literal["image", "markdown", "pdf", "text", "video"]


class ArtifactFileLike(Protocol):
    """Minimal artifact shape consumed by the viewer."""

    path: str
    kind: str


@dataclass(frozen=True)
class ArtifactFileViewSpec:
    """Artifact path and kind metadata for a terminal viewer document."""

    path: str | Path
    kind: str | None = None


@dataclass(frozen=True)
class ArtifactFileImageArea:
    """Terminal cell area reserved for displaying an artifact image."""

    columns: int
    rows: int
    left: int = 0
    top: int = 0


@dataclass(frozen=True)
class ArtifactFileViewerWarning:
    """Structured warning returned by artifact rendering/viewer helpers."""

    code: str
    message: str
    tool: str | None = None


@dataclass(frozen=True)
class ArtifactRenderResult:
    """Rendered artifact pages ready for terminal display."""

    pages: tuple[Path, ...]
    warnings: tuple[ArtifactFileViewerWarning, ...] = ()

    @property
    def ok(self) -> bool:
        """Return whether at least one displayable page was produced."""
        return bool(self.pages) and not self.warnings


@dataclass(frozen=True)
class ArtifactFileViewerResult:
    """Result returned after trying to open an artifact outside Textual."""

    ok: bool
    warning: str | None = None
    warnings: tuple[ArtifactFileViewerWarning, ...] = ()
    pane_id: str | None = None


ImageViewerResult = ArtifactFileViewerResult


def viewer_result_from_warnings(
    warnings: tuple[ArtifactFileViewerWarning, ...],
) -> ArtifactFileViewerResult:
    """Convert structured viewer warnings into the public viewer result."""
    return ArtifactFileViewerResult(
        False,
        warning=warnings[0].message if warnings else None,
        warnings=warnings,
    )
