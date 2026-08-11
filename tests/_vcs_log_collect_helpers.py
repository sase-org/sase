"""Shared fakes for VCS log collection tests."""

from __future__ import annotations

from sase.core.vcs_log_wire import CommitOrigin, VcsCommitWire
from sase.vcs_log.models import CommitFilters
from sase.vcs_provider._types import MergeVisibility


def commit(
    full: str, ts: int, subject: str = "s", origin: CommitOrigin = "manual"
) -> VcsCommitWire:
    return VcsCommitWire(
        full_id=full,
        short_id=full[:7],
        author_name="bryan",
        author_email="b@x",
        timestamp=ts,
        subject=subject,
        body="",
        origin=origin,
    )


class FakeProvider:
    def __init__(self, commits: list[VcsCommitWire]) -> None:
        self._commits = commits

    def log(
        self,
        cwd: str,
        limit: int,
        *,
        since: int | None = None,
        until: int | None = None,
        authors: tuple[str, ...] = (),
        merges: MergeVisibility = "hide",
    ) -> list[VcsCommitWire]:
        del cwd, since, until, authors, merges
        return self._commits if limit < 0 else self._commits[:limit]


class FailProvider:
    def log(
        self,
        cwd: str,
        limit: int,
        *,
        since: int | None = None,
        until: int | None = None,
        authors: tuple[str, ...] = (),
        merges: MergeVisibility = "hide",
    ) -> list[VcsCommitWire]:
        del cwd, limit, since, until, authors, merges
        raise RuntimeError("no such checkout")


class RemoteProvider:
    def __init__(
        self,
        commits: list[VcsCommitWire],
        *,
        remote_ref: str | None = "origin/main",
        ahead: set[str] | None = None,
        behind: set[str] | None = None,
        fetch_ok: bool = True,
    ) -> None:
        self._commits = commits
        self._remote_ref = remote_ref
        self._ahead = ahead or set()
        self._behind = behind or set()
        self._fetch_ok = fetch_ok
        self.fetch_calls: list[tuple[str, ...]] = []
        self.log_revs: tuple[str, ...] | None = None
        self.log_limit: int | None = None
        self.log_filters: CommitFilters | None = None
        self.partition_merges: MergeVisibility | None = None

    def resolve_remote_log_ref(
        self, cwd: str, ref_name: str | None = None
    ) -> str | None:
        del cwd
        if ref_name:
            return f"origin/{ref_name}"
        return self._remote_ref

    def fetch_remote(
        self, cwd: str, refs: tuple[str, ...], *, timeout: int = 120
    ) -> tuple[bool, str | None]:
        del cwd, timeout
        self.fetch_calls.append(refs)
        if not self._fetch_ok:
            return (False, "network down")
        return (True, None)

    def partition_commits(
        self,
        cwd: str,
        *,
        local_ref: str,
        remote_ref: str,
        merges: MergeVisibility = "hide",
    ) -> tuple[set[str], set[str]]:
        del cwd, local_ref, remote_ref
        self.partition_merges = merges
        return (self._ahead, self._behind)

    def log(
        self,
        cwd: str,
        limit: int,
        *,
        since: int | None = None,
        until: int | None = None,
        authors: tuple[str, ...] = (),
        merges: MergeVisibility = "hide",
        revs: tuple[str, ...] = ("HEAD",),
    ) -> list[VcsCommitWire]:
        del cwd
        self.log_revs = revs
        self.log_limit = limit
        self.log_filters = CommitFilters(since, until, authors, merges)
        return self._commits if limit < 0 else self._commits[:limit]


class LocalOnlyProvider(FakeProvider):
    def resolve_remote_log_ref(
        self, cwd: str, ref_name: str | None = None
    ) -> str | None:
        del cwd, ref_name
        raise NotImplementedError(
            "resolve_remote_log_ref is not supported by this VCS provider"
        )
