"""Sticky subject-line rendering for the pager.

No Textual imports here: everything is a plain function from document/section
state to a Rich :class:`~rich.text.Text`, so the shapes are unit-testable
without booting an App.
"""

from __future__ import annotations

from typing import Any

from rich.cells import cell_len
from rich.text import Text

from sase.pager._chrome_history import (
    history_badge,
    history_context,
    honest_chip,
    pill_forms,
    state_moment,
)
from sase.pager._chrome_sections import section_accent, section_icon
from sase.pager._trail_chrome_model import MUTED_STYLE
from sase.pager._trail_chrome_text import append_path_label
from sase.pager.document import PagerDocument, PagerSection


def _format_char_count(count: int) -> str:
    """Format a character count for the subject line's ``⌘`` readout."""
    if count < 1_000:
        return f"{count}c"
    if count < 1_000_000:
        return f"{count / 1_000:.1f}Kc"
    return f"{count / 1_000_000:.1f}Mc"


def subject_parts(
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
) -> tuple[Text, Text]:
    """Return the subject line's ``(left, right)`` halves.

    Same inputs and truncation as :func:`subject_line`; framed panes paint
    the halves as border title/subtitle instead of one padded row.

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
    glyph = section_icon(current_section.kind)
    accent = section_accent(current_section.kind)

    show_section_title = section_total > 1 and current_section.title != document.title

    base_right = []
    if section_total > 1:
        base_right.append(f"{section_index}/{section_total}")
    base_right.append(f"{scroll_percent}%")
    base_right_str = " · ".join(base_right)

    moment = state_moment(history_state)
    # The folded honest state rides in the chip when the time band folds
    # away, ahead of any pill and with no context.
    honest = honest_chip(history_state, styles)
    context_full = history_context(moment, history_state, styles)
    context_short = history_context(moment, history_state, styles, short=True)

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

    # Shedding order (§5.2): the pill keeps its full form while the
    # hint, the count, then the context shed (the Δ segment kept longest
    # in the diff view). Only then does the pill step through its shorter
    # forms, and finally the title middle-truncates. The pill is never
    # cropped and never reappears as width shrinks.
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
    forms = pill_forms(moment, history_state, styles) if honest is None else []
    full_pill = forms[0] if forms else None
    chosen: tuple[str, Text | None, Text | None, bool] | None = None
    if honest is not None:
        for right_str, context in stages:
            right_width = cell_len(right_str)
            context_width = cell_len(context.plain) if context is not None else 0
            pill_width = cell_len(honest.plain)
            if (
                width >= 1
                and glyph_prefix
                + full_title_width
                + pill_width
                + context_width
                + 1
                + (1 if context is not None else 0)
                + right_width
                <= width - 1
            ):
                chosen = (right_str, context, honest, True)
                break
    else:
        # Phase A: full pill while shedding hint, count, then context.
        for right_str, context in stages:
            if full_pill is None:
                pill: Text | None = None
                pill_width = 0
            else:
                pill = full_pill
                pill_width = cell_len(pill.plain)
            right_width = cell_len(right_str)
            context_width = cell_len(context.plain) if context is not None else 0
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
        # Phase B: context gone, base readout, pill shortens, title full.
        if chosen is None and full_pill is not None:
            for form in forms:
                pill_width = cell_len(form.plain)
                right_width = cell_len(base_right_str)
                if (
                    width >= 1
                    and glyph_prefix + full_title_width + pill_width + 1 + right_width
                    <= width - 1
                ):
                    chosen = (base_right_str, None, form, True)
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
            else history_badge(moment, history_state, styles, 0)
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
    return (left, right)


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
    left, right = subject_parts(
        document,
        current_section,
        section_index=section_index,
        section_total=section_total,
        scroll_percent=scroll_percent,
        char_count=char_count,
        width=width,
        syntax_hint=syntax_hint,
        history_state=history_state,
        history_styles=history_styles,
    )
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


__all__ = [
    "subject_line",
    "subject_parts",
]
