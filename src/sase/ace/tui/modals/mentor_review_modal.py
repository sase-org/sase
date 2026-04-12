"""Mentor Review modal for the ace TUI.

Displays mentor comments from the latest commit with navigation,
acceptance toggling, and running mentor killing.
"""

from __future__ import annotations

import logging

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import ModalScreen
from textual.widgets import Static

from sase.ace.mentor_output import (
    save_acceptance_state,
    save_read_state,
)

from .base import CopyModeForwardingMixin
from .mentor_review_models import (
    MentorApplyResult,
    MentorInfo,
    MentorKillResult,
    MentorReviewData,
    MentorRunResult,
    lexer_for_path,
)

log = logging.getLogger(__name__)


class MentorReviewModal(
    CopyModeForwardingMixin,
    ModalScreen[MentorApplyResult | MentorKillResult | MentorRunResult | None],
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
        ("a", "apply_propose", "Apply + propose"),
        ("A", "apply_commit", "Apply + commit"),
        ("r", "run_profile", "Run mentor profile"),
        ("K", "kill_mentor", "Kill mentor"),
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
    ]

    def __init__(self, data: MentorReviewData) -> None:
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
        self._mark_current_read()
        self._update_title()
        self._update_side_panel()
        self._update_main_panel()
        self._update_footer()

    def _build_title(self) -> Text:
        """Static placeholder for compose(); replaced by _update_title()."""
        text = Text()
        text.append(" Mentor Review", style="bold white")
        return text

    def _update_title(self) -> None:
        """Build a rich status header with global position and acceptance."""
        current, total = self._global_comment_index()
        accepted = self._data.acceptance.accepted_count

        text = Text()
        if total == 0:
            # No comments — simple centered title
            text.append(" ── ", style="dim #87D7FF")
            text.append("Mentor Review", style="bold white")
            text.append(" ──", style="dim #87D7FF")
        else:
            text.append(" ── ", style="dim #87D7FF")
            text.append("Mentor Review", style="bold white")
            text.append(" ────── ", style="dim #87D7FF")
            text.append(f"{current} / {total}", style="bold white")
            text.append(" ────── ", style="dim #87D7FF")
            if accepted > 0:
                text.append(f"✓ {accepted} accepted", style="bold #00D7AF")
            else:
                text.append(f"✓ {accepted} accepted", style="dim")
            text.append(" ──", style="dim #87D7FF")

        try:
            title = self.query_one("#mentor-review-title", Static)
            title.update(text)
        except Exception:
            pass

    def _current_mentor(self) -> MentorInfo | None:
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

            # Comment count + read progress bar
            if m.comments:
                total = len(m.comments)
                accepted = self._accepted_count_for_mentor(m)
                read = self._read_count_for_mentor(m)
                text.append(f" ({accepted}/{total})", style="dim")

                # Mini progress bar: ■ = read, □ = unread
                bar_width = min(total, 5)
                filled = round(read / total * bar_width)
                filled = max(0, min(bar_width, filled))
                text.append(" ")
                if read == total:
                    text.append("■" * bar_width, style="#00D7AF")
                else:
                    text.append("■" * filled, style="#87D7FF")
                    text.append("□" * (bar_width - filled), style="dim #4A4A6A")
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

        # Header: Comment X/Y · mentor_name                [✓ ACCEPTED]
        is_accepted = self._data.acceptance.is_accepted(
            mentor.profile_name, mentor.mentor_name, self._comment_idx
        )
        header_left = f" Comment {self._comment_idx + 1}/{total}"
        header_right = "[✓ ACCEPTED]" if is_accepted else "[ ]"

        text.append(header_left, style="bold white")
        text.append(f" · {mentor.mentor_name}", style="dim")

        # Right-align acceptance indicator: pad to fill ~56 chars total
        used = len(header_left) + len(f" · {mentor.mentor_name}")
        pad = max(2, 56 - used - len(header_right))
        text.append(" " * pad)
        if is_accepted:
            text.append(header_right, style="bold green")
        else:
            text.append(header_right, style="dim")

        text.append("\n")
        text.append(" " + "\u2500" * 56 + "\n", style="dim #87D7FF")

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

        # Code snippet with syntax highlighting
        snippet = self._build_code_snippet(
            str(comment["file_path"]),
            int(comment["line_number"]),
            text.plain.count("\n"),
        )

        try:
            panel = self.query_one("#mentor-main-panel", Static)
            if snippet is not None:
                panel.update(Group(text, snippet))
            else:
                panel.update(text)
        except Exception:
            pass

    def _build_code_snippet(
        self, file_path: str, line_number: int, header_lines: int
    ) -> Syntax | None:
        """Build a syntax-highlighted code snippet centered on line_number."""
        # Try file snapshots first (instant, no subprocess)
        content = self._data.file_snapshots.get(file_path)

        # Fall back to VCS provider for old mentor outputs without snapshots
        if content is None and self._data.vcs_provider and self._data.revision:
            try:
                ok, vcs_content = self._data.vcs_provider.file_at_revision(
                    self._data.revision, file_path, self._data.vcs_cwd
                )
                if ok and vcs_content and vcs_content.strip():
                    content = vcs_content
            except (NotImplementedError, Exception):
                pass

        if content is None:
            return None

        total_lines = content.count("\n") + 1
        line_number = max(1, min(line_number, total_lines))

        lexer = lexer_for_path(file_path)

        # Compute available lines from panel height
        try:
            panel = self.query_one("#mentor-main-panel", Static)
            panel_height = panel.content_size.height
        except Exception:
            panel_height = 0
        max_lines = max(5, (panel_height or 40) - header_lines - 1)

        # Center the range on the target line
        half = max_lines // 2
        start = max(1, line_number - half)
        end = min(total_lines, start + max_lines - 1)
        start = max(1, end - max_lines + 1)

        return Syntax(
            content,
            lexer,
            theme="monokai",
            line_numbers=True,
            line_range=(start, end),
            highlight_lines={line_number},
            word_wrap=True,
        )

    def _update_footer(self) -> None:
        accepted = self._data.acceptance.accepted_count
        total = self._data.total_comments

        text = Text()

        # Visual progress bar
        bar_width = min(total, 10) if total > 0 else 0
        if bar_width > 0:
            filled = round(accepted / total * bar_width)
            filled = max(0, min(bar_width, filled))
            all_done = accepted == total
            fill_style = "#00D7AF" if all_done else "#87D7FF"
            text.append(" ")
            text.append("■" * filled, style=fill_style)
            text.append("□" * (bar_width - filled), style="dim #4A4A6A")
            text.append(f" {accepted}/{total} accepted", style="bold")
        else:
            text.append(f" {accepted}/{total} accepted", style="bold")

        text.append("  \u2502  ", style="dim")

        bindings = [
            ("n/p", "comments"),
            ("j/k", "mentors"),
            ("\u2423", "toggle"),
            ("a", "apply+propose"),
            ("A", "apply+commit"),
            ("K", "kill"),
            ("r", "run"),
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

    def _collect_accepted(self) -> list[dict[str, str | int]]:
        """Collect all accepted comments across mentors."""
        accepted: list[dict[str, str | int]] = []
        for m in self._data.mentors:
            for i, comment in enumerate(m.comments):
                if self._data.acceptance.is_accepted(m.profile_name, m.mentor_name, i):
                    accepted.append(comment)
        return accepted

    def action_apply_commit(self) -> None:
        """Apply accepted comments and commit (A key)."""
        accepted = self._collect_accepted()
        if not accepted:
            self.app.notify("No comments accepted", severity="warning")
            return
        self.dismiss(
            MentorApplyResult(
                accepted_comments=accepted,
                cl_name=self._data.cl_name,
                mode="commit",
            )
        )

    def action_apply_propose(self) -> None:
        """Apply accepted comments and propose (a key)."""
        accepted = self._collect_accepted()
        if not accepted:
            self.app.notify("No comments accepted", severity="warning")
            return
        self.dismiss(
            MentorApplyResult(
                accepted_comments=accepted,
                cl_name=self._data.cl_name,
                mode="propose",
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

    # -- Run profile --

    def action_run_profile(self) -> None:
        """Open profile picker and dismiss with MentorRunResult on selection."""
        from sase.config.mentor import get_all_mentor_profiles

        from .mentor_profile_select_modal import MentorProfileSelectModal

        profiles = get_all_mentor_profiles()
        if not profiles:
            self.app.notify("No mentor profiles configured", severity="warning")
            return

        def on_profile_dismiss(profile_name: str | None) -> None:
            if profile_name is None:
                return
            self.dismiss(
                MentorRunResult(
                    profile_name=profile_name,
                    cl_name=self._data.cl_name,
                    entry_id=self._data.entry_id,
                )
            )

        self.app.push_screen(
            MentorProfileSelectModal(profiles, self._data.mentors),
            on_profile_dismiss,
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

    def _mark_current_read(self) -> None:
        """Mark the currently displayed comment as read and persist."""
        mentor = self._current_mentor()
        if not mentor or not mentor.comments:
            return
        idx = max(0, min(self._comment_idx, len(mentor.comments) - 1))
        newly_read = self._data.read_state.mark_read(
            mentor.profile_name, mentor.mentor_name, idx
        )
        if newly_read:
            save_read_state(
                self._data.cl_name, self._data.entry_id, self._data.read_state
            )

    def _read_count_for_mentor(self, mentor: MentorInfo) -> int:
        return self._data.read_state.read_count_for_mentor(
            mentor.profile_name, mentor.mentor_name, len(mentor.comments)
        )

    def _all_comments_accepted(self, mentor: MentorInfo) -> bool:
        if not mentor.comments:
            return False
        return all(
            self._data.acceptance.is_accepted(
                mentor.profile_name, mentor.mentor_name, i
            )
            for i in range(len(mentor.comments))
        )

    def _accepted_count_for_mentor(self, mentor: MentorInfo) -> int:
        return sum(
            1
            for i in range(len(mentor.comments))
            if self._data.acceptance.is_accepted(
                mentor.profile_name, mentor.mentor_name, i
            )
        )

    def _global_comment_index(self) -> tuple[int, int]:
        """Return (current_1based, total) position across all mentors.

        Returns (0, 0) when there are no comments.
        """
        total = self._data.total_comments
        if total == 0:
            return (0, 0)

        current = 0
        for i, m in enumerate(self._data.mentors):
            if i == self._mentor_idx:
                current += self._comment_idx + 1
                break
            current += len(m.comments)

        return (current, total)
