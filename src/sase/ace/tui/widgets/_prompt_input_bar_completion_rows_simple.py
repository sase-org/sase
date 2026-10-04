"""Simple rows for the prompt input completion panel."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets._completion_match_highlight import append_highlighted
from sase.ace.tui.widgets._ranking_signal_rows import (
    build_score_meter,
    format_reason_chip,
    ranking_label_width,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.history_word_completion import (
    HistoryWordCompletionMetadata,
)
from sase.ace.tui.widgets.jinja_completion import JinjaCompletionMetadata
from sase.ace.tui.widgets.placeholder_completion import PlaceholderCompletionMetadata
from sase.ace.tui.widgets.macro_arg_assist import (
    MacroArgNameMetadata,
    MacroAssistEntry,
    append_input_hints,
    input_default_style,
    input_default_suffix,
    input_name_style,
)

_PROMPT_PLACEHOLDER_BADGE = "<> "
_PROMPT_PLACEHOLDER_STYLE = "cyan"
_COMMON_PLACEHOLDER_BADGE = "◆  "
_COMMON_PLACEHOLDER_STYLE = "#D7AF5F"
_PLACEHOLDER_LABEL_WIDTH_CAP = 28


def append_xprompt_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one xprompt completion row using assist metadata when present."""
    content.append(
        candidate.display,
        style="bold green" if is_selected else "green",
    )
    entry = (
        candidate.metadata if isinstance(candidate.metadata, MacroAssistEntry) else None
    )
    if entry is None:
        return

    kind = "skill" if entry.is_skill else entry.kind
    content.append(f"  {kind}", style="dim")
    # A ``#skill/foo`` row also advertises the ``/foo`` name the same source
    # installs as; the slash row already shows that name as its display.
    if entry.is_skill and entry.skill_name and not candidate.display.startswith("/"):
        content.append(f"  /{entry.skill_name}", style="dim")
    if entry.description:
        content.append(f"  {entry.description}", style="dim")
    append_input_hints(content, entry.inputs)


def xprompt_arg_name_label_width(candidate: CompletionCandidate) -> int:
    """Visible width for the keyword name payload column."""
    return cell_len(candidate.display)


def append_xprompt_arg_name_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    *,
    label_width: int,
    inner_width: int,
) -> None:
    """Append one keyword-argument name row with input metadata columns."""
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, MacroArgNameMetadata)
        else None
    )
    if metadata is None:
        content.append(
            candidate.display,
            style="bold yellow" if is_selected else "yellow",
        )
        return

    input_hint = metadata.input_hint
    label = candidate.display
    label_style = input_name_style(input_hint)
    if is_selected:
        label_style = f"bold {label_style}"
    content.append(label, style=label_style)

    available = max(0, inner_width - 2)
    used = cell_len(label)
    label_padding = max(0, label_width - used) + 2
    type_text = input_hint.type
    type_cost = label_padding + cell_len(type_text)
    if available and used + type_cost > available:
        return

    content.append(" " * label_padding)
    content.append(type_text, style="dim")
    used += type_cost

    if not input_hint.required:
        suffix = input_default_suffix(input_hint)
        suffix_cost = 2 + cell_len(suffix)
        if not available or used + suffix_cost <= available:
            content.append("  ")
            content.append(suffix, style=input_default_style())
            used += suffix_cost

    if not input_hint.description:
        return
    description_cost = 2 + cell_len(input_hint.description)
    if available and used + description_cost > available:
        remaining = available - used
        if remaining <= 2:
            return
        description = Text(
            input_hint.description,
            style="dim",
            no_wrap=True,
            overflow="ellipsis",
        )
        description.truncate(remaining - 2, overflow="ellipsis")
        content.append("  ")
        content.append_text(description)
        return

    content.append("  ")
    content.append(input_hint.description, style="dim")


@dataclass(frozen=True, slots=True)
class JinjaRowStyles:
    """Theme-resolved styles for Jinja2 completion rows.

    Built once on the UI thread from the app theme and passed down as
    data, so the pure row renderer never touches the app. Name styles
    mirror the roles in ``_jinja_highlight.py`` (variables render as the
    editor will color them once inserted); each source badge chip gets a
    distinct theme color, with conditional rows in the warning color.
    """

    variable: str = "bold cyan"
    filter: str = "green"
    keyword: str = "bold magenta"
    badges: dict[str, str] = field(default_factory=dict)


