"""Copy actions specific to the ChangeSpecs tab."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ....changespec import get_raw_changespec_text

from ._base import ClipboardBase
from ._helpers import (
    capture_tmux_pane,
    copy_to_system_clipboard,
    format_changespec_for_clipboard,
    format_multi_copy_content,
)

if TYPE_CHECKING:
    from ....changespec import ChangeSpec


class ClipboardChangeSpecMixin(ClipboardBase):
    """Copy actions for entries on the ChangeSpecs tab."""

    def _copy_changespec(self) -> None:
        """Copy the raw changespec text to clipboard (%%)."""
        changespec = self.changespecs[self.current_idx]
        content = get_raw_changespec_text(changespec)
        if content is None:
            content = format_changespec_for_clipboard(changespec)

        if copy_to_system_clipboard(content.strip()):
            self.notify("Copied: ChangeSpec")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to copy to clipboard", severity="error")  # type: ignore[attr-defined]

    def _copy_changespec_and_snapshot(self) -> None:
        """Copy changespec and tmux pane snapshot with multi-format (%!)."""
        changespec = self.changespecs[self.current_idx]

        # Get changespec content
        cs_content = get_raw_changespec_text(changespec)
        if cs_content is None:
            cs_content = format_changespec_for_clipboard(changespec)

        # Get tmux pane snapshot
        snapshot_content = capture_tmux_pane()
        if snapshot_content is None:
            self.notify("Failed to capture tmux pane", severity="warning")  # type: ignore[attr-defined]
            return

        # Format with headers
        contents = [
            ("ChangeSpec", cs_content.strip()),
            ("`sase ace` Snapshot", snapshot_content.strip()),
        ]
        final_content = format_multi_copy_content(contents)

        if copy_to_system_clipboard(final_content):
            self.notify("Copied: ChangeSpec + Snapshot")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to copy to clipboard", severity="error")  # type: ignore[attr-defined]

    def _copy_bug_number(self) -> None:
        """Copy the bug number from the current changespec (%b)."""
        changespec = self.changespecs[self.current_idx]
        bug_number = self._get_bug_number(changespec)
        if bug_number is None:
            return  # Error already notified

        if copy_to_system_clipboard(bug_number):
            self.notify(f"Copied: Bug Number ({bug_number})")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to copy to clipboard", severity="error")  # type: ignore[attr-defined]

    def _copy_cl_number(self) -> None:
        """Copy the CL number from the current changespec (%c)."""
        changespec = self.changespecs[self.current_idx]
        cl_number = self._get_cl_number(changespec)
        if cl_number is None:
            return  # Error already notified

        if copy_to_system_clipboard(cl_number):
            self.notify(f"Copied: CL Number ({cl_number})")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to copy to clipboard", severity="error")  # type: ignore[attr-defined]

    def _copy_cl_name(self) -> None:
        """Copy the CL name from the current changespec (%n)."""
        changespec = self.changespecs[self.current_idx]
        cl_name = changespec.name

        if copy_to_system_clipboard(cl_name):
            self.notify(f"Copied: CL Name ({cl_name})")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to copy to clipboard", severity="error")  # type: ignore[attr-defined]

    def _copy_project_spec(self) -> None:
        """Copy the project spec file content (%p)."""
        changespec = self.changespecs[self.current_idx]
        content = self._get_project_spec_content(changespec)
        if content is None:
            return  # Error already notified

        if copy_to_system_clipboard(content.strip()):
            self.notify("Copied: Project Spec File")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to copy to clipboard", severity="error")  # type: ignore[attr-defined]

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
        """Read the entire project spec (.gp) file content.

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

    def _get_cl_number(self, changespec: ChangeSpec) -> str | None:
        """Extract the CL/PR number from a ChangeSpec's CL URL.

        Args:
            changespec: The ChangeSpec.

        Returns:
            The CL/PR number string, or None if unavailable.
        """
        if not changespec.cl:
            self.notify("No CL URL available", severity="warning")  # type: ignore[attr-defined]
            return None

        # Match http://cl/<number> or https://cl/<number> (hg)
        match = re.match(r"https?://cl/(\d+)", changespec.cl)
        if match:
            return match.group(1)

        # Match GitHub PR URL
        match = re.match(r"https?://github\.com/.+/pull/(\d+)", changespec.cl)
        if match:
            return match.group(1)

        self.notify("Could not extract CL/PR number from URL", severity="warning")  # type: ignore[attr-defined]
        return None
