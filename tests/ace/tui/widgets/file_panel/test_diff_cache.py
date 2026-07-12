"""Tests for the Phase-6 diff worker dedupe and worktree cache."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.widgets.file_panel import _diff as diff_mod
from tests.ace.tui.widgets.file_panel._diff_cache_helpers import (
    _DiffTextProvider,
    _FailedDiffProvider,
    _FakeProvider,
    _git_diff,
    _make_active_coder_followup,
    _make_root_plan_agent,
    _make_running_agent,
    _setup_workspace,
)


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
