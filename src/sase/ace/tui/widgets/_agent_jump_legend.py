"""Width-responsive jump legend renderable for the Agents tab jump panel."""

from __future__ import annotations

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text

from sase.agent.status_buckets import AGENT_STATUS_BUCKET_GLYPHS

from ._agent_list_styling import _AGENT_NAME_ANNOTATION_STYLE
from .prompt_panel._member_roster import (
    MemberJumpMap,
    member_status_style,
)

MIN_LABEL_CELLS = 10

_NEUTRAL_ACCENT = "#8787AF"
_JUMP_TITLE_STYLE = "bold #D7D7FF"
_DIM_STYLE = "dim"
_DIM_ITALIC_STYLE = "dim italic"
_NAME_STYLE = _AGENT_NAME_ANNOTATION_STYLE
_DISMISSED_PREFIX_STYLE = "dim #FFAF00"
_LABEL_BUDGETS: tuple[int, ...] = (32, 24, 18, 14, 12, 10)
_NARROW_MODES = ("collapsed", "expanded")


def jump_legend_border_accent(jump_map: MemberJumpMap) -> str:
    """Return the first section accent, or a neutral fallback."""
    if jump_map.sections:
        return jump_map.sections[0].accent
    return _NEUTRAL_ACCENT


def jump_legend_title(jump_map: MemberJumpMap, *, prefix: str | None = None) -> Text:
    """Return the color-legend border title for a jump map."""
    title = Text()
    title.append("JUMP", style=_JUMP_TITLE_STYLE)
    if prefix is not None:
        title.append(" · ", style=_DIM_STYLE)
        title.append(f"{prefix}▁", style=_JUMP_TITLE_STYLE)
        return title
    offset = 0
    for section in jump_map.sections:
        targets = jump_map.targets[offset : offset + section.numbered_count]
        offset += section.numbered_count
        if not targets:
            continue
        first = targets[0].number
        last = targets[-1].number
        number_range = first if first == last else f"{first}–{last}"
        title.append(" · ", style=_DIM_STYLE)
        title.append(section.title, style=f"bold {section.accent}")
        title.append(f" {number_range}", style=_DIM_STYLE)
    return title


def _truncate_middle(label: str, budget: int) -> str:
    """Truncate a label with a middle ellipsis, keeping ~40% head, 60% tail."""
    if cell_len(label) <= budget:
        return label
    if budget <= 1:
        return "…"
    target = budget - 1
    head_target = int(target * 0.4)
    tail_target = target - head_target
    head = ""
    width = 0
    for char in label:
        char_width = cell_len(char)
        if width + char_width > head_target:
            break
        head += char
        width += char_width
    tail_chars: list[str] = []
    width = 0
    for char in reversed(label):
        char_width = cell_len(char)
        if width + char_width > tail_target:
            break
        tail_chars.append(char)
        width += char_width
    return f"{head}…{''.join(reversed(tail_chars))}"


def _target_accent(jump_map: MemberJumpMap, index: int) -> str:
    """Return the accent of the section owning target ``index``."""
    offset = 0
    for section in jump_map.sections:
        if offset <= index < offset + section.numbered_count:
            return section.accent
        offset += section.numbered_count
    return _NEUTRAL_ACCENT


def _build_cell(
    number: str,
    accent: str,
    label: str,
    *,
    bucket: str | None,
    dismissed: bool,
    show_revive: bool,
) -> Text:
    """Build one legend cell matching the roster row styling."""
    cell = Text()
    if dismissed:
        cell.append("⊘ ", style=_DISMISSED_PREFIX_STYLE)
    cell.append(number, style=f"bold black on {accent}")
    cell.append(" ")
    if dismissed:
        cell.append(label, style=f"dim {_NAME_STYLE}")
    else:
        cell.append(label, style=_NAME_STYLE)
    if bucket is not None:
        glyph = AGENT_STATUS_BUCKET_GLYPHS.get(bucket, "")
        if glyph:
            cell.append(" ")
            cell.append(glyph, style=member_status_style(bucket))
    if show_revive and dismissed:
        cell.append(" revive", style=_DIM_STYLE)
    return cell


def _column_widths(cells: list[Text], columns: int) -> list[int]:
    """Return the max cell width per column for a row-major grid."""
    widths = [0] * columns
    for index, cell in enumerate(cells):
        column = index % columns
        width = cell_len(cell.plain)
        if width > widths[column]:
            widths[column] = width
    return widths


def _grid_fits(cells: list[Text], columns: int, width: int) -> bool:
    """Return whether a row-major grid of ``cells`` fits ``width``."""
    if columns <= 0:
        return False
    col_widths = _column_widths(cells, columns)
    return sum(col_widths) + 2 * (columns - 1) <= width


