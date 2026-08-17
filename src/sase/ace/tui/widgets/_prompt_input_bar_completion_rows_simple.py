"""Simple rows for the prompt input completion panel."""

from __future__ import annotations

from rich.cells import cell_len
from rich.text import Text

from sase.ace.tui.widgets._ranking_signal_rows import (
    build_score_meter,
    format_reason_chip,
    ranking_label_width,
)
from sase.ace.tui.widgets.file_completion import CompletionCandidate
from sase.ace.tui.widgets.jinja_completion import JinjaCompletionMetadata
from sase.ace.tui.widgets.placeholder_completion import PlaceholderCompletionMetadata
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    append_input_hints,
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
        candidate.metadata
        if isinstance(candidate.metadata, XPromptAssistEntry)
        else None
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


def append_jinja_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one Jinja2 completion row."""
    metadata = (
        candidate.metadata
        if isinstance(candidate.metadata, JinjaCompletionMetadata)
        else None
    )
    kind = metadata.kind if metadata is not None else "jinja"
    style_by_kind = {
        "variable": "cyan",
        "keyword": "magenta",
        "filter": "green",
    }
    style = style_by_kind.get(kind, "white")
    if is_selected:
        style = f"bold {style}"
    content.append(candidate.display, style=style)
    content.append(f"  {kind}", style="dim")


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
) -> None:
    """Append one prompt-local word without a file-type icon."""
    content.append(candidate.display, style="bold" if is_selected else "")
