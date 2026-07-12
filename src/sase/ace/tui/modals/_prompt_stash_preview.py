"""Shared preview pane and render builders for prompt-stash pickers."""

from __future__ import annotations

from dataclasses import dataclass

from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Label, Static

from sase.ace.tui.util.xprompt_syntax import highlight_prompt_text
from sase.core.prompt_stash_wire import PromptStashEntryWire
from sase.history.prompt_metadata import summarize_prompt_for_preview

from ._prompt_history_preview import append_metadata_row
from .prompt_stash_row import stash_row_age

_PROJECT_PLACEHOLDER = "—"
_NO_PROMPT_SELECTED = "No prompt selected"


@dataclass(frozen=True)
class _PromptStashPreviewContent:
    """Renderable pieces for one prompt-stash preview."""

    frontmatter: Text | None
    body: Text
    metadata: Text


def _build_prompt_stash_frontmatter(frontmatter: str) -> Text | None:
    """Build the optional YAML-highlighted stored frontmatter block."""
    if not frontmatter:
        return None
    try:
        return Syntax(frontmatter, "yaml", theme="monokai").highlight(frontmatter)
    except Exception:
        return Text(frontmatter, style="dim")


def _build_prompt_stash_metadata(
    entry: PromptStashEntryWire,
    *,
    prompt_count: int,
) -> Text:
    """Build the metadata footer for one stash entry."""
    summary = summarize_prompt_for_preview(entry.text)
    metadata = Text()
    metadata.append("\n--- Metadata ---\n", style="dim")
    append_metadata_row(metadata, "Project", entry.project or _PROJECT_PLACEHOLDER)
    if summary.xprompts:
        append_metadata_row(
            metadata,
            "Workflows",
            ", ".join(summary.xprompts),
            value_style="green",
        )
    if summary.directives:
        append_metadata_row(
            metadata,
            "Directives",
            ", ".join(summary.directives),
            value_style="yellow",
        )
    if prompt_count > 1:
        append_metadata_row(
            metadata, "Prompts", str(prompt_count), value_style="magenta"
        )
    append_metadata_row(metadata, "Created", stash_row_age(entry))
    append_metadata_row(metadata, "Pinned", "yes" if entry.pinned else "no")
    append_metadata_row(metadata, "Source", entry.source or _PROJECT_PLACEHOLDER)
    return metadata


def _build_prompt_stash_preview(
    entry: PromptStashEntryWire,
    *,
    prompt_count: int,
    highlighted_body: Text | None = None,
) -> _PromptStashPreviewContent:
    """Build all renderable pieces for one stash entry."""
    return _PromptStashPreviewContent(
        frontmatter=_build_prompt_stash_frontmatter(entry.frontmatter),
        body=(
            highlighted_body
            if highlighted_body is not None
            else highlight_prompt_text(entry.text)
        ),
        metadata=_build_prompt_stash_metadata(entry, prompt_count=prompt_count),
    )


class PromptStashPreviewPane(Vertical):
    """Reusable full-text preview pane for prompt-stash picker modals."""

    def compose(self) -> ComposeResult:
        yield Label("Preview", classes="prompt-stash-preview-label")
        with VerticalScroll(classes="prompt-stash-preview-scroll"):
            yield Static(
                _NO_PROMPT_SELECTED,
                classes="prompt-stash-preview-placeholder",
                markup=False,
            )
            yield Static(
                "",
                classes="prompt-stash-preview-frontmatter hidden",
                markup=False,
            )
            yield Static("", classes="prompt-stash-preview-body", markup=False)
            yield Static("", classes="prompt-stash-preview-metadata", markup=False)

    def show_entry(
        self,
        entry: PromptStashEntryWire,
        *,
        prompt_count: int,
        highlighted_body: Text | None = None,
    ) -> None:
        """Render *entry* and reset the preview scroll position."""
        content = _build_prompt_stash_preview(
            entry,
            prompt_count=prompt_count,
            highlighted_body=highlighted_body,
        )
        placeholder = self.query_one(".prompt-stash-preview-placeholder", Static)
        frontmatter = self.query_one(".prompt-stash-preview-frontmatter", Static)
        body = self.query_one(".prompt-stash-preview-body", Static)
        metadata = self.query_one(".prompt-stash-preview-metadata", Static)
        placeholder.add_class("hidden")
        if content.frontmatter is None:
            frontmatter.update("")
            frontmatter.add_class("hidden")
        else:
            frontmatter.update(content.frontmatter)
            frontmatter.remove_class("hidden")
        body.update(content.body)
        metadata.update(content.metadata)
        self.reset_scroll()

    def show_placeholder(self) -> None:
        """Show the empty-selection placeholder."""
        self.query_one(".prompt-stash-preview-placeholder", Static).remove_class(
            "hidden"
        )
        frontmatter = self.query_one(".prompt-stash-preview-frontmatter", Static)
        frontmatter.update("")
        frontmatter.add_class("hidden")
        self.query_one(".prompt-stash-preview-body", Static).update("")
        self.query_one(".prompt-stash-preview-metadata", Static).update("")
        self.reset_scroll()

    def reset_scroll(self) -> None:
        """Reset the preview to its first line."""
        self.query_one(".prompt-stash-preview-scroll", VerticalScroll).scroll_home(
            animate=False
        )

    def scroll_half_page(self, direction: int) -> None:
        """Scroll half a viewport in *direction* (``1`` down, ``-1`` up)."""
        scroll = self.query_one(".prompt-stash-preview-scroll", VerticalScroll)
        amount = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=direction * amount, animate=False)


__all__ = ["PromptStashPreviewPane"]
