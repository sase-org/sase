"""Open the Snippets panel from a prompt-bar ``gT`` / ``^GT`` request."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sase.ace.tui.widgets import PromptInputBar
    from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

    from ._types import PromptContext


@dataclass(frozen=True, slots=True)
class _SnippetPromptFocus:
    """Prompt pane state restored after the snippets panel closes."""

    text_area: PromptTextArea
    vim_mode: str
    cursor: tuple[int, int]
    selection: Any


class PromptBarSnippetsPanelMixin:
    """Handle ``PromptInputBar.SnippetPanelRequested`` from the app layer."""

    _prompt_context: PromptContext | None

    def on_prompt_input_bar_snippet_panel_requested(self, event: object) -> None:
        """Open the snippets panel seeded from the trigger under the cursor."""
        from ...modals import SnippetsPanel
        from ...widgets import PromptInputBar

        if not isinstance(event, PromptInputBar.SnippetPanelRequested):
            return

        restore = self._capture_snippet_prompt_focus()
        launch_workspace = self._snippet_panel_launch_workspace()

        def _on_dismissed(_result: object) -> None:
            self._restore_snippet_prompt_focus(restore)

        self.push_screen(  # type: ignore[attr-defined]
            SnippetsPanel(
                launch_workspace=launch_workspace,
                initial_trigger=event.trigger,
            ),
            _on_dismissed,
        )

    def _snippet_panel_launch_workspace(self) -> str | None:
        """Return the prompt's workspace so the panel can include it in the ring."""
        ctx = getattr(self, "_prompt_context", None)
        if ctx is None or getattr(ctx, "is_home_mode", False):
            return None
        workspace_dir = getattr(ctx, "workspace_dir", "")
        return workspace_dir or None

    def _capture_snippet_prompt_focus(self) -> _SnippetPromptFocus | None:
        """Record the focused prompt pane, vim mode, cursor, and selection."""
        bar = self._mounted_snippet_prompt_bar()
        if bar is None:
            return None
        try:
            text_area = bar.active_text_area()
            vim_mode = str(getattr(text_area, "_vim_mode", "insert") or "insert")
            cursor = text_area.cursor_location
            selection = getattr(text_area, "selection", None)
        except Exception:
            return None
        if not isinstance(cursor, tuple) or len(cursor) != 2:
            cursor = (0, 0)
        return _SnippetPromptFocus(
            text_area=text_area,
            vim_mode=vim_mode,
            cursor=(int(cursor[0]), int(cursor[1])),
            selection=selection,
        )

    def _restore_snippet_prompt_focus(
        self, restore: _SnippetPromptFocus | None
    ) -> None:
        """Return focus, vim mode, selection, and cursor to the opening pane."""
        if restore is None:
            return
        text_area = restore.text_area
        if not getattr(text_area, "is_mounted", False):
            bar = self._mounted_snippet_prompt_bar()
            if bar is None:
                return
            try:
                text_area = bar.active_text_area()
            except Exception:
                return
        try:
            text_area.focus()
            if restore.vim_mode == "insert":
                text_area._enter_insert_mode()
            else:
                text_area._enter_normal_mode()
            if restore.selection is not None:
                try:
                    text_area.selection = restore.selection
                except Exception:
                    pass
            text_area.cursor_location = restore.cursor
        except Exception:
            return

    def _mounted_snippet_prompt_bar(self) -> PromptInputBar | None:
        """Return the mounted prompt bar, or ``None``."""
        from ...widgets import PromptInputBar

        mounted = getattr(self, "_mounted_prompt_bar", None)
        if callable(mounted):
            bar = mounted()
            if bar is not None:
                return bar  # type: ignore[no-any-return]
        try:
            return self.query_one("#prompt-input-bar", PromptInputBar)  # type: ignore[attr-defined,no-any-return]
        except Exception:
            return None
