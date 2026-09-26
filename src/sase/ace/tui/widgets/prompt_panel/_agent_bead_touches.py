"""Compact ARTIFACTS ``Beads`` row renderer for the prompt-panel header."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.text import Text

from sase.ace.tui.bead_hint_targets import bead_hint_target as _bead_hint_target
from sase.ace.tui.bead_touches import BeadTouchEntry
from sase.core.bead_touch_index_facade import BeadNotePreview, BeadTouchClose
from sase.bead.touch_glyphs import touch_glyph

from ._agent_context_common import (
    COLOR_BEAD_CLOSED_CAP,
    COLOR_BEAD_CLOSED_GLYPH,
    COLOR_BEAD_CLOSED_MUTED_CAP,
    COLOR_BEAD_CLOSED_MUTED_GLYPH,
    COLOR_BEAD_CLOSED_MUTED_PILL,
    COLOR_BEAD_CLOSED_PILL,
    COLOR_BEAD_CLOSED_STALE,
    COLOR_BEAD_CREATED_CAP,
    COLOR_BEAD_CREATED_CHIP,
    COLOR_BEAD_CREATED_PILL,
    COLOR_BEAD_PRIMARY,
    COLOR_BEAD_REOPENED_SINCE,
    COLOR_BEAD_RESOLUTION,
    COLOR_BEAD_SUBHEADER,
    COLOR_SUMMARY,
    COLOR_TRUNCATION,
    REASON_LINE_CELL_LIMIT,
    append_context_reason,
    append_lane_row,
    format_local_hhmm,
)
from ._agent_display_state import HeaderHintState
from ._helpers import wrap_text_by_cells

MAX_VISIBLE_BEADS = 5
BEAD_TOUCHES_SECTION_ID = "artifacts-beads"
_SUBSECTION_ROW_PREFIX = "  "
_MAX_NOTE_TEXT_LINES = 3

__all__ = [
    "BEAD_TOUCHES_SECTION_ID",
    "MAX_VISIBLE_BEADS",
    "ResponsiveBeadTouchesSection",
    "append_agent_bead_touch_rows",
    "bead_touches_section_for",
]

CLOSED_PILL_TEXT = "CLOSED"
CLOSED_PILL_LEFT = "▐"
CLOSED_PILL_RIGHT = "▌"
CREATED_PILL_TEXT = "CREATED"
CREATED_PILL_LEFT = "▐"
CREATED_PILL_RIGHT = "▌"
REOPENED_SINCE_CHIP = "reopened since"
ASSIGNED_CHIP = "assigned"
CREATED_CHIP = "created"


def _standing_close(entry: BeadTouchEntry) -> BeadTouchClose | None:
    """Return the standing agent close, or ``None`` when there is none."""
    close = entry.agent_close
    if close is not None and close.standing:
        return close
    return None


def _is_created(entry: BeadTouchEntry) -> bool:
    """Return whether the indexed verbs credit this agent with creation.

    The ``created`` verb comes only from the core reducer's creator row;
    assignment (``own``) never implies it.
    """
    return "created" in entry.verbs


def _is_assigned_only(entry: BeadTouchEntry) -> bool:
    """Return whether the row is an assignment with no creator credit."""
    return bool(entry.own) and not _is_created(entry)


def _close_resolution(entry: BeadTouchEntry) -> str:
    """Return the normalized close resolution, ``done`` when absent."""
    close = entry.agent_close
    if close is None:
        return "done"
    resolution = close.resolution if isinstance(close.resolution, str) else ""
    resolution = resolution.strip()
    return resolution or "done"


def _bead_touch_glyph_style(entry: BeadTouchEntry) -> str:
    """Return the glyph style, green/grey for standing closes."""
    if _standing_close(entry) is not None:
        if _close_resolution(entry) == "done":
            return COLOR_BEAD_CLOSED_GLYPH
        return COLOR_BEAD_CLOSED_MUTED_GLYPH
    return COLOR_BEAD_SUBHEADER


def _closed_pill_styles(entry: BeadTouchEntry) -> tuple[str, str]:
    """Return ``(cap_style, pill_style)`` for a standing close row."""
    if _close_resolution(entry) == "done":
        return (COLOR_BEAD_CLOSED_CAP, COLOR_BEAD_CLOSED_PILL)
    return (COLOR_BEAD_CLOSED_MUTED_CAP, COLOR_BEAD_CLOSED_MUTED_PILL)


def _styled_bead_verb_chips(entry: BeadTouchEntry) -> list[tuple[str, str]]:
    """Return ``(chip, style)`` pairs with the closed/created rewrite applied.

    Standing closes drop the plain ``closed`` chip because the pill replaces
    it; a non-``done`` resolution adds its raw resolution chip, and a
    non-standing close keeps a struck ``closed`` followed by
    ``reopened since``. A non-closed created row drops the plain ``created``
    chip because the amber ``▐CREATED▌`` pill replaces it; a standing close
    on a created row keeps the ``▐CLOSED▌`` pill priority and adds a
    compact ``created`` chip instead. Assignment-only rows render a calm
    ``assigned`` chip; created rows never claim assignment.
    """
    created = _is_created(entry)
    assigned_only = _is_assigned_only(entry)
    close = entry.agent_close
    if close is None:
        chips: list[tuple[str, str]] = []
        if assigned_only:
            chips.append((ASSIGNED_CHIP, COLOR_SUMMARY))
        for verb, count in entry.verbs.items():
            if verb in ("read", "viewed"):
                continue
            if verb == "created":
                # The CREATED pill carries this; avoid doubling it as a chip.
                continue
            chips.append((_chip(verb, count), COLOR_SUMMARY))
        if "read" in entry.verbs:
            chips.append((_chip("read", entry.verbs["read"]), COLOR_SUMMARY))
        if "viewed" in entry.verbs:
            chips.append((_chip("viewed", entry.verbs["viewed"]), COLOR_SUMMARY))
        return chips
    styled: list[tuple[str, str]] = []
    if assigned_only:
        styled.append((ASSIGNED_CHIP, COLOR_SUMMARY))
    if close.standing:
        if _close_resolution(entry) != "done":
            styled.append((_close_resolution(entry), COLOR_BEAD_RESOLUTION))
        if created:
            styled.append((CREATED_CHIP, COLOR_BEAD_CREATED_CHIP))
        for verb, count in entry.verbs.items():
            if verb in ("closed", "created", "read", "viewed"):
                continue
            styled.append((_chip(verb, count), COLOR_SUMMARY))
    else:
        for verb, count in entry.verbs.items():
            if verb in ("read", "viewed"):
                continue
            if verb == "closed":
                styled.append((_chip(verb, count), COLOR_BEAD_CLOSED_STALE))
                styled.append((REOPENED_SINCE_CHIP, COLOR_BEAD_REOPENED_SINCE))
                continue
            if verb == "created":
                styled.append((_chip(verb, count), COLOR_BEAD_CREATED_CHIP))
                continue
            styled.append((_chip(verb, count), COLOR_SUMMARY))
    if "read" in entry.verbs:
        styled.append((_chip("read", entry.verbs["read"]), COLOR_SUMMARY))
    if "viewed" in entry.verbs:
        styled.append((_chip("viewed", entry.verbs["viewed"]), COLOR_SUMMARY))
    return styled


def _standing_close_reason(entry: BeadTouchEntry) -> str:
    """Return the ``↳`` line for a standing close with a reason, else ````."""
    close = _standing_close(entry)
    if close is None:
        return ""
    reason = close.reason.strip() if isinstance(close.reason, str) else ""
    if not reason:
        return ""
    resolution = _close_resolution(entry)
    if resolution == "done":
        return f"closed: {reason}"
    return f"{resolution}: {reason}"


def _visible_bead_entries(
    entries: tuple[BeadTouchEntry, ...] | Sequence[BeadTouchEntry],
) -> tuple[BeadTouchEntry, ...]:
    """Return the rows that claim the visible slots, newest-first.

    Standing closes claim slots first (newest first, up to
    ``MAX_VISIBLE_BEADS``); the remaining slots fill by rank. The chosen rows
    keep the original newest-first order so hint numbers and rows stay
    aligned.
    """
    ordered = tuple(entries)
    if len(ordered) <= MAX_VISIBLE_BEADS:
        return ordered
    picked: list[BeadTouchEntry] = []
    picked_ids: set[int] = set()
    for item in ordered:
        if len(picked) >= MAX_VISIBLE_BEADS:
            break
        if _standing_close(item) is not None:
            picked.append(item)
            picked_ids.add(id(item))
    if len(picked) < MAX_VISIBLE_BEADS:
        for item in ordered:
            if id(item) in picked_ids:
                continue
            picked.append(item)
            picked_ids.add(id(item))
            if len(picked) >= MAX_VISIBLE_BEADS:
                break
    order = {id(item): index for index, item in enumerate(ordered)}
    picked.sort(key=lambda item: order[id(item)])
    return tuple(picked)


def _bead_touch_glyph(entry: BeadTouchEntry) -> str:
    """Return the row's single strongest verb glyph via the shared vocabulary."""
    return touch_glyph(entry.verbs)


