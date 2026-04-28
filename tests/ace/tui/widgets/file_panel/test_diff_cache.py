"""Tests for the Phase-6 diff worker dedupe and worktree cache."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.file_panel import _diff as diff_mod


def _make_running_agent(workspace_num: int = 1) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my-feature",
        project_file="/tmp/projects/myproj/myproj.gp",
        status="RUNNING",
        start_time=None,
        workspace_num=workspace_num,
        workflow="ace(run)-202604010000",
        raw_suffix="202604010000",
    )


def _setup_workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "myproj_1"
    (workspace / ".git").mkdir(parents=True)
    (workspace / ".git" / "index").write_bytes(b"\x00" * 16)
    return workspace


class _FakeProvider:
    def __init__(self) -> None:
        self.calls = 0

    def diff_with_untracked(self, cwd: str, *, timeout: int = 10):  # type: ignore[no-untyped-def]
        self.calls += 1
        return (True, f"diff for call {self.calls}")


def test_get_agent_diff_caches_on_unchanged_worktree(tmp_path: Path) -> None:
    diff_mod._diff_cache.clear()
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent()
    provider = _FakeProvider()

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(
            diff_mod, "get_workspace_directory", return_value=str(workspace)
        ):
            with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
                first = diff_mod.get_agent_diff(agent)
                second = diff_mod.get_agent_diff(agent)

    assert first == "diff for call 1"
    # Same agent, same TTL bucket and git index sig → cache hit.
    assert second == "diff for call 1"
    assert provider.calls == 1


def test_get_agent_diff_invalidates_after_ttl(tmp_path: Path) -> None:
    """Regression: working-tree edits must surface within DIFF_CACHE_TTL_SECONDS.

    ``.git/index`` does not change on working-tree edits, so before the fix
    the cache stayed permanently warm while a running agent edited files.
    The TTL bucket is now the primary invalidation signal.
    """
    diff_mod._diff_cache.clear()
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent()
    provider = _FakeProvider()

    t0 = 1_700_000_000.0
    t1 = t0 + diff_mod.DIFF_CACHE_TTL_SECONDS + 0.01

    with patch.object(diff_mod, "get_workspace_directory", return_value=str(workspace)):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            with patch.object(diff_mod.time, "time", return_value=t0):
                first = diff_mod.get_agent_diff(agent)
            # .git/index unchanged — only the working tree changed (which is
            # what the fake provider's incrementing call count simulates).
            with patch.object(diff_mod.time, "time", return_value=t1):
                second = diff_mod.get_agent_diff(agent)

    assert first == "diff for call 1"
    assert second == "diff for call 2"
    assert provider.calls == 2


def test_get_agent_diff_invalidates_when_index_changes(tmp_path: Path) -> None:
    diff_mod._diff_cache.clear()
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent()
    provider = _FakeProvider()

    with patch.object(diff_mod, "get_workspace_directory", return_value=str(workspace)):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            diff_mod.get_agent_diff(agent)
            # Mutate the .git/index file (changes mtime + size).
            (workspace / ".git" / "index").write_bytes(b"\x01" * 32)
            second = diff_mod.get_agent_diff(agent)

    assert provider.calls == 2
    assert second == "diff for call 2"


def test_compute_diff_cache_key_includes_provider_name(tmp_path: Path) -> None:
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent()
    provider = _FakeProvider()

    with patch.object(diff_mod, "get_workspace_directory", return_value=str(workspace)):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            key = diff_mod.compute_diff_cache_key(agent)

    assert key is not None
    assert key[1] == str(workspace)
    assert key[2] == "_FakeProvider"
    assert key[3] is not None  # git index signature present
    assert isinstance(key[4], int)  # TTL bucket always present


def test_compute_diff_cache_key_ttl_bucket_present_without_git_index(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "myproj_1"
    workspace.mkdir()
    # No .git directory → fingerprint is None; TTL bucket still present.
    agent = _make_running_agent()
    provider = _FakeProvider()

    with patch.object(diff_mod, "get_workspace_directory", return_value=str(workspace)):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            key = diff_mod.compute_diff_cache_key(agent)

    assert key is not None
    assert key[3] is None
    assert isinstance(key[4], int)


def test_compute_diff_cache_key_returns_none_without_provider(
    tmp_path: Path,
) -> None:
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent()

    from sase.vcs_provider import VCSProviderNotFoundError

    def raise_not_found(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        raise VCSProviderNotFoundError("none")

    with patch.object(diff_mod, "get_workspace_directory", return_value=str(workspace)):
        with patch.object(diff_mod, "get_vcs_provider", side_effect=raise_not_found):
            assert diff_mod.compute_diff_cache_key(agent) is None
