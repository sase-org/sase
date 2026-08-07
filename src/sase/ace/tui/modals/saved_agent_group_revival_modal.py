"""Saved dismissed-agent group revival modal."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.actions.navigation.jump_hints import normalize_jump_key
from sase.core.agent_group_archive_wire import (
    SavedAgentGroupPageWire,
    SavedAgentGroupSummaryWire,
    SavedAgentGroupWire,
)

from .base import OptionListNavigationMixin
from .confirm_action_modal import ConfirmActionModal
from .confirm_dialog import ConfirmKind
from .pane_entry_jump import KeyedPaneEntryJumpMixin
from .saved_agent_group_revival_rendering import (
    apply_jump_hint_prefix,
    build_empty_groups_preview,
    build_load_more_preview,
    build_saved_group_preview,
    format_saved_group_row,
)

_CUSTOM_SEARCH_ID = "custom-search"
_EMPTY_ID = "empty"
_LOAD_MORE_ID = "load-more"
_RECENT_HEADING_ID = "heading:recent"
_SAVED_HEADING_ID = "heading:saved"
_RECENT_EMPTY_ID = "empty:recent"
_SAVED_EMPTY_ID = "empty:saved"
_SAVED_RECENT_SEPARATOR_ID = "sep:1"
_RECENT_ACTIONS_SEPARATOR_ID = "sep:2"
_RECENT_PREFIX = "recent:"
_GROUP_PREFIX = "group:"


@dataclass(frozen=True)
class SavedAgentGroupRevivalResult:
    """Result returned by the saved-group revival modal."""

    action: Literal["revive_group", "custom_search"]
    group_id: str | None = None
    location: Literal["saved", "recent"] = "saved"


class SavedAgentGroupRevivalModal(
    KeyedPaneEntryJumpMixin[str],
    OptionListNavigationMixin,
    ModalScreen[SavedAgentGroupRevivalResult | None],
):
    """Two-pane modal for saved dismissed-agent group revival."""

    _option_list_id = "saved-agent-group-list"
    BINDINGS = [
        *OptionListNavigationMixin.NAVIGATION_BINDINGS,
        Binding("pagedown", "load_more", "Load More", priority=True),
        Binding("apostrophe", "jump_to_entry", "Jump"),
        Binding("ctrl+d", "delete_group", "Delete", priority=True),
    ]

    def __init__(
        self,
        initial_page: SavedAgentGroupPageWire,
        *,
        recent_page: SavedAgentGroupPageWire | None = None,
        page_loader: Callable[[int | None], SavedAgentGroupPageWire] | None = None,
        group_loader: Callable[[str], SavedAgentGroupWire | None] | None = None,
        recent_group_loader: Callable[[str], SavedAgentGroupWire | None] | None = None,
        delete_callback: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__()
        self._recent_groups: list[SavedAgentGroupSummaryWire] = list(
            recent_page.groups if recent_page is not None else ()
        )
        self._groups: list[SavedAgentGroupSummaryWire] = list(initial_page.groups)
        self._next_cursor = initial_page.next_cursor
        self._page_loader = page_loader
        self._group_loader = group_loader
        self._recent_group_loader = recent_group_loader
        self._delete_callback = delete_callback
        self._loaded_groups: dict[str, SavedAgentGroupWire | None] = {}

    @property
    def groups(self) -> tuple[SavedAgentGroupSummaryWire, ...]:
        """Currently loaded group summaries."""

        return tuple(self._groups)

    @property
    def recent_groups(self) -> tuple[SavedAgentGroupSummaryWire, ...]:
        """Currently loaded recent-dismissal summaries."""

        return tuple(self._recent_groups)

    @property
    def next_cursor(self) -> int | None:
        """Cursor for the next unloaded page."""

        return self._next_cursor

    def compose(self) -> ComposeResult:
        """Compose the saved-group revival modal."""

        with Container(id="saved-agent-group-modal-container"):
            yield Label("Agent Restore", id="saved-agent-group-title")
            with Horizontal(id="saved-agent-group-panels"):
                with Vertical(id="saved-agent-group-list-panel"):
                    yield Static("Groups", id="saved-agent-group-list-heading")
                    yield OptionList(
                        *self._create_options(),
                        id="saved-agent-group-list",
                    )
                with Vertical(id="saved-agent-group-preview-panel"):
                    yield Static("Preview", id="saved-agent-group-preview-heading")
                    with VerticalScroll(id="saved-agent-group-preview-scroll"):
                        yield Static("", id="saved-agent-group-preview")
            yield Static(
                self._hints_text(),
                id="saved-agent-group-hints",
            )

    def on_mount(self) -> None:
        """Focus the group list and render the first preview."""

        option_list = self.query_one("#saved-agent-group-list", OptionList)
        option_list.focus()
        self._update_preview_for_option_id(self._first_option_id())
        self._update_hints()

    def action_load_more(self) -> None:
        """Load another page of saved groups, if available."""

        self._load_more()

    def action_delete_group(self) -> None:
        """Delete the highlighted saved group after confirmation."""

        option_id = self._current_highlighted_option_id()
        if _group_location_from_option(option_id) != "saved":
            return
        group_id = _group_id_from_option(option_id, prefix=_GROUP_PREFIX)
        if group_id is None:
            return

        summary = self._summary_for_group_id(group_id, location="saved")
        title = _group_display_title(summary, group_id)

        def _on_confirm(confirmed: bool | None) -> None:
            if confirmed is True:
                self._perform_delete(group_id)

        self.app.push_screen(
            ConfirmActionModal(
                title="Delete Saved Agent Group",
                message=(
                    f"Delete saved agent group '{title}'?\n\n"
                    "This removes only the saved group record. The dismissed "
                    "agents themselves are not deleted and can still be found "
                    "with custom revival search.\n\n"
                    "This action cannot be undone."
                ),
                kind=ConfirmKind.DANGER,
                confirm_label="Delete",
                cancel_label="Cancel",
            ),
            _on_confirm,
        )

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Update the preview when the highlighted row changes."""

        option_id = event.option.id if event.option else None
        self._update_preview_for_option_id(option_id)
        self._update_hints()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle Enter on a group or sentinel row."""

        option_id = event.option.id if event.option else None
        if option_id == _LOAD_MORE_ID:
            self._load_more()
            return
        if option_id == _CUSTOM_SEARCH_ID:
            self.dismiss(SavedAgentGroupRevivalResult(action="custom_search"))
            return
        recent_group_id = _group_id_from_option(option_id, prefix=_RECENT_PREFIX)
        if recent_group_id is not None:
            self.dismiss(
                SavedAgentGroupRevivalResult(
                    action="revive_group",
                    group_id=recent_group_id,
                    location="recent",
                )
            )
            return
        group_id = _group_id_from_option(option_id, prefix=_GROUP_PREFIX)
        if group_id is not None:
            self.dismiss(
                SavedAgentGroupRevivalResult(
                    action="revive_group",
                    group_id=group_id,
                    location="saved",
                )
            )

    def _load_more(self) -> None:
        if self._next_cursor is None:
            self._update_preview_for_option_id(_LOAD_MORE_ID)
            return
        if self._page_loader is None:
            self.notify("No saved-group page loader is available", severity="warning")
            return

        old_highlighted_id = self._current_highlighted_option_id()
        try:
            page = self._page_loader(self._next_cursor)
        except Exception as exc:
            self.notify(f"Failed to load saved groups: {exc}", severity="error")
            return

        seen = {group.group_id for group in self._groups}
        self._groups.extend(
            group for group in page.groups if group.group_id not in seen
        )
        self._next_cursor = page.next_cursor
        # Pagination changes the option set; drop any jump hints so the rebuilt
        # list never renders stale markers, and the back stack with them since
        # its stored positions no longer name the same rows.
        self.invalidate_jump_hints(identities_changed=True, target_count=0)
        self._rebuild_options(highlighted_option_id=old_highlighted_id)
        self._update_hints()

    def _perform_delete(self, group_id: str) -> None:
        if self._delete_callback is None:
            self.notify(
                "No saved-group delete handler is available",
                severity="warning",
            )
            return

        summary = self._summary_for_group_id(group_id, location="saved")
        title = _group_display_title(summary, group_id)
        next_highlight = self._next_highlight_after_saved_delete(group_id)
        try:
            deleted = self._delete_callback(group_id)
        except Exception as exc:
            self.notify(
                f"Failed to delete saved group '{title}': {exc}", severity="error"
            )
            return

        self._groups = [group for group in self._groups if group.group_id != group_id]
        self._loaded_groups.pop(f"{_GROUP_PREFIX}{group_id}", None)
        self.invalidate_jump_hints(identities_changed=True, target_count=0)
        self._rebuild_options(highlighted_option_id=next_highlight)
        self._focus_option_list()
        self._update_preview_for_option_id(self._current_highlighted_option_id())
        self._update_hints()

        if deleted:
            self.notify(f"Deleted saved group '{title}'")
        else:
            self.notify(
                f"Saved group '{title}' was already gone",
                severity="warning",
            )

    def _next_highlight_after_saved_delete(self, group_id: str) -> str:
        for idx, group in enumerate(self._groups):
            if group.group_id != group_id:
                continue
            next_group = self._groups[idx + 1] if idx + 1 < len(self._groups) else None
            if next_group is not None:
                return f"{_GROUP_PREFIX}{next_group.group_id}"
            previous_group = self._groups[idx - 1] if idx > 0 else None
            if previous_group is not None:
                return f"{_GROUP_PREFIX}{previous_group.group_id}"
            break
        if self._next_cursor is not None:
            return _LOAD_MORE_ID
        if self._recent_groups:
            return f"{_RECENT_PREFIX}{self._recent_groups[0].group_id}"
        return _CUSTOM_SEARCH_ID

    def _create_options(
        self, *, jump_hints: dict[str, str] | None = None
    ) -> list[Option]:
        hints = jump_hints or {}

        def labeled(label: Text, option_id: str) -> Text:
            """Apply a jump hint marker to a selectable row when present."""

            hint = hints.get(option_id)
            if hint is None:
                return label
            return apply_jump_hint_prefix(label, hint)

        options: list[Option] = []
        options.append(
            Option(
                Text(f"Saved groups ({len(self._groups)})", style="bold #87D7FF"),
                id=_SAVED_HEADING_ID,
                disabled=True,
            )
        )
        if self._groups:
            for group in self._groups:
                option_id = f"{_GROUP_PREFIX}{group.group_id}"
                options.append(
                    Option(
                        labeled(format_saved_group_row(group), option_id),
                        id=option_id,
                    )
                )
        else:
            options.append(
                Option(
                    Text("No saved groups yet", style="dim"),
                    id=_SAVED_EMPTY_ID,
                    disabled=True,
                )
            )

        if self._next_cursor is not None:
            options.append(
                Option(
                    labeled(
                        Text("Load more saved groups...", style="bold #00D7AF"),
                        _LOAD_MORE_ID,
                    ),
                    id=_LOAD_MORE_ID,
                )
            )

        options.append(Option(Text(""), id=_SAVED_RECENT_SEPARATOR_ID, disabled=True))

        options.append(
            Option(
                Text(
                    f"Recent dismissals ({len(self._recent_groups)})",
                    style="bold #87D7FF",
                ),
                id=_RECENT_HEADING_ID,
                disabled=True,
            )
        )
        if self._recent_groups:
            for group in self._recent_groups:
                option_id = f"{_RECENT_PREFIX}{group.group_id}"
                options.append(
                    Option(
                        labeled(format_saved_group_row(group), option_id),
                        id=option_id,
                    )
                )
        else:
            options.append(
                Option(
                    Text("No recent dismissals", style="dim"),
                    id=_RECENT_EMPTY_ID,
                    disabled=True,
                )
            )

        options.append(Option(Text(""), id=_RECENT_ACTIONS_SEPARATOR_ID, disabled=True))

        options.append(
            Option(
                labeled(
                    Text("Custom revival search...", style="bold #D7AFFF"),
                    _CUSTOM_SEARCH_ID,
                ),
                id=_CUSTOM_SEARCH_ID,
            )
        )
        return options

    def _rebuild_options(
        self,
        *,
        highlighted_option_id: str | None = None,
        show_jump_hints: bool = False,
    ) -> None:
        option_list = self.query_one("#saved-agent-group-list", OptionList)
        option_list.clear_options()
        jump_hints = self.jump_hints_by_key() if show_jump_hints else None
        for option in self._create_options(jump_hints=jump_hints):
            option_list.add_option(option)

        if highlighted_option_id is not None:
            row = self._row_for_option_id(option_list, highlighted_option_id)
            if row is not None:
                option_list.highlighted = row

    def _update_hints(self) -> None:
        static = self.query_one("#saved-agent-group-hints", Static)
        if self.jump_mode_active:
            action = "back" if self.jump_back_stack else "first"
            static.update(f"JUMP ' {action}  <esc> cancel")
        else:
            static.update(self._hints_text())

    def _hints_text(self) -> str:
        recent_count = len(self._recent_groups)
        group_count = len(self._groups)
        load_more = " | PgDn/load row: more" if self._next_cursor is not None else ""
        delete = (
            " | ^d: delete"
            if _group_location_from_option(self._current_highlighted_option_id())
            == "saved"
            else ""
        )
        return (
            f"j/k: navigate | ': jump | Enter: revive/open | "
            f"{group_count} saved loaded | {recent_count} recent"
            f"{load_more}{delete} | Esc/q: cancel"
        )

    def _first_option_id(self) -> str:
        if self._groups:
            return f"{_GROUP_PREFIX}{self._groups[0].group_id}"
        if self._recent_groups:
            return f"{_RECENT_PREFIX}{self._recent_groups[0].group_id}"
        return _CUSTOM_SEARCH_ID

    def _current_highlighted_option_id(self) -> str | None:
        """Return the option id of the currently highlighted row, if any."""

        try:
            option_list = self.query_one("#saved-agent-group-list", OptionList)
        except Exception:
            return None
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            return option_list.get_option_at_index(highlighted).id
        except Exception:
            return None

    def _row_for_option_id(self, option_list: OptionList, option_id: str) -> int | None:
        """Return the option-list row position for an option id."""

        for row in range(option_list.option_count):
            if option_list.get_option_at_index(row).id == option_id:
                return row
        return None

    def _focus_option_list(self) -> None:
        try:
            self.query_one("#saved-agent-group-list", OptionList).focus()
        except Exception:
            return

    def _jump_target_keys(self) -> list[str]:
        """Return selectable option ids in current visual order.

        Skips disabled headings, separators, and empty-state rows so jump
        hints only land on rows the user can actually activate.
        """

        ids: list[str] = []
        for option in self._create_options():
            if option.disabled or option.id is None:
                continue
            ids.append(option.id)
        return ids

    def _jump_current_key(self) -> str | None:
        return self._current_highlighted_option_id()

    def _jump_select_key(self, key: str) -> None:
        self._update_hints()
        # Setting ``highlighted`` for the target row emits ``OptionHighlighted``,
        # which drives the preview through the normal highlight-update path.
        self._rebuild_options(highlighted_option_id=key)

    def _jump_repaint(self) -> None:
        highlighted_id = self._current_highlighted_option_id()
        self._update_hints()
        self._rebuild_options(
            highlighted_option_id=highlighted_id,
            show_jump_hints=self.jump_mode_active,
        )

    def on_key(self, event: events.Key) -> None:
        """Intercept jump-mode keypresses before modal bindings run."""

        if not self.jump_mode_active:
            return
        key = normalize_jump_key(event.key, event.character)
        if self.handle_jump_key(key):
            event.prevent_default()
            event.stop()

    def _update_preview_for_option_id(self, option_id: str | None) -> None:
        try:
            preview = self.query_one("#saved-agent-group-preview", Static)
        except Exception:
            return

        if option_id in {_EMPTY_ID, _RECENT_EMPTY_ID, _SAVED_EMPTY_ID}:
            preview.update(build_empty_groups_preview())
            return
        if option_id == _LOAD_MORE_ID:
            preview.update(build_load_more_preview(self._next_cursor))
            return
        if option_id in {
            _RECENT_HEADING_ID,
            _SAVED_HEADING_ID,
            _SAVED_RECENT_SEPARATOR_ID,
            _RECENT_ACTIONS_SEPARATOR_ID,
        }:
            return
        if option_id == _CUSTOM_SEARCH_ID or option_id is None:
            preview.update(build_saved_group_preview(None))
            return

        location = _group_location_from_option(option_id)
        group_id = _group_id_from_option(
            option_id,
            prefix=_RECENT_PREFIX if location == "recent" else _GROUP_PREFIX,
        )
        summary = self._summary_for_group_id(group_id, location=location)
        if summary is None:
            preview.update(build_saved_group_preview(None))
            return

        group = self._load_group(option_id, group_id, location=location)
        preview.update(build_saved_group_preview(summary, group))

    def _summary_for_group_id(
        self,
        group_id: str | None,
        *,
        location: Literal["saved", "recent"] | None = None,
    ) -> SavedAgentGroupSummaryWire | None:
        if group_id is None:
            return None
        groups = self._recent_groups if location == "recent" else self._groups
        for group in groups:
            if group.group_id == group_id:
                return group
        return None

    def _load_group(
        self,
        option_id: str | None,
        group_id: str | None,
        *,
        location: Literal["saved", "recent"] | None = None,
    ) -> SavedAgentGroupWire | None:
        if group_id is None or option_id is None:
            return None
        loader = (
            self._recent_group_loader if location == "recent" else self._group_loader
        )
        if loader is None:
            return None
        if option_id not in self._loaded_groups:
            try:
                self._loaded_groups[option_id] = loader(group_id)
            except Exception as exc:
                self.notify(
                    f"Failed to load saved group {group_id}: {exc}",
                    severity="error",
                )
                self._loaded_groups[option_id] = None
        return self._loaded_groups[option_id]


def _group_location_from_option(
    option_id: str | None,
) -> Literal["saved", "recent"] | None:
    if option_id and option_id.startswith(_RECENT_PREFIX):
        return "recent"
    if option_id and option_id.startswith(_GROUP_PREFIX):
        return "saved"
    return None


def _group_id_from_option(option_id: str | None, *, prefix: str) -> str | None:
    if not option_id or not option_id.startswith(prefix):
        return None
    return option_id.removeprefix(prefix)


def _group_display_title(
    summary: SavedAgentGroupSummaryWire | None,
    fallback: str,
) -> str:
    if summary is None:
        return fallback
    return (summary.name or summary.title or fallback).strip() or fallback
