"""Pure rendering helpers for the pager's sticky chrome and footer.

No Textual imports here: everything is a plain function from document/section
state to a Rich :class:`~rich.text.Text`, so the shapes are unit-testable
without booting an App.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, cast

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui._artifact_tab_model import ARTIFACTS_ACCENTS, ARTIFACTS_ICONS
from sase.pager._trail_chrome_model import MUTED_STYLE
from sase.pager._trail_chrome_text import append_path_label
from sase.pager.document import PagerDocument, PagerSection

#: Pager sections carry the *singular* kind vocabulary their adapters chose
#: (``"bead"``, ``"file"``) rather than the Artifacts tab's plural pane keys.
#: Translate through this table instead of inventing a second glyph/accent
#: registry, per the epic plan's "one glyph, one accent table" seam with the
#: ``sase-ug`` link rail.
_SECTION_KIND_TAB: Mapping[str, str] = {
    "bead": "beads",
    "file": "files",
    "agent": "agents",
}
_DEFAULT_SECTION_ICON = "◆"
_DEFAULT_SECTION_ACCENT = "#AFAFAF"

_DIVIDER_CHAR = "━"


def _section_icon(kind: str) -> str:
    """Return the glyph for a pager section's ``kind``."""
    tab = _SECTION_KIND_TAB.get(kind)
    if tab is None:
        return _DEFAULT_SECTION_ICON
    return ARTIFACTS_ICONS.get(tab, _DEFAULT_SECTION_ICON)


def _section_accent(kind: str) -> str:
    """Return the accent color for a pager section's ``kind``."""
    tab = _SECTION_KIND_TAB.get(kind)
    if tab is None:
        return _DEFAULT_SECTION_ACCENT
    return ARTIFACTS_ACCENTS.get(tab, _DEFAULT_SECTION_ACCENT)


def section_accent(kind: str) -> str:
    """Return the public accent color for a pager section ``kind``."""
    return _section_accent(kind)


_GOTO_SIGIL_STYLE = "bold #FFD75F"
_GOTO_DIGIT_STYLE = "white"
_GOTO_INVALID_STYLE = "bold #FF5F5F"
_GOTO_RANGE_STYLE = "dim"
_GOTO_INVALID_RANGE_STYLE = "dim #FF5F5F"
_ELLIPSIS = "…"


def goto_command_line(
    *,
    digits: str,
    line_count: int,
    section_title: str | None,
    section_kind: str | None,
    width: int,
) -> Text:
    """Render the one-line ``:`` go-to-line strip.

    The section glyph+title (multi-section documents only) truncates before
    the valid-range readout disappears.
    """
    invalid = _goto_digits_are_invalid(digits, line_count)
    left = Text(no_wrap=True, overflow="crop")
    left.append(":", style=_GOTO_SIGIL_STYLE)
    left.append(digits, style=_GOTO_INVALID_STYLE if invalid else _GOTO_DIGIT_STYLE)
    left.append(" ", style="reverse")

    range_text = f"out of range · 1-{line_count}" if invalid else f"line 1-{line_count}"
    range_style = _GOTO_INVALID_RANGE_STYLE if invalid else _GOTO_RANGE_STYLE
    context = None if invalid else _goto_section_context(section_title, section_kind)
    return _assemble_goto_line(
        left,
        range_text=range_text,
        range_style=range_style,
        context=context,
        width=max(width, 0),
    )


def _goto_digits_are_invalid(digits: str, line_count: int) -> bool:
    if not digits:
        return False
    value = int(digits)
    return value == 0 or value > line_count


def _goto_section_context(
    section_title: str | None,
    section_kind: str | None,
) -> tuple[str, str] | None:
    if section_title is None:
        return None
    return (_section_icon(section_kind or ""), section_title)


def _assemble_goto_line(
    left: Text,
    *,
    range_text: str,
    range_style: str,
    context: tuple[str, str] | None,
    width: int,
) -> Text:
    right = _goto_right_side(
        range_text,
        range_style=range_style,
        context=context,
        available=max(0, width - cell_len(left.plain)),
    )
    content = Text(no_wrap=True, overflow="crop")
    content.append_text(left)
    if not right.plain:
        return content
    padding = width - cell_len(left.plain) - cell_len(right.plain)
    content.append(" " * max(2, padding))
    content.append_text(right)
    return content


