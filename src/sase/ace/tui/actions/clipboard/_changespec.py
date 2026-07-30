"""Copy actions specific to the ChangeSpecs tab."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ....changespec import get_raw_changespec_text
from sase.project_display_names import humanize_cl_name

from ._base import ClipboardBase
from ._delivery import schedule_copy_delivery
from ._helpers import (
    cap_copy_content,
    capture_tmux_pane,
    format_changespec_for_clipboard,
    format_markdown_link,
    format_multi_copy_content_capped,
)

if TYPE_CHECKING:
    from ....changespec import ChangeSpec


class ClipboardChangeSpecMixin(ClipboardBase):
    """Copy actions for entries on the ChangeSpecs tab."""

    def _copy_changespec(self) -> None:
        """Copy the raw changespec text to clipboard (%%)."""
        changespec = self.changespecs[self.current_idx]
        state = {"truncated": False}

        def content() -> str:
            value = get_raw_changespec_text(changespec)
            if value is None:
                value = format_changespec_for_clipboard(changespec)
            capped = cap_copy_content(value.strip())
            state["truncated"] = capped.truncated
            return capped.value

        schedule_copy_delivery(
            self,
            content,
            copied_label=lambda: (
                "ChangeSpec — truncated" if state["truncated"] else "ChangeSpec"
            ),
            task_name="sase-copy-changespec",
        )

    def _copy_changespec_and_snapshot(self) -> None:
        """Copy changespec and tmux pane snapshot with multi-format (%!)."""
        changespec = self.changespecs[self.current_idx]
        state = {"truncated": False}

        def content() -> str:
            cs_content = get_raw_changespec_text(changespec)
            if cs_content is None:
                cs_content = format_changespec_for_clipboard(changespec)
            snapshot_content = capture_tmux_pane()
            if snapshot_content is None:
                raise RuntimeError("failed to capture tmux pane")
            contents = [
                ("ChangeSpec", cs_content.strip()),
                ("`sase ace` Snapshot", snapshot_content.strip()),
            ]
            capped = format_multi_copy_content_capped(contents)
            state["truncated"] = capped.truncated
            return capped.value

        schedule_copy_delivery(
            self,
            content,
            copied_label=lambda: (
                "ChangeSpec + snapshot — truncated"
                if state["truncated"]
                else "ChangeSpec + snapshot"
            ),
            task_name="sase-copy-changespec-snapshot",
        )

    def _copy_bug_number(self) -> None:
        """Copy the bug number from the current changespec (%b)."""
        changespec = self.changespecs[self.current_idx]
        bug_number = self._get_bug_number(changespec)
        if bug_number is None:
            return  # Error already notified

        schedule_copy_delivery(
            self,
            bug_number,
            copied_label=f"bug number ({bug_number})",
            task_name="sase-copy-changespec-bug",
        )

    def _copy_pr_number(self) -> None:
        """Copy the PR number from the current changespec (%c)."""
        changespec = self.changespecs[self.current_idx]
        pr_number = self._get_pr_number(changespec)
        if pr_number is None:
            return  # Error already notified

        schedule_copy_delivery(
            self,
            pr_number,
            copied_label=f"PR number ({pr_number})",
            task_name="sase-copy-changespec-pr",
        )

    def _copy_cl_name(self) -> None:
        """Copy the ChangeSpec name from the current changespec (%n)."""
        changespec = self.changespecs[self.current_idx]
        cl_name = humanize_cl_name(changespec.name)

        schedule_copy_delivery(
            self,
            cl_name,
            copied_label=f"ChangeSpec name ({cl_name})",
            task_name="sase-copy-changespec-name",
        )

    def _copy_changespec_link(self) -> None:
        """Copy a Markdown link to the current ChangeSpec's PR."""

        changespec = self.changespecs[self.current_idx]
        if not changespec.pr_url:
            self.notify("No PR URL available", severity="warning")  # type: ignore[attr-defined]
            return
        label = humanize_cl_name(changespec.name)
        schedule_copy_delivery(
            self,
            format_markdown_link(label, changespec.pr_url),
            copied_label="ChangeSpec Markdown link",
            task_name="sase-copy-changespec-link",
        )

    def _copy_project_spec(self) -> None:
        """Copy the project spec file content (%p)."""
        changespec = self.changespecs[self.current_idx]
        state = {"truncated": False}

        def content() -> str:
            with open(changespec.file_path) as handle:
                capped = cap_copy_content(handle.read().rstrip("\n").strip())
                state["truncated"] = capped.truncated
                return capped.value

        schedule_copy_delivery(
            self,
            content,
            copied_label=lambda: (
                "ProjectSpec file — truncated"
                if state["truncated"]
                else "ProjectSpec file"
            ),
            task_name="sase-copy-project-spec",
        )

    def _get_bug_number(self, changespec: ChangeSpec) -> str | None:
        """Extract the bug number from a ChangeSpec's bug field.

        Args:
            changespec: The ChangeSpec.

        Returns:
            The bug number string, or None if unavailable.
        """
        if not changespec.bug:
            self.notify("No bug number available", severity="warning")  # type: ignore[attr-defined]
            return None

        # Match http://b/<number> or https://b/<number>
        match = re.match(r"https?://b/(\d+)", changespec.bug)
        if match:
            return match.group(1)

        # Match b/<number>
        match = re.match(r"b/(\d+)", changespec.bug)
        if match:
            return match.group(1)

        # Plain number
        match = re.match(r"(\d+)$", changespec.bug)
        if match:
            return match.group(1)

        self.notify("Could not extract bug number", severity="warning")  # type: ignore[attr-defined]
        return None

    def _get_project_spec_content(self, changespec: ChangeSpec) -> str | None:
        """Read the entire project spec file content.

        Args:
            changespec: The ChangeSpec (to get file_path).

        Returns:
            The file content, or None if an error occurred.
        """
        try:
            with open(changespec.file_path) as f:
                return f.read().rstrip("\n")
        except OSError as e:
            self.notify(f"Could not read project file: {e}", severity="error")  # type: ignore[attr-defined]
            return None

    def _get_pr_number(self, changespec: ChangeSpec) -> str | None:
        """Extract the PR/review number from a ChangeSpec's PR URL.

        Args:
            changespec: The ChangeSpec.

        Returns:
            The PR/review number string, or None if unavailable.
        """
        if not changespec.pr_url:
            self.notify("No PR URL available", severity="warning")  # type: ignore[attr-defined]
            return None

        # Match http://cl/<number> or https://cl/<number> (hg)
        match = re.match(r"https?://cl/(\d+)", changespec.pr_url)
        if match:
            return match.group(1)

        # Match GitHub PR URL
        match = re.match(r"https?://github\.com/.+/pull/(\d+)", changespec.pr_url)
        if match:
            return match.group(1)

        self.notify("Could not extract PR number from URL", severity="warning")  # type: ignore[attr-defined]
        return None
