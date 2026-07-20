"""Tests for the ``sase vcs list`` collection service."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.core.vcs_log_wire import VcsCommitWire
from sase.core.vcs_repo_stats_wire import VcsRepoStatsWire
from sase.vcs_list import collect as collect_module
from sase.vcs_list.collect import _collect_vcs_list, run_vcs_list
from sase.vcs_log.models import LogRepo
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


def _stats(
    total: int,
    ts: int | None,
    *,
    contributors: tuple[str, ...] = ("Bryan <b@x>",),
    branch: str | None = "main",
    dirty: bool = False,
) -> VcsRepoStatsWire:
    return VcsRepoStatsWire(
        total_commits=total,
        contributors=contributors,
        last_commit=_commit(str(ts), ts) if ts is not None else None,
        branch=branch,
        dirty=dirty,
    )


class _FakeProvider:
    def __init__(self, stats: VcsRepoStatsWire) -> None:
        self._stats = stats

    def repo_stats(self, cwd: str) -> VcsRepoStatsWire:
        del cwd
        return self._stats


class _FailProvider:
    def repo_stats(self, cwd: str) -> VcsRepoStatsWire:
        del cwd
        raise RuntimeError("no such checkout")


def test_collect_keeps_failing_repo_listed_and_totals_successful_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        collect_module,
        "_linked_config_descriptions",
        lambda primary_dir: {"sase-core": "Core backend"},
    )
    repos = [
        LogRepo("sase", "/p/sase", "primary"),
        LogRepo("sase-core", "/p/core", "linked"),
        LogRepo("sase-bad", "/p/bad", "linked"),
    ]
    providers = {
        "/p/sase": _FakeProvider(_stats(10, 300, contributors=("Bryan <b@x>",))),
        "/p/core": _FakeProvider(_stats(4, 200, contributors=("Amy <a@x>",))),
        "/p/bad": _FailProvider(),
    }

    result = _collect_vcs_list(
        repos,
        provider_factory=lambda path: providers[path],
    )

    assert [listing.repo.name for listing in result.repos] == [
        "sase",
        "sase-core",
        "sase-bad",
    ]
    assert result.repos[1].description == "Core backend"
    assert result.repos[1].description_source == "config"
    assert result.repos[2].stats is None
    assert result.repos[2].error == "no such checkout"
    assert result.warnings == ("sase-bad: no such checkout",)
    assert result.totals.repo_count == 3
    assert result.totals.total_commits == 14
    assert result.totals.contributors == ("Amy <a@x>", "Bryan <b@x>")
    assert result.totals.latest_activity == 300
    assert result.color_repos == tuple(repos)


def test_collect_sort_modes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collect_module, "_linked_config_descriptions", lambda _: {})
    repos = [
        LogRepo("zeta", "/z", "primary"),
        LogRepo("alpha", "/a", "linked"),
        LogRepo("middle", "/m", "linked"),
    ]
    providers = {
        "/z": _FakeProvider(_stats(1, 100)),
        "/a": _FakeProvider(_stats(9, 50)),
        "/m": _FakeProvider(_stats(3, 900)),
    }

    by_name = _collect_vcs_list(
        repos, sort="name", provider_factory=lambda path: providers[path]
    )
    by_commits = _collect_vcs_list(
        repos, sort="commits", provider_factory=lambda path: providers[path]
    )
    by_recent = _collect_vcs_list(
        repos, sort="recent", provider_factory=lambda path: providers[path]
    )

    assert [listing.repo.name for listing in by_name.repos] == [
        "alpha",
        "middle",
        "zeta",
    ]
    assert [listing.repo.name for listing in by_commits.repos] == [
        "alpha",
        "middle",
        "zeta",
    ]
    assert [listing.repo.name for listing in by_recent.repos] == [
        "middle",
        "zeta",
        "alpha",
    ]
    assert by_recent.color_repos == tuple(repos)


def test_run_merges_resolution_warnings_ahead_of_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(collect_module, "_linked_config_descriptions", lambda _: {})
    include_sidecars_values: list[bool] = []

    def fake_resolve(  # type: ignore[no-untyped-def]
        *, cwd, repo_filters=(), current_only=False, include_sidecars=False
    ):
        include_sidecars_values.append(include_sidecars)
        return ResolvedRepos(
            repos=[LogRepo("sase", "/p/sase", "primary")],
            warnings=["resolve-warning"],
        )

    monkeypatch.setattr(collect_module, "resolve_log_repos", fake_resolve)
    result = run_vcs_list(
        cwd="/anywhere",
        provider_factory=lambda path: _FailProvider(),
    )

    assert result.warnings == ("resolve-warning", "sase: no such checkout")
    assert [listing.repo.name for listing in result.repos] == ["sase"]
    assert include_sidecars_values == [True]


def test_run_skips_stale_sdd_clone_without_materialized_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import sase.main.utils as main_utils
    import sase.sdd as sdd_module
    import sase.vcs_log.resolve as resolve_module
    import sase.workspace_provider.utils as workspace_utils

    primary = tmp_path / "repo"
    stale_sdd = primary / ".sase" / "sdd"
    stale_sdd.mkdir(parents=True)
    monkeypatch.setattr(
        main_utils,
        "ensure_project_file_and_get_workspace_num",
        lambda *, create_missing=False: (str(tmp_path / "repo.sase"), 0, "repo"),
    )
    monkeypatch.setattr(
        workspace_utils, "parse_workspace_dir", lambda project_file: str(primary)
    )
    monkeypatch.setattr(resolve_module, "project_display_name_for", lambda key: key)
    monkeypatch.setattr(
        resolve_module,
        "_resolve_linked_repos",
        lambda project_file, primary_dir, warnings, *, include_sidecars: [],
    )
    monkeypatch.setattr(sdd_module, "materialized_sdd_clone", lambda primary: None)
    monkeypatch.setattr(collect_module, "_linked_config_descriptions", lambda _: {})

    result = run_vcs_list(
        cwd=str(primary),
        provider_factory=lambda path: _FakeProvider(_stats(3, 100)),
    )

    assert stale_sdd.is_dir()
    assert [(listing.repo.name, listing.repo.kind) for listing in result.repos] == [
        ("repo", "primary")
    ]
    assert result.warnings == ()
