"""Tests for remote state and fetch caching during VCS log collection."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from tests._vcs_log_collect_helpers import RemoteProvider, commit

from sase.vcs_log import collect as collect_module
from sase.vcs_log.collect import collect_vcs_log
from sase.vcs_log.fetch_cache import _read_fetch_cache, record_successful_fetch
from sase.vcs_log.models import LogRepo


def test_collect_classifies_remote_presence_and_records_state(tmp_path: Path) -> None:
    provider = RemoteProvider(
        [commit("synced", 300), commit("ahead", 200), commit("behind", 100)],
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
        "/cached": RemoteProvider([commit("cached", 300)]),
        "/fresh": RemoteProvider([commit("fresh", 200)]),
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
    provider = RemoteProvider([commit("synced", 300)])
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
    provider = RemoteProvider([commit("synced", 300)], fetch_ok=False)
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
    first = RemoteProvider([commit("synced", 300)])
    second = RemoteProvider([commit("synced", 300)])

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
    first = RemoteProvider([commit("synced", 300)])
    second = RemoteProvider([commit("synced", 300)])

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
    provider = RemoteProvider([commit("synced", 300)])

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
    provider = RemoteProvider([commit("synced", 300)])

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
        "/a": RemoteProvider([commit("a", 300)], remote_ref="origin/main"),
        "/b": RemoteProvider([commit("b", 300)], remote_ref="origin/main"),
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

    ref_provider = RemoteProvider([commit("dev", 300)], remote_ref="origin/main")
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
    provider = RemoteProvider([commit("synced", 300)], fetch_ok=False)

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
    provider = RemoteProvider([commit("synced", 300)])

    collect_vcs_log(
        [LogRepo("sase", "/a", "primary")],
        limit=20,
        now=1000.0,
        fetch_cache_path=cache_path,
        provider_factory=lambda path: provider,
    )

    assert provider.fetch_calls == [("origin/main",)]
    assert _read_fetch_cache(cache_path) != {}
