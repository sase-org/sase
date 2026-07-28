"""Inline query editor and completion menu for the commits timeline."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from textual.message import Message

from sase.ace.tui.widgets.filter_bar import FilterBar
from sase.vcs_log.filter_query import completion_context

from .types import ARTIFACTS_ACCENTS

__all__ = ["CommitFilterBar"]

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


class CommitFilterBar(FilterBar):
    """Slash-style commit filter editor with warm, context-aware completion."""

    ACCENT = ARTIFACTS_ACCENTS["commits"]
    ROW_ID = "commit-filter-row"
    SIGIL_ID = "commit-filter-sigil"
    INPUT_ID = "commit-filter-input"
    STATUS_ID = "commit-filter-status"
    COMPLETION_ID = "commit-filter-completion"
    CANDIDATE_ID_PREFIX = "commit-filter-candidate"
    KEY_COMPLETIONS = (
        ("project", "single project name; omitted means all projects"),
        ("repo", "repository name or alias"),
        ("author", "name or email substring"),
        ("since", "from an instant or the start of a named day"),
        ("until", "through an instant or the full named day"),
        ("sidecar", "include sidecar repositories"),
        ("limit", "row cap; all removes it"),
    )
    STATIC_VALUE_COMPLETIONS = {
        "since": _DATE_COMPLETIONS,
        "until": _DATE_COMPLETIONS,
        "sidecar": ("true", "false"),
        "limit": ("40", "100", "200", "all"),
    }
    VALUE_HINTS = {
        "project": "project name",
        "repo": "repository",
        "author": "author",
        "since": "date bound",
        "until": "named days include the full day",
        "sidecar": "true or false",
        "limit": "row cap or all",
    }
    REPEATABLE_VALUE_KINDS = frozenset(("repo", "author"))
    NEGATABLE_KEYS = frozenset(("repo", "author"))
    FREE_TEXT_HINT = "subject terms (AND)"
    PERSISTENT = True

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

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._projects: tuple[str, ...] = ()
        self._repos: tuple[str, ...] = ()
        self._authors: tuple[str, ...] = ()

    def set_completion_sources(
        self,
        repos: Iterable[str],
        authors: Iterable[str],
    ) -> None:
        """Replace the in-memory repository and author completion sources."""
        self._repos = tuple(repos)
        self._authors = tuple(authors)
        self._refresh_completion_sources()

    def set_project_completion_sources(self, projects: Iterable[str]) -> None:
        """Replace the warm configured-project-name completion source."""
        self._projects = tuple(projects)
        self._refresh_completion_sources()

    def _refresh_completion_sources(self) -> None:
        self._set_completion_sources(
            {
                "project": self._projects,
                "repo": self._repos,
                "author": self._authors,
            }
        )

    def set_status(
        self,
        match_count: int | None,
        exact: bool,
        error: str | Exception | None,
        *,
        coverage_label: str | None = None,
        lower_bound: bool = False,
    ) -> None:
        """Render coverage only; the Commits legend owns the displayed count."""
        del match_count, lower_bound
        super().set_status(
            None,
            exact,
            error,
            coverage_label=coverage_label,
        )

    def _completion_context(
        self,
        text: str,
        cursor: int,
    ) -> tuple[str, str, bool]:
        return completion_context(text, cursor)
