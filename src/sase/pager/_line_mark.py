"""Line or range mark for pager landing and ``;`` goto."""

from __future__ import annotations

from dataclasses import dataclass

_EN_DASH = "–"


@dataclass(frozen=True, slots=True)
class LineMark:
    """Inclusive 1-based line range within one composed section."""

    section_index: int
    start_line: int
    end_line: int

    def __post_init__(self) -> None:
        if self.end_line < self.start_line:
            object.__setattr__(self, "end_line", self.start_line)

    @property
    def emphasis_range(self) -> tuple[int, int]:
        return (self.start_line, self.end_line)

    @property
    def suffix(self) -> str:
        if self.start_line == self.end_line:
            return f":{self.start_line}"
        return f":{self.start_line}{_EN_DASH}{self.end_line}"


def reading_scroll_y(
    *,
    start_row: int,
    end_row: int,
    viewport_height: int,
    max_scroll_y: int,
) -> int:
    """Return the scroll offset that places *start_row* at a reading position.

    ``context = clamp(viewport_height // 4, 2, 8)`` lines sit above the start.
    When the marked range fits in the viewport but its last row would fall
    below it, the viewport is pulled down just far enough to keep the range
    on screen without lifting the start above one row of context.
    """
    viewport_height = max(int(viewport_height), 1)
    context = min(max(viewport_height // 4, 2), 8)
    y = start_row - context
    range_height = end_row - start_row + 1
    if range_height <= viewport_height and end_row > y + viewport_height - 1:
        y = max(end_row - viewport_height + 1, start_row - 1)
    return max(0, min(int(max_scroll_y), y))


__all__ = ["LineMark", "reading_scroll_y"]
