"""Mentor profile selection modal for the ace TUI.

Allows users to pick a mentor profile to run from the Mentor Review modal.
"""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.config.mentor import MentorProfileConfig

from .base import CopyModeForwardingMixin
from .mentor_review_modal import MentorInfo


class MentorProfileSelectModal(CopyModeForwardingMixin, ModalScreen[str | None]):
    """Modal for selecting a mentor profile to run."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("j", "next_profile", "Next"),
        ("k", "prev_profile", "Prev"),
        ("enter", "select_profile", "Select"),
    ]

    def __init__(
        self,
        profiles: list[MentorProfileConfig],
        existing_mentors: list[MentorInfo],
    ) -> None:
        super().__init__()
        self._profiles = profiles
        self._existing_mentors = existing_mentors
        self._selected_idx = 0

    def compose(self) -> ComposeResult:
        with Container(id="mentor-profile-select-container"):
            yield Static(id="mentor-profile-select-title")
            yield Static(id="mentor-profile-select-list")
            yield Static(id="mentor-profile-select-footer")

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        self._update_title()
        self._update_list()
        self._update_footer()

    def _update_title(self) -> None:
        text = Text()
        text.append(" Run Mentor Profile", style="bold white")
        try:
            self.query_one("#mentor-profile-select-title", Static).update(text)
        except Exception:
            pass

    def _update_list(self) -> None:
        text = Text()

        for i, profile in enumerate(self._profiles):
            is_selected = i == self._selected_idx

            # Derive status from existing mentors
            status_indicator, status_style = self._profile_status(profile)

            # Selection indicator
            if is_selected:
                text.append(" \u25b8 ", style="bold #00D7AF")
            elif status_indicator:
                text.append(f" {status_indicator} ", style=status_style)
            else:
                text.append("   ")

            # Profile name
            name_style = "bold white" if is_selected else ""
            text.append(profile.profile_name, style=name_style)

            # Mentor count
            text.append(f" ({len(profile.mentors)} mentors)", style="dim")
            text.append("\n")

        try:
            self.query_one("#mentor-profile-select-list", Static).update(text)
        except Exception:
            pass

    def _update_footer(self) -> None:
        text = Text()
        bindings = [
            ("j/k", "navigate"),
            ("\u23ce", "select"),
            ("q", "close"),
        ]
        for i, (key, label) in enumerate(bindings):
            if i > 0:
                text.append("  ")
            text.append(key, style="bold #00D7AF")
            text.append(f": {label}", style="dim")
        try:
            self.query_one("#mentor-profile-select-footer", Static).update(text)
        except Exception:
            pass

    def _profile_status(self, profile: MentorProfileConfig) -> tuple[str, str]:
        """Return (indicator, style) for a profile's status."""
        matching = [
            m for m in self._existing_mentors if m.profile_name == profile.profile_name
        ]
        if not matching:
            return ("", "")

        any_running = any(m.is_running for m in matching)
        if any_running:
            return ("\u25cf", "bold yellow")  # ●

        all_terminal = all(m.status in ("COMMENTED", "PASSED") for m in matching)
        if all_terminal:
            return ("\u2713", "bold green")  # ✓

        any_failed = any(m.status == "FAILED" for m in matching)
        if any_failed:
            return ("\u2717", "bold red")  # ✗

        return ("", "")

    # -- Navigation --

    def action_next_profile(self) -> None:
        if self._profiles:
            self._selected_idx = (self._selected_idx + 1) % len(self._profiles)
            self._refresh()

    def action_prev_profile(self) -> None:
        if self._profiles:
            self._selected_idx = (self._selected_idx - 1) % len(self._profiles)
            self._refresh()

    def action_select_profile(self) -> None:
        if self._profiles:
            self.dismiss(self._profiles[self._selected_idx].profile_name)

    def action_close(self) -> None:
        self.dismiss(None)