def jinja_row_styles(theme: Any | None) -> JinjaRowStyles:
    """Resolve Jinja2 row styles from an app theme (or fallbacks)."""
    if theme is None:
        return JinjaRowStyles()
    return JinjaRowStyles(
        variable=_theme_style(theme, "secondary", "cyan", bold=True),
        filter=_theme_style(theme, "success", "green"),
        keyword=_theme_style(theme, "accent", "magenta", bold=True),
        badges={
            "input": _theme_color(theme, "secondary", "cyan"),
            "local": _theme_color(theme, "primary", "blue"),
            "loop": _theme_color(theme, "accent", "magenta"),
            "sase": _theme_color(theme, "success", "green"),
            "arg": _theme_color(theme, "secondary", "cyan"),
            "skill": _theme_color(theme, "primary", "blue"),
            "jinja": "dim",
            "%repeat": _theme_color(theme, "warning", "yellow"),
            "%wait": _theme_color(theme, "warning", "yellow"),
            "legacy": _theme_color(theme, "warning", "yellow"),
            "closes for": _theme_color(theme, "accent", "magenta"),
        },
    )


def _theme_color(theme: Any, name: str, fallback: str) -> str:
    """Return a theme color as a Rich style, or *fallback* when unusable."""
    try:
        value = str(getattr(theme, name, fallback) or fallback)
    except Exception:
        return fallback
    return value if value.startswith("#") else fallback


def _theme_style(theme: Any, name: str, fallback: str, *, bold: bool = False) -> str:
    """Return a (possibly bold) theme color as a Rich style."""
    color = _theme_color(theme, name, fallback)
    return f"bold {color}" if bold else color


def _jinja_badge_text(candidate: CompletionCandidate) -> str:
    """Return the source badge chip text for one Jinja2 candidate."""
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, JinjaCompletionMetadata)
        else None
    )
    if metadata is None:
        return "jinja"
    if metadata.legacy_for:
        return "legacy"
    if metadata.availability == "conditional":
        hint = metadata.hint or ""
        return "%wait" if "%wait" in hint else "%repeat"
    if metadata.closes:
        return "closes for"
    if metadata.slot == "member" and metadata.namespace == "loop":
        return "loop"
    return {
        "input": "input",
        "local": "local",
        "sase": "sase",
        "positional": "arg",
        "provider": "skill",
        "jinja": "jinja",
    }.get(metadata.source, "jinja")


def jinja_label_width(candidate: CompletionCandidate) -> int:
    """Visible width of the name column for one Jinja2 candidate."""
    return cell_len(candidate.display)


def jinja_badge_width(candidate: CompletionCandidate) -> int:
    """Visible width of the badge chip column for one Jinja2 candidate."""
    return cell_len(_jinja_badge_text(candidate))


def append_jinja_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    *,
    label_width: int,
    badge_width: int,
    inner_width: int,
    styles: JinjaRowStyles | None = None,
) -> None:
    """Append one engine-backed Jinja2 completion row.

    The grid mirrors the xprompt arg-name menu: the name is styled as
    the editor's Jinja highlighter will color that token kind once
    inserted (with fuzzy match runs highlighted), then the type or
    signature, a fixed-width source badge chip, the ``=default`` for
    optional inputs, and a truncated dim description. Conditional and
    legacy rows render dim.
    """
    palette = styles or JinjaRowStyles()
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, JinjaCompletionMetadata)
        else None
    )
    kind = metadata.kind if metadata is not None else "variable"
    if kind in ("variable", "member"):
        name_style = palette.variable
    elif kind in ("filter", "function", "test"):
        name_style = palette.filter
    else:
        name_style = palette.keyword
    dimmed = metadata is not None and (
        metadata.availability == "conditional" or metadata.legacy_for is not None
    )
    if is_selected:
        name_style = f"bold {name_style}"
    base_style = f"dim {name_style}" if dimmed else name_style
    runs = metadata.match_runs if metadata is not None else ()
    append_highlighted(
        content,
        candidate.display,
        runs,
        base_style=base_style,
    )

    available = max(0, inner_width - 2)
    used = cell_len(candidate.display)
    name_padding = max(0, label_width - used) + 2
    type_text = ""
    if metadata is not None:
        type_text = metadata.signature or metadata.type_label or ""
    type_cost = name_padding + cell_len(type_text)
    if available and used + type_cost > available:
        return
    content.append(" " * name_padding)
    if type_text:
        content.append(type_text, style="dim")
    used += type_cost

    badge = _jinja_badge_text(candidate)
    badge_style = palette.badges.get(badge, "dim")
    if dimmed and badge_style != "dim":
        badge_style = f"dim {badge_style}"
    badge_cost = 2 + badge_width
    if available and used + badge_cost > available:
        return
    content.append("  ")
    content.append(badge, style=badge_style)
    content.append(" " * max(0, badge_width - cell_len(badge)))
    used += badge_cost

    if (
        metadata is not None
        and metadata.source == "input"
        and not metadata.required
        and metadata.default_display
    ):
        suffix = f"={metadata.default_display}"
        suffix_cost = 2 + cell_len(suffix)
        if not available or used + suffix_cost <= available:
            content.append("  ")
            content.append(suffix, style=input_default_style())
            used += suffix_cost

    summary = metadata.summary if metadata is not None else None
    if not summary:
        return
    description_cost = 2 + cell_len(summary)
    if available and used + description_cost > available:
        remaining = available - used
        if remaining <= 2:
            return
        description = Text(summary, style="dim", no_wrap=True, overflow="ellipsis")
        description.truncate(remaining - 2, overflow="ellipsis")
        content.append("  ")
        content.append_text(description)
        return
    content.append("  ")
    content.append(summary, style="dim")