def _chip(verb: str, count: int) -> str:
    if count > 1:
        return f"{verb} ×{count}"
    return verb


_MIN_NOTE_CONTENT_CELLS = 24


def _safe_note_text(value: str) -> str:
    """Return display data with whitespace normalized and controls removed."""
    without_controls = "".join(
        " " if character.isspace() else character
        for character in value
        if ord(character) >= 32 and ord(character) != 127
    )
    return " ".join(without_controls.split())


def _append_note_line(text: Text, *, indent: int, content: str, style: str) -> None:
    text.append(" " * indent + "│ ", style=COLOR_BEAD_SUBHEADER)
    text.append(content + "\n", style=style)


def _append_bead_note_preview(
    text: Text,
    *,
    preview: BeadNotePreview,
    current_note_count: int,
    indent: int,
    role_label: str | None = None,
    line_cell_limit: int = REASON_LINE_CELL_LIMIT,
) -> None:
    """Render one bounded, attributed note block beneath its bead row.

    This is intentionally a pure Text helper: the loader has already read the
    cached touch index off the event loop, and rendering performs no bead
    lookup.  The note text is data, never Rich markup, and its display limit
    is independent from the cache's Unicode-safe prefix limit. Wrapping uses
    the available Context-card width so at most three physical body lines
    appear in spread, paged, narrow, and split layouts.
    """
    body = _safe_note_text(preview.text)
    if not body:
        return
    author = _safe_note_text(preview.author)
    if not author:
        return
    metadata = f"{format_local_hhmm(preview.timestamp)} · {author}"
    role = _safe_note_text(role_label or "")
    if role:
        metadata += f" · {role}"
    if preview.edited_at:
        metadata += " · edited"

    # In a narrow Context card the lane-aligned indent would squeeze the note
    # into a sliver, so give up indent before readable width.
    gutter_cells = cell_len("│ ")
    indent = max(
        0,
        min(indent, line_cell_limit - gutter_cells - _MIN_NOTE_CONTENT_CELLS),
    )
    available = max(1, line_cell_limit - indent - gutter_cells)
    for line in wrap_text_by_cells(metadata, available):
        _append_note_line(text, indent=indent, content=line, style=COLOR_SUMMARY)

    body_lines = wrap_text_by_cells(body, available)
    for line in body_lines[:_MAX_NOTE_TEXT_LINES]:
        _append_note_line(text, indent=indent, content=line, style="")

    overflow_needed = len(body_lines) > _MAX_NOTE_TEXT_LINES or preview.truncated
    if overflow_needed:
        overflow = "… full note in bead detail"
        for line in wrap_text_by_cells(overflow, available):
            _append_note_line(
                text,
                indent=indent,
                content=line,
                style=COLOR_TRUNCATION,
            )
    earlier = max(current_note_count - 1, 0)
    if earlier:
        noun = "note" if earlier == 1 else "notes"
        earlier_line = f"+{earlier} earlier {noun} in bead detail"
        for line in wrap_text_by_cells(earlier_line, available):
            _append_note_line(
                text,
                indent=indent,
                content=line,
                style=COLOR_TRUNCATION,
            )


