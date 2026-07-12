"""Tests for the Phase-6 diff worker dedupe and worktree cache."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets.file_panel import _diff as diff_mod


def _make_running_agent(
    *,
    workspace_num: int = 1,
    workspace_dir: str | None = None,
    project_file: str = "/tmp/projects/myproj/myproj.sase",
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my-feature",
        project_file=project_file,
        status="RUNNING",
        start_time=None,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        workflow="ace(run)-202604010000",
        raw_suffix="202604010000",
    )


def _make_root_plan_agent(workspace_num: int = 1) -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my-feature",
        project_file="/tmp/projects/myproj/myproj.sase",
        status="PLAN APPROVED",
        start_time=datetime(2024, 1, 1, 14, 0),
        workspace_num=workspace_num,
        workflow="ace(plan)-202604010000",
        raw_suffix="202604010000",
        role_suffix="-plan",
        plan_chain_root=True,
    )


def _make_active_coder_followup(
    *,
    workspace_num: int,
    workspace_dir: str | None = None,
    project_file: str = "/tmp/projects/myproj/myproj.sase",
    start_time: datetime,
    raw_suffix: str,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my-feature-code",
        project_file=project_file,
        status="PLAN APPROVED",
        start_time=start_time,
        workspace_num=workspace_num,
        workspace_dir=workspace_dir,
        workflow="ace(run)-202604010000-code",
        raw_suffix=raw_suffix,
        parent_timestamp="202604010000",
        role_suffix="-code",
    )


def _setup_workspace(tmp_path: Path, name: str = "myproj_1") -> Path:
    workspace = tmp_path / name
    (workspace / ".git").mkdir(parents=True)
    (workspace / ".git" / "index").write_bytes(b"\x00" * 16)
    return workspace


def _write_project_file(tmp_path: Path, primary_workspace: Path) -> Path:
    project_file = tmp_path / "projects" / "myproj.sase"
    project_file.parent.mkdir(parents=True)
    project_file.write_text(
        f"WORKSPACE_DIR: {primary_workspace}\nNAME: my-feature\n",
        encoding="utf-8",
    )
    return project_file


class _FakeProvider:
    def __init__(self) -> None:
        self.calls = 0
        self.cwd_calls: list[str] = []

    def diff_with_untracked(self, cwd: str, *, timeout: int = 10):  # type: ignore[no-untyped-def]
        self.calls += 1
        self.cwd_calls.append(cwd)
        return (True, f"diff for call {self.calls}")


def test_get_agent_diff_caches_on_unchanged_worktree(tmp_path: Path) -> None:
    diff_mod._diff_cache.clear()
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent(workspace_dir=str(workspace))
    provider = _FakeProvider()

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch(
            "sase.running_field.get_workspace_directory",
            side_effect=AssertionError("workspace materialization was called"),
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
    agent = _make_running_agent(workspace_dir=str(workspace))
    provider = _FakeProvider()

    t0 = 1_700_000_000.0
    t1 = t0 + diff_mod.DIFF_CACHE_TTL_SECONDS + 0.01

    with patch(
        "sase.running_field.get_workspace_directory",
        side_effect=AssertionError("workspace materialization was called"),
    ):
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
    agent = _make_running_agent(workspace_dir=str(workspace))
    provider = _FakeProvider()

    with patch(
        "sase.running_field.get_workspace_directory",
        side_effect=AssertionError("workspace materialization was called"),
    ):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            diff_mod.get_agent_diff(agent)
            # Mutate the .git/index file (changes mtime + size).
            (workspace / ".git" / "index").write_bytes(b"\x01" * 32)
            second = diff_mod.get_agent_diff(agent)

    assert provider.calls == 2
    assert second == "diff for call 2"


def test_get_agent_diff_resolves_root_plan_to_newest_active_coder_workspace(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    _setup_workspace(tmp_path, "myproj_1")
    _setup_workspace(tmp_path, "myproj_2")
    newest_workspace = _setup_workspace(tmp_path, "myproj_3")
    root = _make_root_plan_agent(workspace_num=1)
    older_coder = _make_active_coder_followup(
        workspace_num=2,
        workspace_dir=str(tmp_path / "myproj_2"),
        start_time=datetime(2024, 1, 1, 15, 0),
        raw_suffix="202604010000-code-1",
    )
    newest_coder = _make_active_coder_followup(
        workspace_num=3,
        workspace_dir=str(newest_workspace),
        start_time=datetime(2024, 1, 1, 16, 0),
        raw_suffix="202604010000-code-2",
    )
    root.followup_agents.extend([older_coder, newest_coder])
    provider = _FakeProvider()

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch(
            "sase.running_field.get_workspace_directory",
            side_effect=AssertionError("workspace materialization was called"),
        ):
            with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
                root_diff = diff_mod.get_agent_diff(root)
                coder_diff = diff_mod.get_agent_diff(newest_coder)

    assert root_diff == "diff for call 1"
    assert coder_diff == "diff for call 1"
    assert provider.calls == 1
    assert provider.cwd_calls == [str(newest_workspace)]


def test_root_plan_active_coder_live_diff_wins_over_coder_fallback(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    coder_workspace = _setup_workspace(tmp_path, "myproj_2")
    fallback = tmp_path / "coder.diff"
    fallback.write_text(_git_diff("src/committed.py"), encoding="utf-8")
    root = _make_root_plan_agent()
    coder = _make_active_coder_followup(
        workspace_num=2,
        workspace_dir=str(coder_workspace),
        start_time=datetime(2024, 1, 1, 16, 0),
        raw_suffix="202604010000-code",
    )
    coder.diff_path = str(fallback)
    root.followup_agents.append(coder)
    provider = _DiffTextProvider(_git_diff("src/live.py"))

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            result = diff_mod.get_agent_diff(root)

    assert result == _git_diff("src/live.py")
    assert provider.calls == 1


def test_get_agent_diff_handles_binary_diff_path(tmp_path: Path) -> None:
    """A diff_path pointing at binary bytes must not crash the TUI.

    Regression for the #sshot crash: malformed historical metadata could
    promote a PNG path into diff_path. Reading it as UTF-8 raised
    UnicodeDecodeError; get_agent_diff now degrades to None instead.
    """
    diff_mod._diff_cache.clear()
    png_path = tmp_path / "shot.png"
    png_path.write_bytes(b"\x89PNG\r\n\x1a\n\xff\xfe\x00\x01binary\x80\x81")
    agent = _make_running_agent(workspace_dir=str(tmp_path))
    agent.diff_path = str(png_path)
    agent.status = "DONE"

    # Must not raise; a completed agent with an unreadable diff yields None.
    assert diff_mod.get_agent_diff(agent) is None


def test_active_dirty_workspace_wins_over_persisted_fallback(tmp_path: Path) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    workspace = _setup_workspace(tmp_path)
    persisted = tmp_path / "persisted.diff"
    persisted.write_text(_git_diff("companion.md"), encoding="utf-8")
    agent = _make_running_agent(workspace_dir=str(workspace))
    agent.diff_path = str(persisted)
    provider = _DiffTextProvider(_git_diff("src/live.py"))

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            result = diff_mod.get_agent_diff(agent)

    assert result == _git_diff("src/live.py")
    assert provider.calls == 1


def test_active_clean_workspace_uses_persisted_fallback(tmp_path: Path) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    workspace = _setup_workspace(tmp_path)
    persisted = tmp_path / "persisted.diff"
    persisted_text = _git_diff("src/committed.py")
    persisted.write_text(persisted_text, encoding="utf-8")
    agent = _make_running_agent(workspace_dir=str(workspace))
    agent.diff_path = str(persisted)
    provider = _DiffTextProvider("")

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            first = diff_mod.get_agent_diff(agent)
            second = diff_mod.get_agent_diff(agent)

    assert first == persisted_text
    assert second == persisted_text
    assert provider.calls == 1


def test_active_unresolvable_workspace_uses_persisted_fallback(
    tmp_path: Path,
) -> None:
    persisted = tmp_path / "persisted.diff"
    persisted_text = _git_diff("src/committed.py")
    persisted.write_text(persisted_text, encoding="utf-8")
    agent = _make_running_agent(workspace_dir=str(tmp_path / "missing"))
    agent.diff_path = str(persisted)

    with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
        result = diff_mod.get_agent_diff(agent)

    assert result == persisted_text
    mock_get_provider.assert_not_called()


def test_active_failed_probe_uses_persisted_fallback_for_detail(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    workspace = _setup_workspace(tmp_path)
    persisted = tmp_path / "persisted.diff"
    persisted_text = _git_diff("src/committed.py")
    persisted.write_text(persisted_text, encoding="utf-8")
    agent = _make_running_agent(workspace_dir=str(workspace))
    agent.diff_path = str(persisted)
    provider = _FailedDiffProvider(raises=True)

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            result = diff_mod.get_agent_diff(agent)

    assert result == persisted_text
    assert provider.calls == 1
    assert diff_mod._diff_cache == {}


@pytest.mark.parametrize("status", ["DONE", "FAILED"])
def test_terminal_agent_uses_persisted_diff_without_workspace_probe(
    tmp_path: Path,
    status: str,
) -> None:
    persisted = tmp_path / "persisted.diff"
    persisted_text = _git_diff("src/final.py")
    persisted.write_text(persisted_text, encoding="utf-8")
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent(workspace_dir=str(workspace))
    agent.status = status
    agent.diff_path = str(persisted)

    with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
        result = diff_mod.get_agent_diff(agent)

    assert result == persisted_text
    mock_get_provider.assert_not_called()


def test_compute_diff_cache_key_includes_provider_name(tmp_path: Path) -> None:
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent(workspace_dir=str(workspace))
    provider = _FakeProvider()

    with patch(
        "sase.running_field.get_workspace_directory",
        side_effect=AssertionError("workspace materialization was called"),
    ):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            key = diff_mod._compute_diff_cache_key(agent)

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
    agent = _make_running_agent(workspace_dir=str(workspace))
    provider = _FakeProvider()

    with patch(
        "sase.running_field.get_workspace_directory",
        side_effect=AssertionError("workspace materialization was called"),
    ):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            key = diff_mod._compute_diff_cache_key(agent)

    assert key is not None
    assert key[3] is None
    assert isinstance(key[4], int)


def test_compute_diff_cache_key_returns_none_without_provider(
    tmp_path: Path,
) -> None:
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent(workspace_dir=str(workspace))

    from sase.vcs_provider import VCSProviderNotFoundError

    def raise_not_found(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        raise VCSProviderNotFoundError("none")

    with patch(
        "sase.running_field.get_workspace_directory",
        side_effect=AssertionError("workspace materialization was called"),
    ):
        with patch.object(diff_mod, "get_vcs_provider", side_effect=raise_not_found):
            assert diff_mod._compute_diff_cache_key(agent) is None


def test_compute_diff_cache_key_derives_numbered_workspace_adjacent_policy(
    tmp_path: Path,
) -> None:
    """Legacy ``adjacent`` policy still resolves to ``{primary}_{N}``."""
    diff_mod._workspace_store_cache.clear()
    primary_workspace = _setup_workspace(tmp_path, "primary")
    derived_workspace = _setup_workspace(tmp_path, "primary_3")
    project_file = _write_project_file(tmp_path, primary_workspace)
    agent = _make_running_agent(workspace_num=3, project_file=str(project_file))
    provider = _FakeProvider()

    with patch.object(
        diff_mod, "load_merged_config", return_value={"workspace": {"root": "adjacent"}}
    ):
        with patch(
            "sase.running_field.get_workspace_directory",
            side_effect=AssertionError("workspace materialization was called"),
        ):
            with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
                key = diff_mod._compute_diff_cache_key(agent)

    assert key is not None
    assert key[1] == str(derived_workspace)


def test_get_agent_diff_returns_none_without_read_only_workspace_metadata(
    tmp_path: Path,
) -> None:
    diff_mod._diff_cache.clear()
    project_file = tmp_path / "projects" / "myproj.sase"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("NAME: my-feature\n", encoding="utf-8")
    agent = _make_running_agent(workspace_num=3, project_file=str(project_file))

    with patch(
        "sase.running_field.get_workspace_directory",
        side_effect=AssertionError("workspace materialization was called"),
    ):
        with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
            assert diff_mod.get_agent_diff(agent) is None

    mock_get_provider.assert_not_called()


def test_compute_diff_cache_key_returns_none_when_explicit_workspace_is_missing(
    tmp_path: Path,
) -> None:
    primary_workspace = _setup_workspace(tmp_path, "primary")
    _setup_workspace(tmp_path, "primary_3")
    project_file = _write_project_file(tmp_path, primary_workspace)
    agent = _make_running_agent(
        workspace_num=3,
        workspace_dir=str(tmp_path / "missing_3"),
        project_file=str(project_file),
    )

    with patch(
        "sase.running_field.get_workspace_directory",
        side_effect=AssertionError("workspace materialization was called"),
    ):
        with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
            assert diff_mod._compute_diff_cache_key(agent) is None

    mock_get_provider.assert_not_called()


def _xdg_state_config() -> dict[str, object]:
    return {"workspace": {"root": "xdg-state", "project_key": "k"}}


def _make_xdg_managed_dir(tmp_path: Path) -> Path:
    """Create a managed ``xdg-state`` checkout (with ``.git/index``)."""
    managed = tmp_path / "state" / "sase" / "workspaces" / "k" / "primary_3"
    (managed / ".git").mkdir(parents=True)
    (managed / ".git" / "index").write_bytes(b"\x00" * 16)
    return managed


def test_resolve_managed_workspace_dir_none_is_primary() -> None:
    # ``workspace_num is None`` short-circuits to the primary dir without
    # constructing a store or loading config.
    assert (
        diff_mod._resolve_managed_workspace_dir("/proj/primary", None)
        == "/proj/primary"
    )


def test_resolve_managed_workspace_dir_zero_is_primary() -> None:
    diff_mod._workspace_store_cache.clear()
    with patch.object(
        diff_mod, "load_merged_config", return_value={"workspace": {"root": "adjacent"}}
    ):
        resolved = diff_mod._resolve_managed_workspace_dir("/proj/primary", 0)
    assert resolved == "/proj/primary"


def test_resolve_managed_workspace_dir_adjacent_policy() -> None:
    diff_mod._workspace_store_cache.clear()
    with patch.object(
        diff_mod, "load_merged_config", return_value={"workspace": {"root": "adjacent"}}
    ):
        resolved = diff_mod._resolve_managed_workspace_dir("/proj/primary", 3)
    assert resolved is not None
    assert resolved.rstrip("/") == "/proj/primary_3"


def test_resolve_managed_workspace_dir_xdg_state_is_not_adjacent(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
    diff_mod._workspace_store_cache.clear()

    with patch.object(diff_mod, "load_merged_config", return_value=_xdg_state_config()):
        resolved = diff_mod._resolve_managed_workspace_dir("/proj/primary", 3)

    assert resolved is not None
    expected = tmp_path / "state" / "sase" / "workspaces" / "k" / "primary_3"
    assert resolved.rstrip("/") == str(expected)
    # The whole point of the fix: the managed path is NOT the adjacent one.
    assert resolved.rstrip("/") != "/proj/primary_3"


def test_resolve_managed_workspace_dir_invalid_config_returns_none() -> None:
    diff_mod._workspace_store_cache.clear()
    # A non-absolute, non-policy ``workspace.root`` makes WorkspaceStore raise;
    # the resolver degrades to None instead of propagating.
    with patch.object(
        diff_mod,
        "load_merged_config",
        return_value={"workspace": {"root": "not-a-policy"}},
    ):
        assert diff_mod._resolve_managed_workspace_dir("/proj/primary", 3) is None


def test_get_workspace_store_constructed_once_per_primary() -> None:
    diff_mod._workspace_store_cache.clear()
    calls = {"n": 0}
    real_store_cls = diff_mod.WorkspaceStore

    def counting(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return real_store_cls(*args, **kwargs)

    with patch.object(diff_mod, "WorkspaceStore", side_effect=counting):
        with patch.object(
            diff_mod,
            "load_merged_config",
            return_value={"workspace": {"root": "adjacent"}},
        ):
            first = diff_mod._get_workspace_store("/proj/primary")
            second = diff_mod._get_workspace_store("/proj/primary")

    assert first is second
    assert calls["n"] == 1


def test_compute_diff_cache_key_xdg_state_prefers_managed_over_stale_adjacent(
    tmp_path: Path, monkeypatch
) -> None:
    """Regression: a stale ``{primary}_{N}`` leftover must not win under xdg-state."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
    diff_mod._diff_cache.clear()
    diff_mod._workspace_store_cache.clear()

    primary_workspace = _setup_workspace(tmp_path, "primary")
    stale_adjacent = _setup_workspace(tmp_path, "primary_3")
    managed = _make_xdg_managed_dir(tmp_path)
    project_file = _write_project_file(tmp_path, primary_workspace)
    agent = _make_running_agent(workspace_num=3, project_file=str(project_file))
    provider = _FakeProvider()

    with patch.object(diff_mod, "load_merged_config", return_value=_xdg_state_config()):
        with patch(
            "sase.running_field.get_workspace_directory",
            side_effect=AssertionError("workspace materialization was called"),
        ):
            with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
                key = diff_mod._compute_diff_cache_key(agent)

    assert key is not None
    assert key[1] == str(managed)
    assert key[1] != str(stale_adjacent)


