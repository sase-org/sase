"""Tests for live agent file-change hints."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.widgets.file_panel import _diff as diff_mod
from tests.ace.tui.widgets.file_panel._diff_cache_helpers import (
    _DiffTextProvider,
    _FailedDiffProvider,
    _git_diff,
    _make_running_agent,
    _setup_workspace,
)


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