def _bead_touch_hint_labels(
    entries: tuple[BeadTouchEntry, ...],
    hint_state: HeaderHintState | None,
) -> tuple[Text | None, ...]:
    """Assign numbered bead hints once so logical and card renders stay aligned."""
    labels: list[Text | None] = []
    for item in _visible_bead_entries(entries):
        label: Text | None = None
        if hint_state is not None:
            target = _bead_hint_target(item.bead_id)
            if target is not None:
                hint_number = hint_state.hint_counter
                hint_state.hint_mappings[hint_number] = target
                hint_state.hint_counter += 1
                label = Text(f"[{hint_number}] ", style="bold #FFFF00")
        labels.append(label)
    return tuple(labels)


def _copied_hint_label(hint_label: Text | None) -> Text | None:
    return hint_label.copy() if hint_label is not None else None


def _bead_touch_reason_lines(entry: BeadTouchEntry) -> list[str]:
    """Return the labeled ``↳`` lines for one bead row, in render order.

    Title first (when available), then the filing reason as ``why: …``
    for created rows, then the standing-close reason and the newest
    audited read reason with explicit labels. Filing, close, and read
    reasons never replace the title. All text is sanitized so control
    characters cannot break the card; wrapping happens at render time.
    """
    lines: list[str] = []
    title = _safe_note_text(entry.title)
    if title:
        lines.append(title)
    if _is_created(entry):
        reason = _safe_note_text(entry.creation_reason)
        if reason:
            lines.append(f"why: {reason}")
            if entry.creation_reason_truncated:
                lines.append("… full reason in bead detail")
    close_reason = _safe_note_text(_standing_close_reason(entry))
    if close_reason:
        lines.append(close_reason)
    if entry.read_reasons:
        first = _safe_note_text(entry.read_reasons[0])
        if first:
            lines.append(f"read: {first}")
    return lines


