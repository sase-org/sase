"""Wire-format helpers shared by the ACE prompt visual catalog fixtures.

The glossary and repo-mention catalogs both hand the prompt text area compiled
objects that scan text into span wires and look a span up by cursor position.
Only the scan differs, so the lookup and the position/offset math live here.
"""

from __future__ import annotations

import abc
from typing import Any

from sase.xprompt._literal_zones import code_literal_ranges


class VisualCompiledSpans(abc.ABC):
    """Base for compiled catalogs that scan prompt text into span wires."""

    @abc.abstractmethod
    def scan(self, text: str) -> list[dict[str, Any]]: ...

    def lookup(
        self,
        text: str,
        line: int,
        character: int,
    ) -> dict[str, Any] | None:
        for span in self.scan(text):
            editor_range = span["range"]
            start = editor_range["start"]
            end = editor_range["end"]
            if (
                start["line"] <= line <= end["line"]
                and (line > start["line"] or character >= start["character"])
                and (line < end["line"] or character < end["character"])
            ):
                return span
        return None


def visual_literal_ranges(text: str) -> list[tuple[int, int]]:
    """Return code-literal ranges, skipping the scan when there are no fences."""
    return code_literal_ranges(text) if "`" in text or "~~~" in text else []


def visual_editor_position(text: str, offset: int) -> dict[str, int]:
    prefix = text[:offset]
    line = prefix.count("\n")
    line_start = prefix.rfind("\n") + 1
    return {
        "line": line,
        "character": sum(
            2 if ord(char) > 0xFFFF else 1 for char in text[line_start:offset]
        ),
    }


def visual_editor_range(text: str, start: int, end: int) -> dict[str, Any]:
    return {
        "start": visual_editor_position(text, start),
        "end": visual_editor_position(text, end),
    }


def visual_span_segment(text: str, start: int, end: int) -> dict[str, Any]:
    return {
        "byte_start": len(text[:start].encode("utf-8")),
        "byte_end": len(text[:end].encode("utf-8")),
        "range": visual_editor_range(text, start, end),
    }
