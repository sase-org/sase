"""Wait modal for the ace TUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from sase.ace.tui.agent_completion import AgentVcsWorkflow, status_style
from sase.ace.tui.models.agent_time import format_compact_duration, format_wait_until
from sase.core.time import local_now
from sase.xprompt._directive_time import parse_absolute_time, parse_duration
from sase.xprompt._exceptions import DirectiveError


@dataclass(frozen=True)
class WaitAgentCandidate:
    """Display metadata for an agent that can be selected as a wait target."""

    wait_name: str
    label: str
    status: str
    runtime: str | None = None
    model: str | None = None
    start_time: str | None = None
    duration: str | None = None
    role: str | None = None
    tribe: str | None = None
    vcs_workflow: AgentVcsWorkflow | None = None
    prompt_snippet: str = ""

    @property
    def search_text(self) -> str:
        return " ".join((self.wait_name, self.label, self.prompt_snippet)).lower()


@dataclass(frozen=True)
class WaitModalResult:
    """Structured result returned by :class:`WaitModal`."""

    agents: list[str]
    time_token: str | None
    runners: int | None = None
    priority: int | None = None
    update_priority: bool = False
    beads: list[str] = field(default_factory=list)
    run_now: bool = False


@dataclass(frozen=True)
class _TimeValidation:
    valid: bool
    token: str | None
    message: str
    css_class: str


@dataclass(frozen=True)
class _RunnersValidation:
    valid: bool
    value: int | None
    message: str
    css_class: str


@dataclass(frozen=True)
class _PriorityValidation:
    valid: bool
    value: int | None
    message: str
    css_class: str


class _WaitInput(Input):
    """Custom Input with readline-style key bindings."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+a", "home", "Home"),
        ("ctrl+e", "end", "End"),
    ]


class _AgentCompletionList(OptionList):
    """Local completion list for waitable agents."""


def _parse_agents_value(value: str) -> list[str]:
    """Parse comma-separated wait targets."""
    return [part.strip() for part in value.split(",") if part.strip()]


def _active_fragment(value: str) -> str:
    """Return the comma-separated fragment under completion."""
    return value.rsplit(",", 1)[-1].strip()


def _replace_active_fragment(value: str, replacement: str) -> str:
    """Replace the current comma fragment with *replacement* and a trailing comma."""
    prefix, separator, _fragment = value.rpartition(",")
    if separator:
        return f"{prefix.strip()}, {replacement}, "
    return f"{replacement}, "