def _goto_right_side(
    range_text: str,
    *,
    range_style: str,
    context: tuple[str, str] | None,
    available: int,
) -> Text:
    range_part = Text(range_text, style=range_style)
    range_width = cell_len(range_text)
    if context is None:
        return range_part
    glyph, title = context
    prefix_budget = available - range_width - 4  # two 2-cell gaps around the prefix
    prefix = _fit_section_prefix(glyph, title, prefix_budget)
    if prefix is None:
        return range_part
    right = Text(no_wrap=True, overflow="crop")
    right.append(prefix, style=_GOTO_RANGE_STYLE)
    right.append("  ")
    right.append_text(range_part)
    return right


def _fit_section_prefix(glyph: str, title: str, budget: int) -> str | None:
    """Return ``glyph title`` fitted to *budget*, or ``None`` to drop it."""
    if budget <= 0:
        return None
    full = f"{glyph} {title}"
    if cell_len(full) <= budget:
        return full
    glyph_prefix = f"{glyph} "
    title_budget = budget - cell_len(glyph_prefix)
    if title_budget < 2:
        return None
    return glyph_prefix + _truncate_to_cells(title, title_budget)


def _truncate_to_cells(text: str, budget: int) -> str:
    if budget <= 0:
        return ""
    if cell_len(text) <= budget:
        return text
    if budget == 1:
        return _ELLIPSIS
    target = budget - cell_len(_ELLIPSIS)
    if target <= 0:
        return _ELLIPSIS
    kept: list[str] = []
    used = 0
    for character in text:
        width = cell_len(character)
        if used + width > target:
            break
        kept.append(character)
        used += width
    return "".join(kept) + _ELLIPSIS


def _format_char_count(count: int) -> str:
    """Format a character count for the subject line's ``⌘`` readout."""
    if count < 1_000:
        return f"{count}c"
    if count < 1_000_000:
        return f"{count / 1_000:.1f}Kc"
    return f"{count / 1_000_000:.1f}Mc"


