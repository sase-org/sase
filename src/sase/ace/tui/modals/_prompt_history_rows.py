"""List-row rendering helpers for the prompt history modal."""

from collections.abc import Callable
from datetime import datetime

from rich.text import Text

from sase.history.prompt_metadata import (
    PromptListSummary,
    summarize_prompt_for_list,
)

from ._prompt_history_models import PromptDisplayItem

_LAST_USED_WIDTH = 11
_MARKER_COL_WIDTH = 2
_PROJECT_COL_WIDTH = 14
_TAGS_COL_WIDTH = 16
_COLUMN_GAP_WIDTH = 2
_OPTION_HORIZONTAL_PADDING_WIDTH = 2
_MIN_PREVIEW_WIDTH = 16
_FALLBACK_PREVIEW_WIDTH = 132
_PROMPT_COL_START = (
    _MARKER_COL_WIDTH
    + _LAST_USED_WIDTH
    + _COLUMN_GAP_WIDTH
    + _PROJECT_COL_WIDTH
    + _COLUMN_GAP_WIDTH
    + _TAGS_COL_WIDTH
    + _COLUMN_GAP_WIDTH
)
_PROJECT_PLACEHOLDER = "—"

_ListSummaryFactory = Callable[[str], PromptListSummary]


def ellipsize_right(value: str, width: int) -> str:
    """Trim text to width, reserving space for an ellipsis when possible."""
    if width <= 0:
        return ""
    if len(value) <= width:
        return value
    if width <= 3:
        return "." * width
    return f"{value[: width - 3]}..."


def format_history_timestamp(timestamp: str) -> str:
    """Format SASE history timestamps as compact MM-DD HH:MM values."""
    raw_timestamp = timestamp.strip()
    try:
        return datetime.strptime(raw_timestamp, "%y%m%d_%H%M%S").strftime("%m-%d %H:%M")
    except ValueError:
        return raw_timestamp[:_LAST_USED_WIDTH].ljust(_LAST_USED_WIDTH)


def prompt_history_header_text() -> Text:
    """Return the fixed-column header aligned with prompt-history rows."""
    text = Text(no_wrap=True, overflow="crop", style="bold dim")
    text.append(" " * _MARKER_COL_WIDTH)
    text.append(f"{'WHEN':<{_LAST_USED_WIDTH}}")
    text.append(" " * _COLUMN_GAP_WIDTH)
    text.append(f"{'PROJECT':<{_PROJECT_COL_WIDTH}}")
    text.append(" " * _COLUMN_GAP_WIDTH)
    text.append(f"{'TAGS':<{_TAGS_COL_WIDTH}}")
    text.append(" " * _COLUMN_GAP_WIDTH)
    text.append("PROMPT")
    return text


def prompt_preview_width_for_list_content(list_content_width: int) -> int:
    """Return prompt-preview column width from the laid-out list content width."""
    if list_content_width <= 0:
        return _FALLBACK_PREVIEW_WIDTH
    text_width = list_content_width - _OPTION_HORIZONTAL_PADDING_WIDTH
    return max(_MIN_PREVIEW_WIDTH, text_width - _PROMPT_COL_START)


def create_prompt_history_label(
    item: PromptDisplayItem,
    *,
    preview_width: int = _FALLBACK_PREVIEW_WIDTH,
    summarize_for_list: _ListSummaryFactory | None = None,
) -> Text:
    """Create a single-line styled label for a prompt history item."""
    text = Text(no_wrap=True, overflow="ellipsis")
    is_cancelled = item.entry.cancelled or item.marker == "x"
    summary = _get_prompt_list_summary(item, summarize_for_list)

    if is_cancelled:
        text.append("x ", style="magenta")
    else:
        text.append("  ")

    metadata_style = "dim italic" if is_cancelled else "dim"
    prompt_style = "dim italic" if is_cancelled else ""
    project_ref_style = "dim italic" if is_cancelled else "cyan"
    xprompt_style = "dim italic" if is_cancelled else "green"
    directive_style = "dim italic" if is_cancelled else "yellow"

    last_used = format_history_timestamp(item.entry.last_used)
    prompt = ellipsize_right(
        summary.clean_preview,
        preview_width,
    )

    text.append(last_used, style=metadata_style)
    text.append(" " * _COLUMN_GAP_WIDTH, style="dim")
    _append_project_column(text, summary, metadata_style, project_ref_style)
    text.append(" " * _COLUMN_GAP_WIDTH, style="dim")
    _append_tag_columns(text, summary, xprompt_style, directive_style)
    text.append(" " * _COLUMN_GAP_WIDTH, style="dim")
    text.append(prompt, style=prompt_style)

    return text


