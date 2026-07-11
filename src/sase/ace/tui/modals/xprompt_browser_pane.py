"""Reusable XPrompt browser pane for the Config Center modal.

This widget hosts the body of the former ``XPromptBrowserModal`` (filter input,
grouped list, preview, and metadata) so it can live inside the **XPrompts** tab
of the :class:`ConfigCenterModal` content switcher. All behavior of the old
browser is preserved; the only structural change is that the surrounding
``ModalScreen`` chrome (centering container, escape handling, tab navigation)
now belongs to the host modal.
"""

from __future__ import annotations

from rich.syntax import Syntax
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.xprompt import get_all_prompts
from sase.xprompt.workflow_models import Workflow

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


class XPromptBrowserPane(XPromptBrowserActionsMixin, Vertical):
    """Pane for browsing, inspecting, and managing xprompts."""

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
    ]

    def __init__(self, project: str | None = None, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._project = project
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
        yield BrowserFilterInput(
            placeholder="Type to filter...",
            id="browser-filter-input",
        )
        with Horizontal(id="browser-panels"):
            with Vertical(id="browser-list-panel"):
                yield OptionList(*self._create_options(), id="browser-list")
            with Vertical(id="browser-preview-panel"):
                with VerticalScroll(id="browser-preview-scroll"):
                    yield Static("", id="browser-preview")
                yield Static("", id="browser-meta")
        yield Static(self._hint_text(loadable=False), id="browser-hints", markup=False)

    def _hint_text(self, *, loadable: bool) -> str:
        """Return the hint line for the current loadability state."""
        return browser_hint_text(loadable=loadable)

    def _set_hints(self, *, loadable: bool) -> None:
        """Sync the hint line to whether the current row is loadable."""
        try:
            hints = self.query_one("#browser-hints", Static)
        except Exception:
            return
        hints.update(self._hint_text(loadable=loadable))

    def _create_options(self) -> list[Option]:
        """Create OptionList items with group headers as disabled options."""
        return create_browser_options(self._grouped)

    def _create_item_label(self, item: BrowserItem) -> object:
        """Create styled label for an xprompt item."""
        return create_item_label(item)

    def on_mount(self) -> None:
        flat_items = self._get_flat_items()
        if flat_items:
            self._update_preview(flat_items[0])
            option_list = self.query_one("#browser-list", OptionList)
            self._skip_to_first_item(option_list)

    def focus_default(self) -> None:
        """Focus the filter input when the XPrompts tab activates."""
        try:
            self.query_one("#browser-filter-input", BrowserFilterInput).focus()
        except Exception:
            pass

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

    def on_input_changed(self, event: Input.Changed) -> None:
        self._rebuild_groups(event.value)
        option_list = self.query_one("#browser-list", OptionList)
        option_list.clear_options()
        for opt in self._create_options():
            option_list.add_option(opt)

        flat_items = self._get_flat_items()
        if flat_items:
            self._skip_to_first_item(option_list)
            self._update_preview(flat_items[0])
        else:
            self._clear_preview()

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        if event.option and event.option.id:
            opt_id = str(event.option.id)
            if opt_id.startswith("__header__"):
                return
            name = opt_id.removeprefix("item__")
            for item in self._get_flat_items():
                if item.name == name:
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
            filter_input = self.query_one("#browser-filter-input", BrowserFilterInput)
            filter_text = filter_input.value
        except Exception:
            filter_text = ""

        highlighted_item = self._get_highlighted_item()
        highlighted_name = highlighted_item.name if highlighted_item else None

        self._load_xprompts()
        self._rebuild_groups(filter_text)

        try:
            title = self.query_one("#browser-title", Label)
            title.update(f"XPrompt Browser [{len(self._all_items)} xprompts]")
        except Exception:
            pass

        option_list = self.query_one("#browser-list", OptionList)
        option_list.clear_options()
        for opt in self._create_options():
            option_list.add_option(opt)

        flat_items = self._get_flat_items()
        restored = False
        if highlighted_name:
            for i in range(option_list.option_count):
                try:
                    opt = option_list.get_option_at_index(i)
                    if opt.id == f"item__{highlighted_name}":
                        option_list.highlighted = i
                        for item in flat_items:
                            if item.name == highlighted_name:
                                self._update_preview(item)
                                break
                        restored = True
                        break
                except Exception:
                    continue

        if not restored and flat_items:
            self._skip_to_first_item(option_list)
            self._update_preview(flat_items[0])

    def _update_preview(self, item: BrowserItem) -> None:
        """Update the preview panel for an item."""
        self._set_hints(loadable=not is_yaml_backed_source(item.source_path))
        try:
            preview = self.query_one("#browser-preview", Static)
            meta = self.query_one("#browser-meta", Static)
        except Exception:
            return

        syntax = Syntax(
            create_preview_content(item.workflow),
            "markdown",
            theme="monokai",
            word_wrap=True,
        )
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
