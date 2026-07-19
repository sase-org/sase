"""Model picker modal for selecting a coder LLM model."""

from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets._option_list import Option

from sase.ace.tui.actions.navigation.jump_hints import (
    build_jump_hint_maps,
    normalize_jump_key,
)

from .base import FilterInput, OptionListNavigationMixin
from .model_picker_options import (
    build_model_options,
    filter_model_rows,
    rows_to_options,
)
from .model_picker_rows import (
    CUSTOM_SENTINEL,
    DEFAULT_SENTINEL,
    AliasSelectionContext,
    AliasSelectionOperation,
    alias_reference_rejection,
    build_model_rows,
)

__all__ = (
    "CUSTOM_SENTINEL",
    "DEFAULT_SENTINEL",
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
        if isinstance(modal, ModelPickerModal) and modal._model_jump_mode_active:
            key = normalize_jump_key(event.key, event.character)
            if modal._handle_model_jump_key(key):
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


class ModelPickerModal(OptionListNavigationMixin, ModalScreen[str | None]):
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
    ) -> None:
        super().__init__()
        self._title = title
        self._include_default_option = include_default_option
        self._distinct_default = distinct_default
        self._alias_context = alias_context
        self._all_rows = build_model_rows(
            include_default_option=include_default_option,
            alias_context=alias_context,
        )
        self._visible_rows = self._all_rows
        self._model_jump_mode_active = False
        self._model_jump_hint_to_id: dict[str, str] = {}
        self._model_jump_id_to_hint: dict[str, str] = {}
        self._model_jump_last_id: str | None = None

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
        jump_hints = (
            self._model_jump_id_to_hint if self._model_jump_mode_active else None
        )
        return rows_to_options(self._visible_rows, jump_hints=jump_hints)

    def _apply_filter(self, query: str) -> None:
        option_list = self.query_one("#model-picker-list", OptionList)
        previous_id = self._highlighted_option_id()
        self._visible_rows = filter_model_rows(self._all_rows, query)
        self._clear_model_jump_hints()
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

    def _visible_selectable_option_ids(self) -> list[str]:
        return [row.option_id for row in self._visible_rows if not row.disabled]

    def action_jump_to_entry(self) -> None:
        option_ids = self._visible_selectable_option_ids()
        if not option_ids:
            return

        self._model_jump_hint_to_id, self._model_jump_id_to_hint = build_jump_hint_maps(
            option_ids
        )
        if not self._model_jump_hint_to_id:
            return

        self._model_jump_mode_active = True
        option_list = self.query_one("#model-picker-list", OptionList)
        preferred_id = self._highlighted_option_id()
        option_list.clear_options()
        option_list.add_options(self._render_options())
        self._ensure_highlight(preferred_id=preferred_id)
        self._update_jump_footer()

    def _clear_model_jump_hints(self) -> None:
        self._model_jump_mode_active = False
        self._model_jump_hint_to_id = {}
        self._model_jump_id_to_hint = {}

    def _exit_model_jump_mode(self) -> None:
        preferred_id = self._highlighted_option_id()
        self._clear_model_jump_hints()
        option_list = self.query_one("#model-picker-list", OptionList)
        option_list.clear_options()
        option_list.add_options(self._render_options())
        self._ensure_highlight(preferred_id=preferred_id)
        self._update_jump_footer()

    def _handle_model_jump_key(self, key: str) -> bool:
        if not self._model_jump_mode_active:
            return False
        if key == "escape":
            self._exit_model_jump_mode()
            return True

        if key == "apostrophe":
            visible_ids = self._visible_selectable_option_ids()
            target_id = (
                self._model_jump_last_id
                if self._model_jump_last_id in visible_ids
                else (visible_ids[0] if visible_ids else None)
            )
            if target_id is None:
                self._exit_model_jump_mode()
                return True
            current_id = self._highlighted_option_id()
            if current_id is not None:
                self._model_jump_last_id = current_id
            return self._jump_to_option_id(target_id)

        target_id = self._model_jump_hint_to_id.get(key)
        if target_id is None:
            self._exit_model_jump_mode()
            return True

        current_id = self._highlighted_option_id()
        if current_id is not None:
            self._model_jump_last_id = current_id
        return self._jump_to_option_id(target_id)

    def _jump_to_option_id(self, option_id: str) -> bool:
        option_list = self.query_one("#model-picker-list", OptionList)
        try:
            target_index = option_list.get_option_index(option_id)
        except Exception:
            self._exit_model_jump_mode()
            return True

        self._clear_model_jump_hints()
        option_list.clear_options()
        option_list.add_options(self._render_options())
        option_list.highlighted = target_index
        self._update_jump_footer()
        return True

    def _update_jump_footer(self) -> None:
        try:
            footer = self.query_one("#model-picker-footer", Static)
        except Exception:
            return

        if self._model_jump_mode_active:
            action = "back" if self._model_jump_last_id is not None else "first"
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
        if self._model_jump_mode_active:
            key = normalize_jump_key(event.key, event.character)
            if self._handle_model_jump_key(key):
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