def test_get_agent_diff_runs_in_managed_workspace_not_stale(
    tmp_path: Path, monkeypatch
) -> None:
    """End-to-end: the live diff is taken from the managed checkout, not the
    stale adjacent leftover that the old heuristic would have picked."""
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
    diff_mod._diff_cache.clear()
    diff_mod._workspace_store_cache.clear()

    primary_workspace = _setup_workspace(tmp_path, "primary")
    _setup_workspace(tmp_path, "primary_3")  # stale adjacent leftover
    managed = _make_xdg_managed_dir(tmp_path)
    project_file = _write_project_file(tmp_path, primary_workspace)
    agent = _make_running_agent(workspace_num=3, project_file=str(project_file))
    provider = _FakeProvider()

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(
            diff_mod, "load_merged_config", return_value=_xdg_state_config()
        ):
            with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
                result = diff_mod.get_agent_diff(agent)

    assert result == "diff for call 1"
    assert provider.cwd_calls == [str(managed)]


def test_resolve_managed_workspace_dir_one_is_primary(
    tmp_path: Path, monkeypatch
) -> None:
    # Legacy metadata uses 0 and 1 interchangeably for the primary checkout.
    # Under the default xdg-state policy resolve(1) would return a managed
    # clone path, so the resolver must normalize 1 -> 0 exactly like the
    # runner-side resolvers do.
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.delenv("SASE_WORKSPACE_ROOT", raising=False)
    diff_mod._workspace_store_cache.clear()

    with patch.object(diff_mod, "load_merged_config", return_value=_xdg_state_config()):
        resolved = diff_mod._resolve_managed_workspace_dir("/proj/primary", 1)

    assert resolved is not None
    assert resolved.rstrip("/") == "/proj/primary"


