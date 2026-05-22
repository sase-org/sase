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
from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState


_SOURCE_SCAN_STATE = AgentLoadState(
    tier="tier2",
    complete_history=True,
    artifact_source="source_scan",
    used_artifact_index=False,
)
_INCOMPLETE_INDEX_STATE = AgentLoadState(
    tier="tier1",
    complete_history=False,
    complete_visible_inbox=False,
    artifact_source="artifact_index",
    used_artifact_index=True,
)


def load_agents_from_disk(*args, **kwargs):
    result = load_agents_from_disk_with_state(*args, **kwargs)
    return result.all_agents, result.dismissed_from_loader


def _make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for self-heal tests."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
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
        self._revived_agent_raw_suffixes: set[str] = set()
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}
        self._agent_search_query = ""
        self._agents_loading = False
        self._agent_load_state: AgentLoadState | None = None
        self._agents_seen_complete_history = False
        self._agents_history_reconcile_pending = False
        self._agents_history_reconcile_armed_mono = 0.0
        # Pretend the first async load already happened so _apply_loaded_agents
        # doesn't try to query widgets that aren't mounted in this fake.
        self._agents_first_load_done = True

    def set_timer(self, _delay: float, _callback: object) -> None:
        """Stub for apply paths that should not schedule timers here."""

    def _finalize_agent_list(self, *args: object, **kwargs: object) -> None:
        """Stub — the real finalizer needs tabbar/panel widgets we don't have."""
        if kwargs.get("save_unfiltered"):
            self._agents_with_children = list(self._agents)

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

    checked_paths: list[str] = []

    def fake_is_dir(path: Path) -> bool:
        checked_paths.append(str(path))
        return False

    with patch.object(Path, "is_dir", autospec=True, side_effect=fake_is_dir):
        app._apply_loaded_agents(
            [], [agent], on_agents_tab=False, selected_identity=None
        )
        first_missing_dir_checks = checked_paths.count(missing_dir)
        app._apply_loaded_agents(
            [], [agent], on_agents_tab=False, selected_identity=None
        )
        # Second reload: no additional is_dir() checks for this artifacts_dir
        # (the orphan-bundle path may still stat the bundles dir).
        assert checked_paths.count(missing_dir) == first_missing_dir_checks


def test_cleanup_does_not_probe_bundles_for_orphaned_identities() -> None:
    """Startup cleanup no longer scans bundles for missing dismissed rows."""
    raw_suffix = "20240101120000"
    identity = (AgentType.WORKFLOW, "archived", raw_suffix)

    with (
        patch("sase.ace.dismissed_agents.has_dismissed_bundle") as mock_has_bundle,
        patch("sase.ace.tui.actions.agents._killing.delete_agent_artifacts"),
    ):
        orphaned, cleaned_dirs = _loading._compute_loader_cleanup({identity}, [])

    assert orphaned == set()
    assert cleaned_dirs == set()
    mock_has_bundle.assert_not_called()


def test_load_agents_from_disk_does_not_include_bundle_only_archive_rows() -> None:
    """Startup revive candidates come from loader rows, not the full archive."""
    bundled = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="bundle_only",
        raw_suffix="20240102120000",
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.load_tiered_agents",
            return_value=([], _SOURCE_SCAN_STATE),
        ),
        patch(
            "sase.ace.tui.actions.agents._snapshot_cache.AgentSnapshotCache"
            ".dismissed_bundles",
            return_value=[bundled],
        ) as mock_dismissed_bundles,
    ):
        load_result = load_agents_from_disk_with_state(set())

    assert load_result.all_agents == []
    assert load_result.dismissed_from_loader == []
    mock_dismissed_bundles.assert_not_called()


