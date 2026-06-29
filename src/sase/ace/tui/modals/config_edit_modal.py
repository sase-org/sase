"""Edit / validate / write flow for the Config Center's Config tab.

The modal has two stages: an edit stage that chooses a writable scope and typed
value operation, and a preview stage that shows the Rust-backed edit plan before
writing it. The public import path remains this module; the pure helpers,
rendering base, and overlay-name prompt live in sibling modules.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from textual.widgets import Input, TextArea
from textual.worker import Worker, WorkerState

from sase.config import (
    AppliedResult,
    ConfigEditError,
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


class ConfigEditModal(ConfigEditModalBase):
    """Edit a single config field and write it."""

    # Focus is managed explicitly (``_focus_editor``); hidden Input/TextArea
    # widgets must not steal focus from key-driven bool/enum editors.
    AUTO_FOCUS = None

    BINDINGS = [
        ("escape", "back", "Back/Cancel"),
        ("ctrl+s", "confirm", "Confirm"),
        ("enter", "confirm", "Confirm"),
        ("space", "toggle_value", "Toggle"),
        ("ctrl+t", "cycle_scope", "Scope"),
        ("ctrl+n", "new_overlay", "New overlay"),
        ("ctrl+r", "toggle_reset", "Reset to default"),
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
        self._plan_worker: Worker[Any] | None = None
        self._apply_worker: Worker[Any] | None = None
        self._target: str | None = None
        self._enum_index = 0
        self._bool_value = False
        self._initial_value: Any = None
        if field is not None:
            self._init_field_state(field)

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

    def action_cycle_scope(self) -> None:
        if self._stage != "edit" or self._busy:
            return
        writable = self._writable_sources()
        if len(writable) <= 1:
            return
        names = [s.name for s in writable]
        try:
            index = names.index(self._target) if self._target in names else -1
        except ValueError:
            index = -1
        self._target = names[(index + 1) % len(names)]
        self._error = None
        self._render_all()

    def action_new_overlay(self) -> None:
        if self._stage != "edit" or self._busy:
            return

        def _on_name(name: str | None) -> None:
            if not name:
                return
            try:
                inventory, layer_name = inventory_with_new_overlay(
                    self._inventory, name
                )
            except Exception as exc:
                self._error = f"could not create overlay: {exc}"
                self._render_all()
                return
            self._inventory = inventory
            self._target = layer_name
            self._error = None
            self._render_all()

        self.app.push_screen(OverlayNameModal(), _on_name)

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

    def action_back(self) -> None:
        if self._busy:
            return
        if self._stage == "preview":
            self._stage = "edit"
            self._plan = None
            self._error = None
            self._status = None
            self._render_all()
            self._focus_editor()
            return
        self.dismiss(None)

    def action_confirm(self) -> None:
        if self._busy:
            return
        if self._stage == "edit":
            self._start_plan()
        else:
            self._start_apply()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "config-edit-input" and self._stage == "edit":
            self._start_plan()

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
            raw = self.query_one("#config-edit-input", Input).value
        else:
            raw = self.query_one("#config-edit-textarea", TextArea).text
        value, error = parse_editor_value(kind, raw, field)
        if error is not None:
            return None, error
        return ConfigEditOp.set_value(value), None

    def _start_plan(self) -> None:
        if self._target is None:
            self._error = "no writable target — create an overlay (ctrl+n)"
            self._render_all()
            return
        op, error = self._current_op()
        if op is None or error is not None:
            self._error = error
            self._render_all()
            return
        self._error = None
        self._status = None
        self._busy = True
        self._stage = "preview"
        self._plan = None
        self.set_focus(None)
        self._render_all()
        inventory = self._inventory
        path = self._field.path if self._field is not None else ""
        target = self._target

        def task() -> EditPlanResult:
            return plan_config_edit(inventory, path, target, op)

        self._plan_worker = self.run_worker(task, thread=True, exclusive=True)

    def _start_apply(self) -> None:
        plan = self._plan
        if plan is None:
            return
        if not plan.is_valid:
            self._error = "fix validation errors before writing"
            self._render_all()
            return
        if not plan.text_diff.strip():
            self._error = "nothing to write — no change"
            self._render_all()
            return
        self._busy = True
        self._error = None
        self._render_all()

        def task() -> tuple[AppliedResult, str | None]:
            result = apply_config_edit(plan)
            note: str | None = None
            if result.used_chezmoi:
                proc = apply_chezmoi(result.path)
                if proc.returncode != 0:
                    detail = proc.stderr.strip() or f"exit {proc.returncode}"
                    note = f"chezmoi apply failed: {detail}"
            return result, note

        self._apply_worker = self.run_worker(task, thread=True, exclusive=True)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.worker is self._plan_worker:
            self._on_plan_worker(event)
        elif event.worker is self._apply_worker:
            self._on_apply_worker(event)

    def _on_plan_worker(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            self._busy = False
            self._plan = event.worker.result
            self._render_all()
        elif event.state == WorkerState.ERROR:
            self._busy = False
            self._error = self._worker_error(event, "could not plan edit")
            self._stage = "edit"
            self._render_all()
            self._focus_editor()

    def _on_apply_worker(self, event: Worker.StateChanged) -> None:
        if event.state == WorkerState.SUCCESS:
            self._busy = False
            outcome = event.worker.result
            if not isinstance(outcome, tuple):
                self.dismiss(None)
                return
            result, note = outcome
            if note is not None:
                # The file was written, but chezmoi propagation failed; keep the
                # modal open so the user can retry or apply chezmoi manually.
                self._error = note
                self._render_all()
                return
            self.dismiss(result)
        elif event.state == WorkerState.ERROR:
            self._busy = False
            self._error = self._worker_error(event, "write failed")
            self._render_all()

    @staticmethod
    def _worker_error(event: Worker.StateChanged, fallback: str) -> str:
        error = event.worker.error
        if isinstance(error, ConfigEditError):
            return str(error)
        return str(error) if error else fallback
