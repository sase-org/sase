"""Pure renderers for the pager's visit-history breadcrumb chrome."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal
import unicodedata

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.modals.trail_strip import entry_marker
from sase.pager.document import PagerDocument, PagerSection
from sase.pager.trail import PagerTrailEntry

TrailEntryState = Literal["back", "current", "forward"]

_CURRENT_MARKER = "●"
_ELLIPSIS = "…"
_SEPARATOR = " › "
_MUTED_STYLE = "#8A8A8A"
_CURRENT_STYLE = "bold reverse"
_SECONDARY_STYLE = "#8A8A8A"
_STATE_STYLES: dict[TrailEntryState, str] = {
    "back": "",
    "current": _CURRENT_STYLE,
    "forward": _SECONDARY_STYLE,
}


@dataclass(frozen=True, slots=True)
class _PagerTrailDisplayEntry:
    """One pager visit as it should be displayed, without restorable state."""

    document_identity: str
    document_title: str
    section_identity: str
    section_title: str
    section_kind: str
    state: TrailEntryState

    @property
    def icon(self) -> str:
        icon, _accent = entry_marker(self.section_kind)
        return icon

    @property
    def accent(self) -> str:
        _icon, accent = entry_marker(self.section_kind)
        return accent

    @property
    def short_label(self) -> str:
        return _safe_label(self.section_title)

    @property
    def full_label(self) -> str:
        document = _safe_label(self.document_title)
        section = _safe_label(self.section_title)
        if section == document:
            return section
        return f"{document} · {section}"

    @property
    def secondary_identity(self) -> str:
        values = tuple(
            _safe_optional(value)
            for value in (
                self.section_identity,
                self.document_identity,
            )
        )
        unique = tuple(value for index, value in enumerate(values) if value)
        if not unique:
            return ""
        if len(unique) == 1:
            return unique[0]
        if unique[0] == unique[1]:
            return unique[0]
        return " · ".join(unique)

    @property
    def signature(self) -> tuple[str, str, str, str, str, str]:
        return (
            self.document_identity,
            self.document_title,
            self.section_identity,
            self.section_title,
            self.section_kind,
            self.state,
        )


@dataclass(frozen=True, slots=True)
class PagerTrailSnapshot:
    """Immutable presentation snapshot for the retained pager visit trail."""

    entries: tuple[_PagerTrailDisplayEntry, ...]
    current_index: int

    @property
    def visible(self) -> bool:
        return self.total > 1

    @property
    def current(self) -> _PagerTrailDisplayEntry:
        return self.entries[self.current_index]

    @property
    def position(self) -> int:
        return self.current_index + 1

    @property
    def total(self) -> int:
        return len(self.entries)

    @property
    def back_count(self) -> int:
        return self.current_index

    @property
    def forward_count(self) -> int:
        return self.total - self.current_index - 1

    @property
    def signature(self) -> tuple[int, tuple[tuple[str, str, str, str, str, str], ...]]:
        return (self.current_index, tuple(entry.signature for entry in self.entries))


@dataclass(frozen=True, slots=True)
class _PagerTrailHelpContent:
    """Rendered help-sheet content plus the current visit's line offset."""

    text: Text
    current_line: int


def build_pager_trail_snapshot(
    *,
    back: Sequence[PagerTrailEntry],
    document: PagerDocument,
    document_identity: str,
    current_section: PagerSection | None,
    forward: Sequence[PagerTrailEntry],
) -> PagerTrailSnapshot:
    """Build the display snapshot from retained stacks and live current metadata."""

    entries: list[_PagerTrailDisplayEntry] = [
        _display_entry_from_history(entry, "back") for entry in back
    ]
    entries.append(
        _display_entry_from_current(
            document,
            document_identity=document_identity,
            current_section=current_section,
        )
    )
    entries.extend(
        _display_entry_from_history(entry, "forward") for entry in reversed(forward)
    )
    return PagerTrailSnapshot(entries=tuple(entries), current_index=len(back))


def trail_band_row_count(*, visible: bool, screen_height: int) -> int:
    """Return the fixed row count for the active band layout."""

    if not visible:
        return 0
    return 1 if screen_height <= 12 else 2


def render_trail_band(
    snapshot: PagerTrailSnapshot,
    *,
    width: int,
    screen_height: int,
) -> Text:
    """Render the active breadcrumb band, clipped to *width* cells per row."""

    width = max(0, int(width))
    compact = (
        trail_band_row_count(
            visible=snapshot.visible,
            screen_height=screen_height,
        )
        == 1
    )
    if compact:
        return _render_compact_trail_row(snapshot, width=width)
    text = Text(no_wrap=True, overflow="crop")
    text.append_text(_render_trail_orientation_row(snapshot, width=width))
    text.append("\n")
    text.append_text(_render_trail_path_row(snapshot, width=width))
    return text


