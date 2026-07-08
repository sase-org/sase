"""Tests for the ``sase vcs log`` collection service (failure isolation)."""

from __future__ import annotations

import pytest

from sase.core.vcs_log_wire import VcsCommitWire
from sase.vcs_log import collect as collect_module
from sase.vcs_log.collect import collect_vcs_log, run_vcs_log
from sase.vcs_log.models import CommitFilters, LogRepo, UNLIMITED
from sase.vcs_log.resolve import ResolvedRepos


def _commit(full: str, ts: int, subject: str = "s") -> VcsCommitWire:
    return VcsCommitWire(
        full_id=full,
        short_id=full[:7],
        author_name="bryan",
        author_email="b@x",
        timestamp=ts,
        subject=subject,
        body="",
    )


class _FakeProvider:
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
    ) -> list[VcsCommitWire]:
        del cwd, since, until, authors
        return self._commits if limit < 0 else self._commits[:limit]


class _FailProvider:
    def log(
        self,
        cwd: str,
        limit: int,
        *,
        since: int | None = None,
        until: int | None = None,
        authors: tuple[str, ...] = (),
    ) -> list[VcsCommitWire]:
        del cwd, limit, since, until, authors
        raise RuntimeError("no such checkout")


class _RemoteProvider:
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
        self, cwd: str, *, local_ref: str, remote_ref: str
    ) -> tuple[set[str], set[str]]:
        del cwd, local_ref, remote_ref
        return (self._ahead, self._behind)

    def log(
        self,
        cwd: str,
        limit: int,
        *,
        since: int | None = None,
        until: int | None = None,
        authors: tuple[str, ...] = (),
        revs: tuple[str, ...] = ("HEAD",),
    ) -> list[VcsCommitWire]:
        del cwd, since, until, authors
        self.log_revs = revs
        return self._commits if limit < 0 else self._commits[:limit]


def test_collect_isolates_failing_repo_and_interleaves() -> None:
    providers = {
        "/p/sase": _FakeProvider([_commit("a", 300, "recent"), _commit("b", 100)]),
        "/p/core": _FakeProvider([_commit("c", 200)]),
        "/p/bad": _FailProvider(),
    }
    repos = [
        LogRepo("sase", "/p/sase", "primary"),
        LogRepo("sase-core", "/p/core", "linked"),
        LogRepo("sase-bad", "/p/bad", "sdd"),
    ]

    result = collect_vcs_log(
        repos, limit=20, provider_factory=lambda path: providers[path]
    )

    # The failing repo becomes a warning; it is not in the read repo set.
    assert [r.name for r in result.repos] == ["sase", "sase-core"]
    assert result.warnings == ("sase-bad: no such checkout",)
    # Merged, newest-first across repos.
    assert [(c.repo, c.commit.full_id) for c in result.commits] == [
        ("sase", "a"),
        ("sase-core", "c"),
        ("sase", "b"),
    ]
    assert result.remote_states == (
        collect_module.RepoRemoteState("sase", None, 0, 0, False),
        collect_module.RepoRemoteState("sase-core", None, 0, 0, False),
    )


def test_collect_empty_repo_set_returns_empty() -> None:
    result = collect_vcs_log([], limit=20, provider_factory=lambda path: None)
    assert result.repos == ()
    assert result.commits == ()
    assert result.warnings == ()


def test_collect_fetches_limit_per_repo() -> None:
    seen: dict[str, int] = {}

    class _Recorder:
        def __init__(self, path: str) -> None:
            self.path = path

        def log(
            self,
            cwd: str,
            limit: int,
            *,
            since: int | None = None,
            until: int | None = None,
            authors: tuple[str, ...] = (),
        ) -> list[VcsCommitWire]:
            del cwd, since, until, authors
            seen[self.path] = limit
            return [_commit("x", 1)]

    repos = [LogRepo("a", "/a", "primary"), LogRepo("b", "/b", "linked")]
    collect_vcs_log(repos, limit=7, provider_factory=_Recorder)
    assert seen == {"/a": 7, "/b": 7}


def test_collect_threads_filters_and_unlimited_sentinel() -> None:
    seen: dict[str, object] = {}

    class _Recorder:
        def __init__(self, path: str) -> None:
            self.path = path

        def log(
            self,
            cwd: str,
            limit: int,
            *,
            since: int | None = None,
            until: int | None = None,
            authors: tuple[str, ...] = (),
        ) -> list[VcsCommitWire]:
            seen["cwd"] = cwd
            seen["limit"] = limit
            seen["since"] = since
            seen["until"] = until
            seen["authors"] = authors
            return [_commit("x", 1)]

    repos = [LogRepo("a", "/a", "primary")]
    collect_vcs_log(
        repos,
        limit=0,
        filters=CommitFilters(since=10, until=20, authors=("bryan", "amy")),
        provider_factory=_Recorder,
    )

    assert seen == {
        "cwd": "/a",
        "limit": UNLIMITED,
        "since": 10,
        "until": 20,
        "authors": ("bryan", "amy"),
    }


def test_collect_classifies_remote_presence_and_records_state() -> None:
    provider = _RemoteProvider(
        [_commit("synced", 300), _commit("ahead", 200), _commit("behind", 100)],
        ahead={"ahead"},
        behind={"behind"},
    )
    repos = [LogRepo("sase", "/a", "primary")]

    result = collect_vcs_log(repos, limit=20, provider_factory=lambda path: provider)

    assert provider.fetch_calls == [("origin/main",)]
    assert provider.log_revs == ("HEAD", "origin/main")
    assert result.remote_states == (
        collect_module.RepoRemoteState("sase", "origin/main", 1, 1, True),
    )
    assert [entry.commit.presence for entry in result.commits] == [
        "synced",
        "local_only",
        "remote_only",
    ]


def test_collect_no_fetch_uses_existing_remote_ref() -> None:
    provider = _RemoteProvider([_commit("synced", 300)])
    repos = [LogRepo("sase", "/a", "primary")]

    result = collect_vcs_log(
        repos,
        limit=20,
        no_fetch=True,
        remote_ref="main",
        provider_factory=lambda path: provider,
    )

    assert provider.fetch_calls == []
    assert provider.log_revs == ("HEAD", "origin/main")
    assert result.remote_states == (
        collect_module.RepoRemoteState("sase", "origin/main", 0, 0, False),
    )


def test_collect_fetch_failure_warns_but_uses_existing_ref() -> None:
    provider = _RemoteProvider([_commit("synced", 300)], fetch_ok=False)
    repos = [LogRepo("sase", "/a", "primary")]

    result = collect_vcs_log(repos, limit=20, provider_factory=lambda path: provider)

    assert result.remote_states == (
        collect_module.RepoRemoteState("sase", "origin/main", 0, 0, False),
    )
    assert result.warnings == (
        "sase: fetch failed for origin/main: network down; using existing remote ref",
    )


def test_run_merges_resolution_warnings_ahead_of_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_resolve(*, cwd, repo_filters=(), current_only=False):  # type: ignore[no-untyped-def]
        return ResolvedRepos(
            repos=[LogRepo("sase", "/p/sase", "primary")],
            warnings=["resolve-warning"],
        )

    monkeypatch.setattr(collect_module, "resolve_log_repos", fake_resolve)

    providers = {"/p/sase": _FailProvider()}
    result = run_vcs_log(
        cwd="/anywhere",
        limit=10,
        provider_factory=lambda path: providers[path],
    )

    # Resolution warning first, then the collection warning.
    assert result.warnings == (
        "resolve-warning",
        "sase: no such checkout",
    )
    assert result.commits == ()