def _format_duration_token(seconds: float) -> str:
    """Render stored wait seconds as a compact directive token."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    parts: list[str] = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if secs or not parts:
        parts.append(f"{secs}s")
    return "".join(parts)


def _format_wait_until_token(iso_value: str) -> str:
    """Render stored ISO wait target as a user-editable absolute-time token."""
    target = datetime.fromisoformat(iso_value)
    now = datetime.now(target.tzinfo) if target.tzinfo is not None else local_now()
    if target.date() == now.date():
        return target.strftime("%H%M")
    return target.strftime("%y%m%d/%H%M")


def _prefill_time_token(
    wait_duration: float | None,
    wait_until: str | None,
) -> str:
    """Return a modal time-field prefill from stored wait fields."""
    if wait_duration is not None:
        return _format_duration_token(wait_duration)
    if wait_until:
        try:
            return _format_wait_until_token(wait_until)
        except ValueError:
            return ""
    return ""


def _validate_time_token(token: str) -> _TimeValidation:
    """Validate a duration or absolute wait-time token for live preview."""
    token = token.strip()
    if not token:
        return _TimeValidation(
            valid=True,
            token=None,
            message="e.g. 5m | 1h30m | 1430 | 260415/0900",
            css_class="wait-time-neutral",
        )

    duration = parse_duration(token)
    if duration is not None:
        label = format_compact_duration(duration)
        return _TimeValidation(
            valid=True,
            token=token,
            message=f"floor: waits {label} after deps",
            css_class="wait-time-valid",
        )

    try:
        absolute = parse_absolute_time(token)
    except DirectiveError as exc:
        return _TimeValidation(
            valid=False,
            token=None,
            message=str(exc),
            css_class="wait-time-error",
        )
    if absolute is not None:
        return _TimeValidation(
            valid=True,
            token=token,
            message=f"until {format_wait_until(absolute)}",
            css_class="wait-time-valid",
        )

    return _TimeValidation(
        valid=False,
        token=None,
        message="time must be a duration or absolute time",
        css_class="wait-time-error",
    )


def _validate_runners_token(token: str) -> _RunnersValidation:
    """Validate an existing-runner threshold for live preview."""
    token = token.strip()
    if not token:
        return _RunnersValidation(
            valid=True,
            value=None,
            message="uses the global max_running_agents cap",
            css_class="wait-time-neutral",
        )
    if not token.isdigit():
        return _RunnersValidation(
            valid=False,
            value=None,
            message="runners must be a non-negative integer",
            css_class="wait-time-error",
        )
    value = int(token)
    message = f"starts when at most {value} other agents are running"
    if value == 0:
        message = "drain barrier: starts when no other agents are running"
    return _RunnersValidation(
        valid=True,
        value=value,
        message=message,
        css_class="wait-time-valid",
    )


def _validate_priority_token(token: str) -> _PriorityValidation:
    """Validate a runner-slot priority for live preview."""
    token = token.strip()
    if not token:
        return _PriorityValidation(
            valid=True,
            value=None,
            message="lower values start first; default is 10",
            css_class="wait-time-neutral",
        )
    if not token.isdigit():
        return _PriorityValidation(
            valid=False,
            value=None,
            message="priority must be a non-negative integer",
            css_class="wait-time-error",
        )
    value = int(token)
    return _PriorityValidation(
        valid=True,
        value=value,
        message=f"runner-slot priority {value}; lower values start first",
        css_class="wait-time-valid",
    )


def _truncate(value: str, width: int) -> str:
    """Truncate *value* to a fixed display width."""
    if len(value) <= width:
        return value
    if width <= 1:
        return value[:width]
    return value[: width - 1] + "…"


def _status_style(status: str) -> str:
    return status_style(status)


def _candidate_option(candidate: WaitAgentCandidate, index: int) -> Option:
    """Render one agent completion row."""
    model = _truncate(candidate.model or "-", 18)
    start = candidate.start_time or "--:--"
    duration = _truncate(candidate.duration or "-", 8)
    role_parts = [part for part in (candidate.role, candidate.tribe) if part]
    role = _truncate("/".join(role_parts), 12) if role_parts else ""

    text = Text()
    text.append("● ", style=_status_style(candidate.status))
    text.append(f"{_truncate(candidate.label, 18):<18}", style="bold")
    text.append(" ")
    text.append(f"{_truncate(candidate.status, 10):<10}", style="dim")
    text.append(" ")
    text.append(f"{model:<18}", style="dim")
    text.append(" ")
    text.append(f"{start:<5}", style="dim")
    text.append(" ")
    text.append(f"{duration:<8}", style="dim")
    if role:
        text.append(" ")
        text.append(role, style="dim")
    return Option(text, id=f"wait-agent-{index}")


class WaitModal(ModalScreen[WaitModalResult | None]):
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

    def __init__(
        self,
        current_waiting_for: list[str] | None = None,
        current_waiting_for_beads: list[str] | None = None,
        current_wait_duration: float | None = None,
        current_wait_until: str | None = None,
        current_wait_runners: int | None = None,
        current_wait_priority: int | None = None,
        candidates: list[WaitAgentCandidate] | None = None,
        is_running: bool = False,
    ) -> None:
        """Initialize the wait modal."""
        super().__init__()
        self._current_waiting_for = current_waiting_for or []
        self._current_waiting_for_beads = current_waiting_for_beads or []
        self._time_prefill = _prefill_time_token(
            current_wait_duration,
            current_wait_until,
        )
        self._runners_prefill = (
            str(current_wait_runners) if current_wait_runners is not None else ""
        )
        self._priority_prefill = (
            str(current_wait_priority) if current_wait_priority is not None else ""
        )
        self._current_wait_priority = current_wait_priority
        self._candidates = candidates or []
        self._filtered_candidates: list[WaitAgentCandidate] = []
        self._is_running = is_running
        self._programmatic_highlight = False

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        agent_prefill = ", ".join(self._current_waiting_for)
        with Container():
            yield Label("Wait", id="modal-title")
            yield Static(
                "Wait for agents, a time floor, and/or a runner threshold.",
                id="wait-modal-summary",
            )
            if self._current_waiting_for_beads:
                yield Label("Beads (read-only)", classes="wait-field-label")
                yield Static(
                    ", ".join(self._current_waiting_for_beads),
                    id="wait-beads-summary",
                )
            yield Label("Agents", classes="wait-field-label")
            yield _WaitInput(
                value=agent_prefill,
                placeholder="agent name, agent.two",
                id="agents-input",
            )
            yield _AgentCompletionList(id="agent-completion")
            yield Label("Time", classes="wait-field-label")
            yield _WaitInput(
                value=self._time_prefill,
                placeholder="5m, 1h30m, 1430",
                id="time-input",
            )
            yield Static("", id="time-preview")
            yield Label("Runners", classes="wait-field-label")
            yield _WaitInput(
                value=self._runners_prefill,
                placeholder="global cap",
                id="runners-input",
            )
            yield Static("", id="runners-preview")
            yield Label("Priority", classes="wait-field-label")
            yield _WaitInput(
                value=self._priority_prefill,
                placeholder="10",
                id="priority-input",
            )
            yield Static("", id="priority-preview")
            footer = "enter apply | tab complete | ^r run now | esc cancel"
            if self._is_running:
                footer = f"{footer} | active agents restart"
            yield Static(footer, id="wait-footer")

    def on_mount(self) -> None:
        """Focus the agents field and initialize live state."""
        self._refresh_completion()
        self._update_time_preview()
        self._update_runners_preview()
        self._update_priority_preview()
        agents_input = self.query_one("#agents-input", _WaitInput)
        agents_input.focus()
        agents_input.cursor_position = len(agents_input.value)

    def on_key(self, event: events.Key) -> None:
        """Keep completion keys local to the modal."""
        if event.key == "enter" and isinstance(self.focused, _AgentCompletionList):
            self._accept_highlighted_candidate()
            event.prevent_default()
            event.stop()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Refresh completions and time validation as inputs change."""
        if event.input.id == "agents-input":
            self._refresh_completion()
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
        """Handle Enter in either input."""
        event.stop()
        if event.input.id == "agents-input" and _active_fragment(event.value):
            if self._accept_highlighted_candidate():
                return
        self._apply()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Accept an agent completion row."""
        if event.option_list.id != "agent-completion":
            return
        self._accept_candidate_index(event.option_index)

    def on_option_list_option_highlighted(
        self, event: OptionList.OptionHighlighted
    ) -> None:
        """Suppress programmatic completion highlight echoes."""
        if event.option_list.id == "agent-completion" and self._programmatic_highlight:
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
        """Accept the highlighted agent completion, if any."""
        self._accept_highlighted_candidate()

    def action_next_candidate(self) -> None:
        """Move to the next completion candidate."""
        option_list = self.query_one("#agent-completion", _AgentCompletionList)
        if option_list.option_count:
            option_list.action_cursor_down()

    def action_prev_candidate(self) -> None:
        """Move to the previous completion candidate."""
        option_list = self.query_one("#agent-completion", _AgentCompletionList)
        if option_list.option_count:
            option_list.action_cursor_up()

    def _refresh_completion(self) -> None:
        """Filter the dropdown on the active comma fragment."""
        agents_input = self.query_one("#agents-input", _WaitInput)
        fragment = _active_fragment(agents_input.value).lower()
        if fragment:
            self._filtered_candidates = [
                c for c in self._candidates if fragment in c.search_text
            ]
        else:
            self._filtered_candidates = list(self._candidates)

        option_list = self.query_one("#agent-completion", _AgentCompletionList)
        options: list[Option] = [
            _candidate_option(candidate, index)
            for index, candidate in enumerate(self._filtered_candidates)
        ]
        if not options:
            options = [
                Option(Text("  no matching visible agents", style="dim"), disabled=True)
            ]

        self._programmatic_highlight = True
        try:
            option_list.clear_options()
            option_list.add_options(options)
            option_list.highlighted = 0 if self._filtered_candidates else None
        finally:
            self._programmatic_highlight = False

    def _update_time_preview(self) -> _TimeValidation:
        """Update the time preview label and return the current validation state."""
        time_input = self.query_one("#time-input", _WaitInput)
        preview = self.query_one("#time-preview", Static)
        validation = _validate_time_token(time_input.value)
        preview.update(validation.message)
        for css_class in self._TIME_CLASSES:
            preview.remove_class(css_class)
        preview.add_class(validation.css_class)
        return validation

    def _update_runners_preview(self) -> _RunnersValidation:
        """Update runner-threshold preview and return validation state."""
        runners_input = self.query_one("#runners-input", _WaitInput)
        preview = self.query_one("#runners-preview", Static)
        validation = _validate_runners_token(runners_input.value)
        preview.update(validation.message)
        for css_class in self._TIME_CLASSES:
            preview.remove_class(css_class)
        preview.add_class(validation.css_class)
        return validation

    def _update_priority_preview(self) -> _PriorityValidation:
        """Update runner-priority preview and return validation state."""
        priority_input = self.query_one("#priority-input", _WaitInput)
        preview = self.query_one("#priority-preview", Static)
        validation = _validate_priority_token(priority_input.value)
        preview.update(validation.message)
        for css_class in self._TIME_CLASSES:
            preview.remove_class(css_class)
        preview.add_class(validation.css_class)
        return validation

    def _accept_highlighted_candidate(self) -> bool:
        """Accept the currently highlighted candidate."""
        option_list = self.query_one("#agent-completion", _AgentCompletionList)
        highlighted = option_list.highlighted
        if highlighted is None:
            return False
        return self._accept_candidate_index(highlighted)

    def _accept_candidate_index(self, index: int | None) -> bool:
        """Insert a candidate into the agents input."""
        if index is None or not (0 <= index < len(self._filtered_candidates)):
            return False
        candidate = self._filtered_candidates[index]
        agents_input = self.query_one("#agents-input", _WaitInput)
        agents_input.value = _replace_active_fragment(
            agents_input.value,
            candidate.wait_name,
        )
        agents_input.cursor_position = len(agents_input.value)
        agents_input.focus()
        self._refresh_completion()
        return True

    def _apply(self) -> None:
        """Validate and dismiss with a structured wait result."""
        validation = self._update_time_preview()
        if not validation.valid:
            self.query_one("#time-input", _WaitInput).focus()
            return
        runners_validation = self._update_runners_preview()
        if not runners_validation.valid:
            self.query_one("#runners-input", _WaitInput).focus()
            return
        priority_validation = self._update_priority_preview()
        if not priority_validation.valid:
            self.query_one("#priority-input", _WaitInput).focus()
            return
        agents = _parse_agents_value(self.query_one("#agents-input", _WaitInput).value)
        run_now = (
            not agents
            and not self._current_waiting_for_beads
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
                beads=list(self._current_waiting_for_beads),
                run_now=run_now,
            )
        )
