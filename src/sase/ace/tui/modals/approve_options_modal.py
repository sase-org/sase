"""Approve-with-options modal for plan approval."""

from dataclasses import dataclass

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Input, Static, Switch


@dataclass
class ApproveOptionsResult:
    """Result from the approve-with-options modal."""

    commit_plan: bool
    run_coder: bool
    coder_prompt: str | None


class ApproveOptionsModal(ModalScreen[ApproveOptionsResult | None]):
    """Modal for configuring plan approval options."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
        ("enter", "approve", "Approve"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="approve-options-container"):
            yield Static(
                "[bold cyan]Approve with Options[/bold cyan]",
                id="approve-options-title",
            )

            with Horizontal(classes="approve-options-row"):
                yield Static("Commit plan", classes="approve-options-label")
                yield Switch(value=True, id="commit-plan-switch")

            with Horizontal(classes="approve-options-row"):
                yield Static("Run coder agent", classes="approve-options-label")
                yield Switch(value=True, id="run-coder-switch")

            yield Static("Additional prompt:", classes="approve-options-prompt-label")
            yield Input(
                placeholder="e.g. #review+  (supports xprompts)",
                id="coder-prompt-input",
            )

            yield Static(
                "[green]enter[/green]=Approve  "
                "[blue]space[/blue]=Toggle  "
                "[dim]tab[/dim]=Next  "
                "[dim]q[/dim]=Back",
                id="approve-options-footer",
            )

    def on_mount(self) -> None:
        self.query_one("#commit-plan-switch", Switch).focus()

    def on_switch_changed(self, event: Switch.Changed) -> None:
        if event.switch.id == "run-coder-switch":
            inp = self.query_one("#coder-prompt-input", Input)
            inp.disabled = not event.value
            label = self.query_one(".approve-options-prompt-label", Static)
            label.add_class("disabled") if not event.value else label.remove_class(
                "disabled"
            )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_approve(self) -> None:
        commit_plan = self.query_one("#commit-plan-switch", Switch).value
        run_coder = self.query_one("#run-coder-switch", Switch).value
        raw = self.query_one("#coder-prompt-input", Input).value.strip()
        coder_prompt = raw if raw else None
        self.dismiss(
            ApproveOptionsResult(
                commit_plan=commit_plan,
                run_coder=run_coder,
                coder_prompt=coder_prompt,
            )
        )