def test_apply_loaded_agents_repairs_dismissed_index_from_bundle() -> None:
    """Recovered bundle candidates are persisted back into dismissed_agents."""
    app = FakeLoadingApp()
    bundled = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="bundle_only",
        raw_suffix="20240102120000",
    )
    bundled._loaded_from_dismissed_bundle = True

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
        patch(
            "sase.ace.tui.actions.agents._loading_apply."
            "sync_dismissed_agent_artifact_index"
        ) as sync_index,
        patch("sase.ace.tui.actions.agents._killing.delete_agent_artifacts"),
    ):
        app._apply_loaded_agents(
            [], [bundled], on_agents_tab=False, selected_identity=None
        )

    assert bundled.identity in app._dismissed_agents
    mock_save.assert_called_once_with(app._dismissed_agents)
    sync_index.assert_called_once_with(app._dismissed_agents, added={bundled.identity})


def test_incomplete_load_preserves_visible_revived_agent() -> None:
    """Tier 1 source scans should not drop same-session revived history."""
    app = FakeLoadingApp()
    revived = _make_agent(cl_name="old", raw_suffix="20240102120000")
    current = _make_agent(cl_name="new", raw_suffix="20260202120000")
    app._agents_with_children = [revived]
    app._agents = [revived]
    app._revived_agent_raw_suffixes = {"20240102120000"}
    incomplete_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        complete_visible_inbox=False,
        artifact_source="source_scan",
        used_artifact_index=False,
    )

    app._apply_loaded_agents(
        [current],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=incomplete_state,
    )

    assert [a.raw_suffix for a in app._agents] == [
        "20260202120000",
        "20240102120000",
    ]
    assert app._revived_agent_raw_suffixes == {"20240102120000"}


def test_incomplete_load_preserves_revived_agent_from_dismissed_objects() -> None:
    """Revived agents missing from _agents_with_children fall back to the
    dismissed-bundle cache so first paint still surfaces them after revive."""
    app = FakeLoadingApp()
    revived = _make_agent(cl_name="old", raw_suffix="20240102120000")
    current = _make_agent(cl_name="new", raw_suffix="20260202120000")
    # ``_agents_with_children`` is empty because the revived agent was
    # long-dismissed and never appeared in a prior in-memory snapshot.
    app._agents_with_children = []
    app._agents = []
    app._dismissed_agent_objects = [revived]
    app._revived_agent_raw_suffixes = {"20240102120000"}
    incomplete_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        complete_visible_inbox=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )

    app._apply_loaded_agents(
        [current],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=incomplete_state,
    )

    assert [a.raw_suffix for a in app._agents] == [
        "20260202120000",
        "20240102120000",
    ]
    assert app._revived_agent_raw_suffixes == {"20240102120000"}


def test_complete_load_clears_revived_agent_preservation() -> None:
    """Once Tier 2 sees the revived row, future loads no longer pin it."""
    app = FakeLoadingApp()
    revived = _make_agent(cl_name="old", raw_suffix="20240102120000")
    app._agents_with_children = [revived]
    app._agents = [revived]
    app._revived_agent_raw_suffixes = {"20240102120000"}

    app._apply_loaded_agents(
        [revived],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=_SOURCE_SCAN_STATE,
    )

    assert app._agents == [revived]
    assert app._revived_agent_raw_suffixes == set()


def test_incomplete_load_after_complete_history_patches_cached_rows() -> None:
    """Tier 1 refreshes after Tier 2 should not shrink the row universe."""
    app = FakeLoadingApp()
    active_cached = _make_agent(
        cl_name="active",
        status="RUNNING",
        raw_suffix="20260202120000",
    )
    active_updated = _make_agent(
        cl_name="active",
        status="DONE",
        raw_suffix="20260202120000",
    )
    historical = _make_agent(cl_name="historical", raw_suffix="20240102120000")
    dismissed = _make_agent(cl_name="dismissed", raw_suffix="20240103120000")
    new_agent = _make_agent(cl_name="new", raw_suffix="20260303120000")

    app._agent_load_state = _SOURCE_SCAN_STATE
    app._agents_seen_complete_history = True
    app._agents_with_children = [active_cached, historical, dismissed]
    app._agents = list(app._agents_with_children)
    app._dismissed_agents = {dismissed.identity}

    app._apply_loaded_agents(
        [new_agent, active_updated],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=_INCOMPLETE_INDEX_STATE,
    )

    assert [a.raw_suffix for a in app._agents] == [
        "20260303120000",
        "20260202120000",
        "20240102120000",
    ]
    assert app._agents[1] is active_updated


