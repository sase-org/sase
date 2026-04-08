"""Approve-with-options modal for plan approval."""

from dataclasses import dataclass

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Static, Switch


def _model_display_label(coder_model: str | None) -> str:
    """Format the coder model for display in the modal."""
    if coder_model is None:
        return "Same as planner"
    from sase.llm_provider.registry import (
        format_provider_model_label,
        resolve_model_provider,
    )

    provider, model = resolve_model_provider(coder_model)
    return format_provider_model_label(provider, model)


@dataclass
class ApproveOptionsResult:
    """Result from the approve-with-options modal."""

    commit_plan: bool
    run_coder: bool
    coder_prompt: str | None
    coder_model: str | None = None


@dataclass
class ApproveOptionsEditPrompt:
    """Sentinel result: user wants to edit the coder prompt via PromptInputBar."""

    commit_plan: bool
    run_coder: bool
    coder_prompt: str
    coder_model: str | None = None


class ApproveOptionsModal(
    ModalScreen[ApproveOptionsResult | ApproveOptionsEditPrompt | None],
):
    """Modal for configuring plan approval options."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "approve", "Approve"),
        ("p", "edit_prompt", "Edit prompt"),
        ("m", "select_model", "Model"),
        ("q", "cancel", "Quit"),
    ]

    def __init__(
        self,
        commit_plan: bool = True,
        run_coder: bool = True,
        coder_prompt: str = "",
        coder_model: str | None = None,
    ) -> None:
        super().__init__()
        self._init_commit_plan = commit_plan
        self._init_run_coder = run_coder
        self._coder_prompt = coder_prompt
        self._coder_model = coder_model

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
                yield Switch(value=self._init_commit_plan, id="commit-plan-switch")

            with Horizontal(classes="approve-options-row"):
                yield Static(
                    "Run coder agent",
                    id="run-coder-label",
                    classes="approve-options-label",
                )
                yield Switch(value=self._init_run_coder, id="run-coder-switch")

            yield Static("Coder model:", classes="approve-options-model-label")
            yield Static(
                _model_display_label(self._coder_model),
                id="coder-model-display",
            )

            yield Static("Additional prompt:", classes="approve-options-prompt-label")
            display = self._coder_prompt or "none"
            if len(display) > 60:
                display = display[:57] + "..."
            yield Static(display, id="coder-prompt-display")

            yield Static(
                "[green]enter[/green]=Approve  "
                "[blue]space[/blue]=Toggle  "
                "[magenta]m[/magenta]=Model  "
                "[magenta]p[/magenta]=Edit prompt  "
                "[dim]ctrl+n[/dim]=Next  "
                "[dim]ctrl+p[/dim]=Prev  "
                "[dim]q/esc[/dim]=Back",
                id="approve-options-footer",
            )

    def on_mount(self) -> None:
        self.query_one("#commit-plan-switch", Switch).focus()
        self._sync_constraints()

    def on_switch_changed(self, event: Switch.Changed) -> None:  # noqa: ARG002
        self._sync_constraints()

    def _sync_constraints(self) -> None:
        """Enforce the invariant: at least one of commit/coder must be ON."""
        commit_sw = self.query_one("#commit-plan-switch", Switch)
        coder_sw = self.query_one("#run-coder-switch", Switch)
        commit_lbl = self.query_one("#commit-plan-label", Static)
        coder_lbl = self.query_one("#run-coder-label", Static)
        prompt_display = self.query_one("#coder-prompt-display", Static)
        prompt_label = self.query_one(".approve-options-prompt-label", Static)
        model_display = self.query_one("#coder-model-display", Static)
        model_label = self.query_one(".approve-options-model-label", Static)

        if not commit_sw.value:
            # Coder only -- lock coder ON
            coder_sw.disabled = True
            coder_lbl.update("Run coder agent (required)")
            coder_lbl.add_class("locked")
            commit_sw.disabled = False
            commit_lbl.update("Commit plan")
            commit_lbl.remove_class("locked")
        elif not coder_sw.value:
            # Commit only -- lock commit ON
            commit_sw.disabled = True
            commit_lbl.update("Commit plan (required)")
            commit_lbl.add_class("locked")
            coder_sw.disabled = False
            coder_lbl.update("Run coder agent")
            coder_lbl.remove_class("locked")
        else:
            # Both ON -- unlock both
            commit_sw.disabled = False
            coder_sw.disabled = False
            commit_lbl.update("Commit plan")
            commit_lbl.remove_class("locked")
            coder_lbl.update("Run coder agent")
            coder_lbl.remove_class("locked")

        # Prompt/model display and p/m keys enabled only when coder is ON
        if coder_sw.value:
            prompt_label.remove_class("disabled")
            prompt_display.remove_class("disabled")
            model_label.remove_class("disabled")
            model_display.remove_class("disabled")
        else:
            prompt_label.add_class("disabled")
            prompt_display.add_class("disabled")
            model_label.add_class("disabled")
            model_display.add_class("disabled")

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
        elif event.key == "p":
            event.prevent_default()
            event.stop()
            self.action_edit_prompt()
        elif event.key == "m":
            event.prevent_default()
            event.stop()
            self.action_select_model()
        elif event.key == "q":
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
            event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_select_model(self) -> None:
        """Open the model picker modal (no-op when coder is OFF)."""
        coder_sw = self.query_one("#run-coder-switch", Switch)
        if not coder_sw.value:
            return

        from .custom_model_input_modal import CustomModelInputModal
        from .model_picker_modal import CUSTOM_SENTINEL, ModelPickerModal

        def on_picker_dismiss(result: str | None) -> None:
            if result == CUSTOM_SENTINEL:
                # Open the custom model input modal
                def on_custom_dismiss(custom_result: str | None) -> None:
                    if custom_result is not None:
                        self._coder_model = custom_result
                        self._update_model_display()

                self.app.push_screen(CustomModelInputModal(), on_custom_dismiss)
            elif result is not None:
                # A known model was selected (result is the model id)
                self._coder_model = result
                self._update_model_display()
            # result is None means "Same as planner" was selected or cancel
            # For cancel (escape), result is None via OptionListNavigationMixin.action_cancel
            # For "Same as planner", result is also None via ModelPickerModal

        self.app.push_screen(ModelPickerModal(), on_picker_dismiss)

    def _update_model_display(self) -> None:
        """Refresh the model display label."""
        model_display = self.query_one("#coder-model-display", Static)
        model_display.update(_model_display_label(self._coder_model))

    def action_edit_prompt(self) -> None:
        """Dismiss with edit-prompt sentinel so the caller can delegate to PromptInputBar."""
        coder_sw = self.query_one("#run-coder-switch", Switch)
        if not coder_sw.value:
            return  # Prompt irrelevant when coder is OFF
        self.dismiss(
            ApproveOptionsEditPrompt(
                commit_plan=self.query_one("#commit-plan-switch", Switch).value,
                run_coder=True,
                coder_prompt=self._coder_prompt,
                coder_model=self._coder_model,
            )
        )

    def action_approve(self) -> None:
        commit_plan = self.query_one("#commit-plan-switch", Switch).value
        run_coder = self.query_one("#run-coder-switch", Switch).value
        coder_prompt = self._coder_prompt if self._coder_prompt else None
        self.dismiss(
            ApproveOptionsResult(
                commit_plan=commit_plan,
                run_coder=run_coder,
                coder_prompt=coder_prompt,
                coder_model=self._coder_model,
            )
        )
