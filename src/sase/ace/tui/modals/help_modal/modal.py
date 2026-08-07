"""Two-tab help modal for the ace TUI."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal, cast

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.css.query import NoMatches
from textual.screen import ModalScreen
from textual.widgets import ContentSwitcher, Input, Static

from ..base import CopyModeForwardingMixin

if TYPE_CHECKING:
    from ...app import AceApp

from ...keymaps import KeymapRegistry, key_display_name, load_keymap_registry
from ...widgets.panel_tab_strip import PanelTab, PanelTabStrip
from .bindings import (
    COLUMN_SPLITS,
    TAB_DISPLAY_NAMES,
    TabName,
    agents_bindings,
    axe_bindings,
    cls_bindings,
)
from .filter_bar import HelpFilterInput, build_filter_empty_state, build_filter_status
from .filter_model import (
    FilteredRow,
    FilterResult,
    balance_split,
    filter_sections,
    matches_title,
)
from .guide_view import build_guide_view
from .query_sections import add_query_history_section, add_saved_queries_section
from .sections_render import add_section

HelpPanelTab = Literal["help-keymaps-view", "help-guide-view"]

_HELP_KEYMAPS_TAB: HelpPanelTab = "help-keymaps-view"
_HELP_GUIDE_TAB: HelpPanelTab = "help-guide-view"
_HELP_PANEL_TAB_ORDER: tuple[HelpPanelTab, ...] = (
    _HELP_KEYMAPS_TAB,
    _HELP_GUIDE_TAB,
)
_HELP_PANEL_LABELS: dict[HelpPanelTab, str] = {
    _HELP_KEYMAPS_TAB: "Keymaps",
    _HELP_GUIDE_TAB: "Guide",
}
_TAB_ACCENTS: dict[TabName, str] = {
    "changespecs": "#00D7AF",
    "agents": "#87D7FF",
    "axe": "#FF5F5F",
}
_TAB_CLASSES: dict[TabName, str] = {
    "changespecs": "-tab-changespecs",
    "agents": "-tab-agents",
    "axe": "-tab-axe",
}


def _modal_key_display(key: str) -> str:
    display = key_display_name(key)
    if display in {"Tab", "Shift+Tab"}:
        return display.lower()
    return display


def _plain_rows(bindings: list[tuple[str, str]]) -> tuple[FilteredRow, ...]:
    """Wrap plain (key, description) bindings as runs-free ``FilteredRow``s."""
    return tuple(
        FilteredRow(key=key, description=description, key_runs=(), description_runs=())
        for key, description in bindings
    )


class HelpModal(CopyModeForwardingMixin, ModalScreen[None]):
    """Help panel with keymaps and per-tab guide views."""

    AUTO_FOCUS = "#help-keymaps-scroll"

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("question_mark", "close", "Close"),
        ("left_square_bracket", "prev_help_tab", "Prev Help Tab"),
        ("right_square_bracket", "next_help_tab", "Next Help Tab"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
        ("slash", "focus_filter", "Filter"),
        # Query history navigation (ChangeSpecs tab only)
        Binding("circumflex_accent", "go_prev_query", "Prev Query", show=False),
        Binding("underscore", "go_next_query", "Next Query", show=False),
    ]

    def __init__(
        self,
        current_tab: TabName,
        active_query: str | None = None,
        *,
        registry: KeymapRegistry | None = None,
        saved_queries: Mapping[str, str] | None = None,
        agents_launch_targets_available: bool = False,
        agents_plugins_installed: bool = True,
    ) -> None:
        """Initialize the help modal.

        Args:
            current_tab: The currently active app tab name.
            active_query: The current canonical query string (for highlighting).
            registry: Active keymap registry; defaults are used outside an app.
            saved_queries: Cached saved-query snapshot; falls back to storage only
                for standalone construction outside the app.
            agents_launch_targets_available: Agents guide launch-target state.
            agents_plugins_installed: Agents guide plugin-install state.
        """
        super().__init__()
        self._current_tab = current_tab
        self._active_query = active_query
        self._registry = registry
        self._saved_queries = dict(saved_queries) if saved_queries is not None else None
        self._agents_launch_targets_available = agents_launch_targets_available
        self._agents_plugins_installed = agents_plugins_installed
        self._active_panel_tab: HelpPanelTab = _HELP_KEYMAPS_TAB
        self._filter_query: str = ""
        self._filter_result: FilterResult | None = None

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        with Container(
            id="help-modal-container",
            classes=self._tab_class(),
        ):
            yield Static(self._build_title(), id="help-title")
            yield PanelTabStrip(
                self._help_panel_tabs(),
                self._active_panel_tab,
                id="help-tabs",
            )
            with ContentSwitcher(
                initial=self._active_panel_tab,
                id="help-content-switcher",
            ):
                with Vertical(id=_HELP_KEYMAPS_TAB):
                    with Horizontal(id="help-filter-bar"):
                        yield Static("/", id="help-filter-prompt")
                        yield HelpFilterInput(
                            placeholder="filter keymaps",
                            id="help-filter-input",
                            select_on_focus=False,
                        )
                        yield Static("", id="help-filter-status")
                    with VerticalScroll(id="help-keymaps-scroll"):
                        with Horizontal(id="help-columns"):
                            yield Static(
                                self._build_left_column(),
                                id="help-left-column",
                                classes="help-column",
                            )
                            yield Static(
                                self._build_right_column(),
                                id="help-right-column",
                                classes="help-column",
                            )
                        yield Static("", id="help-filter-empty")
                with Container(id=_HELP_GUIDE_TAB):
                    yield self._build_guide_view()
            yield Static(self._build_footer(), id="help-footer")

    def _tab_accent(self) -> str:
        return _TAB_ACCENTS[self._current_tab]

    def _tab_class(self) -> str:
        return _TAB_CLASSES[self._current_tab]

    def _help_panel_tabs(self) -> tuple[PanelTab, ...]:
        accent = self._tab_accent()
        return tuple(
            PanelTab(tab, _HELP_PANEL_LABELS[tab], accent)
            for tab in _HELP_PANEL_TAB_ORDER
        )

    def _build_title(self) -> Text:
        """Build the styled title."""
        text = Text()
        text.append("  ", style="")
        text.append("\u2726 ", style="bold #FFD700")
        text.append("sase ace Help", style="bold white")
        text.append(" \u2726", style="bold #FFD700")
        text.append("\n")
        tab_name = TAB_DISPLAY_NAMES.get(self._current_tab, self._current_tab)
        text.append(f"  {tab_name} Tab", style=self._tab_accent())
        return text

    def _build_footer(self) -> str:
        """Build the footer with configured tab-switch hints."""
        if self._filter_input_has_focus():
            return (
                "type to filter  |  ↑ / ↓ scroll  |  enter apply  |  esc clear filter"
            )
        km = self._get_km()
        next_tab = _modal_key_display(km.app.next_tab)
        prev_tab = _modal_key_display(km.app.prev_tab)
        return (
            "? / q / esc close  |  / filter  |  [ / ] panel tabs  |  "
            f"{next_tab} / {prev_tab} app tabs  |  Ctrl+D/U scroll"
        )

    def _filter_input_has_focus(self) -> bool:
        try:
            return self.query_one("#help-filter-input", HelpFilterInput).has_focus
        except (NoMatches, LookupError):
            return False

    def _current_filter_result(self) -> FilterResult:
        if self._filter_result is None:
            self._filter_result = filter_sections(
                self._get_bindings_for_tab(), self._filter_query
            )
        return self._filter_result

    def _append_query_panels(self, text: Text, result: FilterResult) -> None:
        km = self._get_km()
        saved_runs = (
            matches_title("Saved Queries", self._filter_query) if result.active else ()
        )
        if not result.active or saved_runs is not None:
            add_saved_queries_section(
                text,
                self._active_query,
                queries=self._saved_queries,
                saved_query_prefix=key_display_name(km.app.open_saved_query_picker),
                title_runs=saved_runs or (),
            )
        # Query history is ChangeSpecs-tab only
        if self._current_tab == "changespecs":
            history_runs = (
                matches_title("Query History", self._filter_query)
                if result.active
                else ()
            )
            if not result.active or history_runs is not None:
                d = key_display_name
                add_query_history_section(
                    text,
                    prev_key=d(km.app.prev_query),
                    next_key=d(km.app.next_query),
                    title_runs=history_runs or (),
                )

    def _query_panel_lead_lines(self, result: FilterResult) -> int:
        scratch = Text()
        self._append_query_panels(scratch, result)
        return len(scratch.plain.splitlines())

    def _build_left_column(self) -> Text:
        """Build the left column content."""
        text = Text()
        result = self._current_filter_result()
        self._append_query_panels(text, result)

        if not result.active:
            bindings = self._get_bindings_for_tab()
            split_idx = COLUMN_SPLITS.get(self._current_tab, 2)
            for section_name, section_bindings in bindings[:split_idx]:
                add_section(text, section_name, _plain_rows(section_bindings))
            return text

        lead_lines = len(text.plain.splitlines())
        split_idx = balance_split(result.sections, lead_lines=lead_lines)
        for section in result.sections[:split_idx]:
            add_section(text, section.name, section.rows, name_runs=section.name_runs)
        return text

    def _build_right_column(self) -> Text:
        """Build the right column content."""
        text = Text()
        result = self._current_filter_result()

        if not result.active:
            bindings = self._get_bindings_for_tab()
            split_idx = COLUMN_SPLITS.get(self._current_tab, 2)
            for section_name, section_bindings in bindings[split_idx:]:
                add_section(text, section_name, _plain_rows(section_bindings))
            return text

        lead_lines = self._query_panel_lead_lines(result)
        split_idx = balance_split(result.sections, lead_lines=lead_lines)
        for section in result.sections[split_idx:]:
            add_section(text, section.name, section.rows, name_runs=section.name_runs)

        return text

    def _build_guide_view(self) -> VerticalScroll:
        return build_guide_view(
            current_tab=self._current_tab,
            registry=self._get_km(),
            agents_launch_targets_available=self._agents_launch_targets_available,
            agents_plugins_installed=self._agents_plugins_installed,
        )

    def _get_km(self) -> KeymapRegistry:
        """Get the keymap registry from the app, falling back to defaults."""
        if self._registry is not None:
            return self._registry
        try:
            return cast("AceApp", self.app)._keymap_registry
        except Exception:
            return load_keymap_registry({})

    def _get_bindings_for_tab(
        self,
    ) -> list[tuple[str, list[tuple[str, str]]]]:
        """Get the keybinding sections for the current tab."""
        km = self._get_km()
        if self._current_tab == "changespecs":
            return cls_bindings(km)
        elif self._current_tab == "agents":
            return agents_bindings(km)
        else:  # axe
            return axe_bindings(km)

    def refresh_for_tab(
        self,
        current_tab: TabName,
        active_query: str | None,
        *,
        registry: KeymapRegistry | None = None,
        saved_queries: Mapping[str, str] | None = None,
        agents_launch_targets_available: bool = False,
        agents_plugins_installed: bool = True,
    ) -> None:
        """Refresh mounted help content for a new app-tab context."""
        self._current_tab = current_tab
        self._active_query = active_query
        if registry is not None:
            self._registry = registry
        if saved_queries is not None:
            self._saved_queries = dict(saved_queries)
        self._agents_launch_targets_available = agents_launch_targets_available
        self._agents_plugins_installed = agents_plugins_installed

        self._filter_result = None
        try:
            container = self.query_one("#help-modal-container", Container)
            self._update_container_tab_class(container)
            self.query_one("#help-title", Static).update(self._build_title())
            strip = self.query_one("#help-tabs", PanelTabStrip)
            strip.set_tabs(
                self._help_panel_tabs(),
                active_tab=self._active_panel_tab,
            )
        except (NoMatches, LookupError):
            return
        self._render_keymaps_content()
        self._refresh_guide_view()
        self._sync_footer()

    def _update_container_tab_class(self, container: Container) -> None:
        for tab_class in _TAB_CLASSES.values():
            container.remove_class(tab_class)
        container.add_class(self._tab_class())

    def _refresh_guide_view(self) -> None:
        try:
            guide_slot = self.query_one(f"#{_HELP_GUIDE_TAB}", Container)
        except (NoMatches, LookupError):
            return
        for child in list(guide_slot.children):
            child.remove()
        guide_slot.mount(self._build_guide_view())

    def _render_keymaps_content(self) -> None:
        """Recompute the filter and re-render the keymaps columns/status."""
        self._filter_result = None
        result = self._current_filter_result()
        try:
            self.query_one("#help-left-column", Static).update(
                self._build_left_column()
            )
            self.query_one("#help-right-column", Static).update(
                self._build_right_column()
            )
            self.query_one("#help-filter-status", Static).update(
                build_filter_status(result)
            )
            columns = self.query_one("#help-columns", Horizontal)
            empty = self.query_one("#help-filter-empty", Static)
        except (NoMatches, LookupError):
            return
        show_empty = result.active and result.keymap_count == 0
        if show_empty:
            empty.update(build_filter_empty_state(result.query))
        columns.display = not show_empty
        empty.display = show_empty

    def _sync_footer(self) -> None:
        try:
            self.query_one("#help-footer", Static).update(self._build_footer())
        except (NoMatches, LookupError):
            return

    def _focus_results(self) -> None:
        try:
            self.query_one("#help-keymaps-scroll", VerticalScroll).focus()
        except (NoMatches, LookupError):
            return

    def on_mount(self) -> None:
        """Rebuild instance bindings with configured app-local keys."""
        from textual.binding import BindingsMap

        km = self._get_km()
        new_bindings = [
            ("escape", "close", "Close"),
            ("q", "close", "Close"),
            ("question_mark", "close", "Close"),
            ("left_square_bracket", "prev_help_tab", "Prev Help Tab"),
            ("right_square_bracket", "next_help_tab", "Next Help Tab"),
            ("ctrl+d", "scroll_down", "Scroll down"),
            ("ctrl+u", "scroll_up", "Scroll up"),
            ("slash", "focus_filter", "Filter"),
        ] + [
            Binding(km.app.prev_query, "go_prev_query", "Prev Query", show=False),
            Binding(km.app.next_query, "go_next_query", "Next Query", show=False),
            Binding(
                km.app.next_tab,
                "next_tab",
                "Next Tab",
                show=False,
                priority=True,
            ),
            Binding(
                km.app.prev_tab,
                "prev_tab",
                "Prev Tab",
                show=False,
                priority=True,
            ),
        ]
        self._bindings = BindingsMap(new_bindings)

    def action_close(self) -> None:
        """Close the modal, or clear an open/active filter first."""
        if self._filter_query or self._filter_input_has_focus():
            self.action_clear_filter()
            return
        self.dismiss(None)

    def action_focus_filter(self) -> None:
        """Open the filter bar and focus it, switching to Keymaps if needed."""
        if self._active_panel_tab != _HELP_KEYMAPS_TAB:
            self._switch_help_tab(_HELP_KEYMAPS_TAB)
        try:
            bar = self.query_one("#help-filter-bar", Horizontal)
            input_widget = self.query_one("#help-filter-input", HelpFilterInput)
        except (NoMatches, LookupError):
            return
        bar.display = True
        input_widget.focus()
        input_widget.cursor_position = len(input_widget.value)
        self._sync_footer()

    def action_clear_filter(self) -> None:
        """Clear the active filter, hide the bar, and return to the results."""
        self._filter_query = ""
        try:
            input_widget = self.query_one("#help-filter-input", HelpFilterInput)
            bar = self.query_one("#help-filter-bar", Horizontal)
        except (NoMatches, LookupError):
            return
        input_widget.value = ""
        bar.display = False
        self._render_keymaps_content()
        self._focus_results()
        self._sync_footer()

    def action_apply_filter(self) -> None:
        """Keep the active filter applied and move focus to the results."""
        self._focus_results()
        self._sync_footer()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Live-filter the keymaps view as the filter bar's text changes."""
        if event.input.id != "help-filter-input":
            return
        self._filter_query = event.value
        self._render_keymaps_content()
        try:
            self.query_one("#help-keymaps-scroll", VerticalScroll).scroll_home(
                animate=False
            )
        except (NoMatches, LookupError):
            return

    def on_input_blurred(self, event: Input.Blurred) -> None:
        if event.input.id != "help-filter-input":
            return
        self._sync_footer()

    @on(Input.Submitted, "#help-filter-input")
    def _on_filter_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.action_apply_filter()

    def _active_scroll(self) -> VerticalScroll:
        if self._active_panel_tab == _HELP_KEYMAPS_TAB:
            return self.query_one("#help-keymaps-scroll", VerticalScroll)
        guide_slot = self.query_one(f"#{_HELP_GUIDE_TAB}", Container)
        for child in guide_slot.children:
            if isinstance(child, VerticalScroll):
                return child
        return guide_slot.query_one(VerticalScroll)

    def action_scroll_down(self) -> None:
        """Scroll the active help view down by half a page."""
        scroll = self._active_scroll()
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def action_scroll_up(self) -> None:
        """Scroll the active help view up by half a page."""
        scroll = self._active_scroll()
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

    def _switch_help_tab(self, tab: HelpPanelTab) -> None:
        if tab == self._active_panel_tab:
            return
        self._active_panel_tab = tab
        try:
            self.query_one("#help-content-switcher", ContentSwitcher).current = tab
            self.query_one("#help-tabs", PanelTabStrip).set_active_tab(tab)
        except (NoMatches, LookupError):
            return

    def action_prev_help_tab(self) -> None:
        """Switch to the previous help-panel tab, wrapping."""
        index = _HELP_PANEL_TAB_ORDER.index(self._active_panel_tab)
        self._switch_help_tab(
            _HELP_PANEL_TAB_ORDER[(index - 1) % len(_HELP_PANEL_TAB_ORDER)]
        )

    def action_next_help_tab(self) -> None:
        """Switch to the next help-panel tab, wrapping."""
        index = _HELP_PANEL_TAB_ORDER.index(self._active_panel_tab)
        self._switch_help_tab(
            _HELP_PANEL_TAB_ORDER[(index + 1) % len(_HELP_PANEL_TAB_ORDER)]
        )

    @on(PanelTabStrip.TabClicked)
    def _on_panel_tab_clicked(self, event: PanelTabStrip.TabClicked) -> None:
        """Handle mouse selection of a Help panel tab."""
        event.stop()
        if event.tab_id in _HELP_PANEL_TAB_ORDER:
            self._switch_help_tab(cast(HelpPanelTab, event.tab_id))

    def action_next_tab(self) -> None:
        """Switch the underlying ACE app to the next tab."""
        cast("AceApp", self.app).action_next_tab()

    def action_prev_tab(self) -> None:
        """Switch the underlying ACE app to the previous tab."""
        cast("AceApp", self.app).action_prev_tab()

    # --- Query history navigation actions (ChangeSpecs tab only) ---

    def action_go_prev_query(self) -> None:
        """Navigate to previous query and close modal."""
        if self._current_tab != "changespecs":
            return
        self.dismiss(None)
        cast("AceApp", self.app).action_prev_query()

    def action_go_next_query(self) -> None:
        """Navigate to next query and close modal."""
        if self._current_tab != "changespecs":
            return
        self.dismiss(None)
        cast("AceApp", self.app).action_next_query()
