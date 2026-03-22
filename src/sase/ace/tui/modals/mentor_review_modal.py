"""Mentor Review modal for the ace TUI.

Displays mentor comments from the latest commit with navigation,
acceptance toggling, and running mentor killing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.changespec.models import MentorEntry
from sase.ace.mentor_output import (
    MentorAcceptanceState,
    MentorOutput,
    load_acceptance_state,
    load_mentor_outputs_for_commit,
    save_acceptance_state,
)

from .base import CopyModeForwardingMixin

log = logging.getLogger(__name__)


@dataclass
class _MentorInfo:
    """Aggregated info for a single mentor in the side panel."""

    mentor_name: str
    profile_name: str
    status: str  # COMMENTED, PASSED, FAILED, RUNNING, KILLED, DEAD
    comments: list[dict[str, str | int]]  # list of comment dicts
    is_running: bool = False


@dataclass
class _MentorReviewData:
    """Data passed to the MentorReviewModal."""

    mentors: list[_MentorInfo]
    acceptance: MentorAcceptanceState
    cl_name: str
    entry_id: str
    total_comments: int = 0

    def __post_init__(self) -> None:
        self.total_comments = sum(len(m.comments) for m in self.mentors)


@dataclass
class MentorApplyResult:
    """Result returned when user presses <enter> to apply accepted comments."""

    accepted_comments: list[dict[str, str | int]]
    cl_name: str


@dataclass
class MentorKillResult:
    """Result returned when user presses K to kill a running mentor."""

    entry_id: str
    mentor_name: str
    profile_name: str
    cl_name: str


def build_mentor_review_data(
    mentor_entry: MentorEntry,
    cl_name: str,
) -> _MentorReviewData | None:
    """Build _MentorReviewData from a MentorEntry.

    Returns None if there are no mentors with comments or actionable status.
    """
    entry_id = mentor_entry.entry_id

    # Load mentor outputs from disk, matching by status line timestamps
    timestamps = (
        {sl.timestamp for sl in mentor_entry.status_lines}
        if mentor_entry.status_lines
        else set()
    )
    outputs = load_mentor_outputs_for_commit(cl_name, timestamps)
    # Map timestamp → MentorOutput (filenames use config-level names, but the
    # JSON content may have LLM-provided names that don't match status lines).
    ts_output_map: dict[str, MentorOutput] = {}
    for path, mo in outputs:
        for ts in timestamps:
            if path.stem.endswith(f"-{ts}"):
                ts_output_map[ts] = mo
                break

    # Build mentor info list from status lines
    mentors: list[_MentorInfo] = []
    seen: set[tuple[str, str]] = set()

    if mentor_entry.status_lines:
        for sl in mentor_entry.status_lines:
            key = (sl.profile_name, sl.mentor_name)
            if key in seen:
                continue
            seen.add(key)

            comments: list[dict[str, str | int]] = []
            output: MentorOutput | None = ts_output_map.get(sl.timestamp)
            if output is not None:
                for c in output.comments:
                    comments.append(
                        {
                            "focus_name": c.focus_name,
                            "file_path": c.file_path,
                            "line_number": c.line_number,
                            "description": c.description,
                            "severity": c.severity,
                        }
                    )

            mentors.append(
                _MentorInfo(
                    mentor_name=sl.mentor_name,
                    profile_name=sl.profile_name,
                    status=sl.status,
                    comments=comments,
                    is_running=sl.suffix_type == "running_agent",
                )
            )

    if not mentors:
        return None

    acceptance = load_acceptance_state(cl_name, entry_id)
    return _MentorReviewData(
        mentors=mentors,
        acceptance=acceptance,
        cl_name=cl_name,
        entry_id=entry_id,
    )


class MentorReviewModal(
    CopyModeForwardingMixin, ModalScreen[MentorApplyResult | MentorKillResult | None]
):
    """Modal for reviewing mentor comments with navigation and acceptance."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("j", "next_mentor", "Next mentor"),
        ("k", "prev_mentor", "Prev mentor"),
        ("n", "next_comment", "Next comment"),
        ("p", "prev_comment", "Prev comment"),
        ("space", "toggle_accept", "Toggle accept"),
        ("enter", "apply", "Apply accepted"),
        ("shift+k", "kill_mentor", "Kill mentor"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
    ]

    def __init__(self, data: _MentorReviewData) -> None:
        super().__init__()
        self._data = data
        self._mentor_idx = 0
        self._comment_idx = 0
        # Start on first mentor that has comments
        for i, m in enumerate(data.mentors):
            if m.comments:
                self._mentor_idx = i
                break

    def compose(self) -> ComposeResult:
        with Container(id="mentor-review-container"):
            yield Static(self._build_title(), id="mentor-review-title")
            with Horizontal(id="mentor-review-panels"):
                yield Static(id="mentor-side-panel")
                yield Static(id="mentor-main-panel")
            yield Static(id="mentor-review-footer")

    def on_mount(self) -> None:
        self._refresh_all()

    def _refresh_all(self) -> None:
        self._update_side_panel()
        self._update_main_panel()
        self._update_footer()

    def _build_title(self) -> Text:
        text = Text()
        text.append(" Mentor Review", style="bold white")
        return text

    def _current_mentor(self) -> _MentorInfo | None:
        if not self._data.mentors:
            return None
        return self._data.mentors[self._mentor_idx]

    def _update_side_panel(self) -> None:
        text = Text()
        text.append(" Mentors\n", style="bold #87D7FF")
        text.append(" " + "\u2500" * 18 + "\n", style="dim #87D7FF")

        for i, m in enumerate(self._data.mentors):
            is_selected = i == self._mentor_idx

            # Status indicator
            if is_selected:
                indicator = "\u25b8"  # ▸
                style = "bold #00D7AF"
            elif m.is_running:
                indicator = "\u25cf"  # ●
                style = "bold yellow"
            elif m.status == "FAILED":
                indicator = "\u2717"  # ✗
                style = "bold red"
            elif m.status == "KILLED" or m.status == "DEAD":
                indicator = "\u2717"  # ✗
                style = "dim red"
            elif self._all_comments_accepted(m):
                indicator = "\u2713"  # ✓
                style = "bold green"
            else:
                indicator = " "
                style = ""

            name_style = "bold white" if is_selected else ""
            text.append(f" {indicator} ", style=style)
            text.append(f"{m.mentor_name}", style=name_style)

            # Comment count
            if m.comments:
                accepted = self._accepted_count_for_mentor(m)
                text.append(f" ({accepted}/{len(m.comments)})", style="dim")
            elif m.is_running:
                text.append(" (running)", style="dim yellow")
            elif m.status == "PASSED":
                text.append(" (passed)", style="dim green")
            elif m.status == "FAILED":
                text.append(" (failed)", style="dim red")
            elif m.status in ("KILLED", "DEAD"):
                text.append(f" ({m.status.lower()})", style="dim red")
            text.append("\n")

        try:
            panel = self.query_one("#mentor-side-panel", Static)
            panel.update(text)
        except Exception:
            pass

    def _update_main_panel(self) -> None:
        mentor = self._current_mentor()
        text = Text()

        if mentor is None or not mentor.comments:
            if mentor and mentor.is_running:
                text.append("\n  Mentor is still running...\n", style="dim yellow")
            elif mentor and mentor.status == "PASSED":
                text.append("\n  No issues found.\n", style="dim green")
            elif mentor and mentor.status == "FAILED":
                text.append("\n  Mentor failed.\n", style="dim red")
            elif mentor and mentor.status in ("KILLED", "DEAD"):
                text.append(f"\n  Mentor {mentor.status.lower()}.\n", style="dim red")
            else:
                text.append("\n  No comments.\n", style="dim")
            try:
                panel = self.query_one("#mentor-main-panel", Static)
                panel.update(text)
            except Exception:
                pass
            return

        # Clamp comment index
        self._comment_idx = max(0, min(self._comment_idx, len(mentor.comments) - 1))
        comment = mentor.comments[self._comment_idx]
        total = len(mentor.comments)

        # Header
        text.append(f" Comment {self._comment_idx + 1}/{total}", style="bold white")
        text.append("\n")
        text.append(" " + "\u2500" * 40 + "\n", style="dim #87D7FF")

        # Focus and severity
        text.append("  Focus: ", style="dim")
        text.append(str(comment["focus_name"]), style="bold #87D7FF")
        text.append("    Severity: ", style="dim")
        severity = str(comment["severity"])
        sev_style = {
            "error": "bold red",
            "warning": "bold yellow",
            "suggestion": "bold #87D7FF",
        }.get(severity, "")
        text.append(severity, style=sev_style)
        text.append("\n\n")

        # File path
        text.append("  File: ", style="dim")
        text.append(
            f"{comment['file_path']}:{comment['line_number']}", style="bold #00D7AF"
        )
        text.append("\n\n")

        # Description
        desc = str(comment["description"])
        for line in desc.split("\n"):
            text.append(f"  {line}\n")
        text.append("\n")

        # Acceptance state
        is_accepted = self._data.acceptance.is_accepted(
            mentor.profile_name, mentor.mentor_name, self._comment_idx
        )
        if is_accepted:
            text.append("  [\u2713 ACCEPTED]", style="bold green")
        else:
            text.append("  [ ]", style="dim")
        text.append("\n")

        try:
            panel = self.query_one("#mentor-main-panel", Static)
            panel.update(text)
        except Exception:
            pass

    def _update_footer(self) -> None:
        accepted = self._data.acceptance.accepted_count
        total = self._data.total_comments

        text = Text()
        text.append(f" Accepted: {accepted}/{total}", style="bold")
        text.append("  \u2502  ", style="dim")

        bindings = [
            ("n/p", "comments"),
            ("j/k", "mentors"),
            ("\u2423", "toggle"),
            ("<enter>", "apply"),
            ("K", "kill"),
            ("q", "close"),
        ]
        for i, (key, label) in enumerate(bindings):
            if i > 0:
                text.append("  ")
            text.append(key, style="bold #00D7AF")
            text.append(f": {label}", style="dim")

        try:
            footer = self.query_one("#mentor-review-footer", Static)
            footer.update(text)
        except Exception:
            pass

    # -- Navigation actions --

    def action_next_mentor(self) -> None:
        if not self._data.mentors:
            return
        self._mentor_idx = (self._mentor_idx + 1) % len(self._data.mentors)
        self._comment_idx = 0
        self._refresh_all()

    def action_prev_mentor(self) -> None:
        if not self._data.mentors:
            return
        self._mentor_idx = (self._mentor_idx - 1) % len(self._data.mentors)
        self._comment_idx = 0
        self._refresh_all()

    def action_next_comment(self) -> None:
        mentor = self._current_mentor()
        if not mentor or not mentor.comments:
            return
        if self._comment_idx < len(mentor.comments) - 1:
            self._comment_idx += 1
        else:
            # Jump to next mentor with comments
            for offset in range(1, len(self._data.mentors)):
                next_idx = (self._mentor_idx + offset) % len(self._data.mentors)
                if self._data.mentors[next_idx].comments:
                    self._mentor_idx = next_idx
                    self._comment_idx = 0
                    break
        self._refresh_all()

    def action_prev_comment(self) -> None:
        mentor = self._current_mentor()
        if not mentor or not mentor.comments:
            return
        if self._comment_idx > 0:
            self._comment_idx -= 1
        else:
            # Jump to previous mentor with comments (last comment)
            for offset in range(1, len(self._data.mentors)):
                prev_idx = (self._mentor_idx - offset) % len(self._data.mentors)
                if self._data.mentors[prev_idx].comments:
                    self._mentor_idx = prev_idx
                    self._comment_idx = len(self._data.mentors[prev_idx].comments) - 1
                    break
        self._refresh_all()

    # -- Acceptance --

    def action_toggle_accept(self) -> None:
        mentor = self._current_mentor()
        if not mentor or not mentor.comments:
            return
        self._data.acceptance.toggle(
            mentor.profile_name, mentor.mentor_name, self._comment_idx
        )
        save_acceptance_state(
            self._data.cl_name, self._data.entry_id, self._data.acceptance
        )
        self._refresh_all()

    # -- Apply --

    def action_apply(self) -> None:
        """Collect accepted comments and dismiss with apply result."""
        accepted: list[dict[str, str | int]] = []
        for m in self._data.mentors:
            for i, comment in enumerate(m.comments):
                if self._data.acceptance.is_accepted(m.profile_name, m.mentor_name, i):
                    accepted.append(comment)

        if not accepted:
            self.app.notify("No comments accepted", severity="warning")
            return

        self.dismiss(
            MentorApplyResult(
                accepted_comments=accepted,
                cl_name=self._data.cl_name,
            )
        )

    # -- Kill --

    def action_kill_mentor(self) -> None:
        mentor = self._current_mentor()
        if not mentor or not mentor.is_running:
            self.app.notify("Mentor is not running", severity="warning")
            return
        self.dismiss(
            MentorKillResult(
                entry_id=self._data.entry_id,
                mentor_name=mentor.mentor_name,
                profile_name=mentor.profile_name,
                cl_name=self._data.cl_name,
            )
        )

    # -- Scroll --

    def action_scroll_down(self) -> None:
        try:
            panel = self.query_one("#mentor-main-panel", Static)
            panel.scroll_relative(y=5, animate=False)
        except Exception:
            pass

    def action_scroll_up(self) -> None:
        try:
            panel = self.query_one("#mentor-main-panel", Static)
            panel.scroll_relative(y=-5, animate=False)
        except Exception:
            pass

    # -- Close --

    def action_close(self) -> None:
        self.dismiss(None)

    # -- Helpers --

    def _all_comments_accepted(self, mentor: _MentorInfo) -> bool:
        if not mentor.comments:
            return False
        return all(
            self._data.acceptance.is_accepted(
                mentor.profile_name, mentor.mentor_name, i
            )
            for i in range(len(mentor.comments))
        )

    def _accepted_count_for_mentor(self, mentor: _MentorInfo) -> int:
        return sum(
            1
            for i in range(len(mentor.comments))
            if self._data.acceptance.is_accepted(
                mentor.profile_name, mentor.mentor_name, i
            )
        )