def test_repeated_incomplete_load_after_complete_history_keeps_cached_rows() -> None:
    """The complete-history watermark survives multiple Tier 1 patches."""
    app = FakeLoadingApp()
    active_cached = _make_agent(
        cl_name="active",
        status="RUNNING",
        raw_suffix="20260202120000",
    )
    historical = _make_agent(cl_name="historical", raw_suffix="20240102120000")
    launched = _make_agent(
        cl_name="launched",
        status="RUNNING",
        raw_suffix="20260303120000",
    )
    launched_updated = _make_agent(
        cl_name="launched",
        status="DONE",
        raw_suffix="20260303120000",
    )

    app._apply_loaded_agents(
        [active_cached, historical],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=_SOURCE_SCAN_STATE,
    )
    assert app._agents_seen_complete_history is True

    app._apply_loaded_agents(
        [launched],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=_INCOMPLETE_INDEX_STATE,
    )

    app._apply_loaded_agents(
        [launched_updated],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=_INCOMPLETE_INDEX_STATE,
    )

    assert [a.raw_suffix for a in app._agents] == [
        "20260303120000",
        "20260202120000",
        "20240102120000",
    ]
    assert app._agents[0] is launched_updated


def test_incomplete_load_after_complete_history_drops_running_duplicate_root() -> None:
    """A Tier 1 RUNNING row must not duplicate a cached WORKFLOW parent."""
    app = FakeLoadingApp()
    raw_suffix = "20260202120000"
    workflow_parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="active",
        status="RUNNING",
        raw_suffix=raw_suffix,
        workflow="ace-run",
        appears_as_agent=True,
    )
    workflow_child = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="active.step",
        status="RUNNING",
        raw_suffix="20260202120001",
        parent_workflow="ace-run",
        parent_timestamp=raw_suffix,
        step_name="prompt",
        step_type="agent",
        step_index=0,
        total_steps=1,
    )
    incoming_running = _make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="active",
        status="RUNNING",
        raw_suffix=raw_suffix,
        workflow="run",
    )

    app._agent_load_state = _SOURCE_SCAN_STATE
    app._agents_seen_complete_history = True
    app._agents_with_children = [workflow_parent, workflow_child]
    app._agents = list(app._agents_with_children)

    app._apply_loaded_agents(
        [incoming_running],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=_INCOMPLETE_INDEX_STATE,
    )

    assert app._agents == [workflow_parent, workflow_child]


def test_incomplete_load_after_complete_history_keeps_non_workflow_suffix_guard() -> (
    None
):
    """Suffix shadows not handled by canonical dedup are still suppressed."""
    app = FakeLoadingApp()
    raw_suffix = "20260202120000"
    cached_running = _make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="active",
        status="RUNNING",
        raw_suffix=raw_suffix,
        workflow="run",
    )
    incoming_running = _make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="unknown",
        status="RUNNING",
        raw_suffix=raw_suffix,
        workflow="run",
    )

    app._agent_load_state = _SOURCE_SCAN_STATE
    app._agents_seen_complete_history = True
    app._agents_with_children = [cached_running]
    app._agents = list(app._agents_with_children)

    app._apply_loaded_agents(
        [incoming_running],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=_INCOMPLETE_INDEX_STATE,
    )

    assert app._agents == [cached_running]