def append_agent_bead_touch_rows(
    text: Text,
    *,
    entries: tuple[BeadTouchEntry, ...],
    hint_state: HeaderHintState | None = None,
    hint_labels: Sequence[Text | None] | None = None,
    line_cell_limit: int = REASON_LINE_CELL_LIMIT,
) -> None:
    """Append newest-first bead rows under an ARTIFACTS ``Beads:`` header.

    The ARTIFACTS lane owns sub-section ordering and the summary counts;
    this helper only paints the compact rows, reasons, hints, and overflow
    footer. The bead id is never truncated. A created row shows a bounded
    title line plus a labeled ``why:`` filing-reason line; every row keeps
    its title line when available while read and close reasons keep
    explicit labels instead of replacing the title. All ``↳`` lines wrap
    via ``append_context_reason``. Note wrapping honors
    ``line_cell_limit`` so a split Context card can keep three physical
    body lines. Rows with no title, filing reason, read reason, close
    reason, or note preview omit ``↳`` lines entirely (legacy fallback).
    """
    visible = _visible_bead_entries(entries)
    if hint_labels is None:
        resolved_hints = _bead_touch_hint_labels(entries, hint_state)
    else:
        padded = list(hint_labels[: len(visible)])
        if len(padded) < len(visible):
            padded.extend([None] * (len(visible) - len(padded)))
        resolved_hints = tuple(padded)
    show_role_column = any(item.agent_label for item in visible)
    extra_indent = len(_SUBSECTION_ROW_PREFIX)
    for item, stored_hint in zip(visible, resolved_hints, strict=True):
        glyph = _bead_touch_glyph(item)
        assert cell_len(glyph) == 1, f"bead glyph must stay single-cell: {glyph!r}"
        text.append(_SUBSECTION_ROW_PREFIX)
        reason_indent = (
            append_lane_row(
                text,
                timestamp=item.last_at or item.first_at,
                glyph=glyph,
                glyph_style=_bead_touch_glyph_style(item),
                primary=item.bead_id,
                primary_style=COLOR_BEAD_PRIMARY,
                role_label=item.agent_label,
                show_role_column=show_role_column,
                hint_label=_copied_hint_label(stored_hint),
            )
            + extra_indent
        )
        if _standing_close(item) is not None:
            cap_style, pill_style = _closed_pill_styles(item)
            text.append(" ", style=COLOR_SUMMARY)
            text.append(CLOSED_PILL_LEFT, style=cap_style)
            text.append(CLOSED_PILL_TEXT, style=pill_style)
            text.append(CLOSED_PILL_RIGHT, style=cap_style)
        elif _is_created(item):
            text.append(" ", style=COLOR_SUMMARY)
            text.append(CREATED_PILL_LEFT, style=COLOR_BEAD_CREATED_CAP)
            text.append(CREATED_PILL_TEXT, style=COLOR_BEAD_CREATED_PILL)
            text.append(CREATED_PILL_RIGHT, style=COLOR_BEAD_CREATED_CAP)
        for chip, chip_style in _styled_bead_verb_chips(item):
            text.append(" · ", style=COLOR_SUMMARY)
            text.append(chip, style=chip_style)
        text.append("\n")
        if item.note_preview is not None:
            _append_bead_note_preview(
                text,
                preview=item.note_preview,
                current_note_count=item.current_note_count,
                indent=reason_indent,
                role_label=item.note_agent_label,
                line_cell_limit=line_cell_limit,
            )
        for reason_line in _bead_touch_reason_lines(item):
            append_context_reason(
                text,
                reason_line,
                indent=reason_indent,
                line_cell_limit=line_cell_limit,
            )

    overflow = len(entries) - len(visible)
    if overflow > 0:
        visible_ids = {id(item) for item in visible}
        hidden = [item for item in entries if id(item) not in visible_ids]
        earliest = hidden[-1] if hidden else entries[-1]
        text.append(
            f"  {_SUBSECTION_ROW_PREFIX}+ {overflow} more · "
            f"{format_local_hhmm(earliest.last_at or earliest.first_at)} earliest",
            style=COLOR_TRUNCATION,
        )
        hidden_standing = sum(1 for item in hidden if _standing_close(item) is not None)
        if hidden_standing:
            text.append(" (", style=COLOR_TRUNCATION)
            text.append(
                f"✓ {hidden_standing} closed",
                style=COLOR_BEAD_CLOSED_GLYPH,
            )
            text.append(")", style=COLOR_TRUNCATION)
        text.append("\n")


