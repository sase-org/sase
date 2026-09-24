"""Shared TRACEBACK block for card-partitioned Main documents."""

from __future__ import annotations

from typing import Any

from rich.syntax import Syntax
from rich.text import Text

from ._agent_display_header import AgentHeader
from ._helpers import append_section_heading


def build_traceback_block(error_tb_syntax: Syntax | None) -> list[Any]:
    """Return the Rich-mode TRACEBACK block for the top of Reply/Output."""
    if error_tb_syntax is None:
        return []
    header = Text()
    header.append("\n")
    header.append("\u2500" * 50 + "\n", style="dim")
    header.append("\n")
    append_section_heading(header, "TRACEBACK", section_id="traceback")
    return [header, error_tb_syntax]


def append_traceback_hint(
    target: AgentHeader,
    traceback: str,
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
) -> int:
    """Append the Text-mode TRACEBACK block to a hint document target."""
    from ._hint_caps import append_bounded_text_with_file_hints

    target.append("\n")
    target.append("\u2500" * 50 + "\n", style="dim")
    target.append("\n")
    append_section_heading(target, "TRACEBACK", section_id="traceback")
    return append_bounded_text_with_file_hints(
        target,
        traceback + "\n",
        hint_counter,
        hint_mappings,
        workspace_dir,
    )


__all__ = ["append_traceback_hint", "build_traceback_block"]
