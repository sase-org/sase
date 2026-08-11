"""Wait modal for the ace TUI."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Input, Label, OptionList, Static

from .wait_modal_beads import BeadsValidation, validate_beads_selection
from .wait_modal_completion import WaitModalCompletionScreen
from .wait_modal_types import WaitAgentCandidate, WaitModalResult
from .wait_modal_values import (
    PriorityValidation,
    RunnersValidation,
    TimeValidation,
    active_fragment as _active_fragment,
    parse_agents_value,
    parse_beads_value,
    prefill_time_token as _prefill_time_token,
    replace_active_fragment as _replace_active_fragment,
    validate_priority_token as _validate_priority_token,
    validate_runners_token as _validate_runners_token,
    validate_time_token as _validate_time_token,
)
from .wait_modal_widgets import (
    AgentCompletionList,
    BeadCompletionList,
    WaitInput,
    candidate_option as _candidate_option,
)


class WaitModal(WaitModalCompletionScreen):
    """Modal for changing an agent wait spec."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+r", "run_now", "Run now"),
        ("tab", "accept_completion", "Complete"),
        ("down", "next_candidate", "Next"),
        ("up", "prev_candidate", "Previous"),
        ("ctrl+n", "next_candidate", "Next"),
        ("ctrl+p", "prev_candidate", "Previous"),
    ]

    _TIME_CLASSES = ("wait-time-neutral", "wait-time-valid", "wait-time-error")

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        agent_prefill = ", ".join(self._current_waiting_for)
        with Container(id="wait-modal-body"):
            yield Label("Wait", id="modal-title")
            yield Static(
                "Wait for agents, beads, a time floor, and/or a runner threshold.",
                id="wait-modal-summary",
            )
            yield Label("Agents", classes="wait-field-label")
            yield WaitInput(
                value=agent_prefill,
                placeholder="agent name, agent.two",
                id="agents-input",
            )
            yield AgentCompletionList(id="agent-completion")
            yield Label("Beads", classes="wait-field-label")
            yield WaitInput(
                value=self._bead_prefill,
                placeholder="bead-1, bead-2",
                id="beads-input",
            )
            yield BeadCompletionList(id="bead-completion")
            yield Static("", id="beads-preview")
            yield Label("Time", classes="wait-field-label")
            yield WaitInput(
                value=self._time_prefill,
                placeholder="5m, 1h30m, 1430",
                id="time-input",
            )
            yield Static("", id="time-preview")
            yield Label("Runners", classes="wait-field-label")
            yield WaitInput(
                value=self._runners_prefill,
                placeholder="global cap",
                id="runners-input",
            )
            yield Static("", id="runners-preview")
            yield Label("Priority", classes="wait-field-label")
            yield WaitInput(
                value=self._priority_prefill,
                placeholder="10",
                id="priority-input",
            )
            yield Static("", id="priority-preview")
            yield Static(self._footer_text(), id="wait-footer")

    def on_mount(self) -> None:
        """Focus the agents field, initialize live state, and load beads."""
        self._refresh_completion()
        self._refresh_bead_completion()
        self._update_time_preview()
        self._update_runners_preview()
        self._update_priority_preview()
        self._update_beads_preview()
        self._apply_active_completion_visibility()
        agents_input = self.query_one("#agents-input", WaitInput)
        agents_input.focus()
        agents_input.cursor_position = len(agents_input.value)
        self.call_after_refresh(self._scroll_body_home)
        self._bead_catalog_worker = self.run_worker(
            self._load_bead_catalog, thread=True, exclusive=True
        )

    def _scroll_body_home(self) -> None:
        """Keep the title in view even though focusing a field can autoscroll."""
        self.query_one("#wait-modal-body", Container).scroll_home(animate=False)

    def on_key(self, event: events.Key) -> None:
        """Keep completion keys local to the modal."""
        if event.key != "enter":
            return
        if isinstance(self.focused, AgentCompletionList):
            self._accept_highlighted_candidate()
            event.prevent_default()
            event.stop()
        elif isinstance(self.focused, BeadCompletionList):
            self._accept_highlighted_bead_candidate()
            event.prevent_default()
            event.stop()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        """Track which completion field last had focus."""
        widget_id = getattr(event.widget, "id", None)
        if widget_id == "agents-input":
            self._set_active_completion("agents")
        elif widget_id == "beads-input":
            self._set_active_completion("beads")

    def on_input_changed(self, event: Input.Changed) -> None:
        """Refresh completions and live validation as inputs change."""
        if event.input.id == "agents-input":
            self._refresh_completion()
            return
        if event.input.id == "beads-input":
            self._bead_guard_armed = False
            self._refresh_bead_completion()
            self._update_beads_preview()
            self._update_footer()
            return
        if event.input.id == "time-input":
            self._update_time_preview()
            return
        if event.input.id == "runners-input":
            self._update_runners_preview()
            return
        if event.input.id == "priority-input":
            self._update_priority_preview()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in any input."""
        event.stop()
        if event.input.id == "agents-input" and _active_fragment(event.value):
            if self._accept_highlighted_candidate():
                return
        elif event.input.id == "beads-input" and _active_fragment(event.value):
            if self._accept_highlighted_bead_candidate():
                return
        self._apply()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Accept a completion row from whichever list it belongs to."""
        if event.option_list.id == "agent-completion":
            self._accept_candidate_index(event.option_index)
        elif event.option_list.id == "bead-completion":
            self._accept_bead_candidate_index(event.option_index)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Suppress programmatic completion highlight echoes."""
        if event.option_list.id == "agent-completion" and self._programmatic_highlight:
            event.stop()
        elif (
            event.option_list.id == "bead-completion"
            and self._programmatic_bead_highlight
        ):
            event.stop()

    def action_cancel(self) -> None:
        """Cancel the modal."""
        self.dismiss(None)

    def action_run_now(self) -> None:
        """Dismiss with an explicit run-now result."""
        self.dismiss(
            WaitModalResult(agents=[], time_token=None, beads=[], run_now=True)
        )

    def action_accept_completion(self) -> None:
        """Accept the highlighted completion, if any, else move focus."""
        accepted = (
            self._accept_highlighted_bead_candidate()
            if self._active_completion == "beads"
            else self._accept_highlighted_candidate()
        )
        if not accepted:
            self.focus_next()

    def action_next_candidate(self) -> None:
        """Move to the next completion candidate in the active list."""
        option_list = self._active_completion_list()
        if option_list.option_count:
            option_list.action_cursor_down()

    def action_prev_candidate(self) -> None:
        """Move to the previous completion candidate in the active list."""
        option_list = self._active_completion_list()
        if option_list.option_count:
            option_list.action_cursor_up()

    def _footer_text(self) -> str:
        if self._bead_guard_armed:
            return "enter again to wait on unverified beads | esc cancel"
        footer = "enter apply | tab complete | ^r run now | esc cancel"
        if self._is_running:
            footer = f"{footer} | active agents restart"
        return footer

    def _update_footer(self) -> None:
        self.query_one("#wait-footer", Static).update(self._footer_text())

    def _apply_validation_preview(
        self,
        preview_id: str,
        message: str,
        css_class: str,
    ) -> None:
        preview = self.query_one(preview_id, Static)
        preview.update(message)
        for old_class in self._TIME_CLASSES:
            preview.remove_class(old_class)
        preview.add_class(css_class)

    def _update_time_preview(self) -> TimeValidation:
        """Update the time preview label and return the current validation state."""
        validation = _validate_time_token(
            self.query_one("#time-input", WaitInput).value
        )
        self._apply_validation_preview(
            "#time-preview", validation.message, validation.css_class
        )
        return validation

    def _update_runners_preview(self) -> RunnersValidation:
        """Update runner-threshold preview and return validation state."""
        validation = _validate_runners_token(
            self.query_one("#runners-input", WaitInput).value
        )
        self._apply_validation_preview(
            "#runners-preview", validation.message, validation.css_class
        )
        return validation

    def _update_priority_preview(self) -> PriorityValidation:
        """Update runner-priority preview and return validation state."""
        validation = _validate_priority_token(
            self.query_one("#priority-input", WaitInput).value
        )
        self._apply_validation_preview(
            "#priority-preview", validation.message, validation.css_class
        )
        return validation

    def _update_beads_preview(self) -> BeadsValidation:
        """Update the beads preview label and return the current validation state."""
        bead_ids = parse_beads_value(self.query_one("#beads-input", WaitInput).value)
        validation = validate_beads_selection(
            self._bead_catalog,
            bead_ids,
            own_bead_ids=self._own_bead_ids,
            project_label=self._project_label,
        )
        self._apply_validation_preview(
            "#beads-preview", validation.message, validation.css_class
        )
        return validation

    def _apply(self) -> None:
        """Validate and dismiss with a structured wait result."""
        validation = self._update_time_preview()
        if not validation.valid:
            self.query_one("#time-input", WaitInput).focus()
            return
        runners_validation = self._update_runners_preview()
        if not runners_validation.valid:
            self.query_one("#runners-input", WaitInput).focus()
            return
        priority_validation = self._update_priority_preview()
        if not priority_validation.valid:
            self.query_one("#priority-input", WaitInput).focus()
            return

        beads_validation = self._update_beads_preview()
        if beads_validation.guard_armed and not self._bead_guard_armed:
            self._bead_guard_armed = True
            self.query_one("#beads-input", WaitInput).focus()
            self._update_footer()
            return

        agents = parse_agents_value(self.query_one("#agents-input", WaitInput).value)
        beads = beads_validation.bead_ids
        run_now = (
            not agents
            and not beads
            and validation.token is None
            and runners_validation.value is None
            and priority_validation.value is None
        )
        self.dismiss(
            WaitModalResult(
                agents=agents,
                time_token=validation.token,
                runners=runners_validation.value,
                priority=priority_validation.value,
                update_priority=(
                    priority_validation.value != self._current_wait_priority
                ),
                beads=beads,
                run_now=run_now,
            )
        )


__all__ = ["WaitAgentCandidate", "WaitModal", "WaitModalResult"]
