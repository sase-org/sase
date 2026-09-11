"""Composition and mount lifecycle for ``PromptInputBar``."""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_stack import PromptStackState
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

if TYPE_CHECKING:
    from textual.widget import Widget
    from textual.widgets import Static as _MixinBase
else:
    _MixinBase = object


class PromptInputBarLifecycleMixin(_MixinBase):
    """Widget composition and mount-time warmup."""

    if TYPE_CHECKING:
        _initial_cursor: tuple[int, int] | None
        _mode: str
        _placeholder: str
        _stack: PromptStackState
        _title_mode_suffix: str

        def _apply_active_classes(self) -> None: ...
        def _build_pane_widgets(self) -> list[Widget]: ...
        def _clamp_cursor_location(
            self,
            text_area: PromptTextArea,
            cursor: tuple[int, int],
        ) -> tuple[int, int]: ...
        def _compute_placeholder(self) -> str: ...
        def _cursor_to_end(self, text_area: PromptTextArea) -> None: ...
        def _refresh_dispatch_context_line(self) -> None: ...
        def _refresh_title(self, mode_suffix: str = "") -> None: ...
        def _schedule_height_update(self) -> None: ...
        def _schedule_xprompt_stale_check(self, *, force: bool = False) -> None: ...
        def _sync_todo_counts_from_mounted_panes(self) -> None: ...
        def _warm_dispatch_target_catalog(self) -> None: ...
        def active_text_area(self) -> PromptTextArea: ...
        def auto_show_frontmatter_panel(self) -> None: ...
        def insert_mode_subtitle(self) -> str: ...
        def refresh_cursor_readouts(self) -> None: ...
        def set_prompt_mode_subtitle(self, subtitle: str) -> None: ...

    def compose(self) -> ComposeResult:
        """Compose the input bar: completion / leader panels, then stack.

        The frontmatter panel sits directly above ``#prompt-stack`` (prompt mode
        only -- feedback / approve-prompt bars are not multi-agent surfaces) and
        starts hidden, auto-showing on mount when the prompt already carries
        frontmatter; otherwise the user opens it with ``g=``.
        """
        self._placeholder = self._compute_placeholder()
        yield Static("", id="prompt-completion", classes="hidden")
        if self._mode == "prompt":
            yield FrontmatterPanel(
                self._stack.frontmatter,
                id="frontmatter-panel",
                classes="hidden",
            )
            yield Static("", id="prompt-dispatch-context", classes="hidden")
        yield Static("", id="prompt-g-prefix-hints", classes="hidden")
        yield Static("", id="prompt-search-command", classes="hidden")
        with Vertical(id="prompt-stack"):
            yield from self._build_pane_widgets()

    def on_mount(self) -> None:
        """Focus the active pane on mount and position its cursor at end."""
        text_area = self.active_text_area()
        self.watch(self.app, "theme", self._app_theme_changed, init=False)
        self._sync_todo_counts_from_mounted_panes()
        text_area.focus()
        if self._initial_cursor is not None:
            text_area.cursor_location = self._clamp_cursor_location(
                text_area,
                self._initial_cursor,
            )
        else:
            self._cursor_to_end(text_area)

        # Border title and subtitle
        self._refresh_title()
        self.set_prompt_mode_subtitle(self.insert_mode_subtitle())
        if self._mode in ("feedback", "approve_prompt"):
            self.add_class("feedback-mode")
        self._schedule_xprompt_stale_check(force=True)
        text_area._warm_current_xprompt_assist_entries()
        text_area._warm_current_artifact_ref_completion_catalog()
        text_area._warm_vcs_project_completion_catalog()
        text_area._warm_model_completion_catalog()
        text_area._warm_prompt_path_inventory()
        text_area._warm_history_word_completion_cache()
        text_area._warm_common_placeholder_cache()
        text_area._on_prompt_completion_context_changed()
        self._warm_dispatch_target_catalog()
        self._refresh_dispatch_context_line()
        self._apply_active_classes()
        self.auto_show_frontmatter_panel()
        self._schedule_height_update()
        self.refresh_cursor_readouts()

    def _app_theme_changed(self) -> None:
        """Recompose theme-derived title chrome after an app theme switch."""
        if self.is_mounted:
            self._refresh_title(self._title_mode_suffix)
