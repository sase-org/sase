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
