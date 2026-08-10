"""Tests for repository resolution in the ``sase stitch log`` runner."""

from __future__ import annotations

import pytest

from tests._vcs_log_collect_helpers import FailProvider, FakeProvider, commit

from sase.vcs_log import collect as collect_module
from sase.vcs_log.collect import run_vcs_log
from sase.vcs_log.models import LogRepo
from sase.vcs_log.resolve import ResolvedRepos


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

    providers = {"/p/sase": FailProvider()}
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
    provider = FakeProvider([commit("a", 300), commit("b", 200), commit("c", 100)])

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

    def provider(path: str) -> FakeProvider:
        provider_paths.append(path)
        return FakeProvider([commit("a", 2), commit("b", 1)])

    result = run_vcs_log(
        cwd="/workspace",
        limit=1,
        exclude_repo_filters=("plans",),
        provider_factory=provider,
    )

    assert resolve_calls == [("plans",)]
    assert provider_paths == ["/p/sase"]
    assert [entry.commit.full_id for entry in result.commits] == ["a"]
