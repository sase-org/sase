"""Agent tag modal for the ace TUI Agents tab."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Label

from sase.ace.agent_tags import InvalidTagError, validate_tag_name


@dataclass(frozen=True)
class AgentTagModalResult:
    """Outcome of the modal: set the tag to a value or unset it."""

    action: Literal["set", "unset"]
    tag: str | None  # None when action == "unset"


class _TagInput(Input):
    """Tag-name input with readline-style key bindings and tab completion."""

    BINDINGS = [
        ("ctrl+f", "cursor_right", "Forward"),
        ("ctrl+b", "cursor_left", "Backward"),
        ("ctrl+a", "home", "Home"),
        ("ctrl+e", "end", "End"),
        ("tab", "complete", "Complete"),
    ]

    def action_complete(self) -> None:
        modal = self.screen
        assert isinstance(modal, AgentTagModal)
        modal._complete_tag()


class AgentTagModal(ModalScreen[AgentTagModalResult | None]):
    """Modal that lets the user set or unset the tag on one or more agents.

    Enter on the input sets the typed tag; Ctrl+d clears it.  Tab
    completes against ``known_tags``.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+d", "unset_tag", "Clear tag", priority=True),
    ]

    def __init__(
        self,
        *,
        target_label: str,
        current_tag: str | None,
        known_tags: tuple[str, ...],
        default_tag: str | None = None,
    ) -> None:
        """Initialize the modal.

        Args:
            target_label: Description of the affected agent(s) — e.g. the
                agent's display name or ``"3 marked agents"``.
            current_tag: Tag currently on the focused agent (or ``None``
                for bulk operations / untagged agents).
            known_tags: Distinct tag names already present in the store —
                used for tab completion suggestions.
            default_tag: Seed value for the input box when the agent has
                no current tag. Does not affect the ``Current:`` label.
        """
        super().__init__()
        self._target_label = target_label
        self._current_tag = current_tag
        self._known_tags = tuple(sorted(set(known_tags)))
        self._default_tag = default_tag

    def compose(self) -> ComposeResult:
        with Container():
            yield Label(f"Tag: {self._target_label}", id="modal-title")
            current_text = f"@{self._current_tag}" if self._current_tag else "(none)"
            yield Label(f"Current: {current_text}", id="agent-tag-current")
            yield Label(
                "[bold]Enter[/] set · [bold]Ctrl+D[/] clear · [bold]Tab[/] complete\n"
                "Type a tag name without the '@' prefix.",
                id="agent-tag-hint",
            )
            initial = self._current_tag or self._default_tag or ""
            yield _TagInput(
                value=initial,
                placeholder="tag-name",
                id="agent-tag-input",
            )

    def on_mount(self) -> None:
        tag_input = self.query_one("#agent-tag-input", _TagInput)
        tag_input.focus()
        if tag_input.value:
            tag_input.select_all()

    def _complete_tag(self) -> None:
        """Tab-complete the input against ``known_tags``."""
        tag_input = self.query_one("#agent-tag-input", _TagInput)
        prefix = tag_input.value
        matches = [t for t in self._known_tags if t.startswith(prefix)]
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
            tag_input.value = common
            tag_input.cursor_position = len(common)
            return
        # Already at the longest common prefix; cycle to the next match.
        try:
            idx = matches.index(prefix)
            next_match = matches[(idx + 1) % len(matches)]
        except ValueError:
            next_match = matches[0]
        tag_input.value = next_match
        tag_input.cursor_position = len(next_match)

    def on_input_submitted(self, _event: Input.Submitted) -> None:
        """Enter on the input sets the typed tag."""
        self._submit_set()

    def action_unset_tag(self) -> None:
        """Ctrl+D clears the agent's tag."""
        self.dismiss(AgentTagModalResult(action="unset", tag=None))

    def _submit_set(self) -> None:
        tag_input = self.query_one("#agent-tag-input", _TagInput)
        raw = tag_input.value.strip()
        if not raw:
            self.notify("Tag name cannot be empty", severity="error")
            return
        try:
            tag = validate_tag_name(raw)
        except InvalidTagError as exc:
            self.notify(str(exc), severity="error")
            return
        self.dismiss(AgentTagModalResult(action="set", tag=tag))

    def action_cancel(self) -> None:
        self.dismiss(None)