def _render_trail_orientation_row(
    snapshot: PagerTrailSnapshot,
    *,
    width: int,
) -> Text:
    """Render the upper orientation row with position and direction counts."""

    width = max(0, int(width))
    if width == 0:
        return Text(no_wrap=True, overflow="crop")

    help_options = ("? trail", "?", "")
    direction_options = (
        _direction_text(snapshot, mode="full"),
        _direction_text(snapshot, mode="compact"),
        Text(),
    )
    for direction in direction_options:
        for help_text in help_options:
            left = _orientation_left(snapshot, direction)
            right = Text(help_text, style="bold") if help_text else Text()
            row = _join_left_right(left, right, width=width)
            if row is not None:
                return row

    fallback = _orientation_left(snapshot, Text("? ", style="bold"))
    return _plain_fallback(fallback.plain, width)


def _render_compact_trail_row(
    snapshot: PagerTrailSnapshot,
    *,
    width: int,
) -> Text:
    """Render the short-height one-line trail layout."""

    width = max(0, int(width))
    if width == 0:
        return Text(no_wrap=True, overflow="crop")

    current = _render_current_only(snapshot.current, width=width)
    direction = _compact_inline_direction(snapshot, current)
    directionless = current
    for middle in (direction, directionless):
        for help_text in ("? trail", "?", ""):
            left = _orientation_left(snapshot, Text(" "))
            if middle.plain:
                left.append_text(middle)
            right = Text(help_text, style="bold") if help_text else Text()
            row = _join_left_right(left, right, width=width)
            if row is not None:
                return row

    return _render_current_only(snapshot.current, width=width)


def _render_trail_path_row(
    snapshot: PagerTrailSnapshot,
    *,
    width: int,
) -> Text:
    """Render the chronological path row with exact counted gaps."""

    width = max(0, int(width))
    if width == 0:
        return Text(no_wrap=True, overflow="crop")

    all_indices = frozenset(range(snapshot.total))
    full = _render_path_for_indices(snapshot, all_indices, width=width, full=True)
    if full is not None:
        return full

    included: frozenset[int] = frozenset({snapshot.current_index})
    best = _render_current_only(snapshot.current, width=width)
    for index in _path_priority(snapshot):
        trial = frozenset((*included, index))
        rendered = _render_path_for_indices(snapshot, trial, width=width, full=False)
        if rendered is not None:
            included = trial
            best = rendered
    return best


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


def _display_entry_from_history(
    entry: PagerTrailEntry,
    state: Literal["back", "forward"],
) -> _PagerTrailDisplayEntry:
    return _PagerTrailDisplayEntry(
        document_identity=entry.document_identity,
        document_title=entry.document_title,
        section_identity=entry.section_identity,
        section_title=entry.section_title,
        section_kind=entry.section_kind,
        state=state,
    )


def _display_entry_from_current(
    document: PagerDocument,
    *,
    document_identity: str,
    current_section: PagerSection | None,
) -> _PagerTrailDisplayEntry:
    if current_section is None:
        return _PagerTrailDisplayEntry(
            document_identity=document_identity,
            document_title=document.title,
            section_identity=document_identity,
            section_title=document.title,
            section_kind="",
            state="current",
        )
    return _PagerTrailDisplayEntry(
        document_identity=document_identity,
        document_title=document.title,
        section_identity=current_section.identity,
        section_title=current_section.title,
        section_kind=current_section.kind,
        state="current",
    )


def _orientation_left(snapshot: PagerTrailSnapshot, suffix: Text) -> Text:
    current = snapshot.current
    text = Text(no_wrap=True, overflow="crop")
    text.append("TRAIL", style=f"bold {current.accent}")
    text.append(" ")
    text.append(f"{snapshot.position}/{snapshot.total}", style="bold reverse")
    text.append_text(suffix)
    return text