def subject_line(
    document: PagerDocument,
    current_section: PagerSection,
    *,
    section_index: int,
    section_total: int,
    scroll_percent: int,
    char_count: int,
    width: int,
    syntax_hint: str | None = None,
    history_state: dict[str, object] | None = None,
    history_styles: Any | None = None,
) -> Text:
    """Build the sticky subject line: title left, position right.

    ``section_index``/``section_total`` are only shown once a document has
    more than one section — a single-section document's own index is not
    information, per the beauty rule that absence costs nothing.

    ``syntax_hint`` is a short language alias (``"py"``, ``"md"``, ``"diff"``)
    shown only when syntax is actually enabled/prepared for the current
    section; it is the first thing dropped at a narrow width, before either
    the subject or the position information it sits beside.
    ``history_state`` optionally carries the version moment (under
    ``"moment"``) plus ``age``/``folded_honest`` for the history pill; it
    truncates without wrapping at narrow widths.

    Width is shed in a fixed order: the syntax hint, the ``⌘`` character
    count, the pill context (the ``Δ`` segment is kept longest in the diff
    view), the pill's shorter forms, and finally the title, which is
    middle-truncated so the basename survives. The pill itself is never
    cropped.
    """
    from sase.pager.history.styles import default_history_styles

    styles = history_styles if history_styles is not None else default_history_styles()
    glyph = _section_icon(current_section.kind)
    accent = _section_accent(current_section.kind)

    show_section_title = section_total > 1 and current_section.title != document.title

    base_right = []
    if section_total > 1:
        base_right.append(f"{section_index}/{section_total}")
    base_right.append(f"{scroll_percent}%")
    base_right_str = " · ".join(base_right)

    moment = _state_moment(history_state)
    # The folded honest state rides in the chip when the time band folds
    # away, ahead of any pill and with no context.
    honest = _honest_chip(history_state, styles)
    context_full = _history_context(moment, history_state, styles)
    context_short = _history_context(moment, history_state, styles, short=True)

    count = f"⌘ {_format_char_count(char_count)}"
    right_tails = [f" · {count}", ""]
    if syntax_hint:
        right_tails.insert(0, f" · {count} · {syntax_hint}")
    context_stages: list[Text | None] = [context_full]
    if context_short is not None and (
        context_full is None or context_short.plain != context_full.plain
    ):
        context_stages.append(context_short)
    if context_stages[-1] is not None:
        context_stages.append(None)
    if honest is not None:
        context_stages = [None]

    # One global shedding sequence: the hint goes, then the count, then
    # the context shortens to its Δ segment and drops. At each step the
    # pill takes the longest fixed form fitting its remaining budget, so
    # the pill shortens through its forms before the title truncates.
    # The pill itself is never dropped when it exists and never cropped.
    stages: list[tuple[str, Text | None]] = [
        (f"{base_right_str}{right_tail}", context_stages[0])
        for right_tail in right_tails
    ]
    stages.extend((base_right_str, shed_context) for shed_context in context_stages[1:])

    width = max(int(width), 0)
    # The leading glyph and its space are always reserved, plus one gap
    # cell between the subject and the position readout.
    glyph_prefix = 2  # glyph cell plus its trailing space
    doc_width = cell_len(document.title)
    sec_width = cell_len(current_section.title) if show_section_title else -3
    full_title_width = doc_width + (3 + sec_width if show_section_title else 0)
    chosen: tuple[str, Text | None, Text | None, bool] | None = None
    for right_str, context in stages:
        right_width = cell_len(right_str)
        context_width = cell_len(context.plain) if context is not None else 0
        pill_budget = (
            width
            - 1
            - glyph_prefix
            - full_title_width
            - right_width
            - context_width
            - (1 if context is not None else 0)
        )
        pill: Text | None
        if honest is not None:
            pill = honest
        else:
            pill = _history_badge(moment, history_state, styles, pill_budget)
        pill_width = cell_len(pill.plain) if pill is not None else 0
        if (
            width >= 1
            and glyph_prefix
            + full_title_width
            + pill_width
            + context_width
            + (1 if pill is not None else 0)
            + (1 if context is not None else 0)
            + right_width
            <= width - 1
        ):
            chosen = (right_str, context, pill, True)
            break
    if chosen is None:
        # The full title fits nowhere: keep the bare percent, the
        # shortest pill, no context, and whatever title cell is left.
        # The pill is never cropped.
        right_str = base_right_str
        context = None
        pill = (
            honest
            if honest is not None
            else _history_badge(moment, history_state, styles, 0)
        )
        full_title = False
    else:
        right_str, context, pill, full_title = chosen

    left = Text()
    left.append(f"{glyph} ", style=f"bold {accent}")
    title_budget = max(
        width
        - 1  # the gap between the subject and the position readout
        - glyph_prefix
        - cell_len(right_str)
        - (cell_len(pill.plain) if pill is not None else 0)
        - (cell_len(context.plain) if context is not None else 0)
        - (1 if pill is not None else 0)
        - (1 if context is not None else 0),
        0,
    )
    if show_section_title:
        if full_title:
            doc_fit, sec_fit = document.title, current_section.title
        else:
            doc_fit, sec_fit = _fit_two_part_title(
                document.title, current_section.title, title_budget
            )
        append_path_label(left, doc_fit, style="bold", root_style=MUTED_STYLE)
        if sec_fit:
            left.append(" · ", style="dim")
            append_path_label(left, sec_fit, style="", root_style=MUTED_STYLE)
    else:
        append_path_label(
            left,
            document.title if full_title else _fit_title(document.title, title_budget),
            style="bold",
            root_style=MUTED_STYLE,
        )
    if pill is not None:
        left.append(" ", style="dim")
        left.append_text(pill)
    if context is not None:
        left.append(" ", style="dim")
        left.append_text(context)

    right = Text(right_str, style="dim")
    gap = max(width - cell_len(left.plain) - cell_len(right.plain), 1)
    line = Text(no_wrap=True, overflow="crop")
    line.append_text(left)
    line.append(" " * gap)
    line.append_text(right)
    return line


