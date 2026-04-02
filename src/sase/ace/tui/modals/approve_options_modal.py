"""Approve-with-options modal for plan approval."""

from dataclasses import dataclass

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Static, Switch, TextArea


class _PromptTextArea(TextArea):
    """TextArea that yields ``enter`` to the parent modal instead of inserting a newline."""

    async def _on_key(self, event: events.Key) -> None:  # type: ignore[override]
        if event.key == "enter":
            event.prevent_default()
            return
        await super()._on_key(event)


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
        ("enter", "approve", "Approve"),
    ]

    def compose(self) -> ComposeResult:
        with Container(id="approve-options-container"):
            yield Static(
                "[bold cyan]Approve with Options[/bold cyan]",
                id="approve-options-title",
            )

            with Horizontal(classes="approve-options-row"):
                yield Static(
                    "Commit plan",
                    id="commit-plan-label",
                    classes="approve-options-label",
                )
                yield Switch(value=True, id="commit-plan-switch")

            with Horizontal(classes="approve-options-row"):
                yield Static(
                    "Run coder agent",
                    id="run-coder-label",
                    classes="approve-options-label",
                )
                yield Switch(value=True, id="run-coder-switch")

            yield Static("Additional prompt:", classes="approve-options-prompt-label")
            yield _PromptTextArea("", id="coder-prompt-input")

            yield Static(
                "[green]enter[/green]=Approve  "
                "[blue]space[/blue]=Toggle  "
                "[dim]ctrl+n[/dim]=Next  "
                "[dim]ctrl+p[/dim]=Prev  "
                "[dim]esc[/dim]=Back",
                id="approve-options-footer",
            )

    def on_mount(self) -> None:
        self.query_one("#commit-plan-switch", Switch).focus()

    def on_switch_changed(self, event: Switch.Changed) -> None:  # noqa: ARG002
        self._sync_constraints()

    def _sync_constraints(self) -> None:
        """Enforce the invariant: at least one of commit/coder must be ON."""
        commit_sw = self.query_one("#commit-plan-switch", Switch)
        coder_sw = self.query_one("#run-coder-switch", Switch)
        commit_lbl = self.query_one("#commit-plan-label", Static)
        coder_lbl = self.query_one("#run-coder-label", Static)
        prompt_input = self.query_one("#coder-prompt-input", TextArea)
        prompt_label = self.query_one(".approve-options-prompt-label", Static)

        if not commit_sw.value:
            # Coder only — lock coder ON
            coder_sw.disabled = True
            coder_lbl.update("Run coder agent (required)")
            coder_lbl.add_class("locked")
            commit_sw.disabled = False
            commit_lbl.update("Commit plan")
            commit_lbl.remove_class("locked")
        elif not coder_sw.value:
            # Commit only — lock commit ON
            commit_sw.disabled = True
            commit_lbl.update("Commit plan (required)")
            commit_lbl.add_class("locked")
            coder_sw.disabled = False
            coder_lbl.update("Run coder agent")
            coder_lbl.remove_class("locked")
        else:
            # Both ON — unlock both
            commit_sw.disabled = False
            coder_sw.disabled = False
            commit_lbl.update("Commit plan")
            commit_lbl.remove_class("locked")
            coder_lbl.update("Run coder agent")
            coder_lbl.remove_class("locked")

        # Prompt area enabled only when coder is ON
        prompt_input.disabled = not coder_sw.value
        if coder_sw.value:
            prompt_label.remove_class("disabled")
        else:
            prompt_label.add_class("disabled")

    def on_key(self, event: events.Key) -> None:
        """Handle key events within the modal.

        Escape and enter are handled directly (not via BINDINGS) so the modal
        acts as an event barrier.  Printable characters (except space, which
        Switch needs for toggling) are stopped here to prevent them from
        reaching ``EventHandlersMixin.on_key`` and accidentally activating a
        custom-mode prefix.
        """
        if event.key == "enter":
            event.prevent_default()
            event.stop()
            self.action_approve()
        elif event.key == "escape":
            event.prevent_default()
            event.stop()
            self.action_cancel()
        elif event.key == "ctrl+n":
            event.prevent_default()
            event.stop()
            self.focus_next()
        elif event.key == "ctrl+p":
            event.prevent_default()
            event.stop()
            self.focus_previous()
        elif event.character and event.character.isprintable() and event.key != "space":
            # Printable chars that reach this handler came from a widget
            # that didn't consume them (e.g. Switch).  Stop them so they
            # don't leak to EventHandlersMixin.on_key at the App level.
            event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_approve(self) -> None:
        commit_plan = self.query_one("#commit-plan-switch", Switch).value
        run_coder = self.query_one("#run-coder-switch", Switch).value
        raw = self.query_one("#coder-prompt-input", TextArea).text.strip()
        coder_prompt = raw if raw else None
        self.dismiss(
            ApproveOptionsResult(
                commit_plan=commit_plan,
                run_coder=run_coder,
                coder_prompt=coder_prompt,
            )
        )
