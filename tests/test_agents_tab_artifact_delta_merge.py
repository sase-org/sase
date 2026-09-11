"""Tests for artifact-delta agents-tab loads merging with cached history."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    merge_incomplete_load_after_complete_history,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import load_artifact_delta_agents
from sase.core.agent_scan_wire import AgentClanContextWire

from tests._agents_tab_incomplete_merge_helpers import (
    _incomplete_tier1_snapshot,
    _write_json,
)
from tests._agents_tab_query_helpers import _make_agent


def test_artifact_delta_deleted_dir_removes_cached_row() -> None:
    """A watcher deletion delta should delete the cached artifact-backed row."""
    artifact_dir = Path("/tmp/projects/sase/artifacts/ace-run/20260528120000")
    cached = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 28, 12, 0, 0),
        raw_suffix="20260528120000",
        artifacts_dir=str(artifact_dir),
    )
    prep = PreparedApplyData(
        filtered_agents=[],
        has_always_visible=False,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    snapshot = _incomplete_tier1_snapshot(
        [cached],
        artifact_source="artifact_delta",
        used_artifact_index=False,
        deleted_artifact_dirs=frozenset({str(artifact_dir)}),
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    assert prep.filtered_agents == []


def test_artifact_delta_preserves_cached_clan_context() -> None:
    """An exact joiner-only delta cannot erase reconciled clan context."""
    context = AgentClanContextWire(
        agent_clan="toobig-0",
        agent_clan_generation="g1",
        clan_tribe="chop",
        clan_tribe_source_launch_timestamp="20260701000000",
        clan_tribe_source_identity="/tmp/declarer",
    )
    cached = _make_agent(
        cl_name="toobig-0.joiner",
        raw_suffix="20260701000001",
        status="WAITING",
    )
    cached.agent_clan = "toobig-0"
    cached.agent_clan_generation = "g1"
    cached.clan_context = context
    refreshed = _make_agent(
        cl_name="toobig-0.joiner",
        raw_suffix="20260701000001",
        status="WAITING",
    )
    refreshed.agent_clan = "toobig-0"
    refreshed.agent_clan_generation = "g1"
    refreshed.clan_context = AgentClanContextWire(
        agent_clan="toobig-0",
        agent_clan_generation="g1",
    )
    prep = PreparedApplyData(
        filtered_agents=[refreshed],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    snapshot = _incomplete_tier1_snapshot(
        [cached],
        artifact_source="artifact_delta",
        used_artifact_index=False,
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    assert [agent for agent in prep.filtered_agents if not agent.is_clan_container] == [
        refreshed
    ]
    assert refreshed.clan_context is not None
    assert refreshed.clan_context.clan_tribe == "chop"
    container = project_clan_tree(prep.filtered_agents)[0]
    assert container.clan_tribes == ("chop",)


def test_artifact_delta_retry_projection_survives_cached_family_reattach() -> None:
    """An exact root retry delta must outrank its cached failed coder child."""
    root_timestamp = "20260706115800"
    cached_parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="retry-family",
        project_file="/tmp/test.sase",
        status="FAILED",
        start_time=datetime(2026, 7, 6, 11, 58, 0),
        raw_suffix=root_timestamp,
        role_suffix="--plan",
        plan_action="tale",
        agent_family="retry-family",
        agent_family_role="root",
        plan_chain_root=True,
    )
    cached_coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="retry-family--code",
        project_file="/tmp/test.sase",
        status="FAILED",
        start_time=datetime(2026, 7, 6, 11, 59, 0),
        raw_suffix="20260706115900",
        parent_timestamp=root_timestamp,
        role_suffix="--code",
        agent_family="retry-family",
        agent_family_role="code",
    )
    refreshed_parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="retry-family",
        project_file="/tmp/test.sase",
        status="RETRYING",
        start_time=datetime(2026, 7, 6, 11, 58, 0),
        raw_suffix=root_timestamp,
        role_suffix="--plan",
        plan_action="tale",
        agent_family="retry-family",
        agent_family_role="root",
        plan_chain_root=True,
        runner_is_live=True,
        retry_status="retrying",
        retry_count=2,
        max_retries=3,
        retry_next_at_epoch=1_800_000_000.0,
    )
    prep = PreparedApplyData(
        filtered_agents=[refreshed_parent],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    snapshot = _incomplete_tier1_snapshot(
        [cached_parent, cached_coder],
        artifact_source="artifact_delta",
        used_artifact_index=False,
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    root = next(
        agent
        for agent in prep.filtered_agents
        if agent.raw_suffix == root_timestamp and not agent.is_child_row
    )
    coder = next(
        agent for agent in prep.filtered_agents if agent.agent_family_role == "code"
    )
    assert root is refreshed_parent
    assert root.status == "RETRYING"
    assert (root.retry_count, root.max_retries) == (2, 3)
    assert root.retry_next_at_epoch == 1_800_000_000.0
    assert coder is cached_coder
    assert coder.status == "FAILED"


def test_exact_child_delta_remirrors_tale_family_root_to_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child-only exact delta must remirror the tale root to TALE DONE."""
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    root_ts = "20260828135111"
    code_ts = "20260828140403"
    project_dir = sase_home / "projects" / "home"
    project_file = project_dir / "home.sase"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("NAME: home\n", encoding="utf-8")
    root_dir = project_dir / "artifacts" / "ace-run" / root_ts
    code_dir = project_dir / "artifacts" / "ace-run" / code_ts

    _write_json(
        root_dir / "workflow_state.json",
        {
            "workflow_name": "ace-run",
            "context": {"cl_name": "0fn"},
            "status": "completed",
            "appears_as_agent": True,
            "start_time": "2026-08-28T13:51:11",
            "steps": [],
        },
    )
    _write_json(
        root_dir / "agent_meta.json",
        {
            "name": "0fn",
            "agent_family": "0fn",
            "agent_family_role": "root",
            "plan_chain_root": True,
            "role_suffix": "--plan",
            "plan": True,
            "plan_approved": True,
            "plan_action": "tale",
            "plan_submitted_at": "2026-08-28T14:00:00Z",
            "run_started_at": "2026-08-28T13:51:11Z",
        },
    )
    _write_json(root_dir / "done.json", {"outcome": "completed", "cl_name": "0fn"})
    _write_json(
        code_dir / "running.json",
        {"pid": 4242, "cl_name": "0fn--code"},
    )
    _write_json(
        code_dir / "agent_meta.json",
        {
            "name": "0fn--code",
            "agent_family": "0fn",
            "agent_family_role": "code",
            "role_suffix": "--code",
            "parent_timestamp": root_ts,
            "plan_action": "tale",
            "run_started_at": "2026-08-28T14:04:03Z",
        },
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=True,
        ),
        patch(
            "sase.ace.tui.models._loaders._workflow_loaders.is_process_running",
            return_value=True,
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
    ):
        before, _ = load_artifact_delta_agents(
            [root_dir, code_dir],
            patch_snapshot=[],
            update_index=False,
        )

    by_name = {agent.agent_name: agent for agent in before if agent.agent_name}
    assert by_name["0fn"].status == "WORKING TALE"
    assert by_name["0fn--code"].status == "WORKING TALE"

    (code_dir / "running.json").unlink()
    _write_json(
        code_dir / "done.json",
        {"outcome": "completed", "cl_name": "0fn--code"},
    )

    with (
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.tui.models._loaders._workflow_loaders.is_process_running",
            return_value=False,
        ),
    ):
        incoming, load_state = load_artifact_delta_agents(
            [code_dir],
            patch_snapshot=[],
            update_index=False,
        )

    assert load_state.artifact_source == "artifact_delta"
    prep = PreparedApplyData(
        filtered_agents=list(incoming),
        has_always_visible=False,
        hidden_count=0,
        hideable_agents=list(incoming),
        dismissed_agent_objects=[],
    )
    snapshot = _incomplete_tier1_snapshot(list(before), load_state=load_state)

    merge_incomplete_load_after_complete_history(prep, snapshot)

    merged = {
        agent.agent_name: agent
        for agent in prep.filtered_agents
        if agent.agent_name and not agent.is_clan_container
    }
    assert merged["0fn"].status == "TALE DONE"
    assert merged["0fn--code"].status == "TALE DONE"