def _fit_title(title: str, budget: int) -> str:
    """Middle-truncate *title* to *budget* cells so the basename survives."""
    from sase.pager._trail_chrome_text import fit_label

    if budget <= 0:
        return ""
    return fit_label(title, budget)


def _fit_two_part_title(
    document_title: str, section_title: str, budget: int
) -> tuple[str, str]:
    """Fit a ``document · section`` title pair into *budget* cells.

    The section title carries the basename, so it keeps cells first; the
    document title takes what is left. Either side middle-truncates.
    """
    from rich.cells import cell_len

    if budget <= 0:
        return ("", "")
    separator = 3  # " · "
    section_width = cell_len(section_title)
    document_width = cell_len(document_title)
    if section_width + separator + document_width <= budget:
        return (document_title, section_title)
    section_budget = min(section_width, max(budget - separator, 0))
    document_budget = max(budget - separator - section_budget, 0)
    if document_budget < 1:
        return ("", _fit_title(section_title, max(budget, 0)))
    return (
        _fit_title(document_title, document_budget),
        _fit_title(section_title, section_budget),
    )


def _state_moment(state: dict[str, object] | None) -> Any | None:
    """Return the ``VersionMoment`` carried by a chrome state dict."""
    if not isinstance(state, dict):
        return None
    moment = state.get("moment")
    if moment is not None and hasattr(moment, "kind"):
        return moment
    return None


def _moment_kind(moment: Any | None, state: dict[str, object] | None) -> str:
    if moment is not None:
        return str(getattr(moment, "kind", "") or "")
    if isinstance(state, dict):
        if bool(state.get("tombstone")):
            return "deleted"
        if bool(state.get("dirty")):
            return "now_dirty"
        ordinal = int(cast(Any, state.get("ordinal", 0)) or 0)
        if ordinal > 0 and str(state.get("kind", "") or "") != "now":
            return "past"
        return "now"
    return ""


def _moment_numbers(
    moment: Any | None, state: dict[str, object] | None
) -> tuple[int, int]:
    """Return ``(shown_ordinal, newest)`` for a pill or context."""
    if moment is not None:
        return (
            int(getattr(moment, "ordinal", 0) or 0),
            int(getattr(moment, "newest", 0) or 0),
        )
    if isinstance(state, dict):
        return (
            int(cast(Any, state.get("ordinal", 0)) or 0),
            int(cast(Any, state.get("total", 0)) or 0),
        )
    return (0, 0)


def _pill_capsule(label: str, *, bg: str, fg: str) -> Text:
    """Render one solid pill capsule with a padding cell on each side."""
    return Text(f" {label} ", style=f"bold {fg} on {bg}")


def _pill_forms(
    moment: Any | None, state: dict[str, object] | None, styles: Any
) -> list[Text]:
    """Return the pill's fixed forms, longest first (never cropped)."""
    kind = _moment_kind(moment, state)
    if kind not in ("past", "now", "now_dirty", "deleted"):
        return []
    ordinal, newest = _moment_numbers(moment, state)
    if kind == "past":
        return [
            _pill_capsule(
                f"⟲ PAST · v{ordinal} of {newest}",
                bg=styles.past_pill_bg,
                fg=styles.past_pill_fg,
            ),
            _pill_capsule(
                f"⟲ PAST · v{ordinal}/{newest}",
                bg=styles.past_pill_bg,
                fg=styles.past_pill_fg,
            ),
            _pill_capsule(
                f"⟲ v{ordinal}/{newest}", bg=styles.past_pill_bg, fg=styles.past_pill_fg
            ),
            _pill_capsule(
                f"⟲ v{ordinal}", bg=styles.past_pill_bg, fg=styles.past_pill_fg
            ),
        ]
    if kind == "now":
        return [
            _pill_capsule(
                f"● NOW · v{newest}", bg=styles.now_pill_bg, fg=styles.now_pill_fg
            ),
            _pill_capsule("● NOW", bg=styles.now_pill_bg, fg=styles.now_pill_fg),
        ]
    if kind == "now_dirty":
        return [
            _pill_capsule(
                "◌ NOW · uncommitted",
                bg=styles.uncommitted_pill_bg,
                fg=styles.uncommitted_pill_fg,
            ),
            _pill_capsule(
                "◌ NOW", bg=styles.uncommitted_pill_bg, fg=styles.uncommitted_pill_fg
            ),
        ]
    if kind == "deleted":
        return [
            _pill_capsule(
                f"✖ DELETED · v{ordinal}",
                bg=styles.deleted_pill_bg,
                fg=styles.deleted_pill_fg,
            ),
            _pill_capsule(
                "✖ DELETED", bg=styles.deleted_pill_bg, fg=styles.deleted_pill_fg
            ),
            _pill_capsule(
                f"✖ v{ordinal}", bg=styles.deleted_pill_bg, fg=styles.deleted_pill_fg
            ),
        ]
    return []


