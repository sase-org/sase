"""Copy actions specific to the AXE tab."""

from __future__ import annotations

from ._base import ClipboardBase
from ._delivery import schedule_copy_delivery
from ._helpers import format_multi_copy_content


class ClipboardAxeMixin(ClipboardBase):
    """Copy actions for output displayed on the AXE tab."""

    def _copy_axe_output(self) -> None:
        """Copy visible command output from the AXE tab (%o)."""
        from textual.containers import VerticalScroll

        from ...bgcmd import read_slot_output_tail

        view = self._axe_current_view
        if view == "axe":
            warm_output = self._axe_output
            source = "Axe Output"
        else:
            warm_output = None
            source = f"Command #{view} Output"

        try:
            scroll = self.query_one("#axe-output-scroll", VerticalScroll)  # type: ignore[attr-defined]
            scroll_y = int(scroll.scroll_y)
            visible_height = scroll.scrollable_content_region.height
        except Exception:
            scroll_y = 0
            visible_height = 0

        lines = 0

        def content() -> str:
            nonlocal lines
            full_output = (
                warm_output if view == "axe" else read_slot_output_tail(view, 10000)
            )
            if not full_output or not full_output.strip():
                raise RuntimeError("no output is available")
            output = full_output
            if visible_height > 0:
                all_lines = full_output.split("\n")
                output = "\n".join(all_lines[scroll_y : scroll_y + visible_height])
            if not output.strip():
                raise RuntimeError("no visible output is available")
            lines = len(output.strip().split("\n"))
            return format_multi_copy_content([(source, output.strip())])

        schedule_copy_delivery(
            self,
            content,
            copied_label=lambda: f"{source.lower()} ({lines} lines)",
            task_name="sase-copy-axe-visible",
        )

    def _copy_axe_full_output(self) -> None:
        """Copy full command output from the AXE tab (%O)."""
        from ...bgcmd import read_slot_output_tail

        view = self._axe_current_view
        if view == "axe":
            warm_output = self._axe_output
            source = "Axe Output (Full)"
        else:
            warm_output = None
            source = f"Command #{view} Output (Full)"

        lines = 0

        def content() -> str:
            nonlocal lines
            output = (
                warm_output if view == "axe" else read_slot_output_tail(view, 10000)
            )
            if not output or not output.strip():
                raise RuntimeError("no output is available")
            lines = len(output.strip().split("\n"))
            return format_multi_copy_content([(source, output.strip())])

        schedule_copy_delivery(
            self,
            content,
            copied_label=lambda: f"{source.lower()} ({lines} lines)",
            task_name="sase-copy-axe-full",
        )
