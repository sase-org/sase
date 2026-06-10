"""Custom approval modal for plan approval."""

from dataclasses import dataclass

from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from .plan_approval_modal import (
    PlanApprovalChoice,
    approval_protocol_for_choice,
)


_CHOICE_ORDER: tuple[PlanApprovalChoice, ...] = (
    "approve",
    "tale",
    "epic",
    "legend",
)
_CHOICE_KEYS: dict[str, PlanApprovalChoice] = {
    "a": "approve",
    "t": "tale",
    "e": "epic",
    "l": "legend",
}
_CHOICE_LABELS: dict[PlanApprovalChoice, str] = {
    "approve": "Approve",
    "tale": "Tale",
    "epic": "Epic",
    "legend": "Legend",
}
_CHOICE_CONSEQUENCES: dict[PlanApprovalChoice, str] = {
    "approve": "No SDD commit; run coder",
    "tale": "Commit to sdd/tales; run coder",
    "epic": "Commit to sdd/epics; launch bd/new_epic",
    "legend": "Commit to sdd/legends; launch bd/new_legend",
}


def _model_display_label(coder_model: str | None) -> str:
    """Format the coder model for display in the modal."""
    from sase.llm_provider.registry import (
        format_provider_model_label,
        resolve_model_provider,
    )

    if coder_model is None:
        from sase.llm_provider import resolve_effective_worker_provider_model

        worker_provider, worker_model = resolve_effective_worker_provider_model()
        return f"Worker — {format_provider_model_label(worker_provider, worker_model)}"

    provider, model = resolve_model_provider(coder_model)
    return format_provider_model_label(provider, model)


@dataclass
class ApproveOptionsResult:
    """Result from the custom approval modal.

    The class name is preserved for compatibility with existing imports.
    """

    choice: PlanApprovalChoice
    coder_prompt: str | None
    coder_model: str | None = None

    @property
    def commit_plan(self) -> bool:
        return approval_protocol_for_choice(self.choice).commit_plan

    @property
    def run_coder(self) -> bool:
        return approval_protocol_for_choice(self.choice).run_coder


@dataclass
class ApproveOptionsEditPrompt:
    """Sentinel result: user wants to edit the coder prompt via PromptInputBar."""

    choice: PlanApprovalChoice
    coder_prompt: str
    coder_model: str | None = None

    @property
    def commit_plan(self) -> bool:
        return approval_protocol_for_choice(self.choice).commit_plan

    @property
    def run_coder(self) -> bool:
        return approval_protocol_for_choice(self.choice).run_coder


class ApproveOptionsModal(
    ModalScreen[ApproveOptionsResult | ApproveOptionsEditPrompt | None],
):
    """Modal for choosing a custom plan approval action."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "approve", "Choose"),
        ("a", "choose_approve", "Approve"),
        ("t", "choose_tale", "Tale"),
        ("e", "choose_epic", "Epic"),
        ("l", "choose_legend", "Legend"),
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
        choice: PlanApprovalChoice | None = None,
    ) -> None:
        super().__init__()
        self._choice = choice or _choice_from_legacy_flags(commit_plan, run_coder)
        self._coder_prompt = coder_prompt
        self._coder_model = coder_model

    def compose(self) -> ComposeResult:
        with Container(id="approve-options-container"):
            yield Static(
                "[bold cyan]Custom Approval[/bold cyan]",
                id="approve-options-title",
            )

            for choice in _CHOICE_ORDER:
                yield Static(
                    self._choice_row_markup(choice),
                    id=f"approval-choice-{choice}",
                    classes="approval-choice-row",
                )

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
                "[green]enter[/green]=Choose  "
                "[green]a/t/e/l[/green]=Action  "
                "[magenta]m[/magenta]=Model  "
                "[magenta]p[/magenta]=Edit prompt  "
                "[dim]ctrl+n[/dim]=Next  "
                "[dim]ctrl+p[/dim]=Prev  "
                "[dim]q/esc[/dim]=Back",
                id="approve-options-footer",
            )

    def on_mount(self) -> None:
        self._refresh_choice_rows()

    def _choice_row_markup(self, choice: PlanApprovalChoice) -> str:
        """Render one selectable action row."""
        marker = ">" if choice == self._choice else " "
        key = next(
            k for k, mapped_choice in _CHOICE_KEYS.items() if mapped_choice == choice
        )
        label = _CHOICE_LABELS[choice]
        consequence = _CHOICE_CONSEQUENCES[choice]
        if choice == self._choice:
            return f"[bold green]{marker} {key} {label:<7}[/] [dim]{consequence}[/]"
        return (
            f"[dim]{marker}[/] [green]{key}[/green] {label:<7} [dim]{consequence}[/dim]"
        )

    def _refresh_choice_rows(self) -> None:
        """Refresh action rows after the current choice changes."""
        for choice in _CHOICE_ORDER:
            row = self.query_one(f"#approval-choice-{choice}", Static)
            row.update(self._choice_row_markup(choice))
            row.set_class(choice == self._choice, "selected")

    def _select_choice(self, choice: PlanApprovalChoice) -> None:
        self._choice = choice
        self._refresh_choice_rows()

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
        elif event.key in _CHOICE_KEYS:
            event.prevent_default()
            event.stop()
            self._select_choice(_CHOICE_KEYS[event.key])
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
            self._select_relative_choice(1)
        elif event.key == "ctrl+p":
            event.prevent_default()
            event.stop()
            self._select_relative_choice(-1)
        elif event.character and event.character.isprintable():
            event.stop()

    def _select_relative_choice(self, offset: int) -> None:
        index = _CHOICE_ORDER.index(self._choice)
        self._select_choice(_CHOICE_ORDER[(index + offset) % len(_CHOICE_ORDER)])

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_choose_approve(self) -> None:
        self._select_choice("approve")

    def action_choose_tale(self) -> None:
        self._select_choice("tale")

    def action_choose_epic(self) -> None:
        self._select_choice("epic")

    def action_choose_legend(self) -> None:
        self._select_choice("legend")

    def action_select_model(self) -> None:
        """Open the model picker modal."""

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
            # result is None means "Worker model (default)" was selected or cancel
            # For cancel (escape), result is None via OptionListNavigationMixin.action_cancel
            # For "Worker model (default)", result is also None via ModelPickerModal

        self.app.push_screen(ModelPickerModal(), on_picker_dismiss)

    def _update_model_display(self) -> None:
        """Refresh the model display label."""
        model_display = self.query_one("#coder-model-display", Static)
        model_display.update(_model_display_label(self._coder_model))

    def action_edit_prompt(self) -> None:
        """Dismiss with edit-prompt sentinel so the caller can delegate to PromptInputBar."""
        self.dismiss(
            ApproveOptionsEditPrompt(
                choice=self._choice,
                coder_prompt=self._coder_prompt,
                coder_model=self._coder_model,
            )
        )

    def action_approve(self) -> None:
        coder_prompt = self._coder_prompt if self._coder_prompt else None
        self.dismiss(
            ApproveOptionsResult(
                choice=self._choice,
                coder_prompt=coder_prompt,
                coder_model=self._coder_model,
            )
        )


def _choice_from_legacy_flags(
    commit_plan: bool,
    run_coder: bool,  # noqa: ARG001 - kept to accept old caller state.
) -> PlanApprovalChoice:
    """Map old switch state to the closest explicit custom action."""
    return "tale" if commit_plan else "approve"


CustomApprovalModal = ApproveOptionsModal
CustomApprovalResult = ApproveOptionsResult
CustomApprovalEditPrompt = ApproveOptionsEditPrompt