def _history_badge(
    moment: Any | None,
    state: dict[str, object] | None,
    styles: Any,
    budget: int,
) -> Text | None:
    """Render the state pill for *moment*, longest form fitting *budget*.

    The pill is a solid capsule — one padding cell on each side, bold
    text — and is never cropped: when nothing fits, the shortest form
    is returned anyway. Without a moment, *state* supplies the same
    numbers in dict form.
    """
    forms = _pill_forms(moment, state, styles)
    if not forms:
        return None
    budget = max(int(budget), 0)
    for form in forms:
        if cell_len(form.plain) <= budget:
            return form
    return forms[-1]


def _history_context(
    moment: Any | None,
    state: dict[str, object] | None,
    styles: Any,
    *,
    short: bool = False,
) -> Text | None:
    """Render the dim context after the pill for *moment*.

    In the diff view the context gains ``Δ vA → vB`` with the base in
    the delete tone, ``→`` dim, and the target in the insert tone. The
    short form keeps only that ``Δ`` segment; every other view shortens
    to nothing. When the time band is folded away, the past and deleted
    context gains the short date, because the band's absolute date is
    not on screen.
    """
    kind = _moment_kind(moment, state)
    if kind in ("", "loading"):
        return None
    age = str(state.get("age", "") or "") if isinstance(state, dict) else ""
    # The short date joins the context only when the time band is folded
    # away: otherwise the band's absolute date is already on screen.
    band_folded = bool(isinstance(state, dict) and state.get("band_folded"))
    delta = _delta_segment(moment, state, styles)
    context = Text()
    if kind == "now":
        context.append("latest", style="dim")
        if age:
            context.append(" · ", style="dim")
            context.append(age, style="dim")
    elif kind == "now_dirty":
        _ordinal, newest = _moment_numbers(moment, state)
        context.append(f"on top of v{newest}", style=styles.uncommitted)
    elif kind == "past":
        date = _short_date(moment) if band_folded else ""
        if date:
            context.append(date, style=styles.past)
            context.append(" · ", style="dim")
        if age:
            context.append(age, style=styles.past)
        elif not date:
            context.append(f"v{_moment_numbers(moment, state)[0]}", style="dim")
    elif kind == "deleted":
        ordinal, _newest = _moment_numbers(moment, state)
        date = _short_date(moment) if band_folded else ""
        if date:
            context.append(date, style=styles.tombstone)
            context.append(" · ", style="dim")
        if age:
            context.append(age, style=styles.tombstone)
        else:
            context.append(f"v{ordinal}", style=styles.tombstone)
    else:  # pragma: no cover - unknown kinds fail open to no context
        return None
    if delta is not None:
        if short:
            return delta
        if context.plain:
            context.append(" · ", style="dim")
        context.append_text(delta)
    if short:
        return None
    return context if context.plain else None


