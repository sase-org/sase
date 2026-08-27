"""Phase-5 result wiring tests for the agent loader.

Verifies snapshot forwarding, dismissal and tribe handling, and load-state
telemetry for ``load_agents_from_disk_with_state``.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.patch import Patch
from sase.ace.tui.actions.agents._loading_compute import (
    compute_apply_loaded_agents,
)
from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.data_providers import AgentsProviderSnapshot, AgentsViewport
from sase.ace.tui.data_providers._direct import DirectAgentsDataProvider
from sase.ace.tui.data_providers._snapshots import agent_snapshot
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.util import trace
from tests._agent_loader_helpers import _empty_artifact_snapshot


def load_agents_from_disk(*args, **kwargs):
    result = load_agents_from_disk_with_state(*args, **kwargs)
    return result.all_agents, result.dismissed_from_loader


def _make_snapshot() -> list[Patch]:
    return [
        Patch(
            name="my_cl",
            description="",
            parent=None,
            cl=None,
            status="WIP",
            file_path="/tmp/proj.sase",
            line_number=1,
        )
    ]


def _make_load_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier2",
        complete_history=True,
        artifact_source="source_scan",
        used_artifact_index=False,
    )


def _make_agent(tribe: str | None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="sample-cl",
        project_file="/tmp/myproj/myproj.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 6, 12, 0, 0),
        tribe=tribe,
    )


def _make_done_agent() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="dismissed-import",
        project_file="/tmp/myproj/myproj.sase",
        status="DONE",
        start_time=datetime(2026, 5, 6, 12, 0, 0),
        raw_suffix="20260506120000",
    )


def test_load_agents_from_disk_passes_snapshot_through() -> None:
    snapshot = _make_snapshot()

    with (
        patch("sase.ace.tui.models.agent_loader.find_all_patches") as mock_find,
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.get_workflow_timestamp_dirs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.agent_tribes.load_agent_tribes",
            return_value={},
        ),
        patch(
            "sase.ace.tui.actions.agents._snapshot_cache.AgentSnapshotCache"
            ".dismissed_bundles",
            return_value=[],
        ),
    ):
        load_agents_from_disk_with_state(set(), patch_snapshot=snapshot)

    mock_find.assert_not_called()


def test_load_agents_from_disk_falls_back_to_find_all() -> None:
    with (
        patch(
            "sase.ace.tui.models.agent_loader.find_all_patches",
            return_value=[],
        ) as mock_find,
        patch(
            "sase.ace.tui.models.agent_loader.get_all_project_files",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=_empty_artifact_snapshot(),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_agents_from_running_field",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.get_workflow_timestamp_dirs",
            return_value=[],
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch(
            "sase.ace.agent_tribes.load_agent_tribes",
            return_value={},
        ),
        patch(
            "sase.ace.tui.actions.agents._snapshot_cache.AgentSnapshotCache"
            ".dismissed_bundles",
            return_value=[],
        ),
    ):
        load_agents_from_disk_with_state(set())

    mock_find.assert_called_once()


def test_load_agents_from_disk_preserves_meta_tag_without_persisted_tag() -> None:
    agent = _make_agent("sase-26")

    with (
        patch(
            "sase.ace.tui.models.agent_loader.load_tiered_agents",
            return_value=([agent], _make_load_state()),
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
    ):
        load_result = load_agents_from_disk_with_state(set())

    assert load_result.dismissed_from_loader == []
    assert load_result.all_agents == [agent]
    assert load_result.all_agents[0].tribe == "sase-26"


def test_load_agents_from_disk_persisted_tag_overrides_meta_tag() -> None:
    agent = _make_agent("sase-26")

    with (
        patch(
            "sase.ace.tui.models.agent_loader.load_tiered_agents",
            return_value=([agent], _make_load_state()),
        ),
        patch(
            "sase.ace.agent_tribes.load_agent_tribes",
            return_value={agent.identity: "manual"},
        ),
    ):
        load_result = load_agents_from_disk_with_state(set())

    assert load_result.dismissed_from_loader == []
    assert load_result.all_agents == [agent]
    assert load_result.all_agents[0].tribe == "manual"


def test_source_scan_filters_identity_only_in_dismissed_bundle_index() -> None:
    agent = _make_done_agent()
    state = AgentLoadState(
        tier="tier2",
        complete_history=True,
        artifact_source="source_scan",
        used_artifact_index=False,
    )

    with (
        patch(
            "sase.ace.dismissed_agents.dismissed_bundle_identities_snapshot",
            return_value={agent.identity},
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_tiered_agents",
            return_value=([agent], state),
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
    ):
        result = load_agents_from_disk_with_state(
            set(),
            full_history=True,
            use_artifact_index=False,
        )

    prep = compute_apply_loaded_agents(
        result.all_agents,
        result.dismissed_from_loader,
        set(),
        False,
        dismissed_bundle_snapshot=result.dismissed_bundle_identities,
    )

    assert result.dismissed_from_loader == [agent]
    assert prep.filtered_agents == []


def test_index_backed_snapshot_matches_bundle_only_source_scan_filter() -> None:
    agent = _make_done_agent()
    state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )

    with (
        patch(
            "sase.ace.dismissed_agents.dismissed_bundle_identities_snapshot",
            return_value={agent.identity},
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_tiered_agents",
            return_value=([], state),
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
    ):
        result = load_agents_from_disk_with_state(set())

    prep = compute_apply_loaded_agents(
        result.all_agents,
        result.dismissed_from_loader,
        set(),
        False,
        dismissed_bundle_snapshot=result.dismissed_bundle_identities,
    )

    assert result.dismissed_from_loader == []
    assert prep.filtered_agents == []


def test_load_from_disk_span_carries_load_state_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ``agents.load_from_disk`` span records the AgentLoadState fields."""

    log = tmp_path / "trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(log))
    trace._context.clear()

    agent = _make_agent("sase-26")
    load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        index_error=None,
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.load_tiered_agents",
            return_value=([agent], load_state),
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
    ):
        load_agents_from_disk_with_state(set(), source="manual")

    rows = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    span_rows = [r for r in rows if r.get("span") == "agents.load_from_disk"]
    assert len(span_rows) == 1
    row = span_rows[0]
    assert row["source"] == "manual"
    assert row["full_history"] is False
    assert row["tier"] == "tier1"
    assert row["artifact_source"] == "artifact_index"
    assert row["complete_history"] is False
    assert row["complete_visible_inbox"] is True
    assert row["repair_recommended"] is False
    assert row["repair_reason"] is None
    assert row["truncated"] is False
    assert row["used_artifact_index"] is True
    assert row["index_error"] is None