def test_incomplete_load_after_complete_history_merges_running_shadow_metadata() -> (
    None
):
    """A dropped Tier 1 RUNNING shadow still donates metadata to the parent."""
    app = FakeLoadingApp()
    raw_suffix = "20260202120000"
    workflow_parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="active",
        status="RUNNING",
        raw_suffix=raw_suffix,
        workflow="ace-run",
        appears_as_agent=True,
    )
    workflow_child = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="active.step",
        status="RUNNING",
        raw_suffix="20260202120001",
        parent_workflow="ace-run",
        parent_timestamp=raw_suffix,
        step_name="prompt",
        step_type="agent",
        step_index=0,
        total_steps=1,
    )
    incoming_running = _make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="active",
        status="RUNNING",
        raw_suffix=raw_suffix,
        workflow="run",
        workspace_num=7,
        response_path="/tmp/response.md",
        model="claude-opus-4-20250514",
        vcs_provider="GitHub",
        agent_name="active-agent",
        step_output={"meta_workspace": "7", "stdout": "done"},
    )

    app._agent_load_state = _SOURCE_SCAN_STATE
    app._agents_seen_complete_history = True
    app._agents_with_children = [workflow_parent, workflow_child]
    app._agents = list(app._agents_with_children)

    app._apply_loaded_agents(
        [incoming_running],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=_INCOMPLETE_INDEX_STATE,
    )

    assert app._agents == [workflow_parent, workflow_child]
    assert workflow_parent.workspace_num == 7
    assert workflow_parent.response_path == "/tmp/response.md"
    assert workflow_parent.model == "claude-opus-4-20250514"
    assert workflow_parent.vcs_provider == "GitHub"
    assert workflow_parent.agent_name == "active-agent"
    assert workflow_parent.step_output == {"meta_workspace": "7", "stdout": "done"}


def test_incomplete_load_after_complete_history_dedups_cross_snapshot_same_pid() -> (
    None
):
    """Post-history Tier 1 patches keep loader-level same-PID invariants."""
    app = FakeLoadingApp()
    cached_vcs_claim = _make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="active",
        status="RUNNING",
        raw_suffix="20260202120000",
        workflow="gh-active",
        pid=4242,
        workspace_num=9,
        model="cached-model",
    )
    incoming_non_vcs = _make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="active",
        status="RUNNING",
        raw_suffix="20260202120100",
        workflow="custom",
        pid=4242,
    )

    app._agent_load_state = _SOURCE_SCAN_STATE
    app._agents_seen_complete_history = True
    app._agents_with_children = [cached_vcs_claim]
    app._agents = list(app._agents_with_children)

    app._apply_loaded_agents(
        [incoming_non_vcs],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=_INCOMPLETE_INDEX_STATE,
    )

    assert app._agents == [incoming_non_vcs]
    assert incoming_non_vcs.workspace_num == 9
    assert incoming_non_vcs.model == "cached-model"


def test_incomplete_load_after_complete_history_reattaches_pid_dedup_children() -> None:
    """Children of a removed same-PID parent stay attached to the survivor."""
    app = FakeLoadingApp()
    cached_suffix = "20260202120000"
    incoming_suffix = "20260202120100"
    cached_running = _make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="active",
        status="RUNNING",
        raw_suffix=cached_suffix,
        workflow="ace(run)",
        pid=4243,
        workspace_num=11,
    )
    cached_child = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="active.step",
        status="RUNNING",
        raw_suffix="20260202120001",
        parent_timestamp=cached_suffix,
        step_name="prompt",
        step_type="agent",
        step_index=0,
        total_steps=1,
    )
    incoming_workflow = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="active",
        status="RUNNING",
        raw_suffix=incoming_suffix,
        workflow="run",
        appears_as_agent=True,
        pid=4243,
    )

    app._agent_load_state = _SOURCE_SCAN_STATE
    app._agents_seen_complete_history = True
    app._agents_with_children = [cached_running, cached_child]
    app._agents = list(app._agents_with_children)

    app._apply_loaded_agents(
        [incoming_workflow],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=_INCOMPLETE_INDEX_STATE,
    )

    assert app._agents == [incoming_workflow, cached_child]
    assert incoming_workflow.workspace_num == 11
    assert cached_child.parent_timestamp == incoming_suffix


def test_incomplete_load_before_complete_history_still_replaces_list() -> None:
    """First-paint Tier 1 behavior stays capped until Tier 2 reconciles."""
    app = FakeLoadingApp()
    historical = _make_agent(cl_name="historical", raw_suffix="20240102120000")
    current = _make_agent(cl_name="current", raw_suffix="20260303120000")
    app._agents_with_children = [historical]
    app._agents = [historical]

    app._apply_loaded_agents(
        [current],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=_INCOMPLETE_INDEX_STATE,
    )

    assert app._agents == [current]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
