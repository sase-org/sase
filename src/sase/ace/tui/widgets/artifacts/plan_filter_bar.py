"""Inline query editor and completion menu for Artifacts plans."""

from __future__ import annotations

from collections.abc import Iterable

from textual.message import Message

from sase.ace.tui.widgets.filter_bar import FilterBar
from sase.plan_search.filter_query import plan_completion_context

from .types import ARTIFACTS_ACCENTS

__all__ = ["PlanFilterBar"]

_DATE_COMPLETIONS = (
    "1h",
    "24h",
    "today",
    "yesterday",
    "3d",
    "7d",
    "2w",
    "YYYY-MM-DD",
)


class PlanFilterBar(FilterBar):
    """Slash-style plans filter editor with plan-shaped completion."""

    ACCENT = ARTIFACTS_ACCENTS["plans"]
    ROW_ID = "plan-filter-row"
    SIGIL_ID = "plan-filter-sigil"
    INPUT_ID = "plan-filter-input"
    STATUS_ID = "plan-filter-status"
    COMPLETION_ID = "plan-filter-completion"
    CANDIDATE_ID_PREFIX = "plan-filter-candidate"
    KEY_COMPLETIONS = (
        ("kind", "proposal, epic, phase, archive"),
        ("status", "open, in_progress, closed, ready, blocked"),
        ("tier", "tale, epic, plan"),
        ("project", "project key or display name"),
        ("since", "Nh/Nd/Nw, today, YYYY-MM-DD"),
        ("until", "Nh/Nd/Nw, today, YYYY-MM-DD"),
    )
    STATIC_VALUE_COMPLETIONS = {
        "kind": ("proposal", "epic", "phase", "archive"),
        "status": (
            "proposed",
            "open",
            "in_progress",
            "closed",
            "ready",
            "blocked",
            "launched",
        ),
        "tier": ("tale", "epic", "plan"),
        "since": _DATE_COMPLETIONS,
        "until": _DATE_COMPLETIONS,
    }
    VALUE_HINTS = {
        "kind": "row kind",
        "status": "plan status",
        "tier": "plan tier",
        "project": "project",
        "since": "date bound",
        "until": "date bound",
    }
    REPEATABLE_VALUE_KINDS = frozenset(("kind", "status", "tier", "project"))
    FREE_TEXT_HINT = "title, body, id (AND)"

    class QueryChanged(Message):
        """The user changed the query text."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Submitted(Message):
        """The user requested that the current query be committed."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Dismissed(Message):
        """The user dismissed the bar after closing any completion menu."""

    def set_completion_sources(
        self,
        statuses: Iterable[str],
        projects: Iterable[str],
    ) -> None:
        """Replace observed archive-status and project completion sources."""
        self._set_completion_sources({"status": statuses, "project": projects})

    def _completion_context(self, text: str, cursor: int) -> tuple[str, str]:
        return plan_completion_context(text, cursor)
