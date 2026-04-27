"""Copy actions specific to the AXE tab."""

from __future__ import annotations

from ._base import ClipboardBase
from ._helpers import format_multi_copy_content, copy_to_system_clipboard


class ClipboardAxeMixin(ClipboardBase):
    """Copy actions for output displayed on the AXE tab."""

    def _copy_axe_output(self) -> None:
        """Copy visible command output from the AXE tab (%o)."""
        from textual.containers import VerticalScroll

        from ...bgcmd import read_slot_output_tail

        if self._axe_current_view == "axe":
            full_output = self._axe_output
            source = "Axe Output"
        else:
            slot = self._axe_current_view
            full_output = read_slot_output_tail(slot, 10000)
            source = f"Command #{slot} Output"

        if not full_output or not full_output.strip():
            self.notify("No output to copy", severity="warning")  # type: ignore[attr-defined]
            return

        # Get visible region from scroll widget
        try:
            scroll = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
            scroll_y = int(scroll.scroll_y)
            visible_height = scroll.scrollable_content_region.height

            # Split output into lines and extract visible portion
            all_lines = full_output.split("\n")
            start_line = scroll_y
            end_line = start_line + visible_height
            visible_lines = all_lines[start_line:end_line]
            output = "\n".join(visible_lines)
        except Exception:
            # Fallback to full output if we can't get scroll info
            output = full_output

        if not output.strip():
            self.notify("No visible output to copy", severity="warning")  # type: ignore[attr-defined]
            return

        # Format with header and code block
        contents = [(source, output.strip())]
        final_content = format_multi_copy_content(contents)

        if copy_to_system_clipboard(final_content):
            lines = len(output.strip().split("\n"))
            self.notify(f"Copied: {source} ({lines} lines)")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to copy to clipboard", severity="error")  # type: ignore[attr-defined]

    def _copy_axe_full_output(self) -> None:
        """Copy full command output from the AXE tab (%O)."""
        from ...bgcmd import read_slot_output_tail

        if self._axe_current_view == "axe":
            output = self._axe_output
            source = "Axe Output (Full)"
        else:
            slot = self._axe_current_view
            output = read_slot_output_tail(slot, 10000)  # Get more for full copy
            source = f"Command #{slot} Output (Full)"

        if not output or not output.strip():
            self.notify("No output to copy", severity="warning")  # type: ignore[attr-defined]
            return

        contents = [(source, output.strip())]
        final_content = format_multi_copy_content(contents)

        if copy_to_system_clipboard(final_content):
            lines = len(output.strip().split("\n"))
            self.notify(f"Copied: {source} ({lines} lines)")  # type: ignore[attr-defined]
        else:
            self.notify("Failed to copy to clipboard", severity="error")  # type: ignore[attr-defined]
