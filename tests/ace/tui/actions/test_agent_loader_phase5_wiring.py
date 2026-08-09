"""Phase-5 wiring tests for the agent loader.

Verifies that ``load_agents_from_disk_with_state`` accepts a pre-fetched
ChangeSpec snapshot and forwards it through to ``load_all_agents`` so the
loader does not call ``find_all_patches()`` itself.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.changespec import ChangeSpec
from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.actions.agents._loading_compute import (
    compute_apply_loaded_agents,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import (
    AgentLoadState,
    _artifact_snapshot_for_tui_load,
)
from sase.ace.tui.util import trace
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from tests._agent_loader_helpers import _empty_artifact_snapshot


def load_agents_from_disk(*args, **kwargs):
    result = load_agents_from_disk_with_state(*args, **kwargs)
    return result.all_agents, result.dismissed_from_loader


def _make_snapshot() -> list[ChangeSpec]:
    return [
        ChangeSpec(
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


def _make_artifact_record(index: int) -> AgentArtifactRecordWire:
    timestamp = f"20260519{index % 1000000:06d}"
    return AgentArtifactRecordWire(
        project_name="proj",
        project_dir="/tmp/projects/proj",
        project_file="/tmp/projects/proj/proj.gp",
        workflow_dir_name="ace-run",
        artifact_dir=f"/tmp/projects/proj/artifacts/ace-run/{timestamp}",
        timestamp=timestamp,
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
        load_agents_from_disk_with_state(set(), changespec_snapshot=snapshot)

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


def test_load_agents_from_disk_uses_artifact_index_for_initial_tier(
    tmp_path,
) -> None:
    """Initial TUI loads query the artifact index instead of scanning history."""

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = _empty_artifact_snapshot()

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            return_value=snapshot,
        ) as mock_query,
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=snapshot,
        ) as mock_scan,
        patch(
            "sase.ace.tui.models.agent_loader.find_all_patches",
            return_value=[],
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
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
    ):
        result = load_agents_from_disk_with_state(set())

    assert result.all_agents == []
    assert result.load_state.used_artifact_index is True
    assert result.load_state.complete_history is False
    assert result.load_state.complete_visible_inbox is True
    assert result.load_state.needs_full_history_reconcile is False
    mock_query.assert_called_once()
    mock_scan.assert_not_called()
    query = mock_query.call_args.kwargs["query"]
    assert query.include_active is True
    assert query.include_recent_completed is True
    assert query.include_full_history is False
    assert query.active_limit == 1000
    assert query.recent_completed_limit == 200
    assert query.include_hidden is False


def test_tier1_large_index_result_does_not_fan_out_to_source_scan(
    tmp_path: Path,
) -> None:
    """Tier 1 keeps filesystem fan-out behind the index query boundary."""

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = _empty_artifact_snapshot()
    snapshot.records.extend(_make_artifact_record(i) for i in range(10_000))

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            return_value=snapshot,
        ) as mock_query,
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
        ) as mock_scan,
    ):
        loaded_snapshot, load_state = _artifact_snapshot_for_tui_load(
            full_history=False
        )

    assert loaded_snapshot is snapshot
    assert len(loaded_snapshot.records) == 10_000
    assert load_state.artifact_source == "artifact_index"
    assert load_state.used_artifact_index is True
    assert load_state.complete_visible_inbox is True
    assert load_state.complete_history is False
    assert load_state.needs_full_history_reconcile is False
    mock_query.assert_called_once()
    mock_scan.assert_not_called()


def test_load_agents_from_disk_full_history_reconciles_from_source() -> None:
    """Full-history refreshes use source artifacts so stale indexes cannot persist."""

    snapshot = _empty_artifact_snapshot()

    with (
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            return_value=snapshot,
        ) as mock_query,
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=snapshot,
        ) as mock_scan,
        patch(
            "sase.ace.tui.models.agent_loader.find_all_patches",
            return_value=[],
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
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
    ):
        result = load_agents_from_disk_with_state(set(), full_history=True)

    assert result.load_state.complete_history is True
    assert result.load_state.complete_visible_inbox is True
    assert result.load_state.artifact_source == "source_scan"
    assert result.load_state.used_artifact_index is False
    mock_query.assert_not_called()
    mock_scan.assert_called_once()


def test_load_agents_from_disk_missing_index_uses_bounded_tier1_source_scan(
    tmp_path,
) -> None:
    """Missing artifact indexes do not force a full source scan before first paint."""

    index_path = tmp_path / "missing_agent_artifact_index.sqlite"
    snapshot = _empty_artifact_snapshot()

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=snapshot,
        ) as mock_scan,
        patch(
            "sase.ace.tui.models.agent_loader.find_all_patches",
            return_value=[],
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
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
    ):
        result = load_agents_from_disk_with_state(set())

    assert result.load_state.tier == "tier1"
    assert result.load_state.complete_history is False
    assert result.load_state.complete_visible_inbox is False
    assert result.load_state.artifact_source == "source_scan"
    assert result.load_state.repair_recommended is True
    assert result.load_state.repair_reason == "artifact_index_missing_bounded_fallback"
    options = mock_scan.call_args.args[0]
    assert options.max_records == 200
    assert options.newest_first is True


def test_load_agents_from_disk_bad_index_uses_bounded_tier1_source_scan(
    tmp_path: Path,
) -> None:
    """Unreadable or stale indexes fall back without scanning full history."""

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = _empty_artifact_snapshot()

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            side_effect=RuntimeError("stale schema"),
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=snapshot,
        ) as mock_scan,
        patch(
            "sase.ace.tui.models.agent_loader.find_all_patches",
            return_value=[],
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
            "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
            return_value=([], {}),
        ),
        patch(
            "sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot",
            return_value=[],
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
    ):
        result = load_agents_from_disk_with_state(set())

    assert result.load_state.tier == "tier1"
    assert result.load_state.complete_history is False
    assert result.load_state.complete_visible_inbox is False
    assert result.load_state.artifact_source == "source_scan"
    assert result.load_state.used_artifact_index is False
    assert result.load_state.index_error == "stale schema"
    assert result.load_state.repair_recommended is True
    assert (
        result.load_state.repair_reason
        == "artifact_index_query_failed_bounded_fallback"
    )
    options = mock_scan.call_args.args[0]
    assert options.max_records == 200
    assert options.newest_first is True


def test_explicit_index_bypass_uses_bounded_scan_without_repair_reaction() -> None:
    snapshot = _empty_artifact_snapshot()

    with (
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            side_effect=AssertionError("bypassed index must not be queried"),
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=snapshot,
        ) as mock_scan,
    ):
        loaded_snapshot, state = _artifact_snapshot_for_tui_load(
            full_history=False,
            use_artifact_index=False,
        )

    assert loaded_snapshot is snapshot
    assert state.artifact_source == "source_scan"
    assert state.complete_visible_inbox is False
    assert state.used_artifact_index is False
    assert state.repair_recommended is False
    options = mock_scan.call_args.args[0]
    assert options.max_records == 200
    assert options.newest_first is True


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