def _direction_text(
    snapshot: PagerTrailSnapshot,
    *,
    mode: Literal["full", "compact"],
) -> Text:
    parts: list[tuple[str, str]] = []
    if snapshot.back_count:
        if mode == "full":
            parts.append(("^O", f" back {snapshot.back_count}"))
        else:
            parts.append(("‹", str(snapshot.back_count)))
    if snapshot.forward_count:
        if mode == "full":
            parts.append(("^I", f" forward {snapshot.forward_count}"))
        else:
            parts.append((str(snapshot.forward_count), "›"))
    if not parts:
        return Text()

    text = Text("    " if mode == "full" else "  ", no_wrap=True, overflow="crop")
    if mode == "compact":
        text.append("‹", style="bold")
        if snapshot.back_count:
            text.append(str(snapshot.back_count))
        if snapshot.back_count and snapshot.forward_count:
            text.append(" ")
        if snapshot.forward_count:
            text.append(str(snapshot.forward_count))
        text.append("›", style="bold")
        return text

    for index, (key, label) in enumerate(parts):
        if index:
            text.append(" · ", style=_MUTED_STYLE)
        text.append(key, style="bold")
        text.append(label)
    return text


def _compact_inline_direction(snapshot: PagerTrailSnapshot, current: Text) -> Text:
    text = Text(no_wrap=True, overflow="crop")
    if snapshot.back_count:
        text.append(f"‹{snapshot.back_count} ", style="bold")
    text.append_text(current)
    if snapshot.forward_count:
        text.append(f" {snapshot.forward_count}›", style="bold")
    return text


def _join_left_right(left: Text, right: Text, *, width: int) -> Text | None:
    left_width = cell_len(left.plain)
    right_width = cell_len(right.plain)
    if not right.plain:
        if left_width <= width:
            return left
        return None
    if left_width + right_width > width:
        return None
    row = Text(no_wrap=True, overflow="crop")
    row.append_text(left)
    row.append(" " * max(width - left_width - right_width, 0))
    row.append_text(right)
    return row


def _plain_fallback(plain: str, width: int) -> Text:
    return Text(_fit_text(plain, width), no_wrap=True, overflow="crop")


def _path_priority(snapshot: PagerTrailSnapshot) -> Iterable[int]:
    current = snapshot.current_index
    seen = {current}
    candidates = [current - 1, current + 1, 0]
    for candidate in candidates:
        if 0 <= candidate < snapshot.total and candidate not in seen:
            seen.add(candidate)
            yield candidate

    for distance in range(2, snapshot.total + 1):
        for candidate in (current - distance, current + distance):
            if 0 <= candidate < snapshot.total and candidate not in seen:
                seen.add(candidate)
                yield candidate


def _render_path_for_indices(
    snapshot: PagerTrailSnapshot,
    indices: frozenset[int],
    *,
    width: int,
    full: bool,
) -> Text | None:
    tokens = _path_tokens(snapshot, indices)
    if full:
        rendered = _render_path_tokens(tokens, full_labels=True)
        return rendered if cell_len(rendered.plain) <= width else None

    budgets = _label_budgets(tokens, width=width)
    if budgets is None:
        return None
    rendered = _render_path_tokens(tokens, label_budgets=budgets)
    if cell_len(rendered.plain) <= width:
        return rendered
    return None


def _path_tokens(
    snapshot: PagerTrailSnapshot,
    indices: frozenset[int],
) -> tuple[int | _PagerTrailDisplayEntry, ...]:
    tokens: list[int | _PagerTrailDisplayEntry] = []
    omitted = 0
    for index, entry in enumerate(snapshot.entries):
        if index not in indices:
            omitted += 1
            continue
        if omitted:
            tokens.append(omitted)
            omitted = 0
        tokens.append(entry)
    if omitted:
        tokens.append(omitted)
    return tuple(tokens)


def _label_budgets(
    tokens: tuple[int | _PagerTrailDisplayEntry, ...],
    *,
    width: int,
) -> dict[int, int] | None:
    entries = [token for token in tokens if isinstance(token, _PagerTrailDisplayEntry)]
    if not entries:
        return {}

    structural = _path_structural_width(tokens)
    minimum = sum(1 for entry in entries if entry.state == "current")
    minimum += sum(3 for entry in entries if entry.state != "current")
    if structural + minimum > width:
        return None

    by_id = {id(entry): entry for entry in entries}
    budgets: dict[int, int] = {id(entry): 0 for entry in entries}
    available = width - structural
    priority = _budget_priority(entries)
    for entry in priority:
        full_width = cell_len(entry.short_label)
        floor = 1 if entry.state == "current" else 3
        cap = _label_cap(entry, width=width)
        wanted = min(full_width, cap)
        give = min(wanted, available)
        if give < floor:
            return None
        budgets[id(entry)] = give
        available -= give

    if available > 0:
        for entry in priority:
            full_width = cell_len(entry.short_label)
            room = full_width - budgets[id(entry)]
            if room <= 0:
                continue
            give = min(room, available)
            budgets[id(entry)] += give
            available -= give
            if available <= 0:
                break

    return {entry_id: budgets[entry_id] for entry_id in by_id}


