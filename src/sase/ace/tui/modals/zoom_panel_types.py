"""Shared types for the Agents-tab zoom panel modal."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from rich.console import RenderableType

from ..widgets.tools_panel import ToolDetailLevel


class ZoomPanelTarget(StrEnum):
    """Panel targets supported by the Agents-tab zoom modal."""

    METADATA = "metadata"
    FILE = "file"
    TOOLS = "tools"


@dataclass(frozen=True)
class ZoomPanelSeed:
    """Lightweight state copied from the base Agents detail panels."""

    metadata_renderable: RenderableType | None = None
    file_renderable: RenderableType | None = None
    tools_renderable: RenderableType | None = None
    metadata_subtitle: Any = None
    file_subtitle: Any = None
    tools_subtitle: Any = None
    file_list: tuple[str, ...] = ()
    file_index: int = 0
    has_file_content: bool = False
    has_tools_content: bool = False
    tools_detail_level: ToolDetailLevel = ToolDetailLevel.COMPACT
    attempt_view_mode: str = "merged"
    attempt_number: int | None = None


_TARGET_ORDER: tuple[ZoomPanelTarget, ...] = (
    ZoomPanelTarget.METADATA,
    ZoomPanelTarget.FILE,
    ZoomPanelTarget.TOOLS,
)


__all__ = ["ZoomPanelSeed", "ZoomPanelTarget"]
