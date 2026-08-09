"""Copy actions specific to the Patches tab."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ....patch import get_raw_patch_text
from sase.project_display_names import humanize_cl_name

from ._base import ClipboardBase
from ._delivery import schedule_copy_delivery
from ._helpers import (
    cap_copy_content,
    capture_tmux_pane,
    format_patch_for_clipboard,
    format_markdown_link,
    format_multi_copy_content_capped,
)

if TYPE_CHECKING:
    from ....patch import Patch


class ClipboardPatchMixin(ClipboardBase):
    """Copy actions for entries on the Patches tab."""

    def _copy_patch(self) -> None:
        """Copy the raw patch text to clipboard (%%)."""
        patch = self.patches[self.current_idx]
        state = {"truncated": False}

        def content() -> str:
            value = get_raw_patch_text(patch)
            if value is None:
                value = format_patch_for_clipboard(patch)
            capped = cap_copy_content(value.strip())
            state["truncated"] = capped.truncated
            return capped.value

        schedule_copy_delivery(
            self,
            content,
            copied_label=lambda: "Patch — truncated" if state["truncated"] else "Patch",
            task_name="sase-copy-patch",
        )

    def _copy_patch_and_snapshot(self) -> None:
        """Copy patch and tmux pane snapshot with multi-format (%!)."""
        patch = self.patches[self.current_idx]
        state = {"truncated": False}

        def content() -> str:
            cs_content = get_raw_patch_text(patch)
            if cs_content is None:
                cs_content = format_patch_for_clipboard(patch)
            snapshot_content = capture_tmux_pane()
            if snapshot_content is None:
                raise RuntimeError("failed to capture tmux pane")
            contents = [
                ("Patch", cs_content.strip()),
                ("`sase ace` Snapshot", snapshot_content.strip()),
            ]
            capped = format_multi_copy_content_capped(contents)
            state["truncated"] = capped.truncated
            return capped.value

        schedule_copy_delivery(
            self,
            content,
            copied_label=lambda: (
                "Patch + snapshot — truncated"
                if state["truncated"]
                else "Patch + snapshot"
            ),
            task_name="sase-copy-patch-snapshot",
        )

    def _copy_bug_number(self) -> None:
        """Copy the bug number from the current patch (%b)."""
        patch = self.patches[self.current_idx]
        bug_number = self._get_bug_number(patch)
        if bug_number is None:
            return  # Error already notified

        schedule_copy_delivery(
            self,
            bug_number,
            copied_label=f"bug number ({bug_number})",
            task_name="sase-copy-patch-bug",
        )

    def _copy_pr_number(self) -> None:
        """Copy the PR number from the current patch (%c)."""
        patch = self.patches[self.current_idx]
        pr_number = self._get_pr_number(patch)
        if pr_number is None:
            return  # Error already notified

        schedule_copy_delivery(
            self,
            pr_number,
            copied_label=f"PR number ({pr_number})",
            task_name="sase-copy-patch-pr",
        )

    def _copy_cl_name(self) -> None:
        """Copy the Patch name from the current patch (%n)."""
        patch = self.patches[self.current_idx]
        cl_name = humanize_cl_name(patch.name)

        schedule_copy_delivery(
            self,
            cl_name,
            copied_label=f"Patch name ({cl_name})",
            task_name="sase-copy-patch-name",
        )

    def _copy_patch_link(self) -> None:
        """Copy a Markdown link to the current Patch's PR."""

        patch = self.patches[self.current_idx]
        if not patch.pr_url:
            self.notify("No PR URL available", severity="warning")  # type: ignore[attr-defined]
            return
        label = humanize_cl_name(patch.name)
        schedule_copy_delivery(
            self,
            format_markdown_link(label, patch.pr_url),
            copied_label="Patch Markdown link",
            task_name="sase-copy-patch-link",
        )

    def _copy_changespec_link(self) -> None:
        """Legacy ChangeSpec link copy action."""

        from . import _changespec as changespec_clipboard

        patch = self.patches[self.current_idx]
        if not patch.pr_url:
            self.notify("No PR URL available", severity="warning")  # type: ignore[attr-defined]
            return
        label = changespec_clipboard.humanize_cl_name(patch.name)
        changespec_clipboard.schedule_copy_delivery(
            self,
            format_markdown_link(label, patch.pr_url),
            copied_label="Patch Markdown link",
            task_name="sase-copy-changespec-link",
        )

    def _copy_project_spec(self) -> None:
        """Copy the project spec file content (%p)."""
        patch = self.patches[self.current_idx]
        state = {"truncated": False}

        def content() -> str:
            with open(patch.file_path) as handle:
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

    def _get_bug_number(self, patch: Patch) -> str | None:
        """Extract the bug number from a Patch's bug field.

        Args:
            patch: The Patch.

        Returns:
            The bug number string, or None if unavailable.
        """
        if not patch.bug:
            self.notify("No bug number available", severity="warning")  # type: ignore[attr-defined]
            return None

        # Match http://b/<number> or https://b/<number>
        match = re.match(r"https?://b/(\d+)", patch.bug)
        if match:
            return match.group(1)

        # Match b/<number>
        match = re.match(r"b/(\d+)", patch.bug)
        if match:
            return match.group(1)

        # Plain number
        match = re.match(r"(\d+)$", patch.bug)
        if match:
            return match.group(1)

        self.notify("Could not extract bug number", severity="warning")  # type: ignore[attr-defined]
        return None

    def _get_project_spec_content(self, patch: Patch) -> str | None:
        """Read the entire project spec file content.

        Args:
            patch: The Patch (to get file_path).

        Returns:
            The file content, or None if an error occurred.
        """
        try:
            with open(patch.file_path) as f:
                return f.read().rstrip("\n")
        except OSError as e:
            self.notify(f"Could not read project file: {e}", severity="error")  # type: ignore[attr-defined]
            return None

    def _get_pr_number(self, patch: Patch) -> str | None:
        """Extract the PR/review number from a Patch's PR URL.

        Args:
            patch: The Patch.

        Returns:
            The PR/review number string, or None if unavailable.
        """
        if not patch.pr_url:
            self.notify("No PR URL available", severity="warning")  # type: ignore[attr-defined]
            return None

        # Match http://cl/<number> or https://cl/<number> (hg)
        match = re.match(r"https?://cl/(\d+)", patch.pr_url)
        if match:
            return match.group(1)

        # Match GitHub PR URL
        match = re.match(r"https?://github\.com/.+/pull/(\d+)", patch.pr_url)
        if match:
            return match.group(1)

        self.notify("Could not extract PR number from URL", severity="warning")  # type: ignore[attr-defined]
        return None
