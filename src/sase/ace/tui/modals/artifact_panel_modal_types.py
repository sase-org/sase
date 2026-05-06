"""Type aliases for the artifact panel modal."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from rich.console import RenderableType

from sase.core.artifact_wire import (
    ArtifactDetailPagedWire,
    ArtifactDetailWire,
    ArtifactGraphOptionsWire,
    ArtifactGraphWire,
    ArtifactNodeWire,
    ArtifactPageRequestWire,
    ArtifactQueryWire,
)

ArtifactShowFunc = Callable[[Path | str, str], ArtifactDetailWire]
ArtifactShowPagedFunc = Callable[
    [Path | str, str, ArtifactPageRequestWire | None], ArtifactDetailPagedWire
]
ArtifactGraphFunc = Callable[[Path | str, ArtifactGraphOptionsWire], ArtifactGraphWire]
ArtifactExportFunc = Callable[[Path | str, ArtifactGraphOptionsWire, str], str]
ArtifactDetailRenderer = Callable[[ArtifactDetailWire], RenderableType]
ArtifactRefreshFunc = Callable[
    [Path | str, str, Path | str | None, Path | str | None], None
]
ArtifactSearchFunc = Callable[[Path | str, ArtifactQueryWire], list[ArtifactNodeWire]]
