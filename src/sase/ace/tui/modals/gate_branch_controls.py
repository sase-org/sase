"""Shared branch-driven controls for ACE notification-gate modals.

The Decision column owns only the choose beat: OR buttons, AND toggles, and
group submits. Typed collection lives on :class:`GateInputPanel`, which this
widget opens when a selection needs input and then posts the same
:class:`Resolved` message the host modals already consume.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button

from sase.notification_gates.branches import GateBranchData
from sase.notification_gates.models import GateFeedbackMode, GateOption

from .gate_branch_layout import (
    GateControlButton,
    compose_group,
    compose_singleton_row,
    parse_option_control_id,
    toggle_label,
)
from .gate_input_panel import GateInputPanel, GateInputPanelResult
from .gate_input_panel_model import (
    DEFAULT_HOST_COLLECTED_PROPERTIES,
    GateInputDraft,
    GateInputRequest,
    build_gate_input_request,
    gate_declares_inputs,
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
        self._draft_by_branch: dict[int, GateInputDraft] = {}
        self._submission_block: str | None = None
        self._panel_open = False

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
            branch_index += 1

    def _branch_options(self, branch_index: int) -> list[GateOption]:
        return [
            self._options_by_id[option_id]
            for option_id in self.data.branches[branch_index]
        ]

    def _branch_label(self, branch_index: int) -> str:
        branch = self.data.branches[branch_index]
        if len(branch) == 1:
            return self._options_by_id[branch[0]].label
        group = self._groups_by_members[frozenset(branch)]
        return group.label or "Submit"

    # -- events ---------------------------------------------------------------

    def on_mount(self) -> None:
        self._refresh_submit_states()

    def on_gate_control_button_control_focused(
        self, event: GateControlButton.ControlFocused
    ) -> None:
        self._set_active_branch(event.branch_index)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        if not button_id.startswith("gate-"):
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
        self._update_submit_state(branch_index)

    def toggle_focused_option(self) -> None:
        focused = self.screen.focused
        if not isinstance(focused, Button):
            return
        indices = parse_option_control_id(focused.id or "")
        if indices is not None:
            self.toggle_option(*indices)

    def submit_primary_branch(self) -> None:
        """Submit the declared primary branch without resetting its UI selection."""
        self._resolve_branch(self._primary_branch_index)

    def submit_active_branch(self) -> None:
        self._resolve_branch(self._active_branch_index)

    def submit_numbered_branch(self, branch_index: int) -> None:
        """Submit a branch selected by its zero-based numbered shortcut."""
        if not 0 <= branch_index < len(self.data.branches):
            return
        self._resolve_branch(branch_index)

    def open_inputs_for_focused_control(self) -> None:
        """Open the input panel for the focused control's branch.

        Used by the gate modal's ``open_inputs`` key. Opens even when the
        selection would otherwise submit immediately, unless there is nothing
        to collect.
        """
        if self._submission_block is not None:
            self.notify(self._submission_block, severity="warning")
            return
        selected = self.selected_option_ids(self._active_branch_index)
        if not selected:
            self.notify(
                "Select at least one option before submitting", severity="warning"
            )
            return
        request = self._request_for_branch(self._active_branch_index, selected)
        if request.conflict is not None:
            self.notify(request.conflict, severity="warning")
            return
        if request.is_empty:
            self.notify("This option takes no input", severity="warning")
            return
        self._open_input_panel(request)

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
                self._update_submit_state(branch_index)
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

    def _set_active_branch(self, branch_index: int) -> None:
        self._active_branch_index = branch_index

    # -- submission -----------------------------------------------------------

    def _refresh_submit_states(self) -> None:
        for branch_index in range(len(self.data.branches)):
            self._update_submit_state(branch_index)

    def _request_for_branch(
        self, branch_index: int, selected: Sequence[str]
    ) -> GateInputRequest:
        return build_gate_input_request(
            self._branch_options(branch_index),
            selected,
            branch_index=branch_index,
            branch_label=self._branch_label(branch_index),
            feedback_mode=self._feedback_mode(branch_index),
            host_collected_properties=self._host_collected_properties,
            draft=self._draft_by_branch.get(branch_index, GateInputDraft()),
        )

    def _resolve_branch(self, branch_index: int) -> None:
        if self._submission_block is not None:
            self.notify(self._submission_block, severity="warning")
            return
        self._set_active_branch(branch_index)
        selected = self.selected_option_ids(branch_index)
        if not selected:
            self.notify(
                "Select at least one option before submitting", severity="warning"
            )
            return
        request = self._request_for_branch(branch_index, selected)
        if request.conflict is not None:
            self.notify(request.conflict, severity="warning")
            return
        if not request.requires_panel:
            self.post_message(
                self.Resolved(selected, self._feedback_value(branch_index), {})
            )
            return
        self._open_input_panel(request)

    def _open_input_panel(self, request: GateInputRequest) -> None:
        if self._panel_open:
            return
        focused = self.screen.focused
        originating_id = focused.id if focused is not None else None
        panel = GateInputPanel(request)
        self._panel_open = True

        def on_done(result: GateInputPanelResult | None) -> None:
            if not self.is_mounted:
                return
            self._panel_open = False
            self._draft_by_branch[request.branch_index] = panel.draft
            if result is None:
                self._refocus_control(originating_id)
                return
            option_inputs = result.option_inputs if request.sections else {}
            self.post_message(
                self.Resolved(
                    request.selected_option_ids,
                    result.feedback,
                    option_inputs,
                )
            )

        self.app.push_screen(panel, on_done)

    def _refocus_control(self, control_id: str | None) -> None:
        if not control_id:
            return
        try:
            self.query_one(f"#{control_id}").focus()
        except Exception:
            return

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
        draft = self._draft_by_branch.get(branch_index)
        if draft is None:
            return None
        normalized = draft.feedback.strip()
        return normalized or None

    def _update_submit_state(self, branch_index: int) -> None:
        # No `is_mounted` guard: every caller runs after compose() has
        # produced this branch's controls (including `on_mount` itself,
        # where `is_mounted` is still False even though the DOM exists).
        branch = self.data.branches[branch_index]
        blocked = self._submission_block is not None
        if len(branch) <= 1:
            self.query_one(f"#gate-singleton-{branch_index}", Button).disabled = blocked
            return
        button = self.query_one(f"#gate-group-submit-{branch_index}", Button)
        button.disabled = blocked or not self.selected_option_ids(branch_index)


__all__ = [
    "DEFAULT_HOST_COLLECTED_PROPERTIES",
    "GateBranchControls",
    "GateBranchData",
    "gate_declares_inputs",
]
