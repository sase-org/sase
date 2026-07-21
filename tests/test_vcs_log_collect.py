"""Tests for the ``sase vcs log`` collection service (failure isolation)."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from sase.core.vcs_log_wire import VcsCommitWire
from sase.vcs_log import collect as collect_module
from sase.vcs_log.collect import collect_vcs_log, run_vcs_log
from sase.vcs_log.dates import parse_time_bound
from sase.vcs_log.fetch_cache import _read_fetch_cache, record_successful_fetch
from sase.vcs_log.models import CommitFilterSpec, CommitFilters, LogRepo, UNLIMITED
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
        self.log_limit: int | None = None
        self.log_filters: CommitFilters | None = None

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
        del cwd
        self.log_revs = revs
        self.log_limit = limit
        self.log_filters = CommitFilters(since, until, authors)
        return self._commits if limit < 0 else self._commits[:limit]


class _LocalOnlyProvider(_FakeProvider):
    def resolve_remote_log_ref(
        self, cwd: str, ref_name: str | None = None
    ) -> str | None:
        del cwd, ref_name
        raise NotImplementedError(
            "resolve_remote_log_ref is not supported by this VCS provider"
        )


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


def test_collect_classifies_remote_presence_and_records_state(tmp_path: Path) -> None:
    provider = _RemoteProvider(
        [_commit("synced", 300), _commit("ahead", 200), _commit("behind", 100)],
        ahead={"ahead"},
        behind={"behind"},
    )
    repos = [LogRepo("sase", "/a", "primary")]
    cache_path = tmp_path / "fetch-cache.json"

    result = collect_vcs_log(
        repos,
        limit=20,
        now=1000.0,
        fetch_cache_path=cache_path,
        provider_factory=lambda path: provider,
    )

    assert provider.fetch_calls == [("origin/main",)]
    assert provider.log_revs == ("HEAD", "origin/main")
    assert result.remote_states == (
        collect_module.RepoRemoteState("sase", "origin/main", 1, 1, True, 1000.0),
    )
    assert [entry.commit.presence for entry in result.commits] == [
        "synced",
        "local_only",
        "remote_only",
    ]


def test_collect_wraps_only_actual_fetches_in_progress(tmp_path: Path) -> None:
    cache_path = tmp_path / "fetch-cache.json"
    assert record_successful_fetch(
        "/cached", "origin/main", fetched_at=1000.0, cache_path=cache_path
    )
    providers = {
        "/cached": _RemoteProvider([_commit("cached", 300)]),
        "/fresh": _RemoteProvider([_commit("fresh", 200)]),
    }
    events: list[str] = []

    @contextmanager
    def progress(repo: LogRepo, remote_ref: str) -> Iterator[None]:
        events.append(f"start:{repo.name}:{remote_ref}")
        yield
        events.append(f"done:{repo.name}:{remote_ref}")

    result = collect_vcs_log(
        [
            LogRepo("cached", "/cached", "primary"),
            LogRepo("fresh", "/fresh", "linked"),
        ],
        limit=20,
        now=1010.0,
        fetch_cache_path=cache_path,
        provider_factory=lambda path: providers[path],
        fetch_progress=progress,
    )

    assert result.warnings == ()
    assert providers["/cached"].fetch_calls == []
    assert providers["/fresh"].fetch_calls == [("origin/main",)]
    assert events == [
        "start:fresh:origin/main",
        "done:fresh:origin/main",
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


def test_collect_fetch_failure_warns_but_uses_existing_ref(tmp_path: Path) -> None:
    provider = _RemoteProvider([_commit("synced", 300)], fetch_ok=False)
    repos = [LogRepo("sase", "/a", "primary")]

    result = collect_vcs_log(
        repos,
        limit=20,
        now=1000.0,
        fetch_cache_path=tmp_path / "fetch-cache.json",
        provider_factory=lambda path: provider,
    )

    assert result.remote_states == (
        collect_module.RepoRemoteState("sase", "origin/main", 0, 0, False),
    )
    assert result.warnings == (
        "sase: fetch failed for origin/main: network down; using existing remote ref",
    )


def test_collect_fetch_cache_skips_second_run_within_ttl(tmp_path: Path) -> None:
    cache_path = tmp_path / "fetch-cache.json"
    repos = [LogRepo("sase", "/a", "primary")]
    first = _RemoteProvider([_commit("synced", 300)])
    second = _RemoteProvider([_commit("synced", 300)])

    collect_vcs_log(
        repos,
        limit=20,
        now=1000.0,
        fetch_cache_path=cache_path,
        provider_factory=lambda path: first,
    )
    result = collect_vcs_log(
        repos,
        limit=20,
        now=1059.0,
        fetch_cache_path=cache_path,
        provider_factory=lambda path: second,
    )

    assert first.fetch_calls == [("origin/main",)]
    assert second.fetch_calls == []
    assert result.remote_states == (
        collect_module.RepoRemoteState("sase", "origin/main", 0, 0, False, 1000.0),
    )


def test_collect_fetch_cache_expires_at_ttl_boundary(tmp_path: Path) -> None:
    cache_path = tmp_path / "fetch-cache.json"
    repos = [LogRepo("sase", "/a", "primary")]
    first = _RemoteProvider([_commit("synced", 300)])
    second = _RemoteProvider([_commit("synced", 300)])

    collect_vcs_log(
        repos,
        limit=20,
        now=1000.0,
        fetch_cache_path=cache_path,
        provider_factory=lambda path: first,
    )
    result = collect_vcs_log(
        repos,
        limit=20,
        now=1060.0,
        fetch_cache_path=cache_path,
        provider_factory=lambda path: second,
    )

    assert second.fetch_calls == [("origin/main",)]
    assert result.remote_states == (
        collect_module.RepoRemoteState("sase", "origin/main", 0, 0, True, 1060.0),
    )


def test_collect_force_fetch_bypasses_fresh_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "fetch-cache.json"
    repos = [LogRepo("sase", "/a", "primary")]
    assert record_successful_fetch(
        "/a", "origin/main", fetched_at=1000.0, cache_path=cache_path
    )
    provider = _RemoteProvider([_commit("synced", 300)])

    result = collect_vcs_log(
        repos,
        limit=20,
        force_fetch=True,
        now=1010.0,
        fetch_cache_path=cache_path,
        provider_factory=lambda path: provider,
    )

    assert provider.fetch_calls == [("origin/main",)]
    assert result.remote_states == (
        collect_module.RepoRemoteState("sase", "origin/main", 0, 0, True, 1010.0),
    )


def test_collect_no_fetch_never_records_fetch_cache(tmp_path: Path) -> None:
    cache_path = tmp_path / "fetch-cache.json"
    provider = _RemoteProvider([_commit("synced", 300)])

    collect_vcs_log(
        [LogRepo("sase", "/a", "primary")],
        limit=20,
        no_fetch=True,
        now=1000.0,
        fetch_cache_path=cache_path,
        provider_factory=lambda path: provider,
    )

    assert provider.fetch_calls == []
    assert _read_fetch_cache(cache_path) == {}


def test_collect_fetch_cache_keys_repo_paths_and_refs_independently(
    tmp_path: Path,
) -> None:
    cache_path = tmp_path / "fetch-cache.json"
    assert record_successful_fetch(
        "/a", "origin/main", fetched_at=1000.0, cache_path=cache_path
    )
    providers = {
        "/a": _RemoteProvider([_commit("a", 300)], remote_ref="origin/main"),
        "/b": _RemoteProvider([_commit("b", 300)], remote_ref="origin/main"),
    }

    result = collect_vcs_log(
        [LogRepo("a", "/a", "primary"), LogRepo("b", "/b", "linked")],
        limit=20,
        now=1010.0,
        fetch_cache_path=cache_path,
        provider_factory=lambda path: providers[path],
    )

    assert providers["/a"].fetch_calls == []
    assert providers["/b"].fetch_calls == [("origin/main",)]
    assert result.remote_states == (
        collect_module.RepoRemoteState("a", "origin/main", 0, 0, False, 1000.0),
        collect_module.RepoRemoteState("b", "origin/main", 0, 0, True, 1010.0),
    )

    ref_provider = _RemoteProvider([_commit("dev", 300)], remote_ref="origin/main")
    collect_vcs_log(
        [LogRepo("a", "/a", "primary")],
        limit=20,
        remote_ref="dev",
        now=1020.0,
        fetch_cache_path=cache_path,
        provider_factory=lambda path: ref_provider,
    )
    assert ref_provider.fetch_calls == [("origin/dev",)]


def test_collect_failed_fetch_is_not_recorded(tmp_path: Path) -> None:
    cache_path = tmp_path / "fetch-cache.json"
    provider = _RemoteProvider([_commit("synced", 300)], fetch_ok=False)

    collect_vcs_log(
        [LogRepo("sase", "/a", "primary")],
        limit=20,
        now=1000.0,
        fetch_cache_path=cache_path,
        provider_factory=lambda path: provider,
    )

    assert provider.fetch_calls == [("origin/main",)]
    assert _read_fetch_cache(cache_path) == {}


def test_collect_corrupt_fetch_cache_is_ignored(tmp_path: Path) -> None:
    cache_path = tmp_path / "fetch-cache.json"
    cache_path.write_text("{nope", encoding="utf-8")
    provider = _RemoteProvider([_commit("synced", 300)])

    collect_vcs_log(
        [LogRepo("sase", "/a", "primary")],
        limit=20,
        now=1000.0,
        fetch_cache_path=cache_path,
        provider_factory=lambda path: provider,
    )

    assert provider.fetch_calls == [("origin/main",)]
    assert _read_fetch_cache(cache_path) != {}


def test_run_merges_resolution_warnings_ahead_of_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scopes: list[tuple[bool, bool]] = []

    def fake_resolve(  # type: ignore[no-untyped-def]
        *,
        cwd,
        repo_filters=(),
        all_projects=False,
        current_only=False,
        include_sidecars=False,
    ):
        scopes.append((all_projects, include_sidecars))
        return ResolvedRepos(
            repos=[LogRepo("sase", "/p/sase", "primary")],
            warnings=["resolve-warning"],
        )

    monkeypatch.setattr(collect_module, "resolve_log_repos", fake_resolve)

    providers = {"/p/sase": _FailProvider()}
    result = run_vcs_log(
        cwd="/anywhere",
        limit=10,
        all_projects=True,
        provider_factory=lambda path: providers[path],
    )
    run_vcs_log(
        cwd="/anywhere",
        limit=10,
        include_sidecars=True,
        provider_factory=lambda path: providers[path],
    )

    # Resolution warning first, then the collection warning.
    assert scopes == [(True, False), (False, True)]
    assert result.warnings == (
        "resolve-warning",
        "sase: no such checkout",
    )
    assert result.commits == ()


def test_run_preserves_collection_truncation_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_resolve(  # type: ignore[no-untyped-def]
        *,
        cwd,
        repo_filters=(),
        all_projects=False,
        current_only=False,
        include_sidecars=False,
    ):
        del cwd, repo_filters, all_projects, current_only, include_sidecars
        return ResolvedRepos(
            repos=[LogRepo("sase", "/p/sase", "primary")],
            warnings=["resolve-warning"],
        )

    monkeypatch.setattr(collect_module, "resolve_log_repos", fake_resolve)
    provider = _FakeProvider([_commit("a", 300), _commit("b", 200), _commit("c", 100)])

    result = run_vcs_log(
        cwd="/workspace",
        limit=3,
        provider_factory=lambda _path: provider,
    )

    assert result.warnings == ("resolve-warning",)
    assert result.aggregate_truncated is False
    assert result.provider_truncation_possible is True
    assert result.potentially_truncated is True


def test_run_threads_repo_exclusions_before_provider_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_calls: list[tuple[str, ...]] = []
    provider_paths: list[str] = []

    def fake_resolve(  # type: ignore[no-untyped-def]
        *,
        cwd,
        repo_filters=(),
        exclude_repo_filters=(),
        all_projects=False,
        project_scope=None,
        current_only=False,
        include_sidecars=False,
    ):
        del (
            cwd,
            repo_filters,
            all_projects,
            project_scope,
            current_only,
            include_sidecars,
        )
        resolve_calls.append(tuple(exclude_repo_filters))
        return ResolvedRepos(
            repos=[LogRepo("sase", "/p/sase", "primary")],
            warnings=[],
        )

    monkeypatch.setattr(collect_module, "resolve_log_repos", fake_resolve)

    def provider(path: str) -> _FakeProvider:
        provider_paths.append(path)
        return _FakeProvider([_commit("a", 2), _commit("b", 1)])

    result = run_vcs_log(
        cwd="/workspace",
        limit=1,
        exclude_repo_filters=("plans",),
        provider_factory=provider,
    )

    assert resolve_calls == [("plans",)]
    assert provider_paths == ["/p/sase"]
    assert [entry.commit.full_id for entry in result.commits] == ["a"]