# --- live_agent_file_change_hint ---------------------------------------------


def _git_diff(path: str) -> str:
    return f"""diff --git a/{path} b/{path}
--- a/{path}
+++ b/{path}
@@ -1 +1 @@
-old
+new
"""


class _DiffTextProvider:
    """VCS provider stub returning a fixed unified diff for the live hint."""

    def __init__(self, diff_text: str) -> None:
        self.diff_text = diff_text
        self.calls = 0

    def diff_with_untracked(self, cwd: str, *, timeout: int = 10):  # type: ignore[no-untyped-def]
        self.calls += 1
        return (True, self.diff_text)


class _FailedDiffProvider:
    def __init__(self, *, raises: bool) -> None:
        self.raises = raises
        self.calls = 0

    def diff_with_untracked(self, cwd: str, *, timeout: int = 10):  # type: ignore[no-untyped-def]
        self.calls += 1
        if self.raises:
            raise TimeoutError("diff timed out")
        return (False, None)


def test_live_hint_true_for_real_workspace_edits(tmp_path: Path) -> None:
    diff_mod._diff_cache.clear()
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent(workspace_dir=str(workspace))
    provider = _DiffTextProvider(_git_diff("src/app.py"))

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            hint = diff_mod.live_agent_file_change_hint(agent)

    assert hint is True


