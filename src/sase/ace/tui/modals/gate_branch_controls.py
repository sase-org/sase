"""Shared branch-driven controls for ACE notification-gate modals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import yaml  # type: ignore[import-untyped]
from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Input, Static, TextArea

from sase.ace.tui.widgets.typed_input_form import TypedFormField, TypedInputForm
from sase.notification_gates.branches import GateBranchData
from sase.notification_gates.input_collection import (
    collected_input_fields,
    input_arg_for_field,
    option_inputs_from_values,
)
from sase.notification_gates.model_inputs import GateInputField
from sase.notification_gates.model_validation import GateError, first_schema_error
from sase.notification_gates.models import GateFeedbackMode, GateGroup, GateOption
from sase.xprompt.models import InputType, XPromptValidationError

#: Properties a raw-schema editor never renders because a sibling control on
#: the modal already collects them (and the executor injects/merges them).
DEFAULT_HOST_COLLECTED_PROPERTIES = frozenset({"feedback"})


def _schema_extra_properties(
    schema: Mapping[str, Any], host_collected_properties: frozenset[str]
) -> tuple[str, ...]:
    """Schema property names not already collected by a sibling host control."""
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        return ()
    return tuple(name for name in properties if name not in host_collected_properties)


def gate_declares_inputs(
    options: Sequence[GateOption], host_collected_properties: frozenset[str]
) -> tuple[bool, bool]:
    """Whether *options* render an Inputs section, and whether any is ``path``.

    Used by the gate modals to decide whether their footer needs an inputs
    hint, without duplicating :class:`GateBranchControls`'s own per-branch
    bookkeeping.
    """
    has_any = False
    has_path = False
    for option in options:
        if option.inputs:
            has_any = True
            if any(field.type is InputType.PATH for field in option.inputs):
                has_path = True
            continue
        if _schema_extra_properties(option.input_schema, host_collected_properties):
            has_any = True
    return has_any, has_path


class _GateControlButton(Button):
    """Button carrying its source branch for focus-driven feedback state."""

    class ControlFocused(Message):
        def __init__(self, branch_index: int) -> None:
            super().__init__()
            self.branch_index = branch_index

    def __init__(self, *args: object, branch_index: int, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.branch_index = branch_index

    def on_focus(self) -> None:
        self.post_message(self.ControlFocused(self.branch_index))


class GateBranchControls(VerticalScroll):
    """Render OR branches, AND toggles, and configured group submits."""

    class Resolved(Message):
        """A valid branch selection activated by the reviewer."""

        def __init__(
            self,
            selected_option_ids: tuple[str, ...],
            feedback: str | None,
            option_inputs: Mapping[str, dict[str, Any]] | None = None,
        ) -> None:
            super().__init__()
            self.selected_option_ids = selected_option_ids
            self.feedback = feedback
            self.option_inputs: dict[str, dict[str, Any]] = (
                dict(option_inputs) if option_inputs else {}
            )

    def __init__(
        self,
        data: GateBranchData,
        *,
        host_collected_properties: frozenset[str] = DEFAULT_HOST_COLLECTED_PROPERTIES,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(id=id, classes=classes)
        self.data = data
        self._host_collected_properties = host_collected_properties
        self._options_by_id = {option.id: option for option in data.options}
        self._groups_by_members = {
            frozenset(group.options): group for group in data.groups
        }
        self._primary_branch_index = data.branches.index(data.primary_branch)
        self._expanded_group_index = (
            self._primary_branch_index if len(data.primary_branch) > 1 else None
        )
        self._selected_by_branch = {
            index: {
                option_id
                for option_id in branch
                if self._options_by_id[option_id].default_selected
            }
            for index, branch in enumerate(data.branches)
            if len(branch) > 1
        }
        self._active_branch_index = 0
        self._feedback_by_branch: dict[int, str] = {}
        self._submission_block: str | None = None

        self._forms: dict[int, TypedInputForm] = {}
        self._branch_fields: dict[int, tuple[GateInputField, ...]] = {}
        self._branch_conflicts: dict[int, str] = {}
        self._branch_raw_options: dict[int, tuple[GateOption, ...]] = {}
        self._raw_editor_valid: dict[tuple[int, str], bool] = {}
        for branch_index, branch in enumerate(data.branches):
            options = [self._options_by_id[option_id] for option_id in branch]
            try:
                self._branch_fields[branch_index] = collected_input_fields(options)
            except GateError as exc:
                self._branch_conflicts[branch_index] = str(exc)
                self._branch_fields[branch_index] = ()
            self._branch_raw_options[branch_index] = tuple(
                option
                for option in options
                if not option.inputs and self._raw_editor_properties(option)
            )
            for option in self._branch_raw_options[branch_index]:
                text = self._seeded_raw_text(option)
                self._raw_editor_valid[(branch_index, option.id)] = (
                    self._raw_editor_error(option, text) is None
                )

    def compose(self) -> ComposeResult:
        branch_index = 0
        while branch_index < len(self.data.branches):
            branch = self.data.branches[branch_index]
            if len(branch) == 1:
                singleton_indices: list[int] = []
                while (
                    branch_index < len(self.data.branches)
                    and len(self.data.branches[branch_index]) == 1
                ):
                    singleton_indices.append(branch_index)
                    branch_index += 1
                with Horizontal(classes="gate-singleton-row"):
                    for index in singleton_indices:
                        option = self._options_by_id[self.data.branches[index][0]]
                        yield _GateControlButton(
                            self._numbered_label(index, self._option_label(option)),
                            branch_index=index,
                            id=f"gate-singleton-{index}",
                            classes=(
                                "gate-singleton gate-primary"
                                if index == self._primary_branch_index
                                else "gate-singleton"
                            ),
                            variant=(
                                "success"
                                if index == self._primary_branch_index
                                else "default"
                            ),
                        )
                for index in singleton_indices:
                    yield from self._compose_branch_inputs(index)
                continue

            group = self._groups_by_members[frozenset(branch)]
            expanded = branch_index == self._expanded_group_index
            with Vertical(classes="gate-group", id=f"gate-group-{branch_index}"):
                yield _GateControlButton(
                    self._numbered_label(
                        branch_index,
                        self._group_label(group),
                    ),
                    branch_index=branch_index,
                    id=f"gate-group-expand-{branch_index}",
                    classes="gate-group-expand hidden"
                    if expanded
                    else "gate-group-expand",
                )
                with Vertical(
                    id=f"gate-group-details-{branch_index}",
                    classes="gate-group-details"
                    if expanded
                    else "gate-group-details hidden",
                ):
                    for option_index, option_id in enumerate(branch):
                        option = self._options_by_id[option_id]
                        yield _GateControlButton(
                            self._toggle_label(
                                option,
                                option_id
                                in self._selected_by_branch.get(branch_index, set()),
                            ),
                            branch_index=branch_index,
                            id=f"gate-option-{branch_index}-{option_index}",
                            classes="gate-option-toggle",
                        )
                    yield _GateControlButton(
                        self._numbered_label(
                            branch_index,
                            self._group_label(group),
                        ),
                        branch_index=branch_index,
                        id=f"gate-group-submit-{branch_index}",
                        classes=(
                            "gate-group-submit gate-primary"
                            if branch_index == self._primary_branch_index
                            else "gate-group-submit"
                        ),
                        variant=(
                            "success"
                            if branch_index == self._primary_branch_index
                            else "default"
                        ),
                        disabled=not self._selected_by_branch.get(branch_index),
                    )
            yield from self._compose_branch_inputs(branch_index)
            branch_index += 1

        yield Static("", id="gate-feedback-label", classes="hidden")
        yield Input(id="gate-feedback-input", classes="hidden")

    # -- declared/raw input composition --------------------------------------

    def _compose_branch_inputs(self, branch_index: int) -> ComposeResult:
        fields = self._branch_fields.get(branch_index, ())
        conflict = self._branch_conflicts.get(branch_index)
        raw_options = self._branch_raw_options.get(branch_index, ())
        if not fields and not raw_options and conflict is None:
            # A gate written before this phase renders exactly as it does
            # today: no container at all, not merely a hidden one.
            return
        with Vertical(id=f"gate-inputs-{branch_index}", classes="gate-branch-inputs"):
            yield Static("Inputs", classes="gate-review-section-title")
            if conflict is not None:
                yield Static(conflict, classes="gate-input-conflict")
                return
            if fields:
                form = TypedInputForm(
                    [self._typed_form_field(field) for field in fields],
                    id_prefix=f"gate-branch-{branch_index}-field",
                    optional_toggle=False,
                    id=f"gate-inputs-form-{branch_index}",
                )
                self._forms[branch_index] = form
                yield form
            for option in raw_options:
                yield from self._compose_raw_editor(branch_index, option)

    def _compose_raw_editor(
        self, branch_index: int, option: GateOption
    ) -> ComposeResult:
        widget_id = f"gate-branch-{branch_index}-raw-{option.id}"
        text = self._seeded_raw_text(option)
        with Vertical(id=f"{widget_id}-block", classes="input-field-block"):
            yield Static(f"{option.label}    (yaml)", classes="field-header")
            yield TextArea(text, id=widget_id, language="yaml")
            error_label = Static("", id=f"{widget_id}-error", classes="field-error")
            error_label.display = False
            yield error_label

    @staticmethod
    def _typed_form_field(field: GateInputField) -> TypedFormField:
        return TypedFormField(
            arg=input_arg_for_field(field),
            label=field.label,
            placeholder=field.placeholder,
            secret=field.secret,
        )

    def _raw_editor_properties(self, option: GateOption) -> tuple[str, ...]:
        properties = option.input_schema.get("properties")
        if not isinstance(properties, Mapping):
            return ()
        return tuple(
            name for name in properties if name not in self._host_collected_properties
        )

    def _seeded_raw_value(self, option: GateOption) -> dict[str, Any]:
        properties = option.input_schema.get("properties")
        if not isinstance(properties, Mapping):
            return {}
        seeded: dict[str, Any] = {}
        for name, property_schema in properties.items():
            if name in self._host_collected_properties:
                continue
            if isinstance(property_schema, Mapping) and "default" in property_schema:
                seeded[name] = property_schema["default"]
        return seeded

    def _seeded_raw_text(self, option: GateOption) -> str:
        seeded = self._seeded_raw_value(option)
        if not seeded:
            return ""
        return str(yaml.safe_dump(seeded, sort_keys=False))

    def _raw_editor_error(self, option: GateOption, text: str) -> str | None:
        try:
            parsed = yaml.safe_load(text) if text.strip() else {}
        except yaml.YAMLError as exc:
            return f"invalid YAML: {exc}"
        if parsed is None:
            parsed = {}
        error = first_schema_error(parsed, option.input_schema)
        return None if error is None else str(error.message)

    def _raw_editor_value(self, branch_index: int, option_id: str) -> Any:
        text_area = self.query_one(
            f"#gate-branch-{branch_index}-raw-{option_id}", TextArea
        )
        text = text_area.text
        return yaml.safe_load(text) if text.strip() else {}

    def on_mount(self) -> None:
        self._update_feedback_controls()
        for branch_index, branch in enumerate(self.data.branches):
            if len(branch) > 1:
                self._sync_branch_input_visibility(branch_index)
            else:
                self._update_submit_state(branch_index)

    def on__gate_control_button_control_focused(
        self, event: _GateControlButton.ControlFocused
    ) -> None:
        self._set_active_branch(event.branch_index)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if not button_id.startswith("gate-"):
            return
        if "-field-" in button_id:
            # Owned by a nested TypedInputForm (e.g. an enum-cycling button),
            # which stops the event itself before it would reach here.
            return
        event.stop()
        if button_id.startswith("gate-singleton-"):
            self._resolve_branch(int(button_id.rsplit("-", 1)[1]))
            return
        if button_id.startswith("gate-group-expand-"):
            self.expand_group(int(button_id.rsplit("-", 1)[1]))
            return
        if button_id.startswith("gate-group-submit-"):
            self._resolve_branch(int(button_id.rsplit("-", 1)[1]))
            return
        if button_id.startswith("gate-option-"):
            _prefix, _gate, branch_value, option_value = button_id.split("-")
            self.toggle_option(int(branch_value), int(option_value))

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "gate-feedback-input":
            return
        self._feedback_by_branch[self._active_branch_index] = event.value
        self._update_submit_state(self._active_branch_index)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "gate-feedback-input":
            self._resolve_branch(self._active_branch_index)

    def on_text_area_changed(self, event: TextArea.Changed) -> None:
        widget_id = event.text_area.id or ""
        for branch_index, options in self._branch_raw_options.items():
            for option in options:
                if widget_id != f"gate-branch-{branch_index}-raw-{option.id}":
                    continue
                error = self._raw_editor_error(option, event.text_area.text)
                self._raw_editor_valid[(branch_index, option.id)] = error is None
                try:
                    error_label = self.query_one(f"#{widget_id}-error", Static)
                except Exception:
                    error_label = None
                if error_label is not None:
                    error_label.update(f"× {error}" if error else "")
                    error_label.display = error is not None
                self._update_submit_state(branch_index)
                return

    def on_typed_input_form_changed(self, event: TypedInputForm.Changed) -> None:
        self._refresh_submit_states()

    def expand_group(self, branch_index: int) -> None:
        """Expand one AND group and collapse every other group."""
        if len(self.data.branches[branch_index]) <= 1:
            return
        for index, branch in enumerate(self.data.branches):
            if len(branch) <= 1:
                continue
            details = self.query_one(f"#gate-group-details-{index}", Vertical)
            expand = self.query_one(f"#gate-group-expand-{index}", Button)
            if index == branch_index:
                details.remove_class("hidden")
                expand.add_class("hidden")
            else:
                details.add_class("hidden")
                expand.remove_class("hidden")
        self._expanded_group_index = branch_index
        self._set_active_branch(branch_index)
        first = self.query_one(f"#gate-option-{branch_index}-0", Button)
        first.focus(scroll_visible=False)

    def toggle_option(self, branch_index: int, option_index: int) -> None:
        """Toggle one AND-member option and refresh its branch submit state."""
        branch = self.data.branches[branch_index]
        option_id = branch[option_index]
        selected = self._selected_by_branch[branch_index]
        if option_id in selected:
            selected.remove(option_id)
        else:
            selected.add(option_id)
        option = self._options_by_id[option_id]
        self.query_one(
            f"#gate-option-{branch_index}-{option_index}", Button
        ).label = self._toggle_label(option, option_id in selected)
        self._set_active_branch(branch_index)
        self._update_feedback_controls()
        self._sync_branch_input_visibility(branch_index)

    def toggle_focused_option(self) -> None:
        focused = self.screen.focused
        if not isinstance(focused, Button) or not (focused.id or "").startswith(
            "gate-option-"
        ):
            return
        _prefix, _gate, branch_value, option_value = (focused.id or "").split("-")
        self.toggle_option(int(branch_value), int(option_value))

    def submit_primary_branch(self) -> None:
        """Submit the declared primary branch without resetting its UI selection."""
        focused = self.screen.focused
        if isinstance(focused, Input) and focused.id == "gate-feedback-input":
            self._resolve_branch(self._active_branch_index)
            return
        self._resolve_branch(self._primary_branch_index)

    def submit_active_branch(self) -> None:
        self._resolve_branch(self._active_branch_index)

    def submit_numbered_branch(self, branch_index: int) -> None:
        """Submit a branch selected by its zero-based numbered shortcut."""
        if not 0 <= branch_index < len(self.data.branches):
            return
        self._resolve_branch(branch_index)

    def selected_option_ids(self, branch_index: int) -> tuple[str, ...]:
        branch = self.data.branches[branch_index]
        if len(branch) == 1:
            return branch
        selected = self._selected_by_branch[branch_index]
        return tuple(option_id for option_id in branch if option_id in selected)

    def apply_selection(self, selected_option_ids: Sequence[str]) -> None:
        """Restore one group selection, used by the plan prompt-edit round trip."""
        selected = set(selected_option_ids)
        for branch_index, branch in enumerate(self.data.branches):
            if len(branch) <= 1 or not selected <= set(branch):
                continue
            self._selected_by_branch[branch_index] = selected
            if self.is_mounted:
                for option_index, option_id in enumerate(branch):
                    option = self._options_by_id[option_id]
                    self.query_one(
                        f"#gate-option-{branch_index}-{option_index}", Button
                    ).label = self._toggle_label(option, option_id in selected)
                self._sync_branch_input_visibility(branch_index)
            return

    def visible_control_ids(self) -> list[str]:
        """Return this section's focusable control ids, in render order."""
        ids: list[str] = []
        for branch_index, branch in enumerate(self.data.branches):
            if len(branch) == 1:
                ids.append(f"gate-singleton-{branch_index}")
            elif branch_index == self._expanded_group_index:
                ids.extend(
                    f"gate-option-{branch_index}-{option_index}"
                    for option_index in range(len(branch))
                )
                ids.append(f"gate-group-submit-{branch_index}")
            else:
                ids.append(f"gate-group-expand-{branch_index}")
            ids.extend(self._branch_input_control_ids(branch_index))
        return ids

    def _branch_input_control_ids(self, branch_index: int) -> list[str]:
        ids: list[str] = []
        form = self._forms.get(branch_index)
        if form is not None:
            ids.extend(form.visible_control_ids())
        ids.extend(
            f"gate-branch-{branch_index}-raw-{option_id}"
            for option_id in self._visible_raw_options(branch_index)
        )
        return ids

    def _visible_raw_options(self, branch_index: int) -> frozenset[str]:
        options = self._branch_raw_options.get(branch_index, ())
        branch = self.data.branches[branch_index]
        if len(branch) <= 1:
            return frozenset(option.id for option in options)
        selected = set(self.selected_option_ids(branch_index))
        return frozenset(option.id for option in options if option.id in selected)

    def _sync_branch_input_visibility(self, branch_index: int) -> None:
        """Reveal only the currently selected options' fields, for AND branches."""
        branch = self.data.branches[branch_index]
        if len(branch) > 1:
            form = self._forms.get(branch_index)
            if form is not None:
                selected_ids = set(self.selected_option_ids(branch_index))
                selected_options = [
                    self._options_by_id[option_id] for option_id in selected_ids
                ]
                try:
                    visible_field_ids = {
                        field.id for field in collected_input_fields(selected_options)
                    }
                except GateError:
                    visible_field_ids = set()
                for field in self._branch_fields.get(branch_index, ()):
                    form.set_field_visible(field.id, field.id in visible_field_ids)
            if self.is_mounted:
                visible_raw = self._visible_raw_options(branch_index)
                for option in self._branch_raw_options.get(branch_index, ()):
                    block = self.query_one(
                        f"#gate-branch-{branch_index}-raw-{option.id}-block", Vertical
                    )
                    block.display = option.id in visible_raw
        self._update_submit_state(branch_index)

    def _set_active_branch(self, branch_index: int) -> None:
        if branch_index == self._active_branch_index:
            self._update_feedback_controls()
            return
        if self.is_mounted:
            current = self.query_one("#gate-feedback-input", Input)
            self._feedback_by_branch[self._active_branch_index] = current.value
        self._active_branch_index = branch_index
        self._update_feedback_controls()
        if len(self.data.branches[branch_index]) > 1:
            self._sync_branch_input_visibility(branch_index)

    def block_submission(self, reason: str | None) -> None:
        """Refuse every submit while *reason* is set, and say why when tried.

        An unaccepted draft blocks the whole Decision section rather than the
        branches that would consume it: getting that per-branch reasoning
        wrong destroys a reviewer's edit silently, and being blunt here cannot.
        """
        self._submission_block = reason
        if self.is_mounted:
            self._refresh_submit_states()

    def _refresh_submit_states(self) -> None:
        for branch_index in range(len(self.data.branches)):
            self._update_submit_state(branch_index)

    def _resolve_branch(self, branch_index: int) -> None:
        if self._submission_block is not None:
            self.notify(self._submission_block, severity="warning")
            return
        conflict = self._branch_conflicts.get(branch_index)
        if conflict is not None:
            self.notify(conflict, severity="warning")
            return
        self._set_active_branch(branch_index)
        selected = self.selected_option_ids(branch_index)
        if not selected:
            self.notify(
                "Select at least one option before submitting", severity="warning"
            )
            return
        feedback = self._feedback_value(branch_index)
        if self._feedback_mode(branch_index) == "required" and feedback is None:
            self.notify("Feedback is required for this option", severity="warning")
            self.query_one("#gate-feedback-input", Input).focus()
            return
        if not self._branch_inputs_valid(branch_index):
            # The submit control is already disabled for this, but a numbered
            # or primary-key shortcut reaches here without going through it.
            self.notify(
                "Fix the highlighted inputs before submitting", severity="warning"
            )
            return
        option_inputs = self._collect_option_inputs(branch_index, selected)
        if option_inputs is None:
            return
        self.post_message(self.Resolved(selected, feedback, option_inputs))

    def _collect_option_inputs(
        self, branch_index: int, selected: tuple[str, ...]
    ) -> dict[str, dict[str, Any]] | None:
        selected_options = [self._options_by_id[option_id] for option_id in selected]
        result: dict[str, dict[str, Any]] = {}
        form = self._forms.get(branch_index)
        if form is not None:
            try:
                values = form.typed_values()
            except XPromptValidationError as exc:
                self.notify(
                    f"Fix the highlighted inputs before submitting: {exc}",
                    severity="error",
                )
                return None
            result = option_inputs_from_values(selected_options, values)
        raw_options = {
            option.id: option
            for option in self._branch_raw_options.get(branch_index, ())
        }
        for option in selected_options:
            if option.id not in raw_options:
                continue
            try:
                result[option.id] = self._raw_editor_value(branch_index, option.id)
            except yaml.YAMLError as exc:
                self.notify(
                    f"Fix the input for {option.label}: {exc}", severity="error"
                )
                return None
        return result

    def _feedback_mode(self, branch_index: int) -> GateFeedbackMode:
        ranks: dict[GateFeedbackMode, int] = {
            "disabled": 0,
            "optional": 1,
            "required": 2,
        }
        selected = self.selected_option_ids(branch_index)
        return max(
            (self._options_by_id[option_id].feedback for option_id in selected),
            key=ranks.__getitem__,
            default="disabled",
        )

    def _feedback_value(self, branch_index: int) -> str | None:
        if branch_index == self._active_branch_index and self.is_mounted:
            value = self.query_one("#gate-feedback-input", Input).value
        else:
            value = self._feedback_by_branch.get(branch_index, "")
        normalized = value.strip()
        return normalized or None

    def _update_feedback_controls(self) -> None:
        if not self.is_mounted:
            return
        mode = self._feedback_mode(self._active_branch_index)
        label = self.query_one("#gate-feedback-label", Static)
        field = self.query_one("#gate-feedback-input", Input)
        if mode == "disabled":
            label.add_class("hidden")
            field.add_class("hidden")
        else:
            label.update(
                "Feedback (required)" if mode == "required" else "Feedback (optional)"
            )
            label.remove_class("hidden")
            field.remove_class("hidden")
            field.placeholder = (
                "Explain your decision before submitting…"
                if mode == "required"
                else "Add context for the sender…"
            )
        value = self._feedback_by_branch.get(self._active_branch_index, "")
        if field.value != value:
            field.value = value
        self._update_submit_state(self._active_branch_index)

    def _branch_inputs_valid(self, branch_index: int) -> bool:
        if branch_index in self._branch_conflicts:
            return False
        form = self._forms.get(branch_index)
        if form is not None and not form.is_valid():
            return False
        for option_id in self._visible_raw_options(branch_index):
            if not self._raw_editor_valid.get((branch_index, option_id), True):
                return False
        return True

    def _update_submit_state(self, branch_index: int) -> None:
        # No `is_mounted` guard: every caller runs after compose() has
        # produced this branch's controls (including `on_mount` itself,
        # where `is_mounted` is still False even though the DOM exists).
        branch = self.data.branches[branch_index]
        blocked = self._submission_block is not None or not self._branch_inputs_valid(
            branch_index
        )
        if len(branch) <= 1:
            self.query_one(f"#gate-singleton-{branch_index}", Button).disabled = blocked
            return
        button = self.query_one(f"#gate-group-submit-{branch_index}", Button)
        button.disabled = (
            blocked
            or not self.selected_option_ids(branch_index)
            or (
                self._feedback_mode(branch_index) == "required"
                and self._feedback_value(branch_index) is None
            )
        )

    @staticmethod
    def _option_label(option: GateOption) -> str:
        value = f"{option.icon} {option.label}" if option.icon else option.label
        return escape(value)

    @classmethod
    def _toggle_label(cls, option: GateOption, selected: bool) -> str:
        return f"{'☑️' if selected else '⬜'} {cls._option_label(option)}"

    @staticmethod
    def _group_label(group: GateGroup) -> str:
        value = f"{group.icon} {group.label}" if group.icon else str(group.label)
        return escape(value)

    @staticmethod
    def _numbered_label(branch_index: int, label: str) -> str:
        return f"{branch_index + 1} {label}"


__all__ = [
    "DEFAULT_HOST_COLLECTED_PROPERTIES",
    "GateBranchControls",
    "GateBranchData",
    "gate_declares_inputs",
]
