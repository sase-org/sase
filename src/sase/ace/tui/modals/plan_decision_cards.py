"""Pure Rich builders for Plan Review decision cards (sase-1ka.1).

Every builder here is Textual-free: inputs are a Decision Sheet row, its
frozen definition, a content width, and display flags; outputs are Rich
renderables (``Group`` of pre-wrapped ``Text`` lines) plus a mouse
option-line map. The :class:`DecisionCard` widget in
:mod:`sase.ace.tui.modals.plan_decision_rows` owns layout and focus; these
functions own every pixel of card text so unit tests can assert wrapping,
chips, and glyphs without a pilot.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.cells import cell_len
from rich.console import Console, Group
from rich.text import Text

from sase.sdd._plan_display_decisions import (
    DECISION_DEFAULT_MARK,
    DECISION_MODIFIED_MARK,
    DECISION_SELECTED_MARK,
    DECISION_UNSELECTED_MARK,
    format_decision_value,
    memory_note_names,
    provenance_chip,
)

# Styling tokens for the current decision card. The focus colour marks the
# current card's id and focus bar; the muted bar is the same hue dimmed for
# when focus sits elsewhere (Actions/Verdict). Both are mirrored in
# ``styles.tcss`` next to the card rules. Changed chips use gold.
FOCUS_COLOR = "#5FD7FF"
FOCUS_BAR_MUTED = "#3A6F80"
CHANGED_COLOR = "#FFD700"
READONLY_BAR_STYLE = "dim"

FOCUS_BAR_GLYPH = "\u258c"
TOGGLE_ON_GLYPH = "\u2611"
TOGGLE_OFF_GLYPH = "\u2610"
MEMORY_GLYPH = "\U0001f9e0"
WARNING_GLYPH = "\u26a0"

#: Inner content width at or above which a choice card uses the two-column
#: option layout instead of the stacked layout.
TWO_COLUMN_MIN_INNER_WIDTH = 60


@dataclass(frozen=True)
class OptionLineMap:
    """Maps one rendered option to its line span for mouse selection."""

    key: str
    first_line: int
    last_line: int


@dataclass(frozen=True)
class BuiltCard:
    """One rendered card: lines plus the mouse option map."""

    renderable: Group
    option_map: tuple[OptionLineMap, ...] = ()
    height: int = 0


def is_unverified_row(
    row: dict[str, Any], definition: dict[str, Any] | None = None
) -> bool:
    """Return True when a memory row still needs a human to turn it on."""
    memory = row.get("memory")
    if not isinstance(memory, dict):
        return False
    if str(memory.get("provenance") or "") in ("quote_not_found", "claim_not_found"):
        return True
    if definition is not None:
        authored = definition.get("default")
        effective = definition.get("effective_default", authored)
        if authored is True and effective is False and row.get("value") is False:
            return True
    return False


def memory_type_chips(memory: dict[str, Any]) -> list[str]:
    """Return the note-kind chips (core/reference/web/new) for a memory row."""
    resolved = memory.get("resolved")
    if not isinstance(resolved, list):
        return []
    chips: list[str] = []
    for record in resolved:
        if not isinstance(record, dict):
            continue
        kind = str(record.get("type") or record.get("kind") or "").strip()
        if kind == "strand":
            kind = "web"
        if kind and kind not in chips:
            chips.append(kind)
        if record.get("exists") is False and "new" not in chips:
            chips.append("new")
    return chips


def unverified_preview(memory: dict[str, Any]) -> str:
    """Return the one-line yellow preview for an unverified memory row."""
    if str(memory.get("provenance") or "") == "claim_not_found":
        return f"{WARNING_GLYPH} claim not found \u00b7 off"
    return f"{WARNING_GLYPH} quote not found \u00b7 off"


def unverified_warning_line(memory: dict[str, Any]) -> str:
    """Return the full warning sentence for an unverified memory row."""
    quote = memory.get("quote")
    quote_text = str(quote).strip() if isinstance(quote, str) else ""
    if str(memory.get("provenance") or "") == "claim_not_found":
        return f'{WARNING_GLYPH} "{quote_text}" \u2014 not in the note \u00b7 off until you turn it on'
    return f'{WARNING_GLYPH} "{quote_text}" \u2014 not in your messages \u00b7 off until you turn it on'


def _answer_chip_parts(row: dict[str, Any]) -> tuple[str, str, bool]:
    """Return ``(value_text, mark, changed)`` for the answer chip.

    ``value_text`` is ``☑ yes`` / ``☐ no`` for toggles, or the raw value
    for choices. ``mark`` is ``★`` at the default and ``●`` when changed.
    """
    kind = str(row.get("kind", ""))
    value = row.get("value")
    changed = bool(row.get("changed"))
    mark = DECISION_MODIFIED_MARK if changed else DECISION_DEFAULT_MARK
    if kind == "toggle":
        glyph = TOGGLE_ON_GLYPH if value is True else TOGGLE_OFF_GLYPH
        return f"{glyph} {format_decision_value(value)}", mark, changed
    return f"{value}", mark, changed


def answer_chip_text(row: dict[str, Any]) -> tuple[str, bool]:
    """Return the answer chip text and whether the value changed.

    At the default the chip reads ``value ★``; changed it reads ``value ●``.
    Toggles show ``☑ yes`` / ``☐ no`` (width-1 glyphs, no VS16).
    """
    value_text, mark, changed = _answer_chip_parts(row)
    return f"{value_text} {mark}", changed


def default_line_text(
    row: dict[str, Any], definition: dict[str, Any] | None = None
) -> tuple[str, bool]:
    """Return the memory-toggle default line and whether it warns.

    Follows the provenance table: ``not_asked`` / ``asked`` /
    ``quote_not_found`` / ``claim_not_found`` / ``correction`` /
    ``inherited``. Plain (non-memory) rows return an empty string.
    """
    memory = row.get("memory")
    if not isinstance(memory, dict):
        return "", False
    provenance = str(memory.get("provenance") or "not_asked")
    quote_raw = memory.get("quote")
    quote = (
        quote_raw.strip() if isinstance(quote_raw, str) and quote_raw.strip() else ""
    )
    if provenance == "quote_not_found":
        return (
            f'{WARNING_GLYPH} off \u2014 "{quote}" is not in your messages; turn on to allow',
            True,
        )
    if provenance == "claim_not_found":
        return (
            f'{WARNING_GLYPH} off \u2014 "{quote}" is not in the note; turn on to allow',
            True,
        )
    if provenance == "asked":
        return f'{DECISION_DEFAULT_MARK} on \u2014 you asked: "{quote}"', False
    if provenance == "correction":
        text = f"{DECISION_DEFAULT_MARK} on \u2014 corrects a statement this plan makes false"
        if quote:
            text += f', "{quote}"'
        return text, False
    if provenance == "inherited":
        return f"{DECISION_DEFAULT_MARK} on \u2014 approved in the epic", False
    return f"{DECISION_DEFAULT_MARK} off \u2014 you did not ask for this edit", False


def _wrap_lines(
    console: Console, text: str, width: int, *, style: str = ""
) -> list[Text]:
    """Wrap *text* to *width* cells, folding unbreakable runs."""
    wrapped = Text(text, style=style, overflow="fold").wrap(
        console, width, justify="left", overflow="fold"
    )
    # Rich pads wrapped lines to the full width; strip the padding so card
    # lines carry no trailing whitespace.
    lines = [
        Text(line.plain.rstrip(), style=style, overflow="fold", no_wrap=True)
        for line in wrapped
    ]
    return lines or [Text("", style=style, no_wrap=True)]


def _indent_lines(lines: list[Text], indent: str) -> list[Text]:
    """Prepend *indent* to wrapped lines (hanging indent after the first)."""
    out: list[Text] = []
    for line in lines:
        prefixed = Text(indent, no_wrap=True) + line
        out.append(prefixed)
    return out


def _header_line(
    row: dict[str, Any],
    content_width: int,
    *,
    current: bool,
    focused: bool,
    read_only: bool,
) -> Text:
    """Build the shared header row: id left, answer chip right.

    The id may ellipsize; the chip never does. The current, editable card
    wraps the chip in muted ``‹ … ›`` ("h/l changes this"). Each piece is
    appended with its own style so wide glyphs (``🧠``) cannot shift spans.
    """
    decision_id = str(row.get("id", ""))
    memory = row.get("memory")
    id_text = (
        f"{MEMORY_GLYPH} {decision_id}" if isinstance(memory, dict) else decision_id
    )
    value_text, mark, changed = _answer_chip_parts(row)
    show_chevrons = current and not read_only
    chip_len = cell_len(value_text) + 1 + cell_len(mark)
    if show_chevrons:
        chip_len += cell_len("\u2039 ") + cell_len(" \u203a")
    id_width = max(content_width - chip_len - 1, 1)
    shown_id = Text(id_text, overflow="ellipsis", no_wrap=True)
    shown_id.truncate(id_width, overflow="ellipsis")
    id_style = "bold"
    if current and not read_only:
        id_style = f"bold {FOCUS_COLOR if focused else FOCUS_BAR_MUTED}"
    elif read_only:
        id_style = "bold dim"
    header = Text(no_wrap=True, overflow="fold")
    header.append(shown_id.plain, style=id_style)
    pad = content_width - cell_len(shown_id.plain) - chip_len
    header.append(" " * max(pad, 1))
    if show_chevrons:
        header.append("\u2039 ", style="dim")
    value_style = CHANGED_COLOR if changed else ""
    header.append(value_text, style=value_style)
    mark_style = CHANGED_COLOR if changed else "dim"
    header.append(f" {mark}", style=mark_style)
    if show_chevrons:
        header.append(" \u203a", style="dim")
    return header


def _bar_text(line: Text, *, current: bool, focused: bool, read_only: bool) -> Text:
    """Prefix one card line with the focus bar (or a blank gutter)."""
    out = Text(no_wrap=True, overflow="fold")
    if current:
        if read_only:
            out.append(f"{FOCUS_BAR_GLYPH} ", style=READONLY_BAR_STYLE)
        elif focused:
            out.append(f"{FOCUS_BAR_GLYPH} ", style=FOCUS_COLOR)
        else:
            out.append(f"{FOCUS_BAR_GLYPH} ", style=FOCUS_BAR_MUTED)
    else:
        out.append("  ")
    out.append_text(line)
    return out


def _build(
    row: dict[str, Any],
    definition: dict[str, Any] | None,
    width: int,
    lines: list[Text],
    option_map: list[OptionLineMap],
    *,
    current: bool,
    focused: bool,
    read_only: bool,
) -> BuiltCard:
    barred = [
        _bar_text(line, current=current, focused=focused, read_only=read_only)
        for line in lines
    ]
    return BuiltCard(
        renderable=Group(*barred),
        option_map=tuple(option_map),
        height=len(barred),
    )


def collapsed_card(
    row: dict[str, Any],
    definition: dict[str, Any] | None,
    width: int,
    *,
    current: bool = False,
    focused: bool = False,
    read_only: bool = False,
    preview_lines: int = 2,
) -> BuiltCard:
    """Build the collapsed card: header plus an ellipsized ask preview.

    ``preview_lines=1`` renders the header only, for short slots.
    """
    width = max(int(width), 8)
    content_width = width - 2
    lines = [
        _header_line(
            row, content_width, current=current, focused=focused, read_only=read_only
        )
    ]
    if preview_lines >= 2:
        memory = row.get("memory")
        if isinstance(memory, dict) and is_unverified_row(row, definition):
            preview = Text(
                unverified_preview(memory),
                style="yellow",
                overflow="ellipsis",
                no_wrap=True,
            )
            preview.truncate(content_width, overflow="ellipsis")
            lines.append(preview)
        else:
            ask = str(row.get("ask", "")).strip().replace("\n", " ")
            if ask:
                preview = Text(ask, style="dim", overflow="ellipsis", no_wrap=True)
                preview.truncate(content_width, overflow="ellipsis")
                lines.append(preview)
            elif isinstance(memory, dict):
                names = memory_note_names(memory)
                chips = memory_type_chips(memory)
                provenance = provenance_chip(str(memory.get("provenance") or ""))
                second = (
                    f"{MEMORY_GLYPH} {', '.join(names) if names else row.get('id', '')}"
                )
                if chips:
                    second += f" \u00b7 {', '.join(chips)}"
                if provenance:
                    second += f" \u00b7 {provenance}"
                preview = Text(second, style="dim", overflow="ellipsis", no_wrap=True)
                preview.truncate(content_width, overflow="ellipsis")
                lines.append(preview)
    return _build(
        row,
        definition,
        width,
        lines,
        [],
        current=current,
        focused=focused,
        read_only=read_only,
    )


def _two_column_head_width(row: dict[str, Any]) -> int:
    """Shared head-column width for option heads and the ``why ★`` footnote."""
    width = cell_len(f"  why {DECISION_DEFAULT_MARK}")
    default = row.get("default")
    choices = row.get("choices")
    if not isinstance(choices, list):
        return width
    for choice in choices:
        if not isinstance(choice, dict):
            continue
        head = f"{DECISION_SELECTED_MARK} {choice.get('key', '')}"
        if str(default) == str(choice.get("key", "")):
            head += f" {DECISION_DEFAULT_MARK}"
        width = max(width, cell_len(head))
    return width


def _choice_option_rows(
    console: Console,
    row: dict[str, Any],
    content_width: int,
    *,
    two_column: bool,
) -> tuple[list[Text], list[tuple[str, int, int]]]:
    """Render the option rows; returns lines plus (key, first, last) spans."""
    lines: list[Text] = []
    spans: list[tuple[str, int, int]] = []
    value = row.get("value")
    default = row.get("default")
    choices = row.get("choices")
    if not isinstance(choices, list):
        return lines, spans
    items = [c for c in choices if isinstance(c, dict)]
    head_width = _two_column_head_width(row) if two_column else 0
    for choice in items:
        key = str(choice.get("key", ""))
        label = str(choice.get("label", ""))
        selected = str(value) == key
        marker = DECISION_SELECTED_MARK if selected else DECISION_UNSELECTED_MARK
        star = f" {DECISION_DEFAULT_MARK}" if str(default) == key else ""
        first = len(lines)
        if two_column:
            # Heads share one column width so labels (and the why text)
            # align vertically. The ★ is its own dim segment at the end of
            # the unpadded head, never a padding cell.
            pad = head_width - cell_len(f"{marker} {key}{star}")
            head_line = Text(no_wrap=True, overflow="fold")
            marker_style = "bold" if selected else "dim"
            head_line.append(f"{marker} {key}", style=marker_style)
            if star:
                head_line.append(star, style="dim")
            if pad > 0:
                head_line.append(" " * pad)
            label_width = content_width - head_width - 4
            label_style = "" if selected else "dim"
            if label and label_width > 8:
                wrapped = _wrap_lines(console, label, label_width)
                head_line.append(" " * 4)
                if wrapped[0].plain:
                    head_line.append(wrapped[0].plain, style=label_style)
                lines.append(head_line)
                for cont in wrapped[1:]:
                    cont_line = Text(" " * (head_width + 4), no_wrap=True)
                    if cont.plain:
                        cont_line.append(cont.plain, style=label_style)
                    lines.append(cont_line)
            else:
                if label:
                    head_line.append(f"    {label}", style=label_style)
                lines.append(head_line)
        else:
            marker_line = Text(f"{marker} {key}{star}", no_wrap=True, overflow="fold")
            if selected:
                marker_line.stylize("bold", 0, cell_len(marker_line.plain))
                if star:
                    marker_line.stylize(
                        "dim",
                        cell_len(marker_line.plain) - 1,
                        cell_len(marker_line.plain),
                    )
            else:
                marker_line.stylize("dim", 0, cell_len(marker_line.plain))
            lines.append(marker_line)
            if label:
                for lab in _indent_lines(
                    _wrap_lines(
                        console,
                        label,
                        content_width - 2,
                        style="" if selected else "dim",
                    ),
                    "  ",
                ):
                    lines.append(lab)
        spans.append((key, first, len(lines) - 1))
    return lines, spans


def expanded_card(
    row: dict[str, Any],
    definition: dict[str, Any] | None,
    width: int,
    *,
    current: bool = True,
    focused: bool = True,
    read_only: bool = False,
) -> BuiltCard:
    """Build the expanded card with every option and footnote.

    Non-current expanded cards (the decision sheet) keep the full body but
    drop the focus bar and the ``‹ ›`` chip wrapper.
    """
    width = max(int(width), 8)
    content_width = width - 2
    console = Console(width=content_width, color_system=None)
    kind = str(row.get("kind", ""))
    memory = row.get("memory")
    lines = [
        _header_line(
            row, content_width, current=current, focused=focused, read_only=read_only
        )
    ]
    ask = str(row.get("ask", "")).strip()
    if ask:
        lines.extend(_wrap_lines(console, ask, content_width))
    option_map: list[OptionLineMap] = []
    if kind == "choice":
        two_column = content_width >= TWO_COLUMN_MIN_INNER_WIDTH
        if ask:
            lines.append(Text("", no_wrap=True))
        opt_lines, spans = _choice_option_rows(
            console, row, content_width, two_column=two_column
        )
        base = len(lines)
        lines.extend(opt_lines)
        for key, first, last in spans:
            option_map.append(OptionLineMap(key, base + first, base + last))
        why = row.get("why")
        if isinstance(why, str) and why.strip():
            lines.append(Text("", no_wrap=True))
            if two_column:
                head_width = _two_column_head_width(row)
                why_head = f"  why {DECISION_DEFAULT_MARK}"
                pad = head_width - cell_len(why_head)
                prefix = why_head + " " * max(pad, 0)
                label_width = max(content_width - head_width - 4, 1)
                why_wrapped = _wrap_lines(
                    console,
                    why.strip(),
                    label_width,
                    style="dim italic",
                )
                first = True
                for part in why_wrapped:
                    if first:
                        line = Text(no_wrap=True, overflow="fold")
                        line.append(prefix, style="dim italic")
                        line.append(" " * 4, style="dim italic")
                        line.append_text(part)
                        lines.append(line)
                        first = False
                    else:
                        indent = Text(" " * (head_width + 4), no_wrap=True)
                        lines.append(indent + part)
            else:
                why_wrapped = _wrap_lines(
                    console,
                    f"why {DECISION_DEFAULT_MARK} {why.strip()}",
                    content_width,
                    style="dim italic",
                )
                lines.extend(why_wrapped)
    elif isinstance(memory, dict):
        names = memory_note_names(memory)
        chips = memory_type_chips(memory)
        selector_text = ", ".join(names) if names else str(row.get("id", ""))
        edits_wrapped = _wrap_lines(
            console, selector_text, max(content_width - 11, 1), style="dim"
        )
        first = True
        for part in edits_wrapped:
            if first:
                lines.append(Text("  edits    ", style="dim", no_wrap=True) + part)
                first = False
            else:
                lines.append(Text(" " * 11, no_wrap=True) + part)
        if chips:
            chip_wrapped = _wrap_lines(
                console,
                ", ".join(chips),
                max(content_width - 11, 1),
                style="dim",
            )
            for part in chip_wrapped:
                lines.append(Text(" " * 11, no_wrap=True) + part)
        default_text, warns = default_line_text(row, definition)
        if default_text:
            default_wrapped = _wrap_lines(
                console,
                default_text,
                content_width - 11,
                style="yellow" if warns else "dim",
            )
            first = True
            for part in default_wrapped:
                if first:
                    lines.append(Text("  default  ", style="dim", no_wrap=True) + part)
                    first = False
                else:
                    lines.append(Text(" " * 11, no_wrap=True) + part)
    else:
        why = row.get("why")
        if isinstance(why, str) and why.strip():
            why_wrapped = _wrap_lines(
                console,
                f"why {DECISION_DEFAULT_MARK} {why.strip()}",
                content_width - 2,
                style="dim italic",
            )
            first = True
            for part in why_wrapped:
                if first:
                    lines.append(Text("  ", no_wrap=True) + part)
                    first = False
                else:
                    lines.append(Text("    ", no_wrap=True) + part)
    return _build(
        row,
        definition,
        width,
        lines,
        [OptionLineMap(o.key, o.first_line, o.last_line) for o in option_map],
        current=current,
        focused=focused,
        read_only=read_only,
    )


def render_lines(renderable: Group, width: int) -> list[str]:
    """Render a built card to plain lines at *width* (tests + measuring)."""
    console = Console(width=max(int(width), 8), record=True, color_system=None)
    with console.capture() as capture:
        console.print(renderable, end="")
    return capture.get().splitlines()


__all__ = [
    "CHANGED_COLOR",
    "FOCUS_BAR_GLYPH",
    "FOCUS_BAR_MUTED",
    "FOCUS_COLOR",
    "READONLY_BAR_STYLE",
    "TWO_COLUMN_MIN_INNER_WIDTH",
    "BuiltCard",
    "OptionLineMap",
    "answer_chip_text",
    "collapsed_card",
    "default_line_text",
    "expanded_card",
    "is_unverified_row",
    "memory_type_chips",
    "render_lines",
    "unverified_preview",
    "unverified_warning_line",
]
