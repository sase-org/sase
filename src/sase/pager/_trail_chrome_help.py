"""Renderers for the pager's scrollable "Trail & keys" help sheet."""

from __future__ import annotations

from dataclasses import dataclass

from rich.cells import cell_len
from rich.text import Text

from sase.pager._trail_chrome_band import join_left_right as _join_left_right
from sase.pager._trail_chrome_model import CURRENT_MARKER as _CURRENT_MARKER
from sase.pager._trail_chrome_model import CURRENT_STYLE as _CURRENT_STYLE
from sase.pager._trail_chrome_model import MUTED_STYLE as _MUTED_STYLE
from sase.pager._trail_chrome_model import PagerTrailSnapshot
from sase.pager._trail_chrome_model import SECONDARY_STYLE as _SECONDARY_STYLE
from sase.pager._trail_chrome_model import STATE_STYLES as _STATE_STYLES
from sase.pager._trail_chrome_text import fit_text as _fit_text
from sase.pager._trail_chrome_text import wrap_cells as _wrap_cells


@dataclass(frozen=True, slots=True)
class _PagerTrailHelpContent:
    """Rendered help-sheet content plus the current visit's line offset."""

    text: Text
    current_line: int


def build_pager_help_content(
    *,
    section_total: int,
    label_count: int = 0,
    trail_snapshot: PagerTrailSnapshot | None = None,
    width: int = 88,
) -> _PagerTrailHelpContent:
    """Build the scrollable Trail & keys sheet body."""

    width = max(12, int(width))
    content = Text(no_wrap=False, overflow="fold")
    current_line = 0
    has_trail = trail_snapshot is not None and trail_snapshot.visible

    if has_trail and trail_snapshot is not None:
        trail_text, current_relative_line = _complete_history_text(
            trail_snapshot,
            width=width,
        )
        current_line = current_relative_line
        content.append_text(trail_text)
        content.append("\n\n")
        content.append(_trail_semantics_note(width), style=_SECONDARY_STYLE)
        content.append("\n\n")
        content.append("Keys\n", style="bold")

    key_text = _key_guide_text(section_total=section_total, label_count=label_count)
    content.append_text(key_text)
    return _PagerTrailHelpContent(text=content, current_line=current_line)


def render_pager_help_header(
    *,
    trail_snapshot: PagerTrailSnapshot | None,
    width: int,
) -> Text:
    """Render the fixed help-sheet title/header row."""

    width = max(0, int(width))
    if width <= 0:
        return Text(no_wrap=True, overflow="crop")
    title = (
        "Trail & keys"
        if trail_snapshot is not None and trail_snapshot.visible
        else "SasePager keys"
    )
    left = Text(_fit_text(title, max(1, width)), style="bold")
    if trail_snapshot is None or not trail_snapshot.visible:
        return left
    right = Text(
        f"{trail_snapshot.position}/{trail_snapshot.total}", style="bold reverse"
    )
    joined = _join_left_right(left, right, width=width)
    if joined is not None:
        return joined
    return left


def render_pager_help_footer(*, width: int) -> Text:
    """Render the fixed help-sheet legend/footer row."""

    width = max(0, int(width))
    legend = "j/k scroll · ctrl+d/u page · g/G ends · q/? close"
    return Text(_fit_text(legend, width), style=_SECONDARY_STYLE, no_wrap=True)


def _complete_history_text(
    snapshot: PagerTrailSnapshot,
    *,
    width: int,
) -> tuple[Text, int]:
    text = Text()
    current_line = 0
    number_width = max(2, len(str(snapshot.total)))
    for index, entry in enumerate(snapshot.entries, start=1):
        if index > 1:
            text.append("\n")
            text.append("  │", style=_MUTED_STYLE)
            text.append("\n")
        if entry.state == "current":
            current_line = text.plain.count("\n")
            marker = _CURRENT_MARKER
            state_style = _CURRENT_STYLE
        else:
            marker = " "
            state_style = _STATE_STYLES[entry.state]

        state = entry.state
        prefix = f"{marker} {index:>{number_width}}  "
        state_width = cell_len(state)
        content_width = max(8, width - cell_len(prefix) - state_width - 2)
        first_label, *wrapped = _wrap_cells(entry.full_label, content_width)

        text.append(prefix, style=state_style if entry.state == "current" else "")
        text.append(f"{entry.icon} ", style=f"bold {entry.accent}")
        text.append(first_label, style=state_style)
        gap = max(width - cell_len(prefix) - 2 - cell_len(first_label) - state_width, 1)
        text.append(" " * gap)
        text.append(state, style=state_style or _SECONDARY_STYLE)

        indent = " " * (cell_len(prefix) + 2)
        for line in wrapped:
            text.append("\n")
            text.append(indent)
            text.append(line, style=state_style)

        secondary = entry.secondary_identity
        if secondary and secondary != entry.full_label:
            for line in _wrap_cells(secondary, content_width):
                text.append("\n")
                text.append(indent)
                text.append(line, style=_SECONDARY_STYLE)

    return text, current_line


def _trail_semantics_note(width: int) -> str:
    message = (
        "Positions count retained visits; ...N marks hidden visits; "
        f"{_CURRENT_MARKER} marks the current visit."
    )
    return "\n".join(_wrap_cells(message, width))


def _key_guide_text(*, section_total: int, label_count: int) -> Text:
    rows = list(_binding_rows(section_total=section_total, label_count=label_count))
    width = max(len(key) for key, _label in rows)
    text = Text()
    for index, (key, label) in enumerate(rows):
        if index:
            text.append("\n")
        text.append(key.rjust(width), style="bold")
        text.append("  ")
        text.append(label)
    return text


def _binding_rows(
    *,
    section_total: int,
    label_count: int,
) -> tuple[tuple[str, str], ...]:
    rows = [
        ("q, escape, ?", "Close this sheet"),
        ("j / k, down / up", "Scroll this sheet one line"),
        ("ctrl+d / ctrl+u", "Scroll this sheet half a page"),
        ("g / G", "Jump this sheet to top / bottom"),
        ("", ""),
        ("Pager keys", ""),
        ("q, escape", "Close the pager"),
        ("j / k, down / up", "Scroll one line"),
        ("ctrl+d / ctrl+u", "Scroll half a page"),
        ("g / G", "Jump to top / bottom"),
        ("; or :", "Jump to a line (1-N)"),
        ("backspace / ctrl+o", "Walk back"),
    ]
    insertion = len(rows)
    if section_total > 1:
        rows.insert(insertion, ("ctrl+n / ctrl+p", "Next / previous section"))
        insertion += 1
    if label_count:
        rows[insertion:insertion] = [
            ("0-9 / a-z / A-Z", "Follow a painted link"),
            ("y..., yy", "Copy a link's ref or path / this section"),
            ("E..., EE", "Edit a link in $EDITOR / this section"),
        ]
    rows.extend(
        [
            ("ctrl+i", "Walk forward"),
            ("r", "Refresh"),
            ("/", "Search forward"),
            ("n / N", "Next / previous match"),
            ("?", "Show trail and keys"),
        ]
    )
    return tuple((key, label) for key, label in rows if key or label)
