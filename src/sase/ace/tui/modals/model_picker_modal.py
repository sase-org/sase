"""Model picker modal for selecting a coder LLM model."""

from dataclasses import dataclass, replace
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
from sase.ace.tui.provider_styles import (
    model_option_text,
    provider_header_text,
    provider_model_badge_markup,
)
from sase.llm_provider import AliasView

from .base import FilterInput, OptionListNavigationMixin

# Sentinel returned when user selects "Custom..."
CUSTOM_SENTINEL = "__custom__"
# Returned when the user selects "Follow-up default" and the caller opted
# into ``distinct_default``. By default this row dismisses with ``None`` (the
# same as cancel); callers that need to tell "use the follow-up default" apart
# from a cancel pass ``distinct_default=True`` to receive this sentinel.
DEFAULT_SENTINEL = "__default__"
_EMPTY_SENTINEL = "__empty__"

AliasSelectionOperation = Literal["persistent", "temporary"]
_RowKind = Literal[
    "alias_header",
    "alias",
    "default",
    "provider",
    "model",
    "custom",
    "empty",
]

_ALIAS_HEADER_SENTINEL = "__header_aliases__"
_ALIAS_NAME_CELL = 22
_ALIAS_TARGET_CELL = 27


@dataclass(frozen=True)
class AliasSelectionContext:
    """Opt-in alias catalog and safety semantics for a Models-panel picker."""

    views: tuple[AliasView, ...]
    target_alias: str
    operation: AliasSelectionOperation


@dataclass(frozen=True)
class _ModelPickerRow:
    kind: _RowKind
    label: str
    option_id: str
    provider: str | None = None
    model_id: str | None = None
    alias: str | None = None
    model_count: int | None = None
    alias_name: str | None = None
    alias_kind: str | None = None
    description: str | None = None
    disabled_reason: str | None = None
    rendered_label: Text | None = None

    @property
    def disabled(self) -> bool:
        return self.kind in {"alias_header", "provider", "empty"} or (
            self.disabled_reason is not None
        )

    @property
    def is_model(self) -> bool:
        return self.kind == "model"

    @property
    def is_target(self) -> bool:
        return self.kind in {"alias", "model"}

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
                self.alias_name,
                f"@{self.alias_name}" if self.alias_name else None,
                self.alias_kind,
                self.description,
                self.rendered_label.plain if self.rendered_label else None,
                self.disabled_reason,
            )
            if part
        )


def _alias_dependencies(views: tuple[AliasView, ...]) -> dict[str, str]:
    """Return the immediate known dependency edge for each alias snapshot row."""
    known = {view.name for view in views}
    dependencies: dict[str, str] = {}
    for view in views:
        dependency = view.references or view.implicit_fallback
        if dependency in known:
            dependencies[view.name] = dependency
    return dependencies


def _alias_disabled_reason(
    context: AliasSelectionContext,
    candidate: str,
) -> str | None:
    """Classify whether selecting *candidate* is unsafe for this operation."""
    target = context.target_alias.strip()
    if candidate == target:
        return "current alias"
    if context.operation == "temporary":
        return None

    dependencies = _alias_dependencies(context.views)
    current = candidate
    visited: set[str] = set()
    # There can be at most one useful visit per known alias. The explicit
    # bound makes malformed snapshots safe even if this helper changes later.
    for _ in range(len(context.views) + 1):
        if current == target:
            return "would create a cycle"
        if current in visited:
            return "would create a cycle"
        visited.add(current)
        dependency = dependencies.get(current)
        if dependency is None:
            return None
        current = dependency
    return "would create a cycle"


def alias_reference_rejection(
    context: AliasSelectionContext | None,
    value: str,
) -> str | None:
    """Return a concise rejection reason for a free-form ``@alias`` value."""
    cleaned = value.strip()
    if context is None or not cleaned.startswith("@"):
        return None
    alias = cleaned[1:].strip()
    known = {view.name for view in context.views}
    if not alias or alias not in known:
        return "unknown alias"
    return _alias_disabled_reason(context, alias)


def _alias_row_text(
    view: AliasView,
    *,
    operation: AliasSelectionOperation,
    disabled_reason: str | None,
) -> Text:
    """Build the immutable styled body for one alias option row."""
    text = Text(no_wrap=True, overflow="ellipsis")
    alias_token = f"@{view.name}"
    if len(alias_token) > _ALIAS_NAME_CELL:
        alias_token = alias_token[: _ALIAS_NAME_CELL - 1] + "…"
    text.append(alias_token.ljust(_ALIAS_NAME_CELL), style="bold #87D7FF")
    text.append("  →  ", style="dim #5F8787")
    badge = Text.from_markup(
        provider_model_badge_markup(view.selection_provider, view.selection_model)
    )
    badge.truncate(_ALIAS_TARGET_CELL, overflow="ellipsis", pad=True)
    text.append_text(badge)
    text.append("  ")
    if disabled_reason is not None:
        text.append(disabled_reason, style="bold #FF875F")
    else:
        semantic = "dynamic ref" if operation == "persistent" else "snapshot"
        if view.override is not None and view.name != "default":
            semantic = f"override now · {semantic}"
        text.append(semantic, style="dim #A8A8A8")
    return text


