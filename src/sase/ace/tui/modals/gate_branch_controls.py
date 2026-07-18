"""Shared branch-driven controls for ACE notification-gate modals."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.widgets import Button, Input, Static

from sase.notification_gates.models import (
    GateError,
    GateFeedbackMode,
    GateGroup,
    GateOption,
    normalize_primary_branch,
)


@dataclass(frozen=True)
class GateBranchData:
    """Verified branch projection consumed by every ACE gate renderer."""

    query: str
    options: tuple[GateOption, ...]
    groups: tuple[GateGroup, ...]
    branches: tuple[tuple[str, ...], ...]
    primary_branch: tuple[str, ...]

    @classmethod
    def from_envelope(
        cls,
        envelope: Mapping[str, object],
        *,
        default_feedback: GateFeedbackMode = "disabled",
    ) -> GateBranchData:
        """Project a verified envelope without re-parsing its canonical query."""
        query = envelope.get("query")
        raw_options = envelope.get("options")
        raw_groups = envelope.get("groups")
        raw_branches = envelope.get("branches")
        raw_primary = envelope.get("primary_branch")
        if not isinstance(query, str) or not query:
            raise GateError("invalid_request", "query", "gate query is missing")
        if not isinstance(raw_options, list) or not raw_options:
            raise GateError("invalid_request", "options", "gate options are missing")
        if not isinstance(raw_groups, list):
            raise GateError("invalid_request", "groups", "gate groups are missing")
        if not isinstance(raw_branches, list) or not raw_branches:
            raise GateError("invalid_request", "branches", "gate branches are missing")

        options = tuple(
            GateOption.from_mapping(
                raw,
                index,
                default_feedback=default_feedback,
            )
            for index, raw in enumerate(raw_options)
        )
        groups = tuple(
            GateGroup.from_mapping(raw, index) for index, raw in enumerate(raw_groups)
        )
        branches: list[tuple[str, ...]] = []
        for index, raw_branch in enumerate(raw_branches):
            if (
                not isinstance(raw_branch, list)
                or not raw_branch
                or not all(isinstance(option_id, str) for option_id in raw_branch)
            ):
                raise GateError(
                    "invalid_request",
                    f"branches[{index}]",
                    "gate branch must be a non-empty array of option ids",
                )
            branches.append(tuple(raw_branch))

        option_ids = {option.id for option in options}
        flattened = [option_id for branch in branches for option_id in branch]
        if len(flattened) != len(set(flattened)) or set(flattened) != option_ids:
            raise GateError(
                "invalid_branches",
                "branches",
                "gate branches do not match the declared options",
            )
        group_members = {frozenset(group.options) for group in groups}
        branch_members = {frozenset(branch) for branch in branches if len(branch) > 1}
        if group_members != branch_members:
            raise GateError(
                "invalid_groups",
                "groups",
                "gate groups do not match the AND branches",
            )
        normalized_branches = tuple(branches)
        primary_branch = normalize_primary_branch(raw_primary, normalized_branches)
        return cls(
            query=query,
            options=options,
            groups=groups,
            branches=normalized_branches,
            primary_branch=primary_branch,
        )


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
        ) -> None:
            super().__init__()
            self.selected_option_ids = selected_option_ids
            self.feedback = feedback

    def __init__(self, data: GateBranchData, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.data = data
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
                            self._option_label(option),
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
                continue

            group = self._groups_by_members[frozenset(branch)]
            expanded = branch_index == self._expanded_group_index
            with Vertical(classes="gate-group", id=f"gate-group-{branch_index}"):
                yield _GateControlButton(
                    self._group_label(group),
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
                        self._group_label(group),
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
            branch_index += 1

        yield Static("", id="gate-feedback-label", classes="hidden")
        yield Input(id="gate-feedback-input", classes="hidden")

    def on_mount(self) -> None:
        self._update_feedback_controls()

    def on__gate_control_button_control_focused(
        self, event: _GateControlButton.ControlFocused
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
        self._update_submit_state(branch_index)

    def focus_next_control(self) -> None:
        self._focus_relative(1)

    def focus_previous_control(self) -> None:
        self._focus_relative(-1)

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
                self._update_submit_state(branch_index)
            return

    def _focus_relative(self, delta: int) -> None:
        control_ids = self._visible_control_ids()
        if not control_ids:
            return
        focused = self.screen.focused
        focused_id = focused.id if isinstance(focused, Button) else None
        try:
            current = control_ids.index(focused_id or "")
        except ValueError:
            current = -1 if delta > 0 else 0
        target_id = control_ids[(current + delta) % len(control_ids)]
        self.query_one(f"#{target_id}", Button).focus(scroll_visible=False)

    def _visible_control_ids(self) -> list[str]:
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

    def _set_active_branch(self, branch_index: int) -> None:
        if branch_index == self._active_branch_index:
            self._update_feedback_controls()
            return
        if self.is_mounted:
            current = self.query_one("#gate-feedback-input", Input)
            self._feedback_by_branch[self._active_branch_index] = current.value
        self._active_branch_index = branch_index
        self._update_feedback_controls()

    def _resolve_branch(self, branch_index: int) -> None:
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
        self.post_message(self.Resolved(selected, feedback))

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

    def _update_submit_state(self, branch_index: int) -> None:
        branch = self.data.branches[branch_index]
        if len(branch) <= 1 or not self.is_mounted:
            return
        button = self.query_one(f"#gate-group-submit-{branch_index}", Button)
        button.disabled = not self.selected_option_ids(branch_index) or (
            self._feedback_mode(branch_index) == "required"
            and self._feedback_value(branch_index) is None
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


__all__ = ["GateBranchControls", "GateBranchData"]
