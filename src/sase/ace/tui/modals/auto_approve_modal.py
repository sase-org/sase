"""Auto-Approve quick-action menu for the agents tab.

This modal configures *future* plan auto-approval for an agent — it is the
single-key replacement for the old ``a``-key 3-state toggle. It must NOT be
confused with :class:`~sase.ace.tui.modals.approve_options_modal.ApproveOptionsModal`
/ :mod:`sase.ace.tui.modals.plan_approval_modal`, which let a human review an
*already submitted* plan. Different flow; similar styling on purpose.

Interaction model: a single key press (``p``/``t``/``e``/``d``) selects the
option, dismisses the modal, and applies the change immediately — no Enter
needed. The agent's current auto-approval state is marked with ``▸`` for
orientation (not a cursor). ``esc``/``q`` cancel with no change.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual import events
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

AutoApproveChoice = Literal["plan", "tale", "epic", "disable"]


@dataclass(frozen=True)
class _AutoApproveOption:
    """One selectable row in the Auto-Approve menu."""

    key: str
    choice: AutoApproveChoice
    label: str
    consequence: str


# Data-driven choice list. The mnemonics intentionally mirror the directive
# aliases (`p`->Plan, `t`->Tale, `e`->Epic) plus `d`->Disable.
_OPTIONS: tuple[_AutoApproveOption, ...] = (
    _AutoApproveOption("p", "plan", "Plan", "approve the plan as-is"),
    _AutoApproveOption("t", "tale", "Tale", "approve & commit as a tale"),
    _AutoApproveOption("e", "epic", "Epic", "approve & commit as an epic"),
    _AutoApproveOption("d", "disable", "Disable", "turn off auto-approval"),
)
_OPTION_BY_KEY: dict[str, _AutoApproveOption] = {opt.key: opt for opt in _OPTIONS}


class AutoApproveModal(ModalScreen[AutoApproveChoice | None]):
    """Single-key Auto-Approve menu pushed when ``a`` is pressed on an agent."""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("q", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        current: AutoApproveChoice,
        agent_name: str = "",
    ) -> None:
        super().__init__()
        self._current = current
        self._agent_name = agent_name

    def compose(self) -> ComposeResult:
        with Container(id="auto-approve-container"):
            yield Static(
                "[bold cyan]Auto-Approve[/bold cyan]",
                id="auto-approve-title",
            )
            for option in _OPTIONS:
                yield Static(
                    self._option_row_markup(option),
                    id=f"auto-approve-choice-{option.choice}",
                    classes="auto-approve-choice-row",
                )
            if self._agent_name:
                yield Static(
                    f"[dim]agent:[/dim] {self._agent_name}",
                    id="auto-approve-agent",
                )
            yield Static(
                "[green]p/t/e/d[/green]=Select  [dim]esc/q[/dim]=Cancel",
                id="auto-approve-footer",
            )

    def on_mount(self) -> None:
        # Highlight the row matching the agent's current state for orientation.
        for option in _OPTIONS:
            row = self.query_one(f"#auto-approve-choice-{option.choice}", Static)
            row.set_class(option.choice == self._current, "selected")

    def _option_row_markup(self, option: _AutoApproveOption) -> str:
        """Render one menu row, marking the agent's current state with ``▸``."""
        is_current = option.choice == self._current
        marker = "▸" if is_current else " "
        if is_current:
            return (
                f"[bold green]{marker} {option.key} {option.label:<8}[/] "
                f"[dim]{option.consequence}[/]"
            )
        return (
            f"[dim]{marker}[/] [green]{option.key}[/green] "
            f"{option.label:<8} [dim]{option.consequence}[/dim]"
        )

    def on_key(self, event: events.Key) -> None:
        """Single-key instant select; guard stray printable characters.

        ``esc``/``q`` cancel. A mapped option key (``p``/``t``/``e``/``d``)
        applies immediately and dismisses with its choice id. Every other
        printable character is stopped here (the established modal pattern) so
        it never leaks to the app's custom-mode prefix handling.
        """
        if event.key in ("escape", "q"):
            event.prevent_default()
            event.stop()
            self.action_cancel()
        elif event.key in _OPTION_BY_KEY:
            event.prevent_default()
            event.stop()
            self.dismiss(_OPTION_BY_KEY[event.key].choice)
        elif event.character and event.character.isprintable():
            event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)
