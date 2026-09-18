"""Shared types for the Agents-tab zoom panel modal."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from rich.console import RenderableType

from ..widgets.llm_calls_panel import ToolDetailLevel


class ZoomPanelTarget(StrEnum):
    """Panel targets supported by the Agents-tab zoom modal."""

    METADATA = "metadata"
    FILE = "file"
    LLM_CALLS = "llm_calls"


@dataclass(frozen=True)
class ZoomPanelSeed:
    """Lightweight state copied from the base Agents detail panels."""

    metadata_renderable: RenderableType | None = None
    file_renderable: RenderableType | None = None
    llm_calls_renderable: RenderableType | None = None
    metadata_subtitle: Any = None
    file_subtitle: Any = None
    llm_calls_subtitle: Any = None
    file_list: tuple[str, ...] = ()
    file_index: int = 0
    has_file_content: bool = False
    has_llm_calls_content: bool = False
    llm_calls_detail_level: ToolDetailLevel = ToolDetailLevel.COMPACT
    attempt_view_mode: str = "merged"
    attempt_number: int | None = None


_TARGET_ORDER: tuple[ZoomPanelTarget, ...] = (
    ZoomPanelTarget.METADATA,
    ZoomPanelTarget.FILE,
    ZoomPanelTarget.LLM_CALLS,
)


__all__ = ["ZoomPanelSeed", "ZoomPanelTarget"]