def test_load_agents_from_disk_uses_data_provider() -> None:
    agent = _make_agent("sase-26")
    load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        bounded_prefix=True,
        requested_limit=13,
        returned_count=1,
        has_more=True,
    )
    shared_snapshot = agent_snapshot(
        [agent],
        provider_source="direct",
        prefers_daemon=False,
        fallback_reason=None,
        fallback_message=None,
        snapshot_id="snap-1",
        page_count=1,
        full_reload=True,
    )
    provider_snapshot = AgentsProviderSnapshot(
        agents=[agent],
        workflow_agent_steps=[],
        load_state=load_state,
        shared_snapshot=shared_snapshot,
    )
    calls: list[dict[str, object]] = []

    class Provider:
        prefers_daemon = False

        def load_agents(self, **kwargs: object) -> AgentsProviderSnapshot:
            calls.append(kwargs)
            return provider_snapshot

    viewport = AgentsViewport(start_row=3, visible_rows=4, prefetch_rows=6)
    with (
        patch(
            "sase.ace.dismissed_agents.dismissed_bundle_identities_snapshot",
            return_value=set(),
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
    ):
        result = load_agents_from_disk_with_state(
            set(),
            patch_snapshot=[],
            search_query="project:sase",
            viewport=viewport,
            data_provider=Provider(),
        )

    assert result.provider_snapshot is provider_snapshot
    assert result.all_agents == [agent]
    assert calls == [
        {
            "patch_snapshot": [],
            "full_history": False,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "search_query": "project:sase",
            "viewport": viewport,
        }
    ]


def test_direct_agents_provider_forwards_viewport_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _make_agent("sase-26")
    load_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        bounded_prefix=True,
        requested_limit=15,
        returned_count=1,
        has_more=True,
    )
    calls: list[dict[str, object]] = []

    def fake_load_tiered_agents(**kwargs: object) -> tuple[list[Agent], AgentLoadState]:
        calls.append(kwargs)
        return [agent], load_state

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader.load_tiered_agents",
        fake_load_tiered_agents,
    )

    viewport = AgentsViewport(start_row=5, visible_rows=4, prefetch_rows=6)
    snapshot = DirectAgentsDataProvider().load_agents(
        patch_snapshot=[],
        full_history=False,
        index_freshness="cached",
        search_query="model:opus",
        viewport=viewport,
    )

    assert calls == [
        {
            "patch_snapshot": [],
            "full_history": False,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "search_query": "model:opus",
            "requested_limit": 15,
        }
    ]
    assert snapshot.load_state is load_state
    assert snapshot.shared_snapshot.metadata["requested_limit"] == 15
    assert snapshot.shared_snapshot.metadata["returned_count"] == 1
    assert snapshot.shared_snapshot.metadata["has_more"] is True
    assert snapshot.shared_snapshot.metadata["bounded_prefix"] is True
    assert snapshot.shared_snapshot.metadata["query"] == "model:opus"
    assert snapshot.shared_snapshot.metadata["surfaces"] == ["list"]
