"""Inline query editor and completion menu for Artifacts Files."""

from __future__ import annotations

from collections.abc import Iterable

from textual.message import Message

from sase.ace.tui.widgets.filter_bar import FilterBar
from sase.core.artifact_file_types import ARTIFACT_FILE_KINDS

from .files_filtering import FILE_ORIGIN_VALUES, files_completion_context
from .types import ARTIFACTS_ACCENTS

_DATE_COMPLETIONS = (
    "3d",
    "7d",
    "2w",
    "1m",
    "YYYY-MM-DD",
    "YYYY-MM",
    "YYYYMM",
)


class FileFilterBar(FilterBar):
    """Slash-style Files filter editor with snapshot-backed completion."""

    ACCENT = ARTIFACTS_ACCENTS["files"]
    ROW_ID = "file-filter-row"
    SIGIL_ID = "file-filter-sigil"
    INPUT_ID = "file-filter-input"
    STATUS_ID = "file-filter-status"
    COMPLETION_ID = "file-filter-completion"
    CANDIDATE_ID_PREFIX = "file-filter-candidate"
    KEY_COMPLETIONS = (
        ("kind", "stored artifact kind"),
        ("project", "project key"),
        ("agent", "agent name"),
        ("workflow", "workflow name"),
        ("origin", "explicit or default"),
        ("since", "YYYY-MM-DD, YYYY-MM, Nd/Nw/Nm"),
        ("until", "YYYY-MM-DD, YYYY-MM, Nd/Nw/Nm"),
    )
    STATIC_VALUE_COMPLETIONS = {
        "kind": ARTIFACT_FILE_KINDS,
        "origin": FILE_ORIGIN_VALUES,
        "since": _DATE_COMPLETIONS,
        "until": _DATE_COMPLETIONS,
    }
    VALUE_HINTS = {
        "kind": "stored artifact kind",
        "project": "project",
        "agent": "agent",
        "workflow": "workflow",
        "origin": "registration origin",
        "since": "date bound",
        "until": "date bound",
    }
    REPEATABLE_VALUE_KINDS = frozenset(
        ("kind", "project", "agent", "workflow", "origin")
    )
    FREE_TEXT_HINT = "label, stored path, source path (AND)"

    class QueryChanged(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Submitted(Message):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class Dismissed(Message):
        pass

    def set_completion_sources(
        self,
        *,
        projects: Iterable[str],
        agents: Iterable[str],
        workflows: Iterable[str],
    ) -> None:
        """Replace dynamic values from the currently loaded snapshot."""

        self._set_completion_sources(
            {
                "project": projects,
                "agent": agents,
                "workflow": workflows,
            }
        )

    def _completion_context(
        self,
        text: str,
        cursor: int,
    ) -> tuple[str, str, bool]:
        return files_completion_context(text, cursor)


__all__ = ["FileFilterBar"]