def _short_date(moment: Any | None) -> str:
    """Return the ``Aug 24`` short date for a moment, or ``""``."""
    if moment is None:
        return ""
    committed = getattr(moment, "committed_time", None)
    if not committed:
        return ""
    try:
        import time as _time

        return _time.strftime("%b %d", _time.localtime(int(committed))).replace(
            " 0", " "
        )
    except (TypeError, ValueError, OverflowError):
        return ""


def _delta_segment(
    moment: Any | None, state: dict[str, object] | None, styles: Any
) -> Text | None:
    """Return the colour-matched ``Δ vA → vB`` segment for a diff view."""
    view = ""
    if moment is not None:
        view = str(getattr(moment, "view", "read") or "read")
    elif isinstance(state, dict):
        view = str(state.get("view", "read") or "read")
    if view != "diff":
        return None
    base: int | None = None
    target: int | None = None
    if moment is not None and getattr(moment, "diff", None):
        base, target = moment.diff
    elif isinstance(state, dict):
        raw_base = state.get("diff_base")
        try:
            base = int(cast(Any, raw_base)) if raw_base is not None else None
        except (TypeError, ValueError):
            base = None
        raw_target = state.get("diff_target")
        try:
            target = int(cast(Any, raw_target)) if raw_target is not None else None
        except (TypeError, ValueError):
            target = None
        if target is None:
            target, _newest = _moment_numbers(moment, state)
    if base is None or target is None:
        return None
    base_label = (
        "start" if base <= 0 and target > 0 else ("now" if base == 0 else f"v{base}")
    )
    if target == 0:
        target_label = "now"
        target_style = styles.uncommitted
    else:
        target_label = f"v{target}"
        target_style = styles.insert
    segment = Text()
    segment.append("Δ ", style="dim")
    segment.append(base_label, style=styles.delete)
    segment.append(" → ", style="dim")
    segment.append(target_label, style=target_style)
    return segment


def time_verbs_for_moment(moment: Any | None) -> list[tuple[str, str]]:
    """Return the ordered destination footer verbs for a moment.

    ``( vK`` steps older, ``) vK``/``) now`` steps newer, ``} now``
    jumps back to the live file (a tombstone reads ``} deleted``), and
    ``}`` appears only when its destination differs from ``)``. A verb
    appears only when its key would do something.
    """
    verbs: list[tuple[str, str]] = []
    if moment is None:
        return verbs
    kind = str(getattr(moment, "kind", "") or "")
    if kind == "loading":
        return verbs
    older = getattr(moment, "older", None)
    newer = getattr(moment, "newer", None)
    to_now = getattr(moment, "to_now", None)
    view = str(getattr(moment, "view", "read") or "read")
    if isinstance(older, int):
        verbs.append((f"( v{older}", ""))
    if isinstance(newer, int):
        verbs.append((") now" if newer == 0 else f") v{newer}", ""))
    if kind == "deleted":
        verbs.append(("} deleted", ""))
    elif isinstance(to_now, int) and to_now != newer:
        verbs.append(("} now", ""))
    verbs.append(("@", "timeline"))
    verbs.append(("=", "read" if view == "diff" else "diff"))
    return verbs


#: Honest states with no usable history: plain chips, styled through
#: the palette. Untracked and ignored read as uncommitted-adjacent; the
#: rest stay dim.
_FOLDED_HONEST_LABELS: dict[str, tuple[str, str]] = {
    "untracked": ("UNTRACKED", "uncommitted"),
    "ignored": ("IGNORED", "uncommitted"),
    "no_vcs": ("NO VCS", "dim"),
    "shallow": ("SHALLOW", "dim"),
    "template": ("TEMPLATE", "dim"),
    "indexing": ("indexing…", "dim"),
    "unavailable": ("history unavailable", "dim"),
}


def _honest_chip(state: dict[str, object] | None, styles: Any) -> Text | None:
    """Return the honest-state chip (untracked, no VCS, …), if any."""
    if not isinstance(state, dict):
        return None
    folded = state.get("folded_honest")
    if not (isinstance(folded, tuple) and len(folded) == 2):
        return None
    label, role = _FOLDED_HONEST_LABELS.get(str(folded[0] or ""), ("history", "dim"))
    style = getattr(styles, role, role) if role != "dim" else "dim"
    return Text(label, style=style)


