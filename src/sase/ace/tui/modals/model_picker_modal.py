"""Model picker modal for selecting a coder LLM model."""

from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets._option_list import Option

from sase.ace.tui.actions.navigation.jump_hints import normalize_jump_key

from .base import FilterInput, OptionListNavigationMixin
from .model_picker_options import (
    build_model_options,
    filter_model_rows,
    rows_to_options,
)
from .model_picker_rows import (
    CUSTOM_SENTINEL,
    DEFAULT_SENTINEL,
    SELECTOR_SENTINEL,
    AliasSelectionContext,
    AliasSelectionOperation,
    alias_reference_rejection,
    build_model_rows,
)
from .pane_entry_jump import KeyedPaneEntryJumpMixin

__all__ = (
    "CUSTOM_SENTINEL",
    "DEFAULT_SENTINEL",
    "SELECTOR_SENTINEL",
    "AliasSelectionContext",
    "AliasSelectionOperation",
    "ModelPickerModal",
    "alias_reference_rejection",
)


class _ModelPickerFilterInput(FilterInput):
    """Filter input that forwards picker navigation keys to the modal."""

    BINDINGS = [
        *FilterInput.BINDINGS,
        ("j", "forward('next_option')", "Next"),
        ("k", "forward('prev_option')", "Previous"),
        ("down", "forward('next_option')", "Next"),
        ("up", "forward('prev_option')", "Previous"),
        ("ctrl+n", "forward('next_option')", "Next"),
        ("ctrl+p", "forward('prev_option')", "Previous"),
        ("enter", "forward('select_model')", "Select"),
        ("escape", "forward('cancel')", "Cancel"),
    ]

    def action_forward(self, action_name: str) -> None:
        modal = self.screen
        if isinstance(modal, ModelPickerModal):
            getattr(modal, f"action_{action_name}")()

    async def _on_key(self, event: events.Key) -> None:
        modal = self.screen
        if isinstance(modal, ModelPickerModal) and modal.jump_mode_active:
            key = normalize_jump_key(event.key, event.character)
            if modal.handle_jump_key(key):
                event.prevent_default()
                event.stop()
                return

        if event.key == "apostrophe" and isinstance(modal, ModelPickerModal):
            event.prevent_default()
            event.stop()
            modal.action_jump_to_entry()
            return

        if event.key in {
            "j",
            "k",
            "down",
            "up",
            "ctrl+n",
            "ctrl+p",
            "escape",
        }:
            event.prevent_default()
            event.stop()
            action = {
                "j": "next_option",
                "down": "next_option",
                "ctrl+n": "next_option",
                "k": "prev_option",
                "up": "prev_option",
                "ctrl+p": "prev_option",
                "escape": "cancel",
            }[event.key]
            self.action_forward(action)
            return
        await super()._on_key(event)