def _build_alias_rows(context: AliasSelectionContext) -> list[_ModelPickerRow]:
    """Build alias rows once from the Models panel's in-memory snapshot."""
    if not context.views:
        return []
    rows = [
        _ModelPickerRow(
            kind="alias_header",
            label=f"  ALIASES  {len(context.views)} aliases",
            option_id=_ALIAS_HEADER_SENTINEL,
            model_count=len(context.views),
        )
    ]
    for view in context.views:
        disabled_reason = _alias_disabled_reason(context, view.name)
        rows.append(
            _ModelPickerRow(
                kind="alias",
                label=f"@{view.name}",
                option_id=f"@{view.name}",
                provider=view.selection_provider,
                model_id=view.selection_model,
                alias_name=view.name,
                alias_kind=view.kind,
                description=view.description,
                disabled_reason=disabled_reason,
                rendered_label=_alias_row_text(
                    view,
                    operation=context.operation,
                    disabled_reason=disabled_reason,
                ),
            )
        )
    return rows


def _build_model_rows(
    *,
    include_default_option: bool = True,
    alias_context: AliasSelectionContext | None = None,
) -> list[_ModelPickerRow]:
    """Build typed model-picker rows grouped by provider."""
    from sase.llm_provider.registry import model_short_alias_map, model_to_provider_map

    aliases = model_short_alias_map()
    provider_models: dict[str, list[str]] = {}
    for model, provider in model_to_provider_map().items():
        provider_models.setdefault(provider, []).append(model)

    rows: list[_ModelPickerRow] = []
    if alias_context is not None:
        rows.extend(_build_alias_rows(alias_context))
    if include_default_option:
        rows.append(
            _ModelPickerRow(
                kind="default",
                label="Follow-up default",
                option_id=DEFAULT_SENTINEL,
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
    filtered: list[_ModelPickerRow] = []
    matched_targets = 0
    index = 0
    while index < len(rows):
        row = rows[index]
        if row.kind == "alias_header":
            alias_header = row
            aliases: list[_ModelPickerRow] = []
            index += 1
            while index < len(rows) and rows[index].kind == "alias":
                aliases.append(rows[index])
                index += 1
            header_matches = _row_matches(alias_header, query)
            matching_aliases = (
                aliases
                if header_matches
                else [alias for alias in aliases if _row_matches(alias, query)]
            )
            if matching_aliases:
                filtered.append(
                    replace(alias_header, model_count=len(matching_aliases))
                )
                filtered.extend(matching_aliases)
                matched_targets += len(matching_aliases)
            continue
        if row.kind == "default":
            filtered.append(row)
            index += 1
            continue
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
            matched_targets += len(matching_models)

    if matched_targets == 0:
        has_aliases = any(row.kind == "alias" for row in rows)
        filtered.append(
            _ModelPickerRow(
                kind="empty",
                label=(
                    "  No matching aliases or models"
                    if has_aliases
                    else "  No matching models"
                ),
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
            row.kind == "provider"
            or row.kind == "custom"
            or previous_kind == "default"
            or (row.kind == "default" and previous_kind == "alias")
        ):
            items.append(None)
        label: str | Text
        if row.kind == "alias_header":
            count = row.model_count or 0
            noun = "alias" if count == 1 else "aliases"
            label = Text("  ")
            label.append("━ ALIASES", style="bold #5FD7D7")
            label.append(f"  {count} {noun}", style="dim #87D7D7")
        elif row.kind == "alias" and row.rendered_label is not None:
            label = Text()
            hint = jump_hints.get(row.option_id) if jump_hints else None
            if hint is not None:
                label.append(f"{hint:>2} ", style="bold #87D7FF")
            else:
                label.append("   ")
            label.append_text(row.rendered_label.copy())
            label.no_wrap = True
            label.overflow = "ellipsis"
        elif row.kind == "provider" and row.provider is not None:
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
            ``"Follow-up default"`` option that returns ``None``.
            Callers like the temporary-override modal that have no
            "use follow-up default" semantics pass ``False`` to omit it.
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
        self._all_rows = _build_model_rows(
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
                    _rows_to_options(self._all_rows)
                    if self._alias_context is not None
                    else _build_model_options(
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