def test_live_hint_false_for_bookkeeping_only_edits(tmp_path: Path) -> None:
    diff_mod._diff_cache.clear()
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent(workspace_dir=str(workspace))
    provider = _DiffTextProvider(_git_diff("sdd/plans/202606/change.md"))

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            hint = diff_mod.live_agent_file_change_hint(agent)

    assert hint is False


def test_live_hint_false_for_clean_workspace(tmp_path: Path) -> None:
    diff_mod._diff_cache.clear()
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent(workspace_dir=str(workspace))
    provider = _DiffTextProvider("")

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            hint = diff_mod.live_agent_file_change_hint(agent)

    assert hint is False


def test_live_hint_none_and_does_not_cache_failed_diff_probe(
    tmp_path: Path,
) -> None:
    for idx, provider in enumerate(
        [_FailedDiffProvider(raises=True), _FailedDiffProvider(raises=False)]
    ):
        diff_mod._diff_cache.clear()
        diff_mod._vcs_provider_cache.clear()
        workspace = _setup_workspace(tmp_path, f"failing_{idx}")
        agent = _make_running_agent(workspace_dir=str(workspace))

        with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
            with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
                hint = diff_mod.live_agent_file_change_hint(agent)

        assert hint is None
        assert provider.calls == 1
        assert diff_mod._diff_cache == {}


