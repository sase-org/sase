"""Reusable XPrompt browser pane for the Config Center modal.

This widget hosts the body of the former ``XPromptBrowserModal`` (grouped
list, preview, metadata, and a slash-revealed live filter) so it can live as
the **XPrompts** child inside the Config catalog. Surrounding
``ModalScreen`` chrome (centering container, escape handling, tab navigation)
belongs to the host modal.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.xprompt import get_all_prompts
from sase.xprompt.workflow_models import Workflow

from ..actions.navigation.jump_hints import normalize_jump_key
from ..util.selection import ProgrammaticSelectionGuard, restore_selection_by_identity
from .config_center_session import SelectionBookmark
from ..util.frontmatter_syntax import markdown_document_syntax
from .pane_entry_jump import PaneEntryJumpMixin
from .xprompt_browser_actions import XPromptBrowserActionsMixin
from .xprompt_browser_catalog import (
    flatten_grouped_items,
    group_browser_items,
    item_matches_filter,
    load_browser_items,
)
from .xprompt_browser_filter_input import BrowserFilterInput
from .xprompt_browser_helpers import (
    BrowserItem,
    classify_source,
    is_yaml_backed_source,
)
from .xprompt_browser_options import (
    browser_hint_text,
    create_browser_options,
    create_item_label,
)
from .xprompt_browser_preview import (
    create_meta_text,
    create_preview_content,
    create_simple_preview,
    create_workflow_preview,
)

if TYPE_CHECKING:
    from .config_hub_pane import ConfigHubPane


class XPromptBrowserPane(PaneEntryJumpMixin, XPromptBrowserActionsMixin, Vertical):
    """Pane for browsing, inspecting, and managing xprompts."""

    can_focus = False
    _option_list_id = "browser-list"
    BINDINGS = [
        ("j", "next_option", "Next"),
        ("k", "prev_option", "Previous"),
        ("down", "next_option", "Next"),
        ("up", "prev_option", "Previous"),
        ("ctrl+n", "next_option", "Next"),
        ("ctrl+p", "prev_option", "Previous"),
        ("ctrl+o", "add_xprompt", "Add"),
        ("ctrl+i", "load_xprompt", "Load"),
        ("ctrl+d", "scroll_preview_down", "Scroll Down"),
        ("ctrl+u", "scroll_preview_up", "Scroll Up"),
        ("enter", "edit_xprompt", "Edit here"),
        ("E", "external_edit_xprompt", "External editor"),
        ("slash", "focus_filter", "Filter"),
        ("apostrophe", "jump_to_entry", "Jump"),
        ("left_square_bracket", "cycle_config_subtab_reverse", "Prev sub-tab"),
        ("right_square_bracket", "cycle_config_subtab", "Next sub-tab"),
    ]

    def __init__(
        self,
        project: str | None = None,
        *,
        bookmark: SelectionBookmark | None = None,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._project = project
        self._bookmark = bookmark or SelectionBookmark()
        self._selection_guard = ProgrammaticSelectionGuard()
        self._all_items: list[BrowserItem] = []
        self._grouped: list[tuple[str, list[BrowserItem]]] = []
        self._load_xprompts()

    def _load_xprompts(self) -> None:
        """Load all xprompts and organize them into groups."""
        self._all_items = load_browser_items(
            self._project,
            prompt_loader=get_all_prompts,
            source_classifier=classify_source,
        )
        self._rebuild_groups()

    def _rebuild_groups(self, filter_text: str = "") -> None:
        """Rebuild grouped items, optionally filtered."""
        self._grouped = group_browser_items(self._all_items, filter_text)

    def _item_matches_filter(self, item: BrowserItem, filter_lower: str) -> bool:
        """Return True when an item matches the filter."""
        return item_matches_filter(item, filter_lower)

    def _get_flat_items(self) -> list[BrowserItem]:
        """Get flat list of items from grouped data for index lookups."""
        return flatten_grouped_items(self._grouped)

    def compose(self) -> ComposeResult:
        total = len(self._all_items)
        yield Label(f"XPrompt Browser [{total} xprompts]", id="browser-title")
        filter_input = BrowserFilterInput(
            placeholder="Type to filter...",
            id="browser-filter-input",
        )
        filter_input.display = False
        yield filter_input
        with Horizontal(id="browser-panels"):
            with Vertical(id="browser-list-panel"):
                yield OptionList(*self._create_options(), id="browser-list")
            with Vertical(id="browser-preview-panel"):
                with VerticalScroll(id="browser-preview-scroll"):
                    yield Static("", id="browser-preview")
                yield Static("", id="browser-meta")
        yield Static(
            self._hint_text(loadable=False, filtering=False),
            id="browser-hints",
            markup=False,
        )

    def on_key(self, event: events.Key) -> None:
        """Drive jump mode for keys that arrive with the row list focused.

        An ``OptionList`` passes unhandled keys straight through -- without this
        handler a digit hint would fall through to the Admin Center's numbered
        tab bindings and switch tabs mid-jump. The filter editor routes jump
        keys itself in :meth:`BrowserFilterInput.on_key` while it has focus.
        """
        if self._filter_input_has_focus():
            return
        if self.jump_mode_active:
            key = normalize_jump_key(event.key, event.character)
            if self.handle_jump_key(key):
                event.prevent_default()
                event.stop()
                return
        if event.key == "apostrophe":
            event.prevent_default()
            event.stop()
            self.action_jump_to_entry()

    def _filter_input(self) -> BrowserFilterInput:
        """Return the pane-local filter editor."""
        return self.query_one("#browser-filter-input", BrowserFilterInput)

    def _filter_input_has_focus(self) -> bool:
        """Whether the filter input owns focus and handles jump keys itself."""
        try:
            return self._filter_input().has_focus
        except Exception:
            return False

    def _filter_is_visible(self) -> bool:
        """Whether the filter editor is currently in the layout."""
        try:
            return bool(self._filter_input().display)
        except Exception:
            return False

    def _hint_text(self, *, loadable: bool, filtering: bool | None = None) -> str:
        """Return the hint line for the current loadability/jump/filter state."""
        if self.jump_mode_active:
            action = "back" if self.jump_back_stack else "first"
            return f"JUMP ' {action}  <esc> cancel"
        if filtering is None:
            filtering = self._filter_is_visible()
        return browser_hint_text(loadable=loadable, filtering=filtering)

    def _set_hints(self, *, loadable: bool) -> None:
        """Sync the hint line to whether the current row is loadable."""
        try:
            hints = self.query_one("#browser-hints", Static)
        except Exception:
            return
        hints.update(self._hint_text(loadable=loadable))

    def _create_options(self) -> list[Option]:
        """Create OptionList items with group headers as disabled options."""
        return create_browser_options(self._grouped, hint_for=self.jump_hint_for)

    def _create_item_label(self, item: BrowserItem) -> object:
        """Create styled label for an xprompt item."""
        return create_item_label(item)

    def on_mount(self) -> None:
        try:
            self._filter_input().display = False
        except Exception:
            pass
        option_list = self.query_one("#browser-list", OptionList)
        self._restore_highlight_and_preview(option_list, filter_text="")

    def focus_default(self) -> None:
        """Focus the visible filter editor, otherwise the row list."""
        try:
            filter_input = self._filter_input()
            if filter_input.display:
                filter_input.focus()
                return
            self.query_one("#browser-list", OptionList).focus()
        except Exception:
            pass

    def _config_hub(self) -> ConfigHubPane | None:
        """Return the enclosing Config hub, if this pane is embedded in one."""
        from .config_hub_pane import ConfigHubPane

        node: object | None = self.parent
        while node is not None:
            if isinstance(node, ConfigHubPane):
                return node
            node = getattr(node, "parent", None)
        return None

    def action_cycle_config_subtab(self) -> None:
        """Cycle to the next Config catalog child when this pane is embedded."""
        hub = self._config_hub()
        if hub is not None:
            hub.action_cycle_subtab()

    def action_cycle_config_subtab_reverse(self) -> None:
        """Cycle to the previous Config catalog child when this pane is embedded."""
        hub = self._config_hub()
        if hub is not None:
            hub.action_cycle_subtab_reverse()

    def action_focus_filter(self) -> None:
        """Reveal the live filter editor and place the cursor for typing."""
        try:
            filter_input = self._filter_input()
        except Exception:
            return
        filter_input.display = True
        filter_input.focus()
        filter_input.cursor_position = len(filter_input.value)
        self._sync_hints()

    def _close_filter(self) -> None:
        """Hide the filter editor, keeping the applied query and list focus."""
        try:
            filter_input = self._filter_input()
        except Exception:
            return
        if not filter_input.display:
            return
        filter_input.display = False
        try:
            self.query_one("#browser-list", OptionList).focus()
        except Exception:
            pass
        self._sync_hints()

    def _sync_hints(self) -> None:
        """Refresh the hint line for the current row and filter visibility."""
        item = self._get_highlighted_item()
        self._set_hints(
            loadable=item is not None and not is_yaml_backed_source(item.source_path)
        )

    def _skip_to_first_item(self, option_list: OptionList) -> None:
        """Skip to the first non-header item."""
        for i in range(option_list.option_count):
            try:
                opt = option_list.get_option_at_index(i)
                if opt.id and not str(opt.id).startswith("__header__"):
                    option_list.highlighted = i
                    return
            except Exception:
                continue

    @staticmethod
    def _is_item_option(opt_id: object | None) -> bool:
        return bool(opt_id) and not str(opt_id).startswith("__header__")

    @staticmethod
    def _option_id_for_item(name: str) -> str:
        return f"item__{name}"

    def _option_index_for_item(self, option_list: OptionList, name: str) -> int | None:
        target = self._option_id_for_item(name)
        for index in range(option_list.option_count):
            try:
                if option_list.get_option_at_index(index).id == target:
                    return index
            except Exception:
                continue
        return None

    def _logical_row_for_item(self, name: str) -> int | None:
        for row, item in enumerate(self._get_flat_items()):
            if item.name == name:
                return row
        return None

    def _record_bookmark(self, item: BrowserItem | None, *, filter_text: str) -> None:
        if item is None:
            if not filter_text.strip() and not self._all_items:
                self._bookmark.record(None, None)
            return
        self._bookmark.record(item.name, self._logical_row_for_item(item.name))

    def _restore_highlight_and_preview(
        self,
        option_list: OptionList,
        *,
        filter_text: str,
        preferred_name: str | None = None,
    ) -> None:
        flat_items = self._get_flat_items()
        selected: BrowserItem | None = None
        self._selection_guard.clear()
        if flat_items:
            row = restore_selection_by_identity(
                flat_items,
                prior_identity=preferred_name or self._bookmark.identity,
                prior_visual_row=self._bookmark.row,
                identity_fn=lambda item: item.name,
            )
            selected = flat_items[row]
            option_index = self._option_index_for_item(option_list, selected.name)
            if option_index is not None:
                self._selection_guard.prepare(selected.name, row)
                option_list.highlighted = option_index
            else:
                selected = flat_items[0]
                option_index = self._option_index_for_item(option_list, selected.name)
                if option_index is not None:
                    self._selection_guard.prepare(selected.name, 0)
                    option_list.highlighted = option_index
        else:
            option_list.highlighted = None
        self._record_bookmark(selected, filter_text=filter_text)
        if selected is not None:
            self._update_preview(selected)
        else:
            self._clear_preview()

    def _current_filter_value(self) -> str:
        try:
            return self._filter_input().value
        except Exception:
            return ""

    def _repaint_options_and_select(self, preferred_name: str | None) -> None:
        """Rebuild the option rows and restore the selection by identity.

        Shared by the jump hooks below: entering/exiting jump mode repaints to
        add/remove hint prefixes, and completing a jump repaints and moves the
        selection in one step, all through the pane's existing highlight path.
        """
        option_list = self.query_one("#browser-list", OptionList)
        option_list.clear_options()
        for opt in self._create_options():
            option_list.add_option(opt)
        self._restore_highlight_and_preview(
            option_list,
            filter_text=self._current_filter_value(),
            preferred_name=preferred_name,
        )

    def _jump_target_count(self) -> int:
        return len(self._get_flat_items())

    def _jump_current_index(self) -> int | None:
        item = self._get_highlighted_item()
        if item is None:
            return None
        return self._logical_row_for_item(item.name)

    def _jump_select_index(self, index: int) -> None:
        flat_items = self._get_flat_items()
        if not 0 <= index < len(flat_items):
            return
        self._repaint_options_and_select(flat_items[index].name)

    def _jump_repaint(self) -> None:
        highlighted = self._get_highlighted_item()
        self._repaint_options_and_select(
            highlighted.name if highlighted is not None else None
        )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "browser-filter-input":
            return
        filter_text = event.value
        previous_names = [item.name for item in self._get_flat_items()]
        self._rebuild_groups(filter_text)
        next_items = self._get_flat_items()
        self.invalidate_jump_hints(
            identities_changed=previous_names != [item.name for item in next_items],
            target_count=len(next_items),
        )
        option_list = self.query_one("#browser-list", OptionList)
        option_list.clear_options()
        for opt in self._create_options():
            option_list.add_option(opt)

        self._restore_highlight_and_preview(option_list, filter_text=filter_text)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "browser-filter-input":
            return
        self._close_filter()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Enter on the row list edits the highlighted xprompt."""
        event.stop()
        if event.option is None or not self._is_item_option(event.option.id):
            return
        self.action_edit_xprompt()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option and event.option.id:
            opt_id = str(event.option.id)
            if opt_id.startswith("__header__"):
                return
            name = opt_id.removeprefix("item__")
            flat_items = self._get_flat_items()
            current = self._get_highlighted_item()
            current_row = (
                self._logical_row_for_item(current.name)
                if current is not None
                else None
            )
            if (
                current is None
                or current_row is None
                or name != current.name
                or self._selection_guard.should_ignore(
                    name,
                    current_row,
                    current_identity=current.name,
                    current_row=current_row,
                )
            ):
                return
            for item in flat_items:
                if item.name == name:
                    self._record_bookmark(item, filter_text="")
                    self._update_preview(item)
                    return

    def action_next_option(self) -> None:
        """Move to next non-header option."""
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        current = option_list.highlighted
        if current is None:
            self._skip_to_first_item(option_list)
            return
        for i in range(current + 1, option_list.option_count):
            try:
                opt = option_list.get_option_at_index(i)
                if opt.id and not str(opt.id).startswith("__header__"):
                    option_list.highlighted = i
                    return
            except Exception:
                continue

    def action_prev_option(self) -> None:
        """Move to previous non-header option."""
        option_list = self.query_one(f"#{self._option_list_id}", OptionList)
        current = option_list.highlighted
        if current is None:
            return
        for i in range(current - 1, -1, -1):
            try:
                opt = option_list.get_option_at_index(i)
                if opt.id and not str(opt.id).startswith("__header__"):
                    option_list.highlighted = i
                    return
            except Exception:
                continue

    def _get_highlighted_item(self) -> BrowserItem | None:
        """Get the currently highlighted browser item."""
        option_list = self.query_one("#browser-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            opt = option_list.get_option_at_index(highlighted)
            if opt.id and not str(opt.id).startswith("__header__"):
                name = str(opt.id).removeprefix("item__")
                for item in self._get_flat_items():
                    if item.name == name:
                        return item
        except Exception:
            pass
        return None

    def _highlighted_loadable_item(self) -> BrowserItem | None:
        """Return the highlighted item only when it is inline-loadable.

        Loadable means a non-YAML row: a standalone ``.md`` prompt-part xprompt.
        YAML-backed rows (workflow ``.yml`` files and config-backed entries) are
        ineligible for the ``Ctrl+I`` load keymap and yield ``None``.
        """
        item = self._get_highlighted_item()
        if item is None or is_yaml_backed_source(item.source_path):
            return None
        return item

    def highlighted_row_is_loadable(self) -> bool:
        """Return True when the highlighted row can be inline-loaded."""
        return self._highlighted_loadable_item() is not None

    def action_load_xprompt(self) -> None:
        """Inline-load the highlighted xprompt into the prompt bar (``Ctrl+I``).

        Mirrors the Select XPrompt ``Ctrl+I`` expansion: the highlighted row's
        body is rendered through :func:`expand_inline_xprompt`, the Admin Center
        closes, and the rendered body is loaded into a home-mode prompt input
        bar for editing/submission. YAML-backed rows are ineligible, so the
        keymap is a no-op for them (parity with the conditional hint text). On
        an expansion error the notification surfaces and the Admin Center stays
        open, matching the selector's failure semantics.
        """
        item = self._highlighted_loadable_item()
        if item is None:
            return

        from sase.ace.tui.widgets.xprompt_inline_expansion import (
            expand_inline_xprompt,
        )

        result = expand_inline_xprompt(item.name, item.workflow, project=self._project)
        if result.error is not None:
            self.notify(result.error, severity="error")
            return

        loader = getattr(self.app, "load_xprompt_into_home_prompt_bar", None)
        if not callable(loader):
            return
        loader(
            result.expanded_text or "",
            display_name=f"#{item.name}",
            inputs=result.inputs,
        )

    def _reload_xprompts(self) -> None:
        """Reload all xprompts and rebuild the list."""
        try:
            filter_text = self._filter_input().value
        except Exception:
            filter_text = ""

        highlighted_item = self._get_highlighted_item()
        highlighted_name = (
            highlighted_item.name if highlighted_item else self._bookmark.identity
        )
        previous_names = [item.name for item in self._get_flat_items()]

        self._load_xprompts()
        self._rebuild_groups(filter_text)
        next_items = self._get_flat_items()
        self.invalidate_jump_hints(
            identities_changed=previous_names != [item.name for item in next_items],
            target_count=len(next_items),
        )

        try:
            title = self.query_one("#browser-title", Label)
            title.update(f"XPrompt Browser [{len(self._all_items)} xprompts]")
        except Exception:
            pass

        option_list = self.query_one("#browser-list", OptionList)
        option_list.clear_options()
        for opt in self._create_options():
            option_list.add_option(opt)

        self._restore_highlight_and_preview(
            option_list,
            filter_text=filter_text,
            preferred_name=highlighted_name,
        )

    def _update_preview(self, item: BrowserItem) -> None:
        """Update the preview panel for an item."""
        self._set_hints(loadable=not is_yaml_backed_source(item.source_path))
        try:
            preview = self.query_one("#browser-preview", Static)
            meta = self.query_one("#browser-meta", Static)
        except Exception:
            return

        syntax = markdown_document_syntax(create_preview_content(item.workflow))
        preview.update(syntax)
        meta.update(create_meta_text(item))

    def _create_simple_preview(self, workflow: Workflow) -> str:
        """Create a preview for a simple xprompt."""
        return create_simple_preview(workflow)

    def _create_workflow_preview(self, workflow: Workflow) -> str:
        """Create a preview string for a workflow."""
        return create_workflow_preview(workflow)

    def _clear_preview(self) -> None:
        """Clear the preview panel."""
        self._set_hints(loadable=False)
        try:
            preview = self.query_one("#browser-preview", Static)
            meta = self.query_one("#browser-meta", Static)
            preview.update("")
            meta.update("")
        except Exception:
            pass

    def scroll_preview_down(self) -> None:
        """Scroll the preview panel down by half a page."""
        scroll = self.query_one("#browser-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def scroll_preview_up(self) -> None:
        """Scroll the preview panel up by half a page."""
        scroll = self.query_one("#browser-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

    def action_scroll_preview_down(self) -> None:
        """Action wrapper so the binding can scroll the preview down."""
        self.scroll_preview_down()

    def action_scroll_preview_up(self) -> None:
        """Action wrapper so the binding can scroll the preview up."""
        self.scroll_preview_up()


__all__ = [
    "XPromptBrowserPane",
    "classify_source",
    "get_all_prompts",
]
