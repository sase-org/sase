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
        ("kind", "proposal, active, archive, plans, research"),
        ("status", "proposed or plan frontmatter status"),
        ("tier", "tale, epic, plan"),
        ("project", "project key or display name"),
        ("since", "Nh/Nd/Nw, today, YYYY-MM-DD"),
        ("until", "Nh/Nd/Nw, today, YYYY-MM-DD"),
    )
    STATIC_VALUE_COMPLETIONS = {
        "kind": ("proposal", "active", "archive", "plans", "research"),
        "status": ("proposed",),
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
    NEGATABLE_KEYS = REPEATABLE_VALUE_KINDS
    FREE_TEXT_HINT = "title, body, path (AND)"

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
        kinds: Iterable[str] = (),
    ) -> None:
        """Replace observed document-kind, status, and project sources."""
        self._set_completion_sources(
            {"kind": kinds, "status": statuses, "project": projects}
        )

    def _completion_context(
        self,
        text: str,
        cursor: int,
    ) -> tuple[str, str, bool]:
        if self._profile is not None:
            return super()._completion_context(text, cursor)
        return plan_completion_context(text, cursor)