def test_live_hint_prefers_live_edits_over_persisted_diff_path(tmp_path: Path) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent(workspace_dir=str(workspace))
    persisted = tmp_path / "demo.diff"
    persisted.write_text(_git_diff("sdd/plans/change.md"), encoding="utf-8")
    agent.diff_path = str(persisted)
    provider = _DiffTextProvider(_git_diff("src/live.py"))

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            hint = diff_mod.live_agent_file_change_hint(agent)

    assert hint is True
    assert provider.calls == 1


def test_live_hint_probe_failure_preserves_existing_signal(tmp_path: Path) -> None:
    diff_mod._diff_cache.clear()
    diff_mod._vcs_provider_cache.clear()
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent(workspace_dir=str(workspace))
    persisted = tmp_path / "demo.diff"
    persisted.write_text(_git_diff("src/committed.py"), encoding="utf-8")
    agent.diff_path = str(persisted)
    provider = _FailedDiffProvider(raises=True)

    with patch.object(diff_mod.time, "time", return_value=1_700_000_000.0):
        with patch.object(diff_mod, "get_vcs_provider", return_value=provider):
            hint = diff_mod.live_agent_file_change_hint(agent)

    # The deferred badge worker treats a transient probe failure as unknown so
    # its apply step retains any stale-while-revalidate hint. The detail panel
    # still uses the persisted fallback (covered above).
    assert hint is None
    assert provider.calls == 1
    assert diff_mod._diff_cache == {}


def test_live_hint_none_for_completed_agent(tmp_path: Path) -> None:
    diff_mod._diff_cache.clear()
    workspace = _setup_workspace(tmp_path)
    agent = _make_running_agent(workspace_dir=str(workspace))
    agent.status = "DONE"

    with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
        hint = diff_mod.live_agent_file_change_hint(agent)

    assert hint is None
    mock_get_provider.assert_not_called()


def test_live_hint_false_without_resolvable_workspace(tmp_path: Path) -> None:
    diff_mod._diff_cache.clear()
    project_file = tmp_path / "projects" / "myproj.sase"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("NAME: my-feature\n", encoding="utf-8")
    agent = _make_running_agent(workspace_num=3, project_file=str(project_file))

    with patch.object(diff_mod, "get_vcs_provider") as mock_get_provider:
        hint = diff_mod.live_agent_file_change_hint(agent)

    # No workspace metadata resolves -> no live diff -> fail closed (no pencil).
    assert hint is False
    mock_get_provider.assert_not_called()
