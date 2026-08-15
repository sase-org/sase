"""Action and positive-integer cards for the Models runner limit."""

from __future__ import annotations

from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Static

from sase.config import EffectiveRunnerLimitSnapshot

from .models_panel_duration import format_remaining
from .models_panel_positive_int import parse_positive_base10

type RunnerLimitAction = Literal["edit", "override", "clear"]
type RunnerLimitMode = Literal["edit", "override"]


def _parse_runner_limit(raw: str) -> int:
    """Parse one unadorned base-10 positive integer."""
    return parse_positive_base10(
        raw,
        empty="Enter a running-agent limit.",
        minimum="The running-agent limit must be at least 1.",
    )


def _format_agents(limit: int) -> str:
    return f"{limit} {'agent' if limit == 1 else 'agents'}"


class RunnerLimitActionModal(ModalScreen[RunnerLimitAction | None]):
    """Choose persistent edit, temporary override, or clear."""

    BINDINGS = [
        Binding("e", "choose_edit", "Edit", show=False),
        Binding("o", "choose_override", "Override", show=False),
        Binding("x", "choose_clear", "Clear", show=False),
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("q", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        snapshot: EffectiveRunnerLimitSnapshot,
        *,
        now: float,
        use_chezmoi: bool,
    ) -> None:
        super().__init__()
        self._snapshot = snapshot
        self._now = now
        self._use_chezmoi = use_chezmoi

    def compose(self) -> ComposeResult:
        with Container(id="runner-limit-action-container"):
            yield Static("Max Running Agents", id="runner-limit-action-title")
            yield Static(self._status_text(), id="runner-limit-action-status")
            with Vertical(id="runner-limit-action-choices"):
                target = "chezmoi source" if self._use_chezmoi else "user sase.yml"
                yield Static(
                    "  [bold]e[/]   Edit permanently\n"
                    f"      [dim]Preview and write the {target}.[/]",
                    classes="runner-limit-action-row",
                )
                yield Static(
                    "  [bold]o[/]   Override temporarily\n"
                    "      [dim]Leave configuration unchanged; choose a duration.[/]",
                    classes="runner-limit-action-row",
                )
                if self._snapshot.active_override(self._now) is not None:
                    yield Static(
                        "  [bold]x[/]   Clear temporary override\n"
                        "      [dim]Resume the configured global cap.[/]",
                        classes="runner-limit-action-row",
                    )
            yield Static(
                "Already-running agents continue if the limit is lowered.\n"
                "Explicit %wait(runners=N) keeps its initial-admission threshold.",
                id="runner-limit-action-note",
            )
            yield Static("esc / q: cancel", id="runner-limit-action-footer")

    def _status_text(self) -> Text:
        text = Text("Current global-cap limit\n", style="bold")
        override = self._snapshot.active_override(self._now)
        if override is None:
            text.append(
                _format_agents(self._snapshot.configured_limit), style="bold cyan"
            )
            return text
        text.append(_format_agents(override.limit), style="bold cyan")
        text.append("  ", style="dim")
        if override.expires_at is None:
            text.append("override · until cleared", style="bold #AF87FF")
        else:
            text.append(
                f"override · {format_remaining(override.expires_at - self._now)} left",
                style="bold #AF87FF",
            )
        text.append("\nConfigured: ", style="dim")
        text.append(_format_agents(self._snapshot.configured_limit), style="bold cyan")
        return text

    def action_choose_edit(self) -> None:
        self.dismiss("edit")

    def action_choose_override(self) -> None:
        self.dismiss("override")

    def action_choose_clear(self) -> None:
        if self._snapshot.active_override(self._now) is not None:
            self.dismiss("clear")

    def action_cancel(self) -> None:
        self.dismiss(None)


class RunnerLimitValueModal(ModalScreen[int | None]):
    """Focused positive-integer editor for persistent or temporary limits."""

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, mode: RunnerLimitMode, *, initial: int) -> None:
        super().__init__()
        self._mode = mode
        self._initial = initial

    def compose(self) -> ComposeResult:
        with Container(id="runner-limit-value-container"):
            yield Static("Running Agent Limit", id="runner-limit-value-title")
            subtitle = (
                "Set the persistent global-cap configuration."
                if self._mode == "edit"
                else "Set a temporary machine-wide global cap."
            )
            yield Static(subtitle, id="runner-limit-value-subtitle")
            yield Input(
                value=str(self._initial),
                id="runner-limit-value-input",
            )
            yield Label("", id="runner-limit-value-error")
            yield Static(
                "minimum 1 · package default 10",
                id="runner-limit-value-constraints",
            )
            yield Static(
                "enter: continue   esc: cancel", id="runner-limit-value-footer"
            )

    def on_mount(self) -> None:
        value_input = self.query_one("#runner-limit-value-input", Input)
        value_input.focus()
        value_input.select_all()
        self._render_validation(value_input.value)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "runner-limit-value-input":
            self._render_validation(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "runner-limit-value-input":
            return
        try:
            value = _parse_runner_limit(event.value)
        except ValueError as error:
            self.query_one("#runner-limit-value-error", Label).update(str(error))
            event.input.focus()
            return
        self.dismiss(value)

    def _render_validation(self, raw: str) -> None:
        error_label = self.query_one("#runner-limit-value-error", Label)
        try:
            _parse_runner_limit(raw)
        except ValueError as error:
            error_label.update(str(error))
        else:
            error_label.update("valid positive integer")

    def action_cancel(self) -> None:
        self.dismiss(None)


__all__ = [
    "RunnerLimitAction",
    "RunnerLimitActionModal",
    "RunnerLimitMode",
    "RunnerLimitValueModal",
]
