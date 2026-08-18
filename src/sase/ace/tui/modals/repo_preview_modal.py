"""Purpose-built repo-mention preview modal."""

from __future__ import annotations

from typing import Any

from rich.console import Group, RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Markdown, Static

from sase.ace.tui.actions.clipboard import schedule_copy_delivery
from sase.xprompt.repo_mention_catalog import (
    EditorRepoMentionCatalog,
    RepoMention,
    synthesized_repo_description,
)

from ._source_file_actions import SourceFileActionsMixin
from .base import CopyModeForwardingMixin
from .repo_preview_render import (
    build_repo_chips,
    build_repo_property_grid,
    build_repo_title,
    repo_card_accent,
    repo_checkout_display,
    repo_checkout_path,
    repo_clones_display,
    repo_declaration_position,
    repo_not_cloned_hint,
    repo_source_path,
)


class RepoPreviewModal(
    CopyModeForwardingMixin,
    SourceFileActionsMixin,
    ModalScreen[None],
):
    """Display one repo mention as a structured repo card."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("y", "copy_description", "Copy description"),
        ("p", "copy_checkout_path", "Copy checkout path"),
        ("Y", "copy_path", "Copy path"),
        ("shift+y", "copy_path", "Copy path"),
        ("o", "open_in_editor", "Open in editor"),
        ("Z", "open_in_viewer", "Open in viewer"),
        ("shift+z", "open_in_viewer", "Open in viewer"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("j", "scroll_line_down", "Line down"),
        ("k", "scroll_line_up", "Line up"),
        ("g", "scroll_top", "Top"),
        ("G", "scroll_bottom", "Bottom"),
        ("shift+g", "scroll_bottom", "Bottom"),
    ]

    def __init__(
        self,
        catalog: EditorRepoMentionCatalog,
        mention: RepoMention,
        *,
        matched_text: str | None,
    ) -> None:
        super().__init__()
        self._catalog = catalog
        self._mention = mention
        self._matched_text = matched_text
        self._accent = _FALLBACK_ACCENT
        self._workspace_num: int | None = None

    def compose(self) -> ComposeResult:
        self._accent = repo_card_accent(self.app.current_theme)
        self._workspace_num = _active_workspace_num(self.app)
        with Container(id="repo-preview-container"):
            yield Static(self._build_title(), id="repo-preview-title")
            with VerticalScroll(id="repo-preview-scroll"):
                yield Markdown(
                    self._description_text(),
                    id="repo-preview-description",
                )
                yield Static(self._build_meta(), id="repo-preview-meta")
            yield Static(self._build_footer(), id="repo-preview-footer")

    def action_close(self) -> None:
        self.dismiss(None)

    def action_copy_description(self) -> None:
        schedule_copy_delivery(
            self,
            self._description_text().strip(),
            copied_label="repo description",
            task_name="sase-repo-preview-copy-description",
        )

    def action_copy_checkout_path(self) -> None:
        path, _exists = repo_checkout_path(
            self._mention, workspace_num=self._workspace_num
        )
        schedule_copy_delivery(
            self,
            path,
            copied_label="checkout path",
            task_name="sase-repo-preview-copy-checkout-path",
        )

    def _source_action_path(self) -> str | None:
        return repo_source_path(self._mention)

    def _source_action_position(self) -> tuple[int | None, int | None]:
        return repo_declaration_position(self._mention)

    def _description_text(self) -> str:
        return synthesized_repo_description(self._mention.record)

    def _build_title(self) -> RenderableType:
        return build_repo_title(
            self._mention,
            matched_text=self._matched_text,
            accent=self._accent,
        )

    def _build_meta(self) -> RenderableType:
        sections: list[RenderableType] = [
            build_repo_chips(self._mention, accent=self._accent)
        ]

        path, exists = repo_checkout_path(
            self._mention, workspace_num=self._workspace_num
        )
        property_grid = build_repo_property_grid(
            self._mention,
            checkout_display=repo_checkout_display(path, exists=exists),
            clones_display=repo_clones_display(self._mention),
            accent=self._accent,
        )
        sections.append(Text("-" * 66, style="dim"))
        sections.append(property_grid)

        hint = repo_not_cloned_hint(self._mention, exists=exists)
        if hint is not None:
            sections.append(Text(hint, style="dim"))
        return Group(*sections)

    def _build_footer(self) -> str:
        parts = ["j/k", "y desc", "p path"]
        if self._source_action_path():
            parts.extend(("Y path", "o edit", "Z view"))
        parts.append("esc")
        parts.append("Ctrl+] opens the repo")
        return " | ".join(parts)

    def action_scroll_down(self) -> None:
        scroll = self.query_one("#repo-preview-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=height, animate=False)

    def action_scroll_up(self) -> None:
        scroll = self.query_one("#repo-preview-scroll", VerticalScroll)
        height = max(1, scroll.scrollable_content_region.height // 2)
        scroll.scroll_relative(y=-height, animate=False)

    def action_scroll_line_down(self) -> None:
        scroll = self.query_one("#repo-preview-scroll", VerticalScroll)
        scroll.scroll_relative(y=1, animate=False)

    def action_scroll_line_up(self) -> None:
        scroll = self.query_one("#repo-preview-scroll", VerticalScroll)
        scroll.scroll_relative(y=-1, animate=False)

    def action_scroll_top(self) -> None:
        scroll = self.query_one("#repo-preview-scroll", VerticalScroll)
        scroll.scroll_home(animate=False)

    def action_scroll_bottom(self) -> None:
        scroll = self.query_one("#repo-preview-scroll", VerticalScroll)
        scroll.scroll_end(animate=False)


_FALLBACK_ACCENT = "#C3ABD8"


def _active_workspace_num(app: Any) -> int | None:
    ctx = getattr(app, "_prompt_context", None)
    if ctx is None or bool(getattr(ctx, "is_home_mode", False)):
        return None
    workspace_num = getattr(ctx, "workspace_num", None)
    return workspace_num if isinstance(workspace_num, int) else None


__all__ = ["RepoPreviewModal"]