def _line_cell_limit_for_width(width: int) -> int:
    return max(1, min(width, REASON_LINE_CELL_LIMIT))


@dataclass(slots=True)
class ResponsiveBeadTouchesSection:
    """Bead rows that re-wrap note previews to the visible Context-card width."""

    entries: tuple[BeadTouchEntry, ...]
    hint_labels: tuple[Text | None, ...] = ()

    @property
    def logical_text(self) -> Text:
        """Return the 80-cell inspection text used by search and header ranges."""
        text = Text()
        append_agent_bead_touch_rows(
            text,
            entries=self.entries,
            hint_labels=self.hint_labels,
            line_cell_limit=REASON_LINE_CELL_LIMIT,
        )
        return text

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        text = Text(end="")
        append_agent_bead_touch_rows(
            text,
            entries=self.entries,
            hint_labels=self.hint_labels,
            line_cell_limit=_line_cell_limit_for_width(options.max_width),
        )
        yield from console.render(text, options)


def bead_touches_section_for(
    entries: tuple[BeadTouchEntry, ...],
    hint_state: HeaderHintState | None,
) -> ResponsiveBeadTouchesSection:
    """Build a width-aware beads section and assign hints a single time."""
    return ResponsiveBeadTouchesSection(
        entries=entries,
        hint_labels=_bead_touch_hint_labels(entries, hint_state),
    )