def placeholder_label_width(candidate: CompletionCandidate) -> int:
    """Visible width for the badge+label column of one placeholder row."""
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, PlaceholderCompletionMetadata)
        else None
    )
    is_common = metadata is not None and metadata.source == "common"
    badge = _COMMON_PLACEHOLDER_BADGE if is_common else _PROMPT_PLACEHOLDER_BADGE
    return ranking_label_width(
        candidate.display,
        badge_cells=cell_len(badge),
        cap=_PLACEHOLDER_LABEL_WIDTH_CAP,
    )


def append_placeholder_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    *,
    label_width: int,
    inner_width: int,
    signals_enabled: bool,
) -> None:
    """Append one reusable placeholder row with a source-specific badge.

    Saved rows carrying ranking evidence append the shared score meter and
    dominant-reason chip, degrading by width -- the chip is dropped first,
    then the meter, leaving exactly today's row. Prompt-local rows,
    ``recent``-mode rows (no ranking metadata), and rows rendered while
    ``signals_enabled`` is False stay exactly as they are today.
    """
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, PlaceholderCompletionMetadata)
        else None
    )
    is_common = metadata is not None and metadata.source == "common"
    badge = _COMMON_PLACEHOLDER_BADGE if is_common else _PROMPT_PLACEHOLDER_BADGE
    label_style = _COMMON_PLACEHOLDER_STYLE if is_common else _PROMPT_PLACEHOLDER_STYLE
    badge_style = _COMMON_PLACEHOLDER_STYLE if is_common else "dim cyan"

    content.append(badge, style=badge_style)
    content.append(
        candidate.display,
        style=f"bold {label_style}" if is_selected else label_style,
    )

    ranking = metadata.ranking if metadata is not None else None
    if ranking is None or not signals_enabled:
        return

    used = cell_len(badge) + cell_len(candidate.display)
    available = inner_width - 2 if inner_width > 0 else None

    meter = build_score_meter(ranking)
    gap_and_padding = label_width - used + 2
    used += gap_and_padding + meter.cell_len
    if available is not None and used > available:
        return
    content.append(" " * gap_and_padding)
    content.append_text(meter)

    chip = format_reason_chip(ranking)
    used += 2 + chip.cell_len
    if available is not None and used > available:
        return
    content.append("  ")
    content.append_text(chip)


def append_prompt_word_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
    *,
    inner_width: int | None = None,
    signals_enabled: bool = True,
) -> None:
    """Append one prompt-local word without a file-type icon.

    Rows the prediction model promotes for the preceding words append the
    sequence-context chip after the word (dropped when it would not fit),
    so promoted rows read as model-predicted without growing a meter
    column this menu otherwise never shows. Every other row renders
    exactly as before.
    """
    content.append(candidate.display, style="bold" if is_selected else "")
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, HistoryWordCompletionMetadata)
        else None
    )
    if metadata is None or metadata.reason != "context" or not signals_enabled:
        return
    chip = format_reason_chip(metadata)
    used = cell_len(candidate.display) + 2 + chip.cell_len
    available = None if inner_width is None else max(0, inner_width - 2)
    if available is not None and used > available:
        return
    content.append("  ")
    content.append_text(chip)
