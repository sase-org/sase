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
from typing import Literal

from ._hookspec import hookimpl
from ._types import (
    IssueListState,
    IssueState,
    IssueWire,
    PullRequestListState,
    PullRequestWire,
)

ProviderCapability = Literal[
    "issue_listing", "issue_reads", "issue_mutations", "pull_requests"
]

_ALL_CAPABILITIES: frozenset[ProviderCapability] = frozenset(
    {"issue_listing", "issue_reads", "issue_mutations", "pull_requests"}
)

_CAPABILITY_METHODS: dict[ProviderCapability, tuple[str, ...]] = {
    "issue_listing": ("vcs_list_issues",),
    "issue_reads": ("vcs_get_issue", "vcs_get_issue_url"),
    "issue_mutations": ("vcs_create_issue", "vcs_update_issue"),
    "pull_requests": ("vcs_list_pull_requests",),
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class _InMemoryIssuePlugin:
    """A network-free, mutable implementation of the issue and PR hooks.

    Args:
        issues: Optional records with which to seed the tracker.
        pull_requests: Optional records with which to seed the PR list.
        base_url: Browser URL prefix used for newly created issues.
        author: Author assigned to newly created issues.
        clock: Timestamp source. Tests can inject a deterministic callable.
        capabilities: Restrict which operations this fake exposes, so
            downstream phases can test capability gating without a network
            call. ``None`` (the default) exposes every capability, matching
            a fully CRUD-capable provider.
    """

    def __init__(
        self,
        issues: Iterable[IssueWire] = (),
        *,
        pull_requests: Iterable[PullRequestWire] = (),
        base_url: str = "https://example.test/issues",
        author: str = "test-user",
        clock: Callable[[], str] | None = None,
        capabilities: Iterable[ProviderCapability] | None = None,
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
        self._pull_requests: dict[int, PullRequestWire] = {}
        for pull_request in pull_requests:
            if pull_request.number in self._pull_requests:
                raise ValueError(
                    f"duplicate pull request number: {pull_request.number}"
                )
            self._pull_requests[pull_request.number] = pull_request

        if capabilities is not None:
            disabled = _ALL_CAPABILITIES - frozenset(capabilities)
            for capability in disabled:
                for method_name in _CAPABILITY_METHODS[capability]:
                    setattr(self, method_name, None)

    @property
    def issues(self) -> tuple[IssueWire, ...]:
        """Return a stable snapshot of every issue, ordered by number."""
        with self._lock:
            return tuple(self._issues[number] for number in sorted(self._issues))

    @property
    def pull_requests(self) -> tuple[PullRequestWire, ...]:
        """Return a stable snapshot of every pull request, ordered by number."""
        with self._lock:
            return tuple(
                self._pull_requests[number] for number in sorted(self._pull_requests)
            )

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

    @hookimpl
    def vcs_list_pull_requests(
        self,
        cwd: str,
        state: PullRequestListState,
        limit: int,
    ) -> list[PullRequestWire]:
        del cwd
        if state not in ("open", "closed", "all"):
            raise ValueError(f"invalid pull request state filter: {state!r}")
        with self._lock:
            pull_requests = [
                pull_request
                for pull_request in self._pull_requests.values()
                if state == "all" or pull_request.state == state
            ]
        pull_requests.sort(
            key=lambda pull_request: (pull_request.updated_at, pull_request.number),
            reverse=True,
        )
        return pull_requests if limit <= 0 else pull_requests[:limit]


# A readable compatibility name for tests that prefer to call fixtures "fake".
FakeIssueProvider = _InMemoryIssuePlugin

__all__ = ["FakeIssueProvider", "ProviderCapability"]
