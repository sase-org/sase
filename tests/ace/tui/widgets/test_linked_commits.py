"""Tests for linked-repository commit computation."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.tui.models.agent import Agent, AgentType, LinkedRepoMetadata
from sase.ace.tui.widgets.file_panel import _linked_commits as linked_commits_mod


class _FakeLinkedCommitProvider:
    def __init__(self, rows_by_workspace: dict[str, str | None]) -> None:
        self.rows_by_workspace = rows_by_workspace
        self.default_parent_calls: list[str] = []
        self.list_commits_calls: list[tuple[str, str, str]] = []

    def get_default_parent_revision(self, cwd: str) -> str:
        self.default_parent_calls.append(cwd)
        return "origin/main"

    def list_commits(
        self, base_ref: str, head_ref: str, cwd: str
    ) -> tuple[bool, str | None]:
        self.list_commits_calls.append((base_ref, head_ref, cwd))
        return (True, self.rows_by_workspace.get(cwd))


@pytest.fixture(autouse=True)
def _clear_linked_commit_caches() -> None:
    linked_commits_mod._linked_commit_cache.clear()
    linked_commits_mod._selected_agent_linked_commit_cache.clear()
    linked_commits_mod._selected_agent_cache_monotonic.clear()


def _agent(
    *,
    status: str = "RUNNING",
    linked_repos: tuple[LinkedRepoMetadata, ...] = (),
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="linked-commits",
        project_file="/tmp/linked-commits.sase",
        status=status,
        start_time=datetime(2026, 6, 20, 12, 0),
        raw_suffix="20260620120000",
        linked_repos=linked_repos,
    )


def _repo(
    name: str,
    workspace_dir: Path,
    *,
    strategy: str = "suffix",
) -> LinkedRepoMetadata:
    return LinkedRepoMetadata(
        name=name,
        workspace_dir=str(workspace_dir),
        workspace_strategy=strategy,
    )


def _patch_provider(
    monkeypatch: pytest.MonkeyPatch,
    provider: _FakeLinkedCommitProvider,
    *,
    wall_time: float = 1_700_000_000.0,
    monotonic: float = 50.0,
) -> None:
    monkeypatch.setattr(
        linked_commits_mod,
        "resolve_vcs_provider_for_live_diff",
        lambda _workspace_dir: provider,
    )
    monkeypatch.setattr(
        linked_commits_mod,
        "git_index_signature_for_live_diff",
        lambda _workspace_dir: None,
    )
    monkeypatch.setattr(linked_commits_mod.time, "time", lambda: wall_time)
    monkeypatch.setattr(linked_commits_mod.time, "monotonic", lambda: monotonic)


def test_compute_linked_commit_groups_filters_dedupes_and_parses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = tmp_path / "sase-core"
    github = tmp_path / "sase-github"
    clean = tmp_path / "clean"
    static = tmp_path / "static"
    for path in (core, github, clean, static):
        path.mkdir()
    missing = tmp_path / "missing"
    provider = _FakeLinkedCommitProvider(
        {
            str(core): "a1b2c3d\x1ffeat: add core API\n9f8e7d6\x1ffix: cache\n",
            str(github): "4c3b2a1\x1ftest: cover linked commits\n",
            str(clean): None,
        }
    )
    _patch_provider(monkeypatch, provider)
    agent = _agent(
        linked_repos=(
            _repo("sase-core", core),
            _repo("sase-static", static, strategy="none"),
            _repo("sase-missing", missing),
            _repo("sase-clean", clean),
            _repo("sase-core", core),
            _repo("sase-github", github),
        )
    )

    groups = linked_commits_mod.compute_linked_commit_groups(agent)

    assert [group.repo_name for group in groups] == ["sase-core", "sase-github"]
    assert groups[0].commits == (
        linked_commits_mod.CommitInfo("a1b2c3d", "feat: add core API"),
        linked_commits_mod.CommitInfo("9f8e7d6", "fix: cache"),
    )
    assert groups[0].fetched_at is not None
    assert groups[1].commits == (
        linked_commits_mod.CommitInfo("4c3b2a1", "test: cover linked commits"),
    )
    assert provider.default_parent_calls == [str(core), str(clean), str(github)]
    assert provider.list_commits_calls == [
        ("origin/main", "HEAD", str(core)),
        ("origin/main", "HEAD", str(clean)),
        ("origin/main", "HEAD", str(github)),
    ]
    assert linked_commits_mod.get_cached_linked_commit_groups(agent) == groups


def test_compute_linked_commit_groups_allows_terminal_agents(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = tmp_path / "sase-core"
    core.mkdir()
    provider = _FakeLinkedCommitProvider({str(core): "a1b2c3d\x1ffeat: done work\n"})
    _patch_provider(monkeypatch, provider)
    agent = _agent(status="DONE", linked_repos=(_repo("sase-core", core),))

    groups = linked_commits_mod.compute_linked_commit_groups(agent)

    assert [group.repo_name for group in groups] == ["sase-core"]
    assert groups[0].commits == (
        linked_commits_mod.CommitInfo("a1b2c3d", "feat: done work"),
    )


def test_get_cached_linked_commit_groups_is_zero_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = tmp_path / "sase-core"
    core.mkdir()
    agent = _agent(linked_repos=(_repo("sase-core", core),))
    cached = (
        linked_commits_mod.LinkedCommitGroup(
            repo_name="sase-core",
            workspace_dir=str(core),
            commits=(linked_commits_mod.CommitInfo("abc1234", "feat: cached"),),
        ),
    )
    linked_commits_mod._selected_agent_linked_commit_cache[agent.identity] = cached

    def fail_provider(_workspace_dir: str) -> object:
        raise AssertionError("cache read resolved a provider")

    monkeypatch.setattr(
        linked_commits_mod,
        "resolve_vcs_provider_for_live_diff",
        fail_provider,
    )

    assert linked_commits_mod.get_cached_linked_commit_groups(agent) == cached


def test_empty_range_caches_no_group(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = tmp_path / "sase-core"
    core.mkdir()
    provider = _FakeLinkedCommitProvider({str(core): ""})
    _patch_provider(monkeypatch, provider)
    agent = _agent(linked_repos=(_repo("sase-core", core),))

    assert linked_commits_mod.compute_linked_commit_groups(agent) == ()
    assert linked_commits_mod.get_cached_linked_commit_groups(agent) == ()


def test_should_refresh_linked_commit_groups_is_memory_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = tmp_path / "sase-core"
    core.mkdir()
    agent = _agent(linked_repos=(_repo("sase-core", core),))
    provider = _FakeLinkedCommitProvider({str(core): None})
    _patch_provider(monkeypatch, provider, monotonic=10.0)

    assert linked_commits_mod.should_refresh_linked_commit_groups(agent) is True
    assert linked_commits_mod.compute_linked_commit_groups(agent) == ()
    assert linked_commits_mod.should_refresh_linked_commit_groups(agent) is False

    monkeypatch.setattr(linked_commits_mod.time, "monotonic", lambda: 12.0)
    assert linked_commits_mod.should_refresh_linked_commit_groups(agent) is True
