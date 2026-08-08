"""Custom approval modal for plan approval."""

from dataclasses import dataclass

from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.plan_approval_choices import (
    PLAN_APPROVAL_MODAL_CHOICES,
    custom_modal_choice_for_key,
    require_plan_approval_choice,
)

from .plan_approval_results import (
    PlanApprovalChoice,
    approval_protocol_for_choice,
)


def _contextual_coder_lane(planner_llm_provider: str | None) -> tuple[str | None, str]:
    """Resolve the coder follow-up default through the planner's coder alias.

    Mirrors the runtime handoff: ``@<planner_provider>_coder`` when the planner
    recorded its provider, else the generic ``@coder``. Resolving the directive
    here keeps the modal's displayed default equal to the model the coder will
    actually launch with.
    """
    from sase.llm_provider.config import (
        CODER_MODEL_ALIAS_NAME,
        coder_model_alias_for_provider,
        role_model_directive_value,
    )
    from sase.llm_provider.registry import resolve_model_provider

    provider = (planner_llm_provider or "").strip()
    alias = (
        coder_model_alias_for_provider(provider) if provider else CODER_MODEL_ALIAS_NAME
    )
    directive = role_model_directive_value(alias)
    try:
        return resolve_model_provider(directive)
    except Exception:
        return None, directive


def _model_display_label(
    coder_model: str | None,
    choice: PlanApprovalChoice,
    *,
    planner_llm_provider: str | None = None,
) -> str:
    """Format the follow-up model for display in the modal.

    When no model is chosen, the displayed default resolves to the model the
    handoff will actually use. Epic execution models live in plan frontmatter,
    so Epic approval has no follow-up-model picker lane.
    """
    from sase.llm_provider.registry import (
        format_provider_model_label,
        resolve_model_provider,
    )

    if coder_model is None:
        if choice == "epic":
            return "Configured by epic plan frontmatter"
        coder_provider, coder_lane_model = _contextual_coder_lane(planner_llm_provider)
        label = format_provider_model_label(coder_provider, coder_lane_model)
        return f"Follow-up — {label}"

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
        *,
        planner_llm_provider: str | None = None,
    ) -> None:
        super().__init__()
        self._choice = choice or _choice_from_legacy_flags(commit_plan, run_coder)
        self._coder_prompt = coder_prompt
        self._coder_model = coder_model
        self._planner_llm_provider = planner_llm_provider

    def compose(self) -> ComposeResult:
        with Container(id="approve-options-container"):
            yield Static(
                "[bold cyan]Custom Approval[/bold cyan]",
                id="approve-options-title",
            )

            for choice in PLAN_APPROVAL_MODAL_CHOICES:
                yield Static(
                    self._choice_row_markup(choice),
                    id=f"approval-choice-{choice}",
                    classes="approval-choice-row",
                )

            yield Static("Coder model:", classes="approve-options-model-label")
            yield Static(
                self._model_display_label(),
                id="coder-model-display",
            )

            yield Static("Additional prompt:", classes="approve-options-prompt-label")
            display = self._coder_prompt or "none"
            if len(display) > 60:
                display = display[:57] + "..."
            yield Static(display, id="coder-prompt-display")

            yield Static(
                "[green]enter[/green]=Choose  "
                "[green]a/t/e[/green]=Action  "
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
        record = require_plan_approval_choice(choice)
        key = record.custom_modal_key or "?"
        label = record.display_label
        consequence = record.consequence_text
        if choice == self._choice:
            return f"[bold green]{marker} {key} {label:<7}[/] [dim]{consequence}[/]"
        return (
            f"[dim]{marker}[/] [green]{key}[/green] {label:<7} [dim]{consequence}[/dim]"
        )

    def _refresh_choice_rows(self) -> None:
        """Refresh action rows after the current choice changes."""
        for choice in PLAN_APPROVAL_MODAL_CHOICES:
            row = self.query_one(f"#approval-choice-{choice}", Static)
            row.update(self._choice_row_markup(choice))
            row.set_class(choice == self._choice, "selected")

    def _select_choice(self, choice: PlanApprovalChoice) -> None:
        self._choice = choice
        self._refresh_choice_rows()
        # The unset default differs by role (coder alias vs epic role
        # alias), so the displayed default must track the selected action.
        self._update_model_display()

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
        elif (choice := custom_modal_choice_for_key(event.key)) is not None:
            event.prevent_default()
            event.stop()
            self._select_choice(choice)
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
        index = PLAN_APPROVAL_MODAL_CHOICES.index(self._choice)
        self._select_choice(
            PLAN_APPROVAL_MODAL_CHOICES[
                (index + offset) % len(PLAN_APPROVAL_MODAL_CHOICES)
            ]
        )

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_choose_approve(self) -> None:
        self._select_choice("approve")

    def action_choose_tale(self) -> None:
        self._select_choice("tale")

    def action_choose_epic(self) -> None:
        self._select_choice("epic")

    def action_select_model(self) -> None:
        """Open the model picker modal."""

        from .custom_model_input_modal import CustomModelInputModal
        from .model_picker_modal import (
            CUSTOM_SENTINEL,
            DEFAULT_SENTINEL,
            ModelPickerModal,
        )

        def on_picker_dismiss(result: str | None) -> None:
            if result == CUSTOM_SENTINEL:
                # Open the custom model input modal
                def on_custom_dismiss(custom_result: str | None) -> None:
                    if custom_result is not None:
                        self._coder_model = custom_result
                        self._update_model_display()

                self.app.push_screen(CustomModelInputModal(), on_custom_dismiss)
            elif result == DEFAULT_SENTINEL:
                # "Follow-up default" selected: reset any prior coder model
                # back to the provider-specific coder role default.
                self._coder_model = None
                self._update_model_display()
            elif result is not None:
                # A known model was selected (result is the model id)
                self._coder_model = result
                self._update_model_display()
            # result is None means cancel (escape): leave the current selection
            # untouched. The picker uses distinct_default=True so the follow-up
            # default returns DEFAULT_SENTINEL, distinct from cancel.

        self.app.push_screen(ModelPickerModal(distinct_default=True), on_picker_dismiss)

    def _model_display_label(self) -> str:
        """Format the current follow-up model for display, with planner context."""
        return _model_display_label(
            self._coder_model,
            self._choice,
            planner_llm_provider=self._planner_llm_provider,
        )

    def _update_model_display(self) -> None:
        """Refresh the model display label."""
        model_display = self.query_one("#coder-model-display", Static)
        model_display.update(self._model_display_label())

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
