"""Inline query editor and completion menu for Artifacts beads."""

from __future__ import annotations

from collections.abc import Iterable

from textual.message import Message

from sase.ace.tui.widgets.filter_bar import FilterBar
from sase.bead.filter_query import (
    BEAD_HAS_VALUES,
    DERIVED_BEAD_STATUS_VALUES,
    bead_completion_context,
)
from sase.bead.model import BeadTier
from sase.bead_status_presentation import bead_status_display_order
from sase.bead_type_presentation import BEAD_TYPE_VALUES
from sase.phase_size_presentation import PHASE_SIZE_VALUES

from .types import ARTIFACTS_ACCENTS

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


class BeadFilterBar(FilterBar):
    """Slash-style Beads filter editor with bead-shaped completion."""

    ACCENT = ARTIFACTS_ACCENTS["beads"]
    ROW_ID = "bead-filter-row"
    SIGIL_ID = "bead-filter-sigil"
    INPUT_ID = "bead-filter-input"
    STATUS_ID = "bead-filter-status"
    COMPLETION_ID = "bead-filter-completion"
    CANDIDATE_ID_PREFIX = "bead-filter-candidate"
    KEY_COMPLETIONS = (
        ("type", "plan, phase, task"),
        ("tier", "plan or epic"),
        ("status", "open, closed, blocked, triage"),
        ("size", "xsmall through xlarge"),
        ("project", "project key or display name"),
        ("assignee", "assigned person or agent"),
        ("owner", "owner email or name"),
        ("model", "work model"),
        ("has", "+1, plan, bug, deps, notes, triage"),
        ("since", "Nh/Nd/Nw, today, YYYY-MM-DD"),
        ("until", "Nh/Nd/Nw, today, YYYY-MM-DD"),
    )
    STATIC_VALUE_COMPLETIONS = {
        "type": BEAD_TYPE_VALUES,
        "tier": tuple(value.value for value in BeadTier),
        "status": (*bead_status_display_order(), *DERIVED_BEAD_STATUS_VALUES),
        "size": PHASE_SIZE_VALUES,
        "has": BEAD_HAS_VALUES,
        "since": _DATE_COMPLETIONS,
        "until": _DATE_COMPLETIONS,
    }
    VALUE_HINTS = {
        "type": "bead type",
        "tier": "plan tier",
        "status": "real or derived status",
        "size": "phase or task size",
        "project": "project",
        "assignee": "assignee",
        "owner": "owner",
        "model": "model",
        "has": "available metadata",
        "since": "date bound",
        "until": "date bound",
    }
    REPEATABLE_VALUE_KINDS = frozenset(
        (
            "type",
            "tier",
            "status",
            "size",
            "project",
            "assignee",
            "owner",
            "model",
            "has",
            "since",
            "until",
        )
    )
    NEGATABLE_KEYS = REPEATABLE_VALUE_KINDS
    FREE_TEXT_HINT = "id, title, body, refs (AND)"

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
        *,
        projects: Iterable[str],
        assignees: Iterable[str],
        owners: Iterable[str],
        models: Iterable[str],
    ) -> None:
        """Replace observed project, people, and model sources."""

        self._set_completion_sources(
            {
                "project": projects,
                "assignee": assignees,
                "owner": owners,
                "model": models,
            }
        )

    def _completion_context(
        self,
        text: str,
        cursor: int,
    ) -> tuple[str, str, bool]:
        return bead_completion_context(text, cursor)


__all__ = ["BeadFilterBar"]
