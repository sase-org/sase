"""Preview-panel rendering helpers for the prompt history modal."""

from collections.abc import Callable

from rich.text import Text

from sase.history.prompt_metadata import (
    PromptPreviewSummary,
    summarize_prompt_for_preview,
)

from ._prompt_history_models import PromptDisplayItem
from ._prompt_history_rows import _PROJECT_PLACEHOLDER

_PreviewSummaryFactory = Callable[[str], PromptPreviewSummary]


def build_prompt_history_metadata(
    item: PromptDisplayItem,
    *,
    summarize_for_preview: _PreviewSummaryFactory | None = None,
) -> Text:
    """Build preview metadata for a prompt history item."""
    summarizer: _PreviewSummaryFactory = summarize_prompt_for_preview
    if summarize_for_preview is not None:
        summarizer = summarize_for_preview

    summary = summarizer(item.entry.text)
    meta_text = Text()
    meta_text.append("\n--- Metadata ---\n", style="dim")
    if item.entry.cancelled:
        append_metadata_row(
            meta_text,
            "Status",
            "Cancelled",
            value_style="magenta",
        )
    append_metadata_row(
        meta_text,
        "Project",
        preview_project_value(summary),
    )
    if summary.xprompts:
        append_metadata_row(
            meta_text,
            "Workflows",
            ", ".join(summary.xprompts),
            value_style="green",
        )
    if summary.directives:
        append_metadata_row(
            meta_text,
            "Directives",
            ", ".join(summary.directives),
            value_style="yellow",
        )
    append_metadata_row(meta_text, "Created", item.entry.timestamp)
    append_metadata_row(meta_text, "Last Used", item.entry.last_used)
    return meta_text


def append_metadata_row(
    meta_text: Text,
    label: str,
    value: str,
    *,
    value_style: str | None = None,
) -> None:
    """Append one aligned metadata row."""
    meta_text.append(f"{label + ':':<12}", style="bold")
    meta_text.append(f"{value}\n", style=value_style)


def preview_project_value(summary: PromptPreviewSummary) -> str:
    """Return the preview metadata value for a prompt project."""
    return summary.vcs_tag.strip() if summary.vcs_tag else _PROJECT_PLACEHOLDER
