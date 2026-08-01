"""Reserved inline-filter slot for the Artifacts Beads pane."""

from __future__ import annotations

from sase.ace.tui.widgets.filter_bar import FilterBar

from .types import ARTIFACTS_ACCENTS


class BeadFilterBar(FilterBar):
    """Mounted but inactive until bead-query filtering is implemented."""

    ACCENT = ARTIFACTS_ACCENTS["beads"]
    ROW_ID = "bead-filter-row"
    SIGIL_ID = "bead-filter-sigil"
    INPUT_ID = "bead-filter-input"
    STATUS_ID = "bead-filter-status"
    COMPLETION_ID = "bead-filter-completion"
    CANDIDATE_ID_PREFIX = "bead-filter-candidate"

    def _completion_context(
        self,
        text: str,
        cursor: int,
    ) -> tuple[str, str, bool]:
        del text, cursor
        return "", "", False


__all__ = ["BeadFilterBar"]
