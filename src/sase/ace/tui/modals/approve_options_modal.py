"""Approve-with-options modal for plan approval."""

from dataclasses import dataclass

from textual import events
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Select, Static, Switch

from sase.llm_provider.registry import get_known_provider_model_choices

_SAME_AS_PLANNER = "__same_as_planner__"
_CUSTOM_MODEL = "__custom_model__"


@dataclass
class ApproveOptionsResult:
    """Result from the approve-with-options modal."""

    commit_plan: bool
    run_coder: bool
    coder_prompt: str | None
    coder_model: str | None


@dataclass
class ApproveOptionsEditPrompt:
    """Sentinel result: user wants to edit the coder prompt via PromptInputBar."""

    commit_plan: bool
    run_coder: bool
    coder_prompt: str
    coder_model: str | None


@dataclass
class ApproveOptionsEditModel:
    """Sentinel result: user wants to edit coder model via PromptInputBar."""

    commit_plan: bool
    run_coder: bool
    coder_prompt: str
    coder_model: str | None


class ApproveOptionsModal(
    ModalScreen[
        ApproveOptionsResult | ApproveOptionsEditPrompt | ApproveOptionsEditModel | None
    ],
):
    """Modal for configuring plan approval options."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("enter", "approve", "Approve"),
        ("p", "edit_prompt", "Edit prompt"),
        ("q", "cancel", "Quit"),
    ]

    def __init__(
        self,
        commit_plan: bool = True,
        run_coder: bool = True,
        coder_prompt: str = "",
        planner_model_label: str | None = None,
        coder_model: str | None = None,
    ) -> None:
        super().__init__()
        self._init_commit_plan = commit_plan
        self._init_run_coder = run_coder
        self._coder_prompt = coder_prompt
        self._planner_model_label = planner_model_label
        self._coder_model = coder_model
        self._model_options = self._build_model_options()
        self._selected_coder_model = coder_model

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

            with Horizontal(classes="approve-options-row"):
                yield Static(
                    "Coder model",
                    id="coder-model-label",
                    classes="approve-options-label",
                )
                yield Select(
                    self._model_options,
                    value=self._selected_value(),
                    allow_blank=False,
                    id="coder-model-select",
                )

            yield Static("Additional prompt:", classes="approve-options-prompt-label")
            display = self._coder_prompt or "none"
            if len(display) > 60:
                display = display[:57] + "..."
            yield Static(display, id="coder-prompt-display")

            yield Static(
                "[green]enter[/green]=Approve  "
                "[blue]space[/blue]=Toggle  "
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
        model_lbl = self.query_one("#coder-model-label", Static)
        model_select = self.query_one("#coder-model-select", Select)
        prompt_display = self.query_one("#coder-prompt-display", Static)
        prompt_label = self.query_one(".approve-options-prompt-label", Static)

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

        # Prompt display and p key enabled only when coder is ON
        if coder_sw.value:
            model_lbl.remove_class("disabled")
            model_select.disabled = False
            prompt_label.remove_class("disabled")
            prompt_display.remove_class("disabled")
        else:
            model_lbl.add_class("disabled")
            model_select.disabled = True
            prompt_label.add_class("disabled")
            prompt_display.add_class("disabled")

    def _same_as_planner_label(self) -> str:
        if self._planner_model_label:
            return f"Same as planner ({self._planner_model_label})"
        return "Same as planner"

    def _build_model_options(self) -> list[tuple[str, str]]:
        options: list[tuple[str, str]] = [
            (
                self._same_as_planner_label(),
                _SAME_AS_PLANNER,
            )
        ]
        known = get_known_provider_model_choices()
        options.extend((value, value) for value in known)
        if self._coder_model and self._coder_model not in known:
            options.append((f"Custom: {self._coder_model}", self._coder_model))
        options.append(("Custom...", _CUSTOM_MODEL))
        return options

    def _selected_value(self) -> str:
        if self._coder_model is None:
            return _SAME_AS_PLANNER
        return self._coder_model

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id != "coder-model-select":
            return
        if not self.query_one("#run-coder-switch", Switch).value:
            return
        if event.value == _CUSTOM_MODEL:
            self.dismiss(
                ApproveOptionsEditModel(
                    commit_plan=self.query_one("#commit-plan-switch", Switch).value,
                    run_coder=True,
                    coder_prompt=self._coder_prompt,
                    coder_model=self._selected_coder_model,
                )
            )
            return
        if event.value == _SAME_AS_PLANNER:
            self._selected_coder_model = None
            return
        self._selected_coder_model = str(event.value)

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
                coder_model=self._selected_coder_model,
            )
        )

    def action_approve(self) -> None:
        commit_plan = self.query_one("#commit-plan-switch", Switch).value
        run_coder = self.query_one("#run-coder-switch", Switch).value
        coder_prompt = self._coder_prompt if self._coder_prompt else None
        coder_model = self._selected_coder_model if run_coder else None
        self.dismiss(
            ApproveOptionsResult(
                commit_plan=commit_plan,
                run_coder=run_coder,
                coder_prompt=coder_prompt,
                coder_model=coder_model,
            )
        )
