"""A deterministic 2x4-dot-per-cell braille drawing canvas."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

_DOT_MASKS = (
    (0x01, 0x08),
    (0x02, 0x10),
    (0x04, 0x20),
    (0x40, 0x80),
)


@dataclass(slots=True)
class _Cell:
    mask: int = 0
    style: str | None = None


class BrailleCanvas:
    """A small clipped canvas whose cells render as Unicode braille glyphs."""

    def __init__(self, width: int, height: int) -> None:
        if width < 1 or height < 1:
            raise ValueError("braille canvas dimensions must be positive")
        self.width = width
        self.height = height
        self._cells = [[_Cell() for _ in range(width)] for _ in range(height)]

    @property
    def dot_width(self) -> int:
        """Width of the high-resolution dot coordinate system."""

        return self.width * 2

    @property
    def dot_height(self) -> int:
        """Height of the high-resolution dot coordinate system."""

        return self.height * 4

    def set(self, x: int, y: int, *, style: str | None = None) -> None:
        """Set one dot; coordinates outside the canvas are ignored."""

        if x < 0 or y < 0 or x >= self.dot_width or y >= self.dot_height:
            return
        cell = self._cells[y // 4][x // 2]
        cell.mask |= _DOT_MASKS[y % 4][x % 2]
        # The first series to touch an overlapping cell owns its style.  This
        # avoids order-dependent recoloring of an already-drawn line.
        if cell.style is None and style:
            cell.style = style

    def draw_line(
        self,
        start: tuple[int, int],
        end: tuple[int, int],
        *,
        style: str | None = None,
    ) -> None:
        """Draw a Bresenham line between two already-scaled points."""

        x0 = min(self.dot_width - 1, max(0, start[0]))
        y0 = min(self.dot_height - 1, max(0, start[1]))
        x1 = min(self.dot_width - 1, max(0, end[0]))
        y1 = min(self.dot_height - 1, max(0, end[1]))
        delta_x = abs(x1 - x0)
        step_x = 1 if x0 < x1 else -1
        delta_y = -abs(y1 - y0)
        step_y = 1 if y0 < y1 else -1
        error = delta_x + delta_y

        while True:
            self.set(x0, y0, style=style)
            if x0 == x1 and y0 == y1:
                break
            doubled = 2 * error
            if doubled >= delta_y:
                error += delta_y
                x0 += step_x
            if doubled <= delta_x:
                error += delta_x
                y0 += step_y

    def draw_polyline(
        self, points: list[tuple[int, int]], *, style: str | None = None
    ) -> None:
        """Draw connected line segments, including a lone point."""

        if not points:
            return
        if len(points) == 1:
            self.set(*points[0], style=style)
            return
        for start, end in zip(points, points[1:], strict=False):
            self.draw_line(start, end, style=style)

    def rows(self) -> list[Text]:
        """Return one styled ``Text`` value per canvas row."""

        rendered: list[Text] = []
        for cells in self._cells:
            row = Text(no_wrap=True)
            for cell in cells:
                glyph = chr(0x2800 + cell.mask) if cell.mask else " "
                row.append(glyph, style=cell.style)
            rendered.append(row)
        return rendered

    def render(self) -> Text:
        """Return the complete styled canvas as a single Rich ``Text``."""

        output = Text(no_wrap=True)
        rows = self.rows()
        for index, row in enumerate(rows):
            output.append_text(row)
            if index < len(rows) - 1:
                output.append("\n")
        return output
