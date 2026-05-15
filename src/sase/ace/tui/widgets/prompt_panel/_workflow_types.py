"""Shared workflow detail display types."""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# Type alias: step_index -> list of embedded step marker dicts
EmbeddedMarkerMap = dict[int, list[dict[str, Any]]]

# Type alias: step_name -> list of embedded workflow metadata dicts
EmbeddedMetaMap = dict[str, list[dict[str, Any]]]

WorkflowJsonLoader = Callable[[Path], Any]


@dataclass(frozen=True)
class WorkflowDetailSnapshot:
    """Filesystem-backed workflow detail data for one render pass."""

    artifacts_path: Path | None
    workflow_state: dict[str, Any] | None
    inputs: dict[str, Any] | None
    meta_raw: dict[str, str] | None
    meta_fields: list[tuple[str, str]]
    steps: list[dict[str, Any]]
    error: str | None
    traceback: str | None
    prompt_content: str | None
    embedded_markers: EmbeddedMarkerMap
    embedded_meta: EmbeddedMetaMap
