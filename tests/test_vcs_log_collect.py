"""Tests for core ``sase vcs log`` collection behavior."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from tests._vcs_log_collect_helpers import (
    FakeProvider as _FakeProvider,
    FailProvider as _FailProvider,
    LocalOnlyProvider as _LocalOnlyProvider,
    RemoteProvider as _RemoteProvider,
    commit as _commit,
)

from sase.core.vcs_log_wire import VcsCommitWire
from sase.vcs_log import collect as collect_module
from sase.vcs_log.collect import collect_vcs_log
from sase.vcs_log.dates import parse_time_bound
from sase.vcs_log.models import CommitFilterSpec, CommitFilters, LogRepo, UNLIMITED


def test_collect_isolates_failing_repo_and_interleaves() -> None:
    providers = {
        "/p/sase": _FakeProvider([_commit("a", 300, "recent"), _commit("b", 100)]),
        "/p/core": _FakeProvider([_commit("c", 200)]),
        "/p/bad": _FailProvider(),
    }
    repos = [
        LogRepo("sase", "/p/sase", "primary"),
        LogRepo("sase-core", "/p/core", "linked"),
        LogRepo("sase-bad", "/p/bad", "sidecar"),
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


def test_collect_applies_merged_limit_across_global_catalog() -> None:
    providers = {
        "/a": _FakeProvider([_commit("a3", 300), _commit("a1", 100)]),
        "/b": _FakeProvider([_commit("b4", 400), _commit("b2", 200)]),
        "/c": _FakeProvider([_commit("c5", 500)]),
    }

    result = collect_vcs_log(
        [
            LogRepo("a", "/a", "primary"),
            LogRepo("b", "/b", "primary"),
            LogRepo("c", "/c", "linked"),
        ],
        limit=2,
        provider_factory=lambda path: providers[path],
    )

    assert [(entry.repo, entry.commit.full_id) for entry in result.commits] == [
        ("c", "c5"),
        ("b", "b4"),
    ]


def test_collect_marks_aggregate_only_truncation_across_repos() -> None:
    providers = {
        "/a": _FakeProvider([_commit("a4", 400), _commit("a2", 200)]),
        "/b": _FakeProvider([_commit("b3", 300), _commit("b1", 100)]),
    }

    result = collect_vcs_log(
        [LogRepo("a", "/a", "primary"), LogRepo("b", "/b", "linked")],
        limit=3,
        provider_factory=lambda path: providers[path],
    )

    assert len(result.commits) == 3
    assert result.aggregate_truncated is True
    assert result.provider_truncation_possible is False
    assert result.potentially_truncated is True


def test_collect_marks_exact_per_repo_cap_as_possible_truncation() -> None:
    result = collect_vcs_log(
        [LogRepo("a", "/a", "primary")],
        limit=3,
        provider_factory=lambda _path: _FakeProvider(
            [_commit("a3", 300), _commit("a2", 200), _commit("a1", 100)]
        ),
    )

    assert len(result.commits) == 3
    assert result.aggregate_truncated is False
    assert result.provider_truncation_possible is True
    assert result.potentially_truncated is True


def test_collect_marks_combined_aggregate_and_provider_truncation() -> None:
    providers = {
        "/a": _FakeProvider(
            [_commit("a4", 400), _commit("a3", 300), _commit("a2", 200)]
        ),
        "/b": _FakeProvider([_commit("b1", 100)]),
    }

    result = collect_vcs_log(
        [LogRepo("a", "/a", "primary"), LogRepo("b", "/b", "linked")],
        limit=3,
        provider_factory=lambda path: providers[path],
    )

    assert len(result.commits) == 3
    assert result.aggregate_truncated is True
    assert result.provider_truncation_possible is True


def test_collect_unlimited_never_marks_cap_truncation() -> None:
    commits = [_commit(str(index), index) for index in range(6)]

    result = collect_vcs_log(
        [LogRepo("a", "/a", "primary")],
        limit=0,
        filters=CommitFilters(until=100),
        provider_factory=lambda _path: _FakeProvider(commits),
    )

    assert len(result.commits) == len(commits)
    assert result.aggregate_truncated is False
    assert result.provider_truncation_possible is False
    assert result.potentially_truncated is False


def test_collect_doubles_bounded_until_candidate_limit() -> None:
    provider = _RemoteProvider([_commit(str(index), index) for index in range(10)])

    result = collect_vcs_log(
        [LogRepo("a", "/a", "primary")],
        limit=3,
        filters=CommitFilters(until=100),
        no_fetch=True,
        provider_factory=lambda _path: provider,
    )

    assert provider.log_limit == 6
    assert len(result.commits) == 6
    assert result.aggregate_truncated is False
    assert result.provider_truncation_possible is True


def test_collect_resolves_relative_bounds_once_against_operation_time(
    tmp_path: Path,
) -> None:
    from sase.core.time import get_timezone

    reference = datetime(2026, 7, 21, 15, 30, tzinfo=get_timezone())
    provider = _RemoteProvider([_commit("inside", int(reference.timestamp()))])
    filter_spec = CommitFilterSpec(
        since=parse_time_bound("2h"),
        until=parse_time_bound("today"),
        authors=("bryan",),
    )

    result = collect_vcs_log(
        [LogRepo("a", "/a", "primary")],
        limit=3,
        filter_spec=filter_spec,
        now=reference,
        fetch_cache_path=tmp_path / "fetch-cache.json",
        provider_factory=lambda _path: provider,
    )

    expected = filter_spec.resolve(now=reference)
    assert provider.log_filters == expected
    assert result.resolved_filters == expected
    assert result.filter_spec == filter_spec
    assert result.remote_states[0].fetched_at == reference.timestamp()
    assert expected.since == int((reference - timedelta(hours=2)).timestamp())
    assert expected.until is not None


def test_collect_unsupported_remote_comparison_uses_local_log() -> None:
    provider = _LocalOnlyProvider([_commit("local", 100)])

    result = collect_vcs_log(
        [LogRepo("local-vcs", "/local", "primary")],
        limit=20,
        provider_factory=lambda path: provider,
    )

    assert result.warnings == ()
    assert [entry.commit.presence for entry in result.commits] == ["unknown"]
    assert result.remote_states == (
        collect_module.RepoRemoteState("local-vcs", None, 0, 0, False),
    )


def test_collect_missing_log_hook_is_actionable_and_isolated() -> None:
    providers = {
        "/good": _FakeProvider([_commit("good", 100)]),
        "/bad": object(),
    }

    result = collect_vcs_log(
        [
            LogRepo("good", "/good", "primary"),
            LogRepo("bad", "/bad", "linked"),
        ],
        limit=20,
        provider_factory=lambda path: providers[path],
    )

    assert [repo.name for repo in result.repos] == ["good"]
    assert result.warnings == ("bad: log is not supported by this VCS provider",)


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
