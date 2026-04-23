"""Tests for the loader self-healing artifact-cleanup cache (Fix 3).

The loader walks every loader-sourced dismissed agent and tries to remove
stale artifact files.  With many dismissed agents accumulated over time,
this turns into hundreds of redundant stat+glob syscalls on every reload.
The cache skips dirs that have already been reconciled in this process.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents import _loading
from sase.ace.tui.actions.agents._loading import AgentLoadingMixin
from sase.ace.tui.models.agent import Agent, AgentType


def _make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for self-heal tests."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.gp",
        "status": "DONE",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class FakeLoadingApp(AgentLoadingMixin):
    """Minimal app exposing just the attrs touched by self-healing."""

    def __init__(self) -> None:
        self.current_tab = "changespecs"
        self.current_idx = 0
        self.hide_non_run_agents = False
        self._agents: list[Agent] = []
        self._agents_with_children: list[Agent] = []
        self._agents_last_idx = 0
        self._has_always_visible = False
        self._hidden_count = 0
        self._hideable_agents: list[Agent] = []
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}
        self._pinned_agents: set[tuple[AgentType, str, str | None]] = set()
        self._agent_custom_order: list[tuple[AgentType, str, str | None]] = []
        self._agent_search_query = ""
        self._agents_loading = False
        # Pretend the first async load already happened so _apply_loaded_agents
        # doesn't try to query widgets that aren't mounted in this fake.
        self._agents_first_load_done = True

    def _finalize_agent_list(self, *args: object, **kwargs: object) -> None:
        """Stub — the real finalizer needs tabbar/panel widgets we don't have."""

    def _persist_dismissed_agent(
        self, identity: tuple[AgentType, str, str | None]
    ) -> None:
        self._dismissed_agents.add(identity)


@pytest.fixture(autouse=True)
def _clear_cleaned_artifact_cache() -> None:
    """Clear the module-level cache between tests."""
    _loading._CLEANED_ARTIFACT_DIRS.clear()


def test_self_heal_skips_cleanup_for_missing_artifacts_dir(tmp_path: Path) -> None:
    """Non-existent artifacts dir is cached after first check."""
    app = FakeLoadingApp()
    missing_dir = str(tmp_path / "gone")
    agent = _make_agent(artifacts_dir=missing_dir)
    app._dismissed_agents = {agent.identity}

    with patch(
        "sase.ace.tui.actions.agents._killing.delete_agent_artifacts"
    ) as mock_delete:
        app._apply_loaded_agents(
            [], [agent], on_agents_tab=False, selected_identity=None
        )

    assert mock_delete.call_count == 0
    assert missing_dir in _loading._CLEANED_ARTIFACT_DIRS


def test_self_heal_cleans_and_caches_existing_dir(tmp_path: Path) -> None:
    """Existing artifacts dir is cleaned once and then cached."""
    app = FakeLoadingApp()
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    agent = _make_agent(artifacts_dir=str(artifacts_dir))
    app._dismissed_agents = {agent.identity}

    with patch(
        "sase.ace.tui.actions.agents._killing.delete_agent_artifacts"
    ) as mock_delete:
        app._apply_loaded_agents(
            [], [agent], on_agents_tab=False, selected_identity=None
        )
        assert mock_delete.call_count == 1

        # Second reload: the cache should short-circuit the cleanup
        app._apply_loaded_agents(
            [], [agent], on_agents_tab=False, selected_identity=None
        )
        assert mock_delete.call_count == 1

    assert str(artifacts_dir) in _loading._CLEANED_ARTIFACT_DIRS


def test_self_heal_skips_second_reload_even_for_missing_dir(tmp_path: Path) -> None:
    """Regression guard: after caching a missing dir, don't re-check it."""
    app = FakeLoadingApp()
    missing_dir = str(tmp_path / "still_gone")
    agent = _make_agent(artifacts_dir=missing_dir)
    app._dismissed_agents = {agent.identity}

    with patch("pathlib.Path.is_dir", return_value=False) as mock_is_dir:
        app._apply_loaded_agents(
            [], [agent], on_agents_tab=False, selected_identity=None
        )
        first_calls = mock_is_dir.call_count
        app._apply_loaded_agents(
            [], [agent], on_agents_tab=False, selected_identity=None
        )
        # Second reload: no additional is_dir() checks for this artifacts_dir
        # (the orphan-bundle path may still stat the bundles dir).
        assert mock_is_dir.call_count == first_calls


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
