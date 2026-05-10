"""Model picker modal for selecting a coder LLM model."""

from dataclasses import dataclass
from typing import Literal

from rich.text import Text
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
from sase.ace.tui.provider_styles import model_option_text, provider_header_text

from .base import FilterInput, OptionListNavigationMixin

# Sentinel returned when user selects "Custom..."
CUSTOM_SENTINEL = "__custom__"
_DEFAULT_SENTINEL = "__default__"
_EMPTY_SENTINEL = "__empty__"

_RowKind = Literal["default", "provider", "model", "custom", "empty"]


@dataclass(frozen=True)
class _ModelPickerRow:
    kind: _RowKind
    label: str
    option_id: str
    provider: str | None = None
    model_id: str | None = None
    alias: str | None = None
    model_count: int | None = None

    @property
    def disabled(self) -> bool:
        return self.kind in {"provider", "empty"}

    @property
    def is_model(self) -> bool:
        return self.kind == "model"

    @property
    def search_terms(self) -> tuple[str, ...]:
        return tuple(
            part.lower()
            for part in (
                self.provider,
                self.provider.upper() if self.provider else None,
                self.model_id,
                self.label,
                self.alias,
            )
            if part
        )


def _build_model_rows(*, include_default_option: bool = True) -> list[_ModelPickerRow]:
    """Build typed model-picker rows grouped by provider."""
    from sase.llm_provider.registry import model_short_alias_map, model_to_provider_map

    aliases = model_short_alias_map()
    provider_models: dict[str, list[str]] = {}
    for model, provider in model_to_provider_map().items():
        provider_models.setdefault(provider, []).append(model)

    rows: list[_ModelPickerRow] = []
    if include_default_option:
        rows.append(
            _ModelPickerRow(
                kind="default",
                label="Same as planner",
                option_id=_DEFAULT_SENTINEL,
            )
        )

    for provider, models in provider_models.items():
        rows.append(
            _ModelPickerRow(
                kind="provider",
                label=f"  {provider.upper()}  {len(models)} models",
                option_id=f"__header_{provider}__",
                provider=provider,
                model_count=len(models),
            )
        )
        for model in models:
            alias = aliases.get(model)
            label = f"    {model}"
            if alias:
                label = f"{label}  ({alias})"
            rows.append(
                _ModelPickerRow(
                    kind="model",
                    label=label,
                    option_id=model,
                    provider=provider,
                    model_id=model,
                    alias=alias,
                )
            )

    rows.append(
        _ModelPickerRow(
            kind="custom",
            label="  Custom...",
            option_id=CUSTOM_SENTINEL,
        )
    )
    return rows


def _row_matches(row: _ModelPickerRow, query: str) -> bool:
    if not query:
        return True
    return any(query in term for term in row.search_terms)


def _filter_model_rows(
    rows: list[_ModelPickerRow],
    query: str,
) -> list[_ModelPickerRow]:
    """Return rows matching the filter while keeping provider groups coherent."""
    query = query.strip().lower()
    if not query:
        return rows

    special_rows = [row for row in rows if row.kind in {"default", "custom"}]
    filtered: list[_ModelPickerRow] = [
        row for row in special_rows if row.kind == "default"
    ]
    matched_models = 0
    index = 0
    while index < len(rows):
        row = rows[index]
        if row.kind != "provider":
            index += 1
            continue

        provider_row = row
        provider_models: list[_ModelPickerRow] = []
        index += 1
        while index < len(rows) and rows[index].kind == "model":
            provider_models.append(rows[index])
            index += 1

        provider_matches = _row_matches(provider_row, query)
        matching_models = (
            provider_models
            if provider_matches
            else [model for model in provider_models if _row_matches(model, query)]
        )
        if matching_models:
            filtered.append(provider_row)
            filtered.extend(matching_models)
            matched_models += len(matching_models)

    if matched_models == 0:
        filtered.append(
            _ModelPickerRow(
                kind="empty",
                label="  No matching models",
                option_id=_EMPTY_SENTINEL,
            )
        )
    filtered.extend(row for row in special_rows if row.kind == "custom")
    return filtered


def _rows_to_options(
    rows: list[_ModelPickerRow],
    *,
    jump_hints: dict[str, str] | None = None,
) -> list[Option | None]:
    """Render typed rows into Textual OptionList content."""
    items: list[Option | None] = []
    previous_kind: _RowKind | None = None
    for row in rows:
        if items and (
            row.kind == "provider" or row.kind == "custom" or previous_kind == "default"
        ):
            items.append(None)
        label: str | Text
        if row.kind == "provider" and row.provider is not None:
            label = provider_header_text(row.provider, row.model_count or 0)
        elif row.kind == "model" and row.model_id is not None:
            label = model_option_text(
                provider=row.provider,
                model_id=row.model_id,
                alias=row.alias,
                hint=jump_hints.get(row.option_id) if jump_hints else None,
            )
        elif jump_hints is not None and not row.disabled:
            hint = jump_hints.get(row.option_id)
            label = Text()
            if hint is not None:
                label.append(f"{hint:>2} ", style="bold #87D7FF")
            else:
                label.append("   ")
            label.append(row.label)
        else:
            label = row.label
        items.append(Option(label, id=row.option_id, disabled=row.disabled))
        previous_kind = row.kind
    return items


def _build_model_options(*, include_default_option: bool = True) -> list[Option | None]:
    """Build the option list items grouped by provider.

    Args:
        include_default_option: If True (default), prepend the
            ``"Same as planner"`` option that returns ``None``.
            Callers like the temporary-override modal that have no
            "use planner default" semantics pass ``False`` to omit it.
    """
    return _rows_to_options(
        _build_model_rows(include_default_option=include_default_option)
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
            ``"Same as planner"`` option whose selection dismisses with
            ``None``.  Pass ``False`` for callers (e.g. the temporary
            override modal) where ``None`` only ever means *cancel*.
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
    ) -> None:
        super().__init__()
        self._title = title
        self._include_default_option = include_default_option
        self._all_rows = _build_model_rows(
            include_default_option=include_default_option
        )
        self._visible_rows = self._all_rows
        self._model_jump_mode_active = False
        self._model_jump_hint_to_id: dict[str, str] = {}
        self._model_jump_id_to_hint: dict[str, str] = {}
        self._model_jump_last_id: str | None = None

    def compose(self) -> ComposeResult:
        with Container(id="model-picker-container"):
            yield Static(
                f"[bold cyan]{self._title}[/bold cyan]",
                id="model-picker-title",
            )
            yield _ModelPickerFilterInput(
                placeholder="Filter providers or models...",
                id="model-picker-filter",
            )
            yield OptionList(
                *_build_model_options(
                    include_default_option=self._include_default_option,
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
        return _rows_to_options(self._visible_rows, jump_hints=jump_hints)

    def _apply_filter(self, query: str) -> None:
        option_list = self.query_one("#model-picker-list", OptionList)
        previous_id = self._highlighted_option_id()
        self._visible_rows = _filter_model_rows(self._all_rows, query)
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
                if row.is_model:
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
        if option_id == _DEFAULT_SENTINEL:
            self.dismiss(None)
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