class ModelPickerModal(
    KeyedPaneEntryJumpMixin[str],
    OptionListNavigationMixin,
    ModalScreen[str | None],
):
    """Modal for selecting a coder LLM model.

    Args:
        title: Heading shown above the list.
        include_default_option: If True (default), include the
            ``"Follow-up default"`` option whose selection dismisses
            with ``None``.  Pass ``False`` for callers (e.g. the temporary
            override modal) where ``None`` only ever means *cancel*.
        distinct_default: If True, selecting ``"Follow-up default"``
            dismisses with :data:`DEFAULT_SENTINEL` instead of ``None`` so the
            caller can tell it apart from a cancel (which always dismisses with
            ``None``). Only meaningful when ``include_default_option`` is True.
        alias_context: Optional Models-panel alias catalog and safety semantics.
            Callers that omit it retain the concrete-model-only picker.
        include_selector_option: If True, add a ``"Pool / fallback..."`` row
            that dismisses with :data:`SELECTOR_SENTINEL`. Only the persistent
            Edit path opts in; selectors are config-only elsewhere.
    """

    _option_list_id = "model-picker-list"

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "select_model", "Select"),
        ("apostrophe", "jump_to_entry", "Jump"),
    ]

    def __init__(
        self,
        *,
        title: str = "Select Coder Model",
        include_default_option: bool = True,
        distinct_default: bool = False,
        alias_context: AliasSelectionContext | None = None,
        include_selector_option: bool = False,
    ) -> None:
        super().__init__()
        self._title = title
        self._include_default_option = include_default_option
        self._distinct_default = distinct_default
        self._alias_context = alias_context
        self._all_rows = build_model_rows(
            include_default_option=include_default_option,
            alias_context=alias_context,
            include_selector_option=include_selector_option,
        )
        self._visible_rows = self._all_rows

    def compose(self) -> ComposeResult:
        with Container(
            id="model-picker-container",
            classes="alias-enabled" if self._alias_context is not None else None,
        ):
            yield Static(
                f"[bold cyan]{self._title}[/bold cyan]",
                id="model-picker-title",
            )
            yield _ModelPickerFilterInput(
                placeholder=(
                    "Filter aliases, providers, or models..."
                    if self._alias_context is not None
                    else "Filter providers or models..."
                ),
                id="model-picker-filter",
            )
            yield OptionList(
                *(
                    rows_to_options(self._all_rows)
                    if self._alias_context is not None
                    else build_model_options(
                        include_default_option=self._include_default_option
                    )
                ),
                id="model-picker-list",
            )
            yield Static(
                "[green]enter[/green]=Select  "
                "[dim]type[/dim]=Filter  "
                "[dim]j/k[/dim]=Navigate  "
                "[dim]'[/dim]=Jump  "
                "[dim]esc[/dim]=Clear/Cancel",
                id="model-picker-footer",
            )

    def on_mount(self) -> None:
        self.query_one("#model-picker-filter", _ModelPickerFilterInput).focus()
        self._ensure_highlight()

    def _render_options(self) -> list[Option | None]:
        jump_hints = self.jump_hints_by_key() if self.jump_mode_active else None
        return rows_to_options(self._visible_rows, jump_hints=jump_hints)

    def _apply_filter(self, query: str) -> None:
        option_list = self.query_one("#model-picker-list", OptionList)
        previous_id = self._highlighted_option_id()
        self._visible_rows = filter_model_rows(self._all_rows, query)
        # Refiltering renames every logical row, so the back stack goes too.
        self.invalidate_jump_hints(identities_changed=True, target_count=0)
        option_list.clear_options()
        option_list.add_options(self._render_options())
        self._ensure_highlight(
            preferred_id=previous_id, prefer_model=bool(query.strip())
        )

    def _highlighted_option_id(self) -> str | None:
        option_list = self.query_one("#model-picker-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return None
        try:
            option = option_list.get_option_at_index(highlighted)
        except Exception:
            return None
        return str(option.id) if option.id is not None else None

    # -- jump host hooks ----------------------------------------------------

    def _jump_target_keys(self) -> list[str]:
        """Return the visible selectable option ids, in row order."""
        return [row.option_id for row in self._visible_rows if not row.disabled]

    def _jump_current_key(self) -> str | None:
        return self._highlighted_option_id()

    def _jump_select_key(self, key: str) -> None:
        # Repaint first so the hint prefixes are gone before the highlight
        # moves, then select the way every other picker path does.
        self._jump_repaint()
        option_list = self.query_one("#model-picker-list", OptionList)
        try:
            option_list.highlighted = option_list.get_option_index(key)
        except Exception:
            return

    def _jump_repaint(self) -> None:
        option_list = self.query_one("#model-picker-list", OptionList)
        preferred_id = self._highlighted_option_id()
        option_list.clear_options()
        option_list.add_options(self._render_options())
        self._ensure_highlight(preferred_id=preferred_id)
        self._update_jump_footer()

    def _update_jump_footer(self) -> None:
        try:
            footer = self.query_one("#model-picker-footer", Static)
        except Exception:
            return

        if self.jump_mode_active:
            action = "back" if self.jump_back_stack else "first"
            footer.update(f"JUMP ' {action}  <esc> cancel")
        else:
            footer.update(
                "[green]enter[/green]=Select  "
                "[dim]type[/dim]=Filter  "
                "[dim]j/k[/dim]=Navigate  "
                "[dim]'[/dim]=Jump  "
                "[dim]esc[/dim]=Clear/Cancel"
            )

    def _ensure_highlight(
        self,
        *,
        preferred_id: str | None = None,
        prefer_model: bool = False,
    ) -> None:
        option_list = self.query_one("#model-picker-list", OptionList)
        if preferred_id is not None:
            try:
                option_list.highlighted = option_list.get_option_index(preferred_id)
                return
            except Exception:
                pass

        target = None
        if prefer_model:
            for row in self._visible_rows:
                if row.is_target and not row.disabled:
                    target = row.option_id
                    break

        if target is None:
            for row in self._visible_rows:
                if not row.disabled:
                    target = row.option_id
                    break

        if target is None:
            option_list.highlighted = None
            return
        option_list.highlighted = option_list.get_option_index(target)

    def action_select_model(self) -> None:
        option_list = self.query_one("#model-picker-list", OptionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return
        option = option_list.get_option_at_index(highlighted)
        if option.disabled:
            return
        option_id = str(option.id)
        if option_id == DEFAULT_SENTINEL:
            self.dismiss(DEFAULT_SENTINEL if self._distinct_default else None)
        else:
            self.dismiss(option_id)

    def action_cancel(self) -> None:
        filter_input = self.query_one("#model-picker-filter", FilterInput)
        if filter_input.value:
            filter_input.value = ""
            self._apply_filter("")
            return
        self.dismiss(None)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "model-picker-filter":
            return
        self._apply_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "model-picker-filter":
            return
        event.stop()
        self.action_select_model()

    def on_key(self, event: events.Key) -> None:
        """Forward navigation keys while the filter input has focus."""
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
        elif event.key in {"down", "ctrl+n", "j"}:
            event.prevent_default()
            event.stop()
            self.action_next_option()
        elif event.key in {"up", "ctrl+p", "k"}:
            event.prevent_default()
            event.stop()
            self.action_prev_option()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle double-click or enter on the option list."""
        event.stop()
        self.action_select_model()
