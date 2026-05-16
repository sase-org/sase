"""Phase 1 measurement and guardrail tests for ``sase-3r``.

These tests pin down the contract of the tiered agent loader for the
Phase 1 measurement scaffolding and the Phase 3 visibility-aware inbox
refactor:

* The ``AgentLoadState`` measurement fields (``full_history``,
  ``agent_search_active``, snapshot stats, loaded row counts,
  ``index_missing``) are populated by every code path.
* A non-empty Agents-tab search query no longer promotes the load to
  Tier 2; the visibility-aware Tier 1 inbox query handles search by
  filtering the cached working set instead. (Updated in Phase 3 of
  ``sase-3r``.)
* A missing artifact index returns an empty Tier 1 snapshot with
  ``index_missing=True`` so the apply layer can schedule a one-off
  rebuild — the loader no longer performs a bounded source scan when
  the index file is absent. (Updated in Phase 3 of ``sase-3r``.)
* An exception from the index query still falls back to a bounded
  source scan and reports the exception message in ``index_error``.
* The ``agents.load_from_disk`` ``tui_trace`` span is enriched with the
  same measurement fields as ``AgentLoadState``.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.models.agent_loader import (
    AgentLoadState,
    _artifact_snapshot_for_tui_load,
    _query_artifact_index_for_loader,
)
from sase.core.agent_scan_wire import (
    AGENT_SCAN_WIRE_SCHEMA_VERSION,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)


def _snapshot_with_stats(
    *,
    records: int = 0,
    artifact_dirs_visited: int = 0,
    marker_files_parsed: int = 0,
    prompt_step_markers_parsed: int = 0,
) -> AgentArtifactScanWire:
    """Build a wire snapshot with concrete (non-default) stats counters."""

    return AgentArtifactScanWire(
        schema_version=AGENT_SCAN_WIRE_SCHEMA_VERSION,
        projects_root="",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(
            artifact_dirs_visited=artifact_dirs_visited,
            marker_files_parsed=marker_files_parsed,
            prompt_step_markers_parsed=prompt_step_markers_parsed,
        ),
        records=[None] * records,  # type: ignore[list-item]
    )


_SOURCE_PATCH_TARGETS: tuple[tuple[str, object], ...] = (
    ("sase.ace.tui.models.agent_loader.find_all_changespecs", []),
    ("sase.ace.tui.models.agent_loader.get_all_project_files", []),
    ("sase.ace.tui.models.agent_loader.load_done_agents_from_snapshot", []),
    ("sase.ace.tui.models.agent_loader.load_running_home_agents_from_snapshot", []),
    ("sase.ace.tui.models.agent_loader.load_agents_from_running_field", []),
    (
        "sase.ace.tui.models.agent_loader.load_workflow_agent_steps_from_snapshot",
        ([], {}),
    ),
    ("sase.ace.tui.models.agent_loader.load_workflow_agents_from_snapshot", []),
    ("sase.ace.agent_tags.load_agent_tags", {}),
)


def _enter_empty_sources(stack: contextlib.ExitStack) -> None:
    for target, value in _SOURCE_PATCH_TARGETS:
        stack.enter_context(patch(target, return_value=value))


# ---------------------------------------------------------------------------
# AgentLoadState defaults
# ---------------------------------------------------------------------------


def test_agent_load_state_phase1_fields_default_to_neutral_values() -> None:
    """The new measurement fields default to neutral values for old callers."""

    state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="source_scan",
        used_artifact_index=False,
    )
    assert state.full_history is False
    assert state.agent_search_active is False
    assert state.snapshot_records == 0
    assert state.loaded_agent_count == 0
    assert state.loaded_workflow_step_count == 0
    assert state.artifact_dirs_visited is None
    assert state.marker_files_parsed is None
    assert state.prompt_step_markers_parsed is None
    assert state.index_missing is False


def test_trace_fields_contain_every_phase1_measurement_key() -> None:
    """``AgentLoadState.trace_fields`` exposes every phase-1 measurement key."""

    state = AgentLoadState(
        tier="tier2",
        complete_history=True,
        artifact_source="source_scan",
        used_artifact_index=False,
        full_history=True,
        agent_search_active=True,
        snapshot_records=7,
        loaded_agent_count=4,
        loaded_workflow_step_count=2,
        artifact_dirs_visited=42,
        marker_files_parsed=99,
        prompt_step_markers_parsed=11,
    )
    fields = state.trace_fields()
    assert fields == {
        "tier": "tier2",
        "complete_history": True,
        "artifact_source": "source_scan",
        "used_artifact_index": False,
        "index_error": None,
        "full_history": True,
        "agent_search_active": True,
        "snapshot_records": 7,
        "loaded_agent_count": 4,
        "loaded_workflow_step_count": 2,
        "artifact_dirs_visited": 42,
        "marker_files_parsed": 99,
        "prompt_step_markers_parsed": 11,
        "index_missing": False,
    }


# ---------------------------------------------------------------------------
# Tier selection / snapshot stats
# ---------------------------------------------------------------------------


def test_index_path_load_records_snapshot_stats_and_no_full_history(
    tmp_path: Path,
) -> None:
    """Index-backed tier-1 loads populate snapshot stats and clear full_history."""

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = _snapshot_with_stats(
        records=3,
        artifact_dirs_visited=12,
        marker_files_parsed=34,
        prompt_step_markers_parsed=5,
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            return_value=snapshot,
        ),
    ):
        result = _query_artifact_index_for_loader(
            full_history=False, agent_search_active=False
        )

    assert result is not None
    _, state = result
    assert state.tier == "tier1"
    assert state.artifact_source == "artifact_index"
    assert state.used_artifact_index is True
    assert state.full_history is False
    assert state.agent_search_active is False
    assert state.snapshot_records == 3
    assert state.artifact_dirs_visited == 12
    assert state.marker_files_parsed == 34
    assert state.prompt_step_markers_parsed == 5


def test_full_history_path_sets_full_history_and_complete_history() -> None:
    """Tier 2 source scans flag ``full_history`` and ``complete_history``."""

    snapshot = _snapshot_with_stats(records=8, artifact_dirs_visited=42)
    with patch(
        "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
        return_value=snapshot,
    ):
        _, state = _artifact_snapshot_for_tui_load(
            full_history=True, agent_search_active=False
        )
    assert state.tier == "tier2"
    assert state.full_history is True
    assert state.complete_history is True
    assert state.snapshot_records == 8
    assert state.artifact_dirs_visited == 42


def test_load_tiered_agents_records_loaded_row_counts() -> None:
    """``load_tiered_agents`` populates ``loaded_agent_count`` from the result."""

    from sase.ace.tui.models.agent_loader import load_tiered_agents

    snapshot = _snapshot_with_stats(records=2, artifact_dirs_visited=2)
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
                return_value=snapshot,
            )
        )
        _enter_empty_sources(stack)
        agents, state = load_tiered_agents(full_history=True)
    assert agents == []
    assert state.loaded_agent_count == 0
    assert state.loaded_workflow_step_count == 0
    assert state.snapshot_records == 2
    assert state.full_history is True


# ---------------------------------------------------------------------------
# Search-forces-Tier-2 contract
# ---------------------------------------------------------------------------


def test_agent_search_active_no_longer_forces_full_history_loader_contract(
    tmp_path: Path,
) -> None:
    """An active search query filters the Tier 1 inbox instead of forcing Tier 2.

    Phase 3 of bead ``sase-3r`` (Fast Agents Tab Disk Loading) demotes the
    "search forces full history" behavior to "search filters the cached
    inbox." With a present index and a non-empty Agents-tab search query,
    the loader stays on the visibility-aware Tier 1 inbox path and never
    triggers a source-tree scan.
    """

    index_path = tmp_path / "index.sqlite"
    index_path.touch()
    indexed_snapshot = _snapshot_with_stats(records=1, artifact_dirs_visited=5)
    with contextlib.ExitStack() as stack:
        mock_scan = stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            )
        )
        mock_query = stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
                return_value=indexed_snapshot,
            )
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
                return_value=index_path,
            )
        )
        _enter_empty_sources(stack)
        result = load_agents_from_disk_with_state(
            set(),
            full_history=False,
            agent_search_active=True,
        )

    state = result.load_state
    assert state.agent_search_active is True
    assert state.full_history is False
    assert state.tier == "tier1"
    assert state.complete_history is False
    assert state.artifact_source == "artifact_index"
    assert state.used_artifact_index is True
    mock_scan.assert_not_called()
    mock_query.assert_called_once()


def test_full_history_request_takes_priority_over_search_flag() -> None:
    """Explicit ``full_history=True`` keeps Tier 2 even with no active search."""

    snapshot = _snapshot_with_stats(records=0)
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
                return_value=snapshot,
            )
        )
        _enter_empty_sources(stack)
        result = load_agents_from_disk_with_state(
            set(),
            full_history=True,
            agent_search_active=False,
        )
    assert result.load_state.full_history is True
    assert result.load_state.agent_search_active is False
    assert result.load_state.tier == "tier2"


# ---------------------------------------------------------------------------
# Missing-index / index-error fallback
# ---------------------------------------------------------------------------


def test_missing_index_returns_empty_snapshot_without_source_scan(
    tmp_path: Path,
) -> None:
    """A missing artifact index returns an empty snapshot — no source scan.

    Phase 3 of bead ``sase-3r`` (Fast Agents Tab Disk Loading). Normal
    Agents-tab refreshes must not trigger a source-tree walk when the
    persistent index is absent — the apply layer schedules a one-off
    rebuild and the cached working set stays visible via the existing
    incomplete-load merge. The load state surfaces this with
    ``index_missing=True`` and zero snapshot stats.
    """

    missing_index = tmp_path / "missing_agent_artifact_index.sqlite"

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=missing_index,
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
        ) as mock_scan,
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
        ) as mock_query,
    ):
        snapshot, state = _artifact_snapshot_for_tui_load(
            full_history=False, agent_search_active=False
        )

    assert state.tier == "tier1"
    assert state.complete_history is False
    assert state.artifact_source == "artifact_index"
    assert state.used_artifact_index is False
    assert state.index_error is None
    assert state.index_missing is True
    assert state.snapshot_records == 0
    assert snapshot.records == []
    mock_scan.assert_not_called()
    mock_query.assert_not_called()


def test_index_query_error_falls_back_with_stringified_error(tmp_path: Path) -> None:
    """An index query exception falls back to a bounded source scan."""

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    fallback = _snapshot_with_stats(records=2, artifact_dirs_visited=9)

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            side_effect=RuntimeError("index corrupt"),
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=fallback,
        ) as mock_scan,
    ):
        _, state = _artifact_snapshot_for_tui_load(
            full_history=False, agent_search_active=False
        )

    assert state.tier == "tier1"
    assert state.artifact_source == "source_scan"
    assert state.used_artifact_index is False
    assert state.index_error == "index corrupt"
    assert state.snapshot_records == 2
    assert state.artifact_dirs_visited == 9
    options = mock_scan.call_args.args[0]
    assert options.max_records == 200


@pytest.mark.parametrize(
    "exc",
    [
        OSError("permission denied"),
        ImportError("rust binding missing"),
        ValueError("schema mismatch"),
        AttributeError("missing function"),
    ],
)
def test_index_query_error_uniformly_falls_back(tmp_path: Path, exc: Exception) -> None:
    """All anticipated index-query exception classes hit the source-scan fallback."""

    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    fallback = _snapshot_with_stats(records=0)

    with (
        patch(
            "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
            return_value=index_path,
        ),
        patch(
            "sase.ace.tui.models.agent_loader.query_agent_artifact_index",
            side_effect=exc,
        ),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
            return_value=fallback,
        ),
    ):
        _, state = _artifact_snapshot_for_tui_load(
            full_history=False, agent_search_active=False
        )
    assert state.used_artifact_index is False
    assert state.index_error is not None
    assert str(exc) in state.index_error


# ---------------------------------------------------------------------------
# Trace span enrichment
# ---------------------------------------------------------------------------


def test_load_from_disk_trace_records_phase1_measurement_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``agents.load_from_disk`` writes the phase-1 measurement fields to the trace."""

    trace_path = tmp_path / "tui_trace.jsonl"
    monkeypatch.setenv("SASE_TUI_TRACE", "1")
    monkeypatch.setenv("SASE_TUI_TRACE_PATH", str(trace_path))

    snapshot = _snapshot_with_stats(
        records=3,
        artifact_dirs_visited=11,
        marker_files_parsed=22,
        prompt_step_markers_parsed=4,
    )
    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
                return_value=snapshot,
            )
        )
        _enter_empty_sources(stack)
        load_agents_from_disk_with_state(
            set(),
            full_history=True,
            agent_search_active=False,
        )

    lines = [
        json.loads(line) for line in trace_path.read_text().splitlines() if line.strip()
    ]
    load_records = [r for r in lines if r.get("span") == "agents.load_from_disk"]
    assert load_records, "expected agents.load_from_disk trace record"
    record = load_records[-1]
    for key in (
        "tier",
        "complete_history",
        "artifact_source",
        "used_artifact_index",
        "index_error",
        "full_history",
        "agent_search_active",
        "snapshot_records",
        "loaded_agent_count",
        "loaded_workflow_step_count",
        "artifact_dirs_visited",
        "marker_files_parsed",
        "prompt_step_markers_parsed",
    ):
        assert key in record, f"trace record missing field {key!r}: {record!r}"
    assert record["tier"] == "tier2"
    assert record["full_history"] is True
    assert record["snapshot_records"] == 3
    assert record["artifact_dirs_visited"] == 11
