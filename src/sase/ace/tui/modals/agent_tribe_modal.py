"""Agent tribe modal for the ace TUI Agents tab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Label

from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.agent_tribes import InvalidTribeError, validate_tribe_name
from sase.ace.tui.models.tribe_display import tribe_identity_style


@dataclass(frozen=True)
class AgentTribeModalResult:
    """Outcome of the modal: set the tribe to a value or unset it."""

    action: Literal["set", "unset"]
    tribe: str | None  # None when action == "unset"


class _TribeInput(SingleLineVimTextArea):
    """Tribe-name vim editor with tab completion."""

    BINDINGS = [
        ("tab", "complete", "Complete"),
    ]

    def action_complete(self) -> None:
        modal = self.screen
        assert isinstance(modal, AgentTribeModal)
        modal._complete_tribe()


class AgentTribeModal(ModalScreen[AgentTribeModalResult | None]):
    """Modal that lets the user set or clear the tribe on one or more agents.

    Enter on the input sets the typed tribe, or clears it when the input is
    empty (or whitespace-only); Ctrl+d also clears.  Tab completes against
    ``known_tribes``.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+d", "unset_tribe", "Clear tribe", priority=True),
    ]

    def __init__(
        self,
        *,
        target_label: str,
        current_tribe: str | None,
        known_tribes: tuple[str, ...],
        default_tribe: str | None = None,
    ) -> None:
        """Initialize the modal.

        Args:
            target_label: Description of the affected agent(s) — e.g. the
                agent's display name or ``"3 marked agents"``.
            current_tribe: Tribe currently on the focused agent (or ``None``
                for bulk operations / agents without a tribe).
            known_tribes: Distinct tribe names already present in the store —
                used for tab completion suggestions.
            default_tribe: Seed value for the input box when the agent has
                no current tribe. Does not affect the ``Current:`` label.
        """
        super().__init__()
        self._target_label = target_label
        self._current_tribe = current_tribe
        self._known_tribes = tuple(sorted(set(known_tribes)))
        self._default_tribe = default_tribe

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(f"Tribe: {self._target_label}", id="modal-title")
            current_text = Text("Current: ")
            if self._current_tribe:
                current_text.append(
                    f"@{self._current_tribe}",
                    style=tribe_identity_style(
                        self._current_tribe,
                        bold=True,
                    ),
                )
            else:
                current_text.append("(none)")
            yield Label(current_text, id="agent-tribe-current")
            yield Label(
                "[bold]Enter[/] set (or clear if empty) · [bold]Ctrl+D[/] clear · [bold]Tab[/] complete\n"
                "Type a tribe name without the '@' prefix.",
                id="agent-tribe-hint",
            )
            initial = (
                "" if self._current_tribe is not None else self._default_tribe or ""
            )
            yield _TribeInput(
                value=initial,
                placeholder="tribe-name",
                id="agent-tribe-input",
            )

    def on_mount(self) -> None:
        tribe_input = self.query_one("#agent-tribe-input", _TribeInput)
        tribe_input.focus()
        if tribe_input.value:
            tribe_input.select_all()
        tribe_input._update_vim_mode_display()

    def _complete_tribe(self) -> None:
        """Tab-complete the input against ``known_tribes``."""
        tribe_input = self.query_one("#agent-tribe-input", _TribeInput)
        prefix = tribe_input.value
        matches = [t for t in self._known_tribes if t.startswith(prefix)]
        if not matches:
            return
        # Compute longest common prefix among matches.
        common = matches[0]
        for m in matches[1:]:
            i = 0
            while i < len(common) and i < len(m) and common[i] == m[i]:
                i += 1
            common = common[:i]
        if common and common != prefix:
            tribe_input.value = common
            tribe_input.cursor_position = len(common)
            return
        # Already at the longest common prefix; cycle to the next match.
        try:
            idx = matches.index(prefix)
            next_match = matches[(idx + 1) % len(matches)]
        except ValueError:
            next_match = matches[0]
        tribe_input.value = next_match
        tribe_input.cursor_position = len(next_match)

    def on_single_line_vim_text_area_submitted(
        self, _event: SingleLineVimTextArea.Submitted
    ) -> None:
        """Enter on the input sets the typed tribe."""
        self._submit_set()

    def action_unset_tribe(self) -> None:
        """Ctrl+D clears the agent's tribe."""
        self.dismiss(AgentTribeModalResult(action="unset", tribe=None))

    def _submit_set(self) -> None:
        tribe_input = self.query_one("#agent-tribe-input", _TribeInput)
        raw = tribe_input.value.strip()
        if not raw:
            self.dismiss(AgentTribeModalResult(action="unset", tribe=None))
            return
        try:
            tribe = validate_tribe_name(raw)
        except InvalidTribeError as exc:
            self.notify(str(exc), severity="error")
            return
        self.dismiss(AgentTribeModalResult(action="set", tribe=tribe))

    def action_cancel(self) -> None:
        self.dismiss(None)
