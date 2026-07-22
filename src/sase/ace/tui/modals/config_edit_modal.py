"""Edit / validate / write flow for the Config Center's Config tab.

The modal has two stages: an edit stage that chooses a writable scope and typed
value operation, and a preview stage that shows the Rust-backed edit plan before
writing it. The public import path remains this module; the pure helpers,
rendering base, and overlay-name prompt live in sibling modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from textual import events
from textual.binding import Binding
from textual.widgets import TextArea

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea

from sase.config import (
    AppliedResult,
    ConfigEditOp,
    ConfigField,
    ConfigInventory,
    ConfigSource,
    EditPlanResult,
    apply_chezmoi,
    apply_config_edit,
    inventory_with_new_overlay,
    plan_config_edit,
)

from .config_edit_helpers import (
    array_item_type,
    check_constraints,
    deref_schema_ref,
    editor_kind_for,
    format_value,
    format_value_for_editor,
    initial_target,
    list_strategy_banner,
    looks_like_string_list,
    parse_editor_value,
    schema_node_for_path,
    scope_label,
    yaml_dumps,
    yaml_loads,
)
from .config_edit_overlay_modal import OverlayNameModal
from .config_edit_rendering import ConfigEditModalBase
from .config_edit_types import EditorKind, Stage
from .config_transaction import (
    ConfigTransactionApplyResult,
    ConfigTransactionControllerMixin,
    ConfigTransactionInputError,
    ConfigTransactionMetadata,
    ConfigTransactionRequest,
    ConfigTransactionScopeUpdate,
)

if TYPE_CHECKING:
    from sase.ace.tui.modals.config_pane import ConfigPaneView


_array_item_type = array_item_type
_check_constraints = check_constraints
_deref = deref_schema_ref
_editor_kind_for = editor_kind_for
_format_value = format_value
_format_value_for_editor = format_value_for_editor
_initial_target = initial_target
_list_strategy_banner = list_strategy_banner
_looks_like_string_list = looks_like_string_list
_parse_editor_value = parse_editor_value
_schema_node_for_path = schema_node_for_path
_scope_label = scope_label
_OverlayNameModal = OverlayNameModal
_yaml_dumps = yaml_dumps
_yaml_loads = yaml_loads

_LIVE_YAML_PARSE_MAX_BYTES = 16_000


@dataclass(frozen=True)
class _ConfigFieldMutation:
    inventory: ConfigInventory
    path: str
    op: ConfigEditOp


class ConfigEditModal(ConfigTransactionControllerMixin, ConfigEditModalBase):
    """Edit a single config field and write it."""

    # Focus is managed explicitly (``_focus_editor``); hidden Input/TextArea
    # widgets must not steal focus from key-driven bool/enum editors.
    AUTO_FOCUS = None

    BINDINGS = [
        ("escape", "back", "Back/Cancel"),
        ("ctrl+s", "confirm", "Confirm"),
        ("enter", "confirm", "Confirm"),
        ("j", "nav_down", "Down"),
        ("k", "nav_up", "Up"),
        ("down", "nav_down", "Down"),
        ("up", "nav_up", "Up"),
        ("ctrl+d", "preview_page_down", "Page Down"),
        ("ctrl+u", "preview_page_up", "Page Up"),
        ("g", "preview_top", "Top"),
        ("G", "preview_bottom", "Bottom"),
        ("space", "toggle_value", "Toggle"),
        Binding("1", "pick_option(1)", "Pick 1", show=False),
        Binding("2", "pick_option(2)", "Pick 2", show=False),
        Binding("3", "pick_option(3)", "Pick 3", show=False),
        Binding("4", "pick_option(4)", "Pick 4", show=False),
        Binding("5", "pick_option(5)", "Pick 5", show=False),
        Binding("6", "pick_option(6)", "Pick 6", show=False),
        Binding("7", "pick_option(7)", "Pick 7", show=False),
        Binding("8", "pick_option(8)", "Pick 8", show=False),
        Binding("9", "pick_option(9)", "Pick 9", show=False),
        ("ctrl+t", "cycle_scope", "Scope"),
        ("ctrl+n", "new_overlay", "New overlay"),
        ("ctrl+r", "toggle_reset", "Reset to default"),
        ("ctrl+l", "reload_transaction", "Reload conflict"),
    ]

    def __init__(
        self,
        view: ConfigPaneView,
        *,
        field: ConfigField | None = None,
    ) -> None:
        super().__init__()
        self._view = view
        self._inventory: ConfigInventory = view.inventory
        self._field = field
        self._stage: Stage = "edit"
        self._editor_kind: EditorKind = "string"
        self._op_unset = False
        self._error: str | None = None
        self._status: str | None = None
        self._busy = False
        self._plan: EditPlanResult | None = None
        self._target: str | None = None
        self._enum_index = 0
        self._bool_value = False
        self._initial_value: Any = None
        if field is not None:
            self._init_field_state(field)
        self._init_config_transaction(
            metadata=ConfigTransactionMetadata(
                title="Edit config field",
                identity=(field.path,) if field is not None else (),
            ),
            plan_callback=self._plan_config_transaction,
            apply_callback=self._apply_config_transaction,
            new_scope_modal_factory=OverlayNameModal,
            create_scope_callback=self._create_overlay_scope,
        )

    def _init_field_state(self, field: ConfigField) -> None:
        state = self._view.state_by_path.get(field.path)
        if state is not None and state.has_effective:
            current = state.effective_value
        elif field.has_default:
            current = field.default
        else:
            current = None
        self._editor_kind = editor_kind_for(field, self._inventory.schema, current)
        self._target = initial_target(self._inventory, field, self._view)
        if self._editor_kind == "bool":
            self._bool_value = bool(current)
        elif self._editor_kind == "enum":
            values = list(field.enum_values)
            self._enum_index = values.index(current) if current in values else 0
        self._initial_value = current

    def on_mount(self) -> None:
        self._sync_expanded_class()
        # Defer first render/focus until composed children are mounted.
        self.call_after_refresh(self._initialize)

    def _initialize(self) -> None:
        self._render_all()
        self._focus_editor()

    def _writable_sources(self) -> list[ConfigSource]:
        return [s for s in self._inventory.sources if s.writable]

    def _target_source(self) -> ConfigSource | None:
        if self._target is None:
            return None
        return self._inventory.source(self._target)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"nav_down", "nav_up"}:
            return self._stage == "preview" or self._can_choose_option()
        if action in {
            "preview_page_down",
            "preview_page_up",
            "preview_top",
            "preview_bottom",
        }:
            return self._stage == "preview"
        if action == "pick_option":
            return self._can_pick_option_by_number()
        return super().check_action(action, parameters)

    def _create_overlay_scope(self, name: str) -> ConfigTransactionScopeUpdate:
        inventory, target = inventory_with_new_overlay(self._inventory, name)
        return ConfigTransactionScopeUpdate(inventory, target)

    def _accept_transaction_scope_state(self, state: Any) -> None:
        if isinstance(state, ConfigInventory):
            self._inventory = state

    def action_toggle_reset(self) -> None:
        if self._stage != "edit" or self._busy:
            return
        self._op_unset = not self._op_unset
        self._error = None
        self._render_all()
        self._focus_editor()

    def action_toggle_value(self) -> None:
        if self._stage != "edit" or self._op_unset or self._busy:
            return
        if self._editor_kind == "bool":
            self._bool_value = not self._bool_value
            self._render_all()
        elif self._editor_kind == "enum":
            field = self._field
            count = len(field.enum_values) if field is not None else 0
            if count:
                self._enum_index = (self._enum_index + 1) % count
                self._render_all()

    def action_nav_down(self) -> None:
        if self._stage == "preview":
            self._scroll_preview(lines=1)
            return
        self._move_option(1)

    def action_nav_up(self) -> None:
        if self._stage == "preview":
            self._scroll_preview(lines=-1)
            return
        self._move_option(-1)

    def action_pick_option(self, number: int) -> None:
        if not self._can_pick_option_by_number():
            return
        self._set_option_index(number - 1)

    def _can_choose_option(self) -> bool:
        return (
            self._stage == "edit"
            and not self._op_unset
            and not self._busy
            and self._editor_kind in ("bool", "enum")
            and self._option_count() > 0
        )

    def _can_pick_option_by_number(self) -> bool:
        count = self._option_count()
        return self._can_choose_option() and 0 < count <= 9

    def _option_count(self) -> int:
        if self._editor_kind == "bool":
            return 2
        if self._editor_kind == "enum" and self._field is not None:
            return len(self._field.enum_values)
        return 0

    def _move_option(self, delta: int) -> None:
        if not self._can_choose_option():
            return
        count = self._option_count()
        if self._editor_kind == "bool":
            index = 0 if self._bool_value else 1
            self._set_option_index((index + delta) % count)
        elif self._editor_kind == "enum":
            self._set_option_index((self._enum_index + delta) % count)

    def _set_option_index(self, index: int) -> None:
        if not self._can_choose_option():
            return
        count = self._option_count()
        if index < 0 or index >= count:
            return
        if self._editor_kind == "bool":
            self._bool_value = index == 0
        elif self._editor_kind == "enum":
            self._enum_index = index
        self._error = None
        self._render_all()

    def on_single_line_vim_text_area_submitted(
        self, event: SingleLineVimTextArea.Submitted
    ) -> None:
        if event.text_area.id == "config-edit-input" and self._stage == "edit":
            self._start_plan()

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        # Both editors are now TextAreas (single-line and multiline), so live
        # validation fires for either one.
        if (
            event.text_area.id in {"config-edit-input", "config-edit-textarea"}
            and self._stage == "edit"
        ):
            self._validate_live()

    def on_click(self, event: events.Click) -> None:
        widget = event.widget
        widget_id = getattr(widget, "id", None)
        if widget_id not in {"config-edit-value", "config-edit-scope"}:
            return
        if widget is not None:
            offset = event.get_content_offset(widget)
            y = offset.y if offset is not None else int(event.y)
        else:
            y = int(event.y)
        if widget_id == "config-edit-value":
            self._set_option_index(y - 1)
        else:
            self._select_scope_index(y - 1)
        event.stop()
        event.prevent_default()

    def _validate_live(self) -> None:
        if self._stage != "edit" or self._op_unset or self._busy:
            return
        if not (self._uses_input() or self._uses_textarea()):
            return
        field = self._field
        if field is None:
            return
        kind = self._editor_kind
        if self._uses_input():
            raw = self.query_one("#config-edit-input", SingleLineVimTextArea).text
        else:
            raw = self.query_one("#config-edit-textarea", VimTextArea).text
        if (
            kind == "yaml"
            and len(raw.encode("utf-8", errors="replace")) > _LIVE_YAML_PARSE_MAX_BYTES
        ):
            self._error = None
            self._status = "large YAML buffer; preview validates it"
            self._render_all()
            return
        _value, error = parse_editor_value(kind, raw, field)
        self._error = error
        self._status = None
        self._render_all()

    def _current_op(self) -> tuple[ConfigEditOp | None, str | None]:
        """Resolve the edit operation from the editor state, or an error."""
        if self._op_unset:
            return ConfigEditOp.unset(), None
        kind = self._editor_kind
        field = self._field
        if field is None:
            return None, "no field to edit"
        if kind == "bool":
            return ConfigEditOp.set_value(self._bool_value), None
        if kind == "enum":
            values = list(field.enum_values)
            if not values:
                return None, "no enum values"
            return ConfigEditOp.set_value(values[self._enum_index]), None
        if self._uses_input():
            raw = self.query_one("#config-edit-input", SingleLineVimTextArea).text
        else:
            raw = self.query_one("#config-edit-textarea", VimTextArea).text
        value, error = parse_editor_value(kind, raw, field)
        if error is not None:
            return None, error
        return ConfigEditOp.set_value(value), None

    def _build_transaction_mutation(self, _target: str) -> _ConfigFieldMutation:
        op, error = self._current_op()
        if op is None or error is not None:
            raise ConfigTransactionInputError(error or "invalid value")
        path = self._field.path if self._field is not None else ""
        return _ConfigFieldMutation(self._inventory, path, op)

    @staticmethod
    def _plan_config_transaction(
        request: ConfigTransactionRequest[_ConfigFieldMutation],
    ) -> EditPlanResult:
        mutation = request.mutation
        return plan_config_edit(
            mutation.inventory,
            mutation.path,
            request.target,
            mutation.op,
        )

    @staticmethod
    def _apply_config_transaction(
        plan: EditPlanResult,
    ) -> ConfigTransactionApplyResult[AppliedResult]:
        result = apply_config_edit(plan)
        note: str | None = None
        # ``chezmoi apply`` takes the home *target* path, not the chezmoi
        # source we just wrote to. Only apply when a real source→target remap
        # happened (target differs from the written source path).
        target = plan.write_plan.file
        if result.used_chezmoi and target is not None and target != result.path:
            proc = apply_chezmoi(target)
            if proc.returncode != 0:
                detail = proc.stderr.strip() or f"exit {proc.returncode}"
                note = f"chezmoi apply failed: {detail}"
        return ConfigTransactionApplyResult(result, note)