def section_rule(
    section: PagerSection,
    *,
    index: int,
    total: int,
    width: int,
) -> Text:
    """Build one section-transition rule, `_show_divider`'s shape plus a
    kind glyph and accent (design doc section D5)."""
    glyph = _section_icon(section.kind)
    accent = _section_accent(section.kind)
    marker = f"{index}/{total}"

    line = Text()
    line.append(f"{_DIVIDER_CHAR}{_DIVIDER_CHAR} ", style="dim")
    line.append(marker, style=f"bold {accent}")
    line.append(f" {_DIVIDER_CHAR} ", style="dim")
    line.append(f"{glyph} ", style=accent)
    append_path_label(line, section.title, style=accent, root_style=MUTED_STYLE)
    prefix_width = cell_len(line.plain) + 1
    fill = _DIVIDER_CHAR * max(width - prefix_width, 0)
    line.append(f" {fill}", style="dim")
    return line


def footer_legend(
    *,
    section_total: int,
    label_count: int = 0,
    pending_prefix: str = "",
    pending_action: str = "follow",
    trail_back_count: int = 0,
    trail_forward_count: int = 0,
    status: str | None = None,
    history_available: bool = False,
    history_pinned: bool = False,
    history_diff_view: bool = False,
    time_verbs: Sequence[tuple[str, str]] | None = None,
) -> Text:
    """Build the availability-driven footer legend.

    Only verbs that would sometimes do nothing are worth a row (the ACE
    footer convention, matched here): plain scrolling (``j``/``k``/``g``/``G``
    /``ctrl+d``/``ctrl+u``) is always available so it lives in ``?`` only.
    History verbs appear only when a provider owns the current section.

    ``time_verbs`` is the ordered destination list built from the version
    moment (``( vK``, ``) vK``/``) now``, ``} now``/``} deleted``,
    ``@ timeline``, ``= diff``/``= read``); it replaces the
    ``history_*`` booleans, which render the legacy ``( )`` form.
    """
    verbs: list[tuple[str, str]] = []
    if status is not None:
        verbs.append(("…", status))
    if time_verbs is not None:
        verbs.extend(time_verbs)
        # A pinned section names its edit verb here ("E edit now"); the
        # label layer must not add a second "E edit".
        label_has_edit = False
        if history_pinned:
            verbs.append(("E", "edit now"))
            label_has_edit = True
    else:
        label_has_edit = False
        if history_available:
            verbs.append(("( )", "version"))
            verbs.append(("=", "read" if history_diff_view else "diff"))
            verbs.append(("@", "timeline"))
            if history_pinned:
                verbs.append(("E", "edits now"))
                label_has_edit = True
    action_key = {"copy": "y", "edit": "E"}.get(pending_action)
    if action_key is not None:
        verbs.append((f"{action_key}{pending_prefix}…", pending_action))
    elif pending_prefix:
        verbs.append((f"{pending_prefix}…", "link"))
    elif label_count:
        verbs.append(("0-9a-z", "follow"))
        verbs.append(("y", "copy"))
        if not label_has_edit:
            verbs.append(("E", "edit"))
    if trail_back_count:
        verbs.append(("⌫/^O", "back"))
    if trail_forward_count:
        verbs.append(("^I", "forward"))
    if section_total > 1:
        verbs.append(("^N/^P", "entity"))
    verbs.append(("/", "search"))
    help_label = "trail/keys" if trail_back_count or trail_forward_count else "keys"
    verbs.append(("?", help_label))
    verbs.append(("q", "close"))

    line = Text()
    for index, (key, label) in enumerate(verbs):
        if index > 0:
            line.append(" · ", style="dim")
        line.append(key, style="bold")
        if label:
            line.append(f" {label}")
    return line


__all__ = [
    "footer_legend",
    "goto_command_line",
    "section_rule",
    "section_accent",
    "subject_line",
    "time_verbs_for_moment",
]