def _render_grid(cells: list[Text], columns: int) -> list[Text]:
    """Render row-major, column-aligned grid lines."""
    if not cells:
        return []
    columns = max(1, min(columns, len(cells)))
    col_widths = _column_widths(cells, columns)
    lines: list[Text] = []
    for start in range(0, len(cells), columns):
        row = cells[start : start + columns]
        line = Text()
        for column, cell in enumerate(row):
            if column > 0:
                line.append("  ")
            line.append_text(cell)
            if column < len(row) - 1:
                padding = col_widths[column] - cell_len(cell.plain)
                if padding > 0:
                    line.append(" " * padding)
        lines.append(line)
    return lines


class JumpLegendRenderable:
    """Width-responsive legend grid over a published jump map."""

    def __init__(self, jump_map: MemberJumpMap, *, mode: str = "collapsed") -> None:
        self._jump_map = jump_map
        self._mode = mode
        self._layout_cache: dict[int, list[Text]] = {}

    @property
    def plain(self) -> str:
        """Return a stable digest view over targets, sections, and mode."""
        parts = [self._mode]
        for target in self._jump_map.targets:
            parts.append(
                f"{target.number}={target.label}@{target.status_bucket}/{target.role}"
            )
        for section in self._jump_map.sections:
            parts.append(
                f"{section.title}:{section.accent}"
                f":{section.numbered_count}:{section.hidden_count}"
                f":{section.hidden_hint}"
            )
        return "|".join(parts)

    @property
    def spans(self) -> list[object]:
        """Return an empty span list so digests stay width-independent."""
        return []

    def __rich_console__(
        self,
        _console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        width = max(1, options.max_width)
        yield from self._lines_for_width(width)

    def _lines_for_width(self, width: int) -> list[Text]:
        """Return cached legend lines packed for ``width``."""
        cached = self._layout_cache.get(width)
        if cached is not None:
            return cached
        if self._mode not in _NARROW_MODES:
            lines = self._narrowed_lines(width, self._mode)
        elif self._mode == "expanded":
            lines = self._expanded_lines(width)
        else:
            lines = self._collapsed_lines(width)
        self._layout_cache[width] = lines
        return lines

    def _narrowed_lines(self, width: int, prefix: str) -> list[Text]:
        """Render full-label targets whose number starts with ``prefix``."""
        jump_map = self._jump_map
        matches = [
            (index, target)
            for index, target in enumerate(jump_map.targets)
            if target.number.startswith(prefix)
        ]
        if not matches:
            return [Text(f"no targets start with {prefix}", style=_DIM_STYLE)]
        cells = [
            _build_cell(
                target.number,
                _target_accent(jump_map, index),
                target.label,
                bucket=target.status_bucket,
                dismissed=target.role == "dismissed",
                show_revive=True,
            )
            for index, target in matches
        ]
        cells = _clamp_cells_to_width(cells, width)
        columns = _largest_fitting_columns(cells, width)
        return _render_grid(cells, columns)

    def _expanded_lines(self, width: int) -> list[Text]:
        """Render every target with full labels, headings, and tails."""
        jump_map = self._jump_map
        show_headings = len(jump_map.sections) >= 2
        lines: list[Text] = []
        if not jump_map.sections:
            if not jump_map.targets:
                return []
            cells = [
                _build_cell(
                    target.number,
                    _NEUTRAL_ACCENT,
                    target.label,
                    bucket=target.status_bucket,
                    dismissed=target.role == "dismissed",
                    show_revive=True,
                )
                for target in jump_map.targets
            ]
            cells = _clamp_cells_to_width(cells, width)
            return _render_grid(cells, _largest_fitting_columns(cells, width))
        offset = 0
        for section in jump_map.sections:
            targets = jump_map.targets[offset : offset + section.numbered_count]
            offset += section.numbered_count
            if show_headings and (targets or section.hidden_hint):
                heading = Text()
                heading.append("❖ ", style=f"bold {section.accent}")
                heading.append(section.title, style=f"bold {section.accent}")
                heading.append(f" · {section.numbered_count}", style=_DIM_STYLE)
                lines.append(heading)
            if targets:
                cells = [
                    _build_cell(
                        target.number,
                        section.accent,
                        target.label,
                        bucket=target.status_bucket,
                        dismissed=target.role == "dismissed",
                        show_revive=True,
                    )
                    for target in targets
                ]
                cells = _clamp_cells_to_width(cells, width)
                lines.extend(
                    _render_grid(cells, _largest_fitting_columns(cells, width))
                )
            if section.hidden_hint:
                for hint_line in section.hidden_hint.split("\n"):
                    if hint_line:
                        lines.append(Text(hint_line, style=_DIM_ITALIC_STYLE))
        return lines

    def _collapsed_lines(self, width: int) -> list[Text]:
        """Render at most two packed rows with uniqueness-safe budgets."""
        jump_map = self._jump_map
        targets = jump_map.targets
        count = len(targets)
        if count == 0:
            return []
        longest = max(cell_len(target.label) for target in targets)
        candidates: list[int] = []
        seen: set[int] = set()
        budgets = (longest, *_LABEL_BUDGETS)
        for budget in budgets:
            if budget > longest or budget in seen:
                continue
            seen.add(budget)
            if budget != longest and budget < MIN_LABEL_CELLS:
                continue
            truncated = [_truncate_middle(target.label, budget) for target in targets]
            by_truncated: dict[str, set[str]] = {}
            clash = False
            for target, short in zip(targets, truncated, strict=True):
                fulls = by_truncated.setdefault(short, set())
                fulls.add(target.label)
                if len(fulls) > 1:
                    clash = True
                    break
            if clash:
                continue
            candidates.append(budget)
        best: tuple[int, int, int, list[str]] | None = None
        for budget in candidates:
            labels = [_truncate_middle(target.label, budget) for target in targets]
            columns = _largest_collapsed_columns(targets, labels, jump_map, width)
            if columns is None:
                continue
            shown = _collapsed_shown_count(count, columns)
            if (
                best is None
                or shown > best[0]
                or (shown == best[0] and budget > best[1])
            ):
                best = (shown, budget, columns, labels)
        if best is None:
            target = targets[0]
            cell = _build_cell(
                target.number,
                _target_accent(jump_map, 0),
                _truncate_middle(target.label, max(1, width - 4)),
                bucket=target.status_bucket,
                dismissed=target.role == "dismissed",
                show_revive=False,
            )
            clamped = Text()
            plain = cell.plain
            current: list[str] = []
            used = 0
            for char in plain:
                char_width = cell_len(char)
                if used + char_width > width:
                    break
                current.append(char)
                used += char_width
            clamped.append("".join(current))
            clamped.spans.extend(cell.spans[: len(clamped.plain)])
            return [clamped]
        _shown, budget, columns, labels = best
        slots = min(count, 2 * columns)
        overflow = count > 2 * columns
        cells: list[Text] = []
        shown_targets = slots - 1 if overflow else slots
        for index in range(shown_targets):
            target = targets[index]
            cells.append(
                _build_cell(
                    target.number,
                    _target_accent(jump_map, index),
                    labels[index],
                    bucket=target.status_bucket,
                    dismissed=target.role == "dismissed",
                    show_revive=False,
                )
            )
        if overflow:
            remaining = count - shown_targets
            cells.append(Text(f"+{remaining}", style=_DIM_STYLE))
        return _render_grid(cells, columns)


def _collapsed_shown_count(count: int, columns: int) -> int:
    """Return how many targets a collapsed grid shows at ``columns``."""
    slots = min(count, 2 * columns)
    if count > 2 * columns:
        return slots - 1
    return slots


def _largest_collapsed_columns(
    targets: tuple[object, ...],
    labels: list[str],
    jump_map: MemberJumpMap,
    width: int,
) -> int | None:
    """Return the largest collapsed column count fitting ``width``."""
    count = len(targets)
    max_columns = min(count, max(1, width // 8))
    typed_targets = jump_map.targets
    for columns in range(max_columns, 0, -1):
        slots = min(count, 2 * columns)
        overflow = count > 2 * columns
        shown = slots - 1 if overflow else slots
        cells: list[Text] = []
        for index in range(shown):
            target = typed_targets[index]
            cells.append(
                _build_cell(
                    target.number,
                    _target_accent(jump_map, index),
                    labels[index],
                    bucket=target.status_bucket,
                    dismissed=target.role == "dismissed",
                    show_revive=False,
                )
            )
        if overflow:
            cells.append(Text(f"+{count - shown}", style=_DIM_STYLE))
        if _grid_fits(cells, columns, width):
            return columns
    return None


def _largest_fitting_columns(cells: list[Text], width: int) -> int:
    """Return the largest column count whose grid fits ``width``."""
    if not cells:
        return 1
    max_columns = min(len(cells), max(1, width // 8))
    for columns in range(max_columns, 0, -1):
        if _grid_fits(cells, columns, width):
            return columns
    return 1


def _clamp_cells_to_width(cells: list[Text], width: int) -> list[Text]:
    """Clamp full-label cells so a single column fits ``width``."""
    if not cells or _grid_fits(cells, 1, width):
        return cells
    clamped: list[Text] = []
    for cell in cells:
        plain = cell.plain
        if cell_len(plain) <= width:
            clamped.append(cell)
            continue
        current: list[str] = []
        used = 0
        for char in plain:
            char_width = cell_len(char)
            if used + char_width > width:
                break
            current.append(char)
            used += char_width
        replacement = Text("".join(current))
        replacement.spans.extend(cell.spans[: len(replacement.plain)])
        clamped.append(replacement)
    return clamped


__all__ = [
    "MIN_LABEL_CELLS",
    "JumpLegendRenderable",
    "jump_legend_border_accent",
    "jump_legend_title",
]