def _budget_priority(
    entries: Sequence[_PagerTrailDisplayEntry],
) -> tuple[_PagerTrailDisplayEntry, ...]:
    current = [entry for entry in entries if entry.state == "current"]
    back = [entry for entry in reversed(entries) if entry.state == "back"]
    forward = [entry for entry in entries if entry.state == "forward"]
    others = [
        entry for entry in entries if entry.state not in {"current", "back", "forward"}
    ]
    seen: set[int] = set()
    ordered: list[_PagerTrailDisplayEntry] = []
    for group in (
        current,
        back[:1],
        forward[:1],
        entries[:1],
        back[1:],
        forward[1:],
        others,
    ):
        for entry in group:
            marker = id(entry)
            if marker in seen:
                continue
            seen.add(marker)
            ordered.append(entry)
    return tuple(ordered)


def _label_cap(entry: _PagerTrailDisplayEntry, *, width: int) -> int:
    if entry.state == "current":
        return max(1, min(32, max(8, width // 3)))
    return max(3, min(18, max(6, width // 5)))


def _path_structural_width(
    tokens: tuple[int | _PagerTrailDisplayEntry, ...],
) -> int:
    width = 0
    for index, token in enumerate(tokens):
        if index:
            width += cell_len(_SEPARATOR)
        if isinstance(token, int):
            width += cell_len(f"{_ELLIPSIS}{token}")
            continue
        width += _crumb_overhead(token)
    return width


def _crumb_overhead(entry: _PagerTrailDisplayEntry) -> int:
    icon = entry.icon
    if entry.state == "current":
        return cell_len(f"[{_CURRENT_MARKER} {icon} ]")
    return cell_len(f"{icon} ")


def _render_path_tokens(
    tokens: tuple[int | _PagerTrailDisplayEntry, ...],
    *,
    full_labels: bool = False,
    label_budgets: dict[int, int] | None = None,
) -> Text:
    text = Text(no_wrap=True, overflow="crop")
    for index, token in enumerate(tokens):
        if index:
            text.append(_SEPARATOR, style=_MUTED_STYLE)
        if isinstance(token, int):
            text.append(f"{_ELLIPSIS}{token}", style=_MUTED_STYLE)
            continue
        label = token.short_label
        if not full_labels:
            assert label_budgets is not None
            label = _fit_label(label, label_budgets[id(token)])
        _append_crumb(text, token, label=label)
    return text


def _append_crumb(text: Text, entry: _PagerTrailDisplayEntry, *, label: str) -> None:
    if entry.state == "current":
        text.append("[", style=_CURRENT_STYLE)
        text.append(f"{_CURRENT_MARKER} ", style=_CURRENT_STYLE)
        text.append(f"{entry.icon} ", style=f"bold {entry.accent} reverse")
        text.append(label, style=_CURRENT_STYLE)
        text.append("]", style=_CURRENT_STYLE)
        return

    style = _STATE_STYLES[entry.state]
    text.append(f"{entry.icon} ", style=f"bold {entry.accent}")
    text.append(label, style=style)


def _render_current_only(entry: _PagerTrailDisplayEntry, *, width: int) -> Text:
    width = max(0, width)
    if width <= 0:
        return Text(no_wrap=True, overflow="crop")

    for bracketed, include_icon in (
        (True, True),
        (True, False),
        (False, True),
        (False, False),
    ):
        overhead = _current_only_overhead(entry, bracketed, include_icon)
        budget = width - overhead
        if budget < 1:
            continue
        label = _fit_label(entry.short_label, budget)
        rendered = Text(no_wrap=True, overflow="crop")
        if bracketed:
            rendered.append("[", style=_CURRENT_STYLE)
        rendered.append(f"{_CURRENT_MARKER} ", style=_CURRENT_STYLE)
        if include_icon:
            rendered.append(f"{entry.icon} ", style=f"bold {entry.accent} reverse")
        rendered.append(label, style=_CURRENT_STYLE)
        if bracketed:
            rendered.append("]", style=_CURRENT_STYLE)
        if cell_len(rendered.plain) <= width:
            return rendered

    if cell_len(_CURRENT_MARKER) <= width:
        return Text(_CURRENT_MARKER, style=_CURRENT_STYLE, no_wrap=True)
    return Text(no_wrap=True, overflow="crop")


def _current_only_overhead(
    entry: _PagerTrailDisplayEntry,
    bracketed: bool,
    include_icon: bool,
) -> int:
    prefix = f"{_CURRENT_MARKER} "
    if bracketed:
        prefix = f"[{prefix}"
    if include_icon:
        prefix += f"{entry.icon} "
    suffix = "]" if bracketed else ""
    return cell_len(prefix) + cell_len(suffix)


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


def _wrap_cells(text: str, width: int) -> tuple[str, ...]:
    width = max(1, width)
    words = _safe_label(text).split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        if not word:
            continue
        if not current:
            if cell_len(word) <= width:
                current = word
            else:
                lines.extend(_hard_wrap(word, width))
            continue
        candidate = f"{current} {word}"
        if cell_len(candidate) <= width:
            current = candidate
        else:
            lines.append(current)
            if cell_len(word) <= width:
                current = word
            else:
                wrapped = list(_hard_wrap(word, width))
                lines.extend(wrapped[:-1])
                current = wrapped[-1] if wrapped else ""
    if current:
        lines.append(current)
    return tuple(lines or ("",))


def _hard_wrap(text: str, width: int) -> tuple[str, ...]:
    clusters = list(_clusters(text))
    lines: list[str] = []
    current: list[str] = []
    used = 0
    for cluster in clusters:
        cluster_width = cell_len(cluster)
        if current and used + cluster_width > width:
            lines.append("".join(current))
            current = []
            used = 0
        if cluster_width > width:
            continue
        current.append(cluster)
        used += cluster_width
    if current:
        lines.append("".join(current))
    return tuple(lines or ("",))


def _fit_label(label: str, budget: int) -> str:
    budget = max(0, int(budget))
    label = _safe_label(label)
    if budget <= 0:
        return ""
    if cell_len(label) <= budget:
        return label
    if budget <= cell_len(_ELLIPSIS):
        return _ELLIPSIS

    ellipsis_width = cell_len(_ELLIPSIS)
    available = budget - ellipsis_width
    suffix_hint = _suffix_hint_width(label)
    suffix_budget = min(available, max(1, available // 2, suffix_hint))
    prefix_budget = available - suffix_budget
    if prefix_budget <= 0:
        return _ELLIPSIS + _take_suffix(label, available)
    return (
        _take_prefix(label, prefix_budget)
        + _ELLIPSIS
        + _take_suffix(label, suffix_budget)
    )


def _fit_text(text: str, budget: int) -> str:
    budget = max(0, int(budget))
    text = _safe_label(text)
    if budget <= 0:
        return ""
    if cell_len(text) <= budget:
        return text
    if budget <= cell_len(_ELLIPSIS):
        return _ELLIPSIS
    return _take_prefix(text, budget - cell_len(_ELLIPSIS)) + _ELLIPSIS


def _suffix_hint_width(label: str) -> int:
    basename = label.rsplit("/", 1)[-1]
    if "." not in basename:
        return 0
    dot = basename.rfind(".")
    if dot <= 0:
        return 0
    return min(cell_len(basename[dot:]) + 2, 12)


def _take_prefix(text: str, budget: int) -> str:
    kept: list[str] = []
    used = 0
    for cluster in _clusters(text):
        width = cell_len(cluster)
        if used + width > budget:
            break
        kept.append(cluster)
        used += width
    return "".join(kept)


def _take_suffix(text: str, budget: int) -> str:
    kept: list[str] = []
    used = 0
    for cluster in reversed(tuple(_clusters(text))):
        width = cell_len(cluster)
        if used + width > budget:
            break
        kept.append(cluster)
        used += width
    return "".join(reversed(kept))


def _clusters(text: str) -> Iterable[str]:
    current = ""
    for character in text:
        if unicodedata.combining(character) and current:
            current += character
            continue
        if current:
            yield current
        current = character
    if current:
        yield current


def _safe_label(value: str) -> str:
    safe = _safe_optional(value)
    return safe or "untitled"


def _safe_optional(value: str) -> str:
    characters = []
    for character in value:
        category = unicodedata.category(character)
        if character in {"\n", "\r", "\t"} or category.startswith("C"):
            characters.append(" ")
        else:
            characters.append(character)
    return " ".join("".join(characters).split())


__all__ = [
    "TrailEntryState",
    "build_pager_help_content",
    "build_pager_trail_snapshot",
    "render_pager_help_footer",
    "render_pager_help_header",
    "render_trail_band",
    "trail_band_row_count",
]