def _get_prompt_list_summary(
    item: PromptDisplayItem,
    summarize_for_list: _ListSummaryFactory | None = None,
) -> PromptListSummary:
    """Return a cached list summary for a prompt display item."""
    if item.summary is None:
        summarizer: _ListSummaryFactory = summarize_prompt_for_list
        if summarize_for_list is not None:
            summarizer = summarize_for_list
        text = item.display_text if item.display_text is not None else item.entry.text
        item.summary = summarizer(text)
    return item.summary


def _append_project_column(
    text: Text,
    summary: PromptListSummary,
    metadata_style: str,
    project_ref_style: str,
) -> None:
    """Append the fixed-width project column to a history row."""
    if not summary.project_prefix and not summary.project_ref_display:
        text.append(_PROJECT_PLACEHOLDER, style=metadata_style)
        text.append(" " * (_PROJECT_COL_WIDTH - len(_PROJECT_PLACEHOLDER)))
        return

    prefix = summary.project_prefix
    ref_width = max(_PROJECT_COL_WIDTH - len(prefix), 0)
    ref = ellipsize_right(summary.project_ref_display, ref_width)
    if not ref and len(prefix) > _PROJECT_COL_WIDTH:
        prefix = ellipsize_right(prefix, _PROJECT_COL_WIDTH)

    text.append(prefix, style=metadata_style)
    if ref:
        text.append(ref, style=project_ref_style)

    padding = _PROJECT_COL_WIDTH - len(prefix) - len(ref)
    if padding > 0:
        text.append(" " * padding)


def _append_tag_columns(
    text: Text,
    summary: PromptListSummary,
    xprompt_style: str,
    directive_style: str,
) -> None:
    """Append the fixed-width xprompt/directive tag column."""
    tokens = [(chip, xprompt_style) for chip in summary.xprompts]
    if summary.directive_token:
        tokens.append((summary.directive_token, directive_style))

    rendered = _fit_tag_tokens(tokens, _TAGS_COL_WIDTH)
    used = _append_tag_tokens(text, rendered)
    padding = _TAGS_COL_WIDTH - used
    if padding > 0:
        text.append(" " * padding)


def _fit_tag_tokens(
    tokens: list[tuple[str, str]],
    width: int,
) -> list[tuple[str, str]]:
    """Fit styled tag tokens into a fixed-width list column."""
    if width <= 0 or not tokens:
        return []

    displayed: list[tuple[str, str]] = []
    hidden_count = 0
    for index, styled_token in enumerate(tokens):
        candidate = [*displayed, styled_token]
        if _tag_tokens_width(candidate) <= width:
            displayed = candidate
            continue
        hidden_count = len(tokens) - index
        break

    if hidden_count == 0:
        return displayed

    if not displayed:
        token_text, style = tokens[0]
        if len(tokens) == 1:
            return [(ellipsize_right(token_text, width), style)]
        suffix = f"+{len(tokens)}"
        return [(ellipsize_right(suffix, width), style)]

    overflow_style = displayed[-1][1]
    while displayed:
        suffix = f"+{hidden_count}" if hidden_count > 1 else "..."
        candidate = [*displayed, (suffix, overflow_style)]
        if _tag_tokens_width(candidate) <= width:
            return candidate
        displayed.pop()
        hidden_count += 1
        overflow_style = displayed[-1][1] if displayed else tokens[0][1]

    suffix = f"+{len(tokens)}"
    return [(ellipsize_right(suffix, width), tokens[0][1])]


def _tag_tokens_width(tokens: list[tuple[str, str]]) -> int:
    """Return plain-text width for space-separated tag tokens."""
    if not tokens:
        return 0
    return sum(len(token) for token, _style in tokens) + len(tokens) - 1


def _append_tag_tokens(text: Text, tokens: list[tuple[str, str]]) -> int:
    """Append fitted tag tokens and return their plain-text width."""
    used = 0
    for index, (token, style) in enumerate(tokens):
        if index:
            text.append(" ")
            used += 1
        text.append(token, style=style)
        used += len(token)
    return used
