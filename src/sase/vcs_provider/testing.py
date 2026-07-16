"""Deterministic issue-provider fixtures for unit and TUI tests.

The fake is a pluggy plugin rather than a :class:`VCSProvider` subclass, so
tests exercise the same :class:`~sase.vcs_provider.VCSPluginManager` dispatch
path as installed providers without needing to implement unrelated VCS hooks.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from threading import RLock

from ._hookspec import hookimpl
from ._types import IssueListState, IssueState, IssueWire


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class InMemoryIssuePlugin:
    """A network-free, mutable implementation of the issue hooks.

    Args:
        issues: Optional records with which to seed the tracker.
        base_url: Browser URL prefix used for newly created issues.
        author: Author assigned to newly created issues.
        clock: Timestamp source. Tests can inject a deterministic callable.
    """

    def __init__(
        self,
        issues: Iterable[IssueWire] = (),
        *,
        base_url: str = "https://example.test/issues",
        author: str = "test-user",
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._author = author
        self._clock = clock or _utc_now
        self._lock = RLock()
        self._issues: dict[int, IssueWire] = {}
        for issue in issues:
            if issue.number in self._issues:
                raise ValueError(f"duplicate issue number: {issue.number}")
            self._issues[issue.number] = issue

    @property
    def issues(self) -> tuple[IssueWire, ...]:
        """Return a stable snapshot of every issue, ordered by number."""
        with self._lock:
            return tuple(self._issues[number] for number in sorted(self._issues))

    @hookimpl
    def vcs_list_issues(
        self,
        cwd: str,
        state: IssueListState,
        limit: int,
    ) -> list[IssueWire]:
        del cwd
        if state not in ("open", "closed", "all"):
            raise ValueError(f"invalid issue state filter: {state!r}")
        with self._lock:
            issues = [
                issue
                for issue in self._issues.values()
                if state == "all" or issue.state == state
            ]
        issues.sort(key=lambda issue: (issue.updated_at, issue.number), reverse=True)
        return issues if limit <= 0 else issues[:limit]

    @hookimpl
    def vcs_get_issue(self, number: int, cwd: str) -> IssueWire:
        del cwd
        with self._lock:
            try:
                return self._issues[number]
            except KeyError:
                raise KeyError(f"issue #{number} does not exist") from None

    @hookimpl
    def vcs_create_issue(
        self,
        title: str,
        body: str,
        labels: Sequence[str],
        cwd: str,
    ) -> IssueWire:
        del cwd
        with self._lock:
            number = max(self._issues, default=0) + 1
            now = self._clock()
            issue = IssueWire(
                number=number,
                title=title,
                state="open",
                body=body,
                labels=tuple(labels),
                author=self._author,
                created_at=now,
                updated_at=now,
                url=self._url(number),
            )
            self._issues[number] = issue
            return issue

    @hookimpl
    def vcs_update_issue(
        self,
        number: int,
        cwd: str,
        title: str | None,
        body: str | None,
        state: IssueState | None,
        labels: Sequence[str] | None,
    ) -> IssueWire:
        del cwd
        if state is not None and state not in ("open", "closed"):
            raise ValueError(f"invalid issue state: {state!r}")
        with self._lock:
            try:
                issue = self._issues[number]
            except KeyError:
                raise KeyError(f"issue #{number} does not exist") from None
            updated = replace(
                issue,
                title=issue.title if title is None else title,
                body=issue.body if body is None else body,
                state=issue.state if state is None else state,
                labels=issue.labels if labels is None else tuple(labels),
                updated_at=self._clock(),
            )
            self._issues[number] = updated
            return updated

    @hookimpl
    def vcs_get_issue_url(self, number: int, cwd: str) -> str:
        del cwd
        with self._lock:
            issue = self._issues.get(number)
        if issue is not None and issue.url:
            return issue.url
        return self._url(number)

    def _url(self, number: int) -> str:
        return f"{self._base_url}/{number}"


# A readable compatibility name for tests that prefer to call fixtures "fake".
FakeIssueProvider = InMemoryIssuePlugin

__all__ = ["FakeIssueProvider", "InMemoryIssuePlugin"]
