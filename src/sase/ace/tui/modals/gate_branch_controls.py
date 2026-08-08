"""Shared branch-driven controls for ACE notification-gate modals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Input, Static

from sase.ace.tui.widgets.typed_input_form import TypedInputForm
from sase.notification_gates.branches import GateBranchData
from sase.notification_gates.models import GateFeedbackMode, GateOption

from .gate_branch_input_section import (
    DEFAULT_HOST_COLLECTED_PROPERTIES,
    GateBranchInputError,
    GateBranchInputSection,
    gate_declares_inputs,
)
from .gate_branch_layout import (
    GateControlButton,
    compose_group,
    compose_singleton_row,
    parse_option_control_id,
    toggle_label,
)


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
        self._sections: dict[int, GateBranchInputSection] = {}

    def compose(self) -> ComposeResult:
        branch_index = 0
        while branch_index < len(self.data.branches):
            if len(self.data.branches[branch_index]) == 1:
                singleton_indices: list[int] = []
                while (
                    branch_index < len(self.data.branches)
                    and len(self.data.branches[branch_index]) == 1
                ):
                    singleton_indices.append(branch_index)
                    branch_index += 1
                yield from compose_singleton_row(
                    singleton_indices,
                    [self._branch_options(index)[0] for index in singleton_indices],
                    primary_branch_index=self._primary_branch_index,
                )
                for index in singleton_indices:
                    yield from self._compose_branch_inputs(index)
                continue

            branch = self.data.branches[branch_index]
            yield from compose_group(
                branch_index,
                self._branch_options(branch_index),
                self._groups_by_members[frozenset(branch)],
                expanded=branch_index == self._expanded_group_index,
                primary=branch_index == self._primary_branch_index,
                selected=self._selected_by_branch.get(branch_index, set()),
            )
            yield from self._compose_branch_inputs(branch_index)
            branch_index += 1

        yield Static("", id="gate-feedback-label", classes="hidden")
        yield Input(id="gate-feedback-input", classes="hidden")

    def _branch_options(self, branch_index: int) -> list[GateOption]:
        return [
            self._options_by_id[option_id]
            for option_id in self.data.branches[branch_index]
        ]

    def _compose_branch_inputs(self, branch_index: int) -> ComposeResult:
        section = GateBranchInputSection(
            branch_index,
            self._branch_options(branch_index),
            host_collected_properties=self._host_collected_properties,
        )
        if section.is_empty:
            return
        self._sections[branch_index] = section
        yield section

    # -- events ---------------------------------------------------------------

    def on_mount(self) -> None:
        self._update_feedback_controls()
        for branch_index, branch in enumerate(self.data.branches):
            if len(branch) > 1:
                self._sync_branch_input_visibility(branch_index)
            else:
                self._update_submit_state(branch_index)

    def on_gate_control_button_control_focused(
        self, event: GateControlButton.ControlFocused
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
        indices = parse_option_control_id(button_id)
        if indices is not None:
            self.toggle_option(*indices)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "gate-feedback-input":
            return
        self._feedback_by_branch[self._active_branch_index] = event.value
        self._update_submit_state(self._active_branch_index)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "gate-feedback-input":
            self._resolve_branch(self._active_branch_index)

    def on_gate_branch_input_section_validated(
        self, event: GateBranchInputSection.Validated
    ) -> None:
        self._update_submit_state(event.branch_index)

    def on_typed_input_form_changed(self, event: TypedInputForm.Changed) -> None:
        self._refresh_submit_states()

    # -- reviewer actions -----------------------------------------------------

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
        ).label = toggle_label(option, option_id in selected)
        self._set_active_branch(branch_index)
        self._update_feedback_controls()
        self._sync_branch_input_visibility(branch_index)

    def toggle_focused_option(self) -> None:
        focused = self.screen.focused
        if not isinstance(focused, Button):
            return
        indices = parse_option_control_id(focused.id or "")
        if indices is not None:
            self.toggle_option(*indices)

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
                    ).label = toggle_label(option, option_id in selected)
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
            section = self._sections.get(branch_index)
            if section is not None:
                ids.extend(section.control_ids())
        return ids

    def block_submission(self, reason: str | None) -> None:
        """Refuse every submit while *reason* is set, and say why when tried.

        An unaccepted draft blocks the whole Decision section rather than the
        branches that would consume it: getting that per-branch reasoning
        wrong destroys a reviewer's edit silently, and being blunt here cannot.
        """
        self._submission_block = reason
        if self.is_mounted:
            self._refresh_submit_states()

    # -- selection state ------------------------------------------------------

    def _sync_branch_input_visibility(self, branch_index: int) -> None:
        """Reveal only the currently selected options' fields, for AND branches."""
        section = self._sections.get(branch_index)
        if section is not None and len(self.data.branches[branch_index]) > 1:
            section.set_visible_options(self.selected_option_ids(branch_index))
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

    # -- submission -----------------------------------------------------------

    def _refresh_submit_states(self) -> None:
        for branch_index in range(len(self.data.branches)):
            self._update_submit_state(branch_index)

    def _resolve_branch(self, branch_index: int) -> None:
        if self._submission_block is not None:
            self.notify(self._submission_block, severity="warning")
            return
        section = self._sections.get(branch_index)
        if section is not None and section.conflict is not None:
            self.notify(section.conflict, severity="warning")
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
            active_section = self._sections.get(branch_index)
            if active_section is not None and active_section.focus_first_invalid():
                return
            self.notify(
                "Fix the highlighted inputs before submitting", severity="warning"
            )
            return
        try:
            option_inputs = {} if section is None else section.collect(selected)
        except GateBranchInputError as exc:
            self.notify(str(exc), severity="error")
            return
        self.post_message(self.Resolved(selected, feedback, option_inputs))

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
        section = self._sections.get(branch_index)
        return section is None or section.is_valid()

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


__all__ = [
    "DEFAULT_HOST_COLLECTED_PROPERTIES",
    "GateBranchControls",
    "GateBranchData",
    "gate_declares_inputs",
]
