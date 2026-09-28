"""Agent tribe modal for sase's TUI Agents tab."""

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

    action: Literal["keep", "set", "unset"]
    tribe: str | None  # canonical name when action == "set"; ignored on "keep"
    tab_action: Literal["keep", "set", "unset"] = "keep"
    tab: str | None = None  # canonical name when tab_action == "set"


class _TabInput(SingleLineVimTextArea):
    """Tab-name vim editor with tab completion."""

    BINDINGS = [
        ("tab", "complete", "Complete"),
    ]

    def action_complete(self) -> None:
        modal = self.screen
        assert isinstance(modal, AgentTribeModal)
        modal._complete_tab()


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
        Binding("ctrl+t", "unset_tab", "Clear tab", priority=True),
    ]

    def __init__(
        self,
        *,
        target_label: str,
        current_tribe: str | None,
        known_tribes: tuple[str, ...],
        default_tribe: str | None = None,
        tab_enabled: bool = False,
        current_tab: str | None = None,
        known_tabs: tuple[str, ...] = (),
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
            tab_enabled: Show the second tab input (Tribe & Tab mode).
            current_tab: Tab currently on the focused agent (or ``None``
                for the default tab / bulk operations).
            known_tabs: Distinct named tabs on the roster — used for tab
                completion suggestions.
        """
        super().__init__()
        self._target_label = target_label
        self._current_tribe = current_tribe
        self._known_tribes = tuple(sorted(set(known_tribes)))
        self._default_tribe = default_tribe
        self._tab_enabled = tab_enabled
        self._current_tab = current_tab
        self._known_tabs = tuple(sorted(set(known_tabs)))

    def compose(self) -> ComposeResult:
        with Container():
            title = "Tribe & Tab" if self._tab_enabled else "Tribe"
            yield Label(f"{title}: {self._target_label}", id="modal-title")
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
            if self._tab_enabled:
                current_tab_text = Text("Tab: ")
                if self._current_tab:
                    current_tab_text.append(self._current_tab, style="bold")
                else:
                    current_tab_text.append("(main)")
                yield Label(current_tab_text, id="agent-tab-current")
                yield Label(
                    "Empty keeps the tab · [bold]main[/] or [bold]Ctrl+T[/] clears · "
                    "[bold]Tab[/] completes.",
                    id="agent-tab-hint",
                )
                yield _TabInput(
                    value="",
                    placeholder="tab-name",
                    id="agent-tab-input",
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

    def _complete_tab(self) -> None:
        """Tab-complete the tab input against ``known_tabs``."""
        tab_input = self.query_one("#agent-tab-input", _TabInput)
        prefix = tab_input.value
        matches = [t for t in self._known_tabs if t.startswith(prefix)]
        if not matches:
            return
        common = matches[0]
        for m in matches[1:]:
            i = 0
            while i < len(common) and i < len(m) and common[i] == m[i]:
                i += 1
            common = common[:i]
        if common and common != prefix:
            tab_input.value = common
            tab_input.cursor_position = len(common)
            return
        try:
            idx = matches.index(prefix)
            next_match = matches[(idx + 1) % len(matches)]
        except ValueError:
            next_match = matches[0]
        tab_input.value = next_match
        tab_input.cursor_position = len(next_match)

    def _read_tab_result(self) -> tuple[Literal["keep", "set", "unset"], str | None]:
        """Read the tab input as a ``(tab_action, tab)`` pair.

        An empty input keeps the tab; ``main`` (or Ctrl+T) clears it back
        to the default tab; anything else is canonicalized like ``%tab``.
        Raises ``ValueError`` with the user-facing message on invalid input.
        """
        if not self._tab_enabled:
            return ("keep", None)
        tab_input = self.query_one("#agent-tab-input", _TabInput)
        raw = tab_input.value.strip()
        if not raw:
            return ("keep", None)
        from sase.core.agent_tab import canonicalize_agent_tab

        try:
            stored = canonicalize_agent_tab(raw)
        except (ValueError, TypeError) as exc:
            raise ValueError(str(exc)) from None
        if stored is None:
            return ("unset", None)
        return ("set", stored)

    def on_single_line_vim_text_area_submitted(
        self, _event: SingleLineVimTextArea.Submitted
    ) -> None:
        """Enter on either input submits the modal."""
        self._submit_set()

    def action_unset_tribe(self) -> None:
        """Ctrl+D clears the agent's tribe."""
        try:
            tab_action, tab = self._read_tab_result()
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        self.dismiss(
            AgentTribeModalResult(
                action="unset", tribe=None, tab_action=tab_action, tab=tab
            )
        )

    def action_unset_tab(self) -> None:
        """Ctrl+T clears the agent's tab back to the default tab."""
        try:
            tribe_action, tribe = self._read_tribe_result()
        except InvalidTribeError as exc:
            self.notify(str(exc), severity="error")
            return
        self.dismiss(
            AgentTribeModalResult(
                action=tribe_action, tribe=tribe, tab_action="unset", tab=None
            )
        )

    def _read_tribe_result(
        self,
    ) -> tuple[Literal["keep", "set", "unset"], str | None]:
        """Read the tribe input, raising ``InvalidTribeError`` when invalid.

        In Tribe & Tab mode an empty input keeps the tribe (explicit
        Ctrl+D still clears it); tribe-only mode keeps the legacy
        empty-means-unset behavior.
        """
        tribe_input = self.query_one("#agent-tribe-input", _TribeInput)
        raw = tribe_input.value.strip()
        if not raw:
            return ("keep", None) if self._tab_enabled else ("unset", None)
        return ("set", validate_tribe_name(raw))

    def _submit_set(self) -> None:
        try:
            tribe_action, tribe = self._read_tribe_result()
        except InvalidTribeError as exc:
            self.notify(str(exc), severity="error")
            return
        try:
            tab_action, tab = self._read_tab_result()
        except ValueError as exc:
            self.notify(str(exc), severity="error")
            return
        if tribe_action == "keep" and tab_action == "keep":
            # Nothing typed: cancel instead of writing a no-op change.
            self.dismiss(None)
            return
        self.dismiss(
            AgentTribeModalResult(
                action=tribe_action, tribe=tribe, tab_action=tab_action, tab=tab
            )
        )

    def action_cancel(self) -> None:
        self.dismiss(None)
