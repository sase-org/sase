"""Inline Vim-style search for the Agents metadata panel."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.containers import VerticalScroll
from textual.events import Key
from textual.widgets import Static

from ...keymaps import split_key_alternatives
from ...widgets.agent_detail import AgentDetail, AgentMetadataIdentityChanged
from ...widgets.prompt_panel import AgentPromptPanel
from ...widgets.renderable_text import renderable_to_text
from ...widgets.vim_search_controller import (
    SearchViewport,
    VimSearchController,
    VimSearchMode,
)
from ..clipboard import copy_to_system_clipboard

if TYPE_CHECKING:
    from textual.widget import Widget


_METADATA_LAYOUT_CLASSES = ("expanded", "layout-priority")


class AgentMetadataSearchMixin:
    """Host the shared Vim-search controller on ``AgentDetail``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._agent_metadata_search = VimSearchController(self)
        self._agent_metadata_search_identity: object | None = None
        self._agent_metadata_search_restore_focus: Widget | None = None
        self._agent_metadata_search_host_active = False
        super().__init__(*args, **kwargs)

    def _agent_metadata_search_can_start(self) -> bool:
        """Return whether the inline metadata surface may claim the keyboard."""
        if getattr(self, "current_tab", None) != "agents":
            return False
        if not bool(getattr(self, "_screen_stack", ())):
            return False
        prompt_input_active = getattr(self, "_prompt_input_active", None)
        if callable(prompt_input_active) and prompt_input_active():
            return False

        from textual.screen import ModalScreen

        return not (
            bool(getattr(self, "_screen_stack", ()))
            and isinstance(self.screen, ModalScreen)  # type: ignore[attr-defined]
        )

    def action_search_forward(self) -> None:
        """Start forward incremental search over the Agents metadata panel."""
        if self._agent_metadata_search_can_start():
            self._agent_metadata_search.start("forward")

    def action_search_reverse(self) -> None:
        """Start reverse incremental search over the Agents metadata panel."""
        if self._agent_metadata_search_can_start():
            self._agent_metadata_search.start("reverse")

    def _handle_agent_metadata_search_key(self, event: Key) -> bool:
        """Handle one key while inline metadata search owns the panel."""
        search = self._agent_metadata_search
        if not search.is_active:
            return False

        if search.mode == "committed":
            if event.key == "q":
                search.exit(
                    restore_scroll=True,
                    restore_from_current_overlay=True,
                    refresh=False,
                )
                return True
            if event.key in {"y", "Y"}:
                self._yank_agent_metadata_search(linewise=event.key == "Y")
                return True
            if self._scroll_agent_metadata_search(event.key):
                return True

        disposition = search.handle_key(
            event.key,
            event.character,
            passthrough_exit_keys=None,
        )
        return disposition == "consumed"

    def _scroll_agent_metadata_search(self, key: str) -> bool:
        """Apply registry-backed Vim scrolling without leaving search mode."""
        app_keys = self._keymap_registry.app  # type: ignore[attr-defined]
        actions = {
            "scroll_detail_down": (1, False),
            "scroll_detail_up": (-1, False),
            "scroll_prompt_down": (1, True),
            "scroll_prompt_up": (-1, True),
        }
        for action, (direction, full_page) in actions.items():
            configured = split_key_alternatives(getattr(app_keys, action))
            if key not in configured:
                continue
            scroll = self.query_one(  # type: ignore[attr-defined]
                "#agent-search-scroll",
                VerticalScroll,
            )
            height = max(1, scroll.scrollable_content_region.height)
            amount = height if full_page else max(1, height // 2)
            scroll.scroll_relative(y=direction * amount, animate=False)
            return True
        return False

    def _yank_agent_metadata_search(self, *, linewise: bool) -> None:
        """Copy the mouse selection, current match, or current match line."""
        search = self._agent_metadata_search
        selection = search.current_selection
        if selection is None or not (0 <= selection.index < len(search.match_spans)):
            self.notify("No search match to copy", severity="warning")  # type: ignore[attr-defined]
            return

        label = "match"
        content = ""
        if not linewise:
            get_selected_text = getattr(self.screen, "get_selected_text", None)  # type: ignore[attr-defined]
            if callable(get_selected_text):
                content = get_selected_text() or ""
                if content:
                    label = "selection"

        start, end = search.match_spans[selection.index]
        if not content and linewise:
            line_start = search.corpus.rfind("\n", 0, start) + 1
            line_end = search.corpus.find("\n", end)
            if line_end < 0:
                line_end = len(search.corpus)
            content = search.corpus[line_start:line_end]
            label = "match line"
        elif not content:
            content = search.corpus[start:end]

        if content and copy_to_system_clipboard(content):
            self.notify(f"Copied search {label} to clipboard")  # type: ignore[attr-defined]

    def _exit_agent_metadata_search_for_context_change(self) -> None:
        """Close a frozen overlay whose tab or selected identity changed."""
        if getattr(self, "current_tab", None) != "agents":
            self._agent_metadata_search_restore_focus = None
        if self._agent_metadata_search.is_active:
            self._agent_metadata_search.exit(
                restore_scroll=False,
                refresh=False,
            )

    def on_agent_metadata_identity_changed(
        self,
        message: AgentMetadataIdentityChanged,
    ) -> None:
        """Drop search when a background refresh replaces the selected row."""
        if (
            self._agent_metadata_search.is_active
            and message.identity != self._agent_metadata_search_identity
        ):
            self._exit_agent_metadata_search_for_context_change()
        message.stop()

    def _agent_detail(self) -> AgentDetail:
        return self.query_one("#agent-detail-panel", AgentDetail)  # type: ignore[attr-defined,no-any-return]

    # VimSearchController host protocol ---------------------------------

    def vim_search_corpus(self) -> str:
        """Capture the visible metadata renderable once per search."""
        if self._agent_metadata_search.is_active:
            return self._agent_metadata_search.corpus
        panel = self._agent_detail().query_one(
            "#agent-prompt-panel",
            AgentPromptPanel,
        )
        return renderable_to_text(getattr(panel, "content", None)) or ""

    def vim_search_origin_scroll(self) -> tuple[int, int]:
        """Return the native or already-active overlay scroll position."""
        selector = (
            "#agent-search-scroll"
            if self._agent_metadata_search.is_active
            else "#agent-prompt-scroll"
        )
        scroll = self._agent_detail().query_one(selector, VerticalScroll)
        return (int(scroll.scroll_x), int(scroll.scroll_y))

    def vim_search_overlay_viewport(self) -> SearchViewport:
        """Return inline overlay scroll position and visible dimensions."""
        scroll = self._agent_detail().query_one(
            "#agent-search-scroll",
            VerticalScroll,
        )
        return SearchViewport(
            scroll_x=int(scroll.scroll_x),
            scroll_y=int(scroll.scroll_y),
            width=scroll.scrollable_content_region.width,
            height=scroll.scrollable_content_region.height,
        )

    def vim_search_started(self) -> None:
        """Remember the frozen document identity and prior keyboard focus."""
        if self._agent_metadata_search_host_active:
            return
        detail = self._agent_detail()
        self._agent_metadata_search_host_active = True
        self._agent_metadata_search_identity = detail.metadata_identity
        self._agent_metadata_search_restore_focus = self.focused  # type: ignore[attr-defined]

    def vim_search_exited(self, *, refresh: bool) -> None:
        """Clear host-only state; native metadata continues refreshing."""
        del refresh
        self._agent_metadata_search_host_active = False
        self._agent_metadata_search_identity = None

    def vim_search_show_overlay(self) -> None:
        """Swap the native metadata scroll for its frozen search overlay."""
        detail = self._agent_detail()
        native = detail.query_one("#agent-prompt-scroll", VerticalScroll)
        search_scroll = detail.query_one("#agent-search-scroll", VerticalScroll)
        for class_name in _METADATA_LAYOUT_CLASSES:
            search_scroll.set_class(native.has_class(class_name), class_name)
        search_scroll.border_subtitle = native.border_subtitle
        native.add_class("hidden")
        search_scroll.remove_class("hidden")
        detail.query_one("#agent-search-command", Static).remove_class("hidden")

    def vim_search_hide_overlay(self) -> None:
        """Reveal the refreshed native panel and clear the frozen widgets."""
        detail = self._agent_detail()
        native = detail.query_one("#agent-prompt-scroll", VerticalScroll)
        search_scroll = detail.query_one("#agent-search-scroll", VerticalScroll)
        for class_name in _METADATA_LAYOUT_CLASSES:
            native.set_class(search_scroll.has_class(class_name), class_name)
        native.border_subtitle = search_scroll.border_subtitle
        detail.query_one("#agent-search-panel", Static).update("")
        search_scroll.add_class("hidden")
        native.remove_class("hidden")
        command = detail.query_one("#agent-search-command", Static)
        command.update("")
        command.border_title = ""
        command.border_subtitle = ""
        command.add_class("hidden")

    def vim_search_paint_overlay(self, content: Text) -> None:
        """Render highlighted corpus text in the frozen inline overlay."""
        self._agent_detail().query_one("#agent-search-panel", Static).update(content)

    def vim_search_command_width(self) -> int:
        """Return usable width inside the inline search command border."""
        command = self._agent_detail().query_one("#agent-search-command", Static)
        return max(0, int(command.size.width) - 4)

    def vim_search_paint_command_line(
        self,
        content: Text,
        mode: VimSearchMode,
    ) -> None:
        """Render the command line and mode-specific inline help."""
        command = self._agent_detail().query_one("#agent-search-command", Static)
        command.border_title = "search"
        if mode == "typing":
            command.border_subtitle = "[enter] accept  [esc/^c] cancel"
        else:
            command.border_subtitle = "[n/N] next/prev  [y] yank  [esc/q] close"
        command.update(content)
        command.remove_class("hidden")

    def vim_search_scroll_overlay(self, *, x: int, y: int) -> None:
        """Scroll the frozen metadata overlay immediately."""
        self._agent_detail().query_one(
            "#agent-search-scroll",
            VerticalScroll,
        ).scroll_to(x=x, y=y, animate=False, immediate=True)

    def vim_search_restore_scroll(self, *, x: int, y: int) -> None:
        """Restore the native metadata scroll after the overlay disappears."""

        def restore() -> None:
            scroll = self._agent_detail().query_one(
                "#agent-prompt-scroll",
                VerticalScroll,
            )
            scroll.scroll_to(x=x, y=y, animate=False, immediate=True)
            self._restore_agent_metadata_search_focus()

        self.call_after_refresh(restore)  # type: ignore[attr-defined]

    def vim_search_focus_overlay(self) -> None:
        """Focus the frozen overlay after it is made visible."""
        self.call_after_refresh(  # type: ignore[attr-defined]
            self._focus_agent_metadata_search_overlay
        )

    def vim_search_focus_native(self) -> None:
        """Restore the widget that owned focus before search began."""
        self.call_after_refresh(  # type: ignore[attr-defined]
            self._restore_agent_metadata_search_focus
        )

    def vim_search_notify(self, message: str) -> None:
        """Surface non-blocking inline-search feedback."""
        self.notify(message, severity="information")  # type: ignore[attr-defined]

    def _focus_agent_metadata_search_overlay(self) -> None:
        try:
            self._agent_detail().query_one(
                "#agent-search-scroll",
                VerticalScroll,
            ).focus()
        except Exception:
            pass

    def _restore_agent_metadata_search_focus(self) -> None:
        widget = self._agent_metadata_search_restore_focus
        self._agent_metadata_search_restore_focus = None
        if widget is None:
            return
        try:
            if widget.is_mounted:
                widget.focus()
        except Exception:
            pass


__all__ = ["AgentMetadataSearchMixin"]
