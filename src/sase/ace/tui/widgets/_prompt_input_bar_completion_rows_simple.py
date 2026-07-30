"""Simple rows for the prompt input completion panel."""

from __future__ import annotations

from rich.text import Text

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


def append_placeholder_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one reusable placeholder row with a source-specific badge."""
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


def append_prompt_word_completion_row(
    content: Text,
    candidate: CompletionCandidate,
    is_selected: bool,
) -> None:
    """Append one prompt-local word without a file-type icon."""
    content.append(candidate.display, style="bold" if is_selected else "")
