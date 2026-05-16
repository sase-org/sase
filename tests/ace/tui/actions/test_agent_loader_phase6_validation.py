"""Phase 6 end-to-end validation tests for the Agents-tab disk loader.

Phase 6 of bead ``sase-3r`` (Fast Agents Tab Disk Loading) is the
end-to-end perf validation step. The earlier phases moved the loader to
the visibility-aware Tier 1 inbox query and removed source-tree walks
from the missing-index path. These tests lock in the deliverable from
the Phase 6 plan:

    Assert normal refresh does not call source scanning when the index
    is present or rebuilding.

The performance numbers themselves live in
``tests/perf/bench_agent_loader_phase6_inbox.py`` (marked ``slow``).
This module owns the structural assertions so a future regression that
re-introduces a source scan into the ordinary Agents-tab refresh fails
loudly in the default ``just test`` run.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._loading_helpers import (
    load_agents_from_disk_with_state,
)
from sase.ace.tui.models.agent_loader import (
    _artifact_snapshot_for_tui_load,
    _query_artifact_index_for_loader,
)
from sase.core.agent_scan_facade import (
    query_agent_artifact_index,
    rebuild_agent_artifact_index,
    replace_dismissed_agent_visibility,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    DismissedAgentIdentityWire,
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


def _populate_fixture(projects_root: Path) -> None:
    """Materialize a tiny projects tree the Rust index can rebuild against."""

    ace_run = projects_root / "home" / "artifacts" / "ace-run"
    ace_run.mkdir(parents=True, exist_ok=True)
    (projects_root / "home" / "home.sase").write_text("", encoding="utf-8")
    for i, ts in enumerate(("20260101000000", "20260101000001")):
        artifact_dir = ace_run / ts
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / "agent_meta.json").write_text(
            json.dumps({"name": f"agent_{i}", "model": "claude-opus-4-7"}),
            encoding="utf-8",
        )
        (artifact_dir / "done.json").write_text(
            json.dumps(
                {
                    "outcome": "completed",
                    "finished_at": 100.0 + i,
                    "cl_name": f"cl_{i}",
                    "name": f"agent_{i}",
                    "model": "claude-opus-4-7",
                }
            ),
            encoding="utf-8",
        )


# ---------------------------------------------------------------------------
# Index present: no source scan
# ---------------------------------------------------------------------------


def test_normal_refresh_with_present_index_never_calls_source_scan(
    tmp_path: Path,
) -> None:
    """End-to-end: index-backed inbox refresh stays off the source-scan path.

    Builds a real on-disk index from a small fixture and drives
    ``load_agents_from_disk_with_state`` exactly like a normal Agents-tab
    refresh (``full_history=False``, no search). The bench in
    ``tests/perf/bench_agent_loader_phase6_inbox.py`` measures the
    latency improvement at scale; this test owns the contract — the
    Tier 2 source-tree walk must not run on ordinary refreshes.
    """

    projects_root = tmp_path / "projects"
    _populate_fixture(projects_root)
    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, projects_root)

    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
                return_value=index_path,
            )
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader._projects_root_for_loader",
                return_value=projects_root,
            )
        )
        mock_scan = stack.enter_context(
            patch("sase.ace.tui.models.agent_loader._scan_artifacts_for_loader")
        )
        _enter_empty_sources(stack)
        result = load_agents_from_disk_with_state(
            set(),
            full_history=False,
            agent_search_active=False,
        )

    state = result.load_state
    assert state.tier == "tier1"
    assert state.artifact_source == "artifact_index"
    assert state.used_artifact_index is True
    assert state.index_missing is False
    assert state.needs_full_history_reconcile is False
    mock_scan.assert_not_called()


def test_normal_refresh_during_index_rebuild_does_not_source_scan(
    tmp_path: Path,
) -> None:
    """Refreshing while the index is being rebuilt also stays off source scan.

    "Rebuilding" in production means the sqlite file is briefly absent or
    incomplete — the apply layer schedules a background rebuild and the
    loader reports ``index_missing=True`` instead of falling back to a
    Tier 2 source-tree walk. This test pins that behavior so a future
    refactor cannot accidentally restore the historical bounded-source
    fallback on missing-index.
    """

    missing_index = tmp_path / "agent_artifact_index.sqlite"
    # Caller-supplied projects root is empty; if the loader did source-scan
    # this would surface as a non-zero scan call below.
    projects_root = tmp_path / "projects"
    projects_root.mkdir()

    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader.default_agent_artifact_index_path",
                return_value=missing_index,
            )
        )
        stack.enter_context(
            patch(
                "sase.ace.tui.models.agent_loader._projects_root_for_loader",
                return_value=projects_root,
            )
        )
        mock_scan = stack.enter_context(
            patch("sase.ace.tui.models.agent_loader._scan_artifacts_for_loader")
        )
        _enter_empty_sources(stack)
        result = load_agents_from_disk_with_state(
            set(),
            full_history=False,
            agent_search_active=False,
        )

    state = result.load_state
    assert state.tier == "tier1"
    assert state.artifact_source == "artifact_index"
    assert state.used_artifact_index is False
    assert state.index_missing is True
    assert state.needs_full_history_reconcile is False
    mock_scan.assert_not_called()


# ---------------------------------------------------------------------------
# Dismissed completions are excluded by the inbox query
# ---------------------------------------------------------------------------


def test_inbox_query_excludes_dismissed_completions_end_to_end(
    tmp_path: Path,
) -> None:
    """Phase 6 sanity: dismissal filtering survives the loader's sync step.

    Mirrors the Phase 6 fixture in
    ``bench_agent_loader_phase6_inbox.py`` at miniature scale: build the
    index, sync a dismissed identity into the sidecar via the legacy
    ``dismissed_agents.json`` file (which the loader replays on every
    inbox query), and confirm the visibility-aware query returns only
    the non-dismissed row. This is the qualitative contract behind the
    bench's latency numbers — the index, not a source scan, is doing
    the work.
    """

    fake_home = tmp_path / "home"
    projects_root = fake_home / ".sase" / "projects"
    _populate_fixture(projects_root)
    index_path = fake_home / ".sase" / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, projects_root)
    replace_dismissed_agent_visibility(
        index_path,
        [
            DismissedAgentIdentityWire(
                agent_type="run",
                cl_name="cl_0",
                raw_suffix="20260101000000",
            )
        ],
    )

    # Write the legacy file with the same dismissed identity so the
    # loader's signature-gated ``maybe_sync_dismissed_from_file`` step
    # does not wipe the sidecar with an empty list.
    (fake_home / ".sase" / "dismissed_agents.json").write_text(
        json.dumps([["run", "cl_0", "20260101000000"]]),
        encoding="utf-8",
    )

    # Reset the per-process signature cache so this test re-reads the file.
    from sase.core import agent_artifact_index_maintenance as _maint

    _maint._last_dismissed_signature = _maint._DISMISSED_SIGNATURE_UNSET

    with (
        patch("pathlib.Path.home", return_value=fake_home),
        patch(
            "sase.ace.tui.models.agent_loader._scan_artifacts_for_loader",
        ) as mock_scan,
    ):
        result = _query_artifact_index_for_loader(
            full_history=False, agent_search_active=False
        )

    assert result is not None
    snapshot, state = result
    timestamps = {record.timestamp for record in snapshot.records}
    assert "20260101000000" not in timestamps  # dismissed
    assert "20260101000001" in timestamps  # not dismissed
    assert state.used_artifact_index is True
    mock_scan.assert_not_called()


def test_explicit_full_history_still_runs_source_scan_after_phase6(
    tmp_path: Path,
) -> None:
    """``full_history=True`` (revive / archive / repair) keeps its Tier 2 scan.

    Phase 6 only removes source scans from the *ordinary* refresh path.
    Revive, archive search, and doctor/repair flows still need a full
    historical view; this test guards against an over-eager cleanup that
    would also delete those Tier 2 paths.
    """

    fake_home = tmp_path / "home"
    projects_root = fake_home / ".sase" / "projects"
    _populate_fixture(projects_root)
    index_path = fake_home / ".sase" / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, projects_root)

    # Drive _artifact_snapshot_for_tui_load directly so we observe the
    # real ``scan_agent_artifacts`` call, not a patched-out seam.
    with patch("pathlib.Path.home", return_value=fake_home):
        snapshot, state = _artifact_snapshot_for_tui_load(
            full_history=True, agent_search_active=False
        )

    assert state.tier == "tier2"
    assert state.full_history is True
    assert state.complete_history is True
    assert state.artifact_source == "source_scan"
    assert state.used_artifact_index is False
    assert len(snapshot.records) == 2


# ---------------------------------------------------------------------------
# Inbox query latency on the smoke-scale fixture
# ---------------------------------------------------------------------------


def test_inbox_query_returns_only_visible_records_after_dismissal_sync(
    tmp_path: Path,
) -> None:
    """End-to-end query call shape mirrors the Phase 6 bench harness.

    The bench is marked ``slow`` and runs only on request; this unit
    test calls ``query_agent_artifact_index`` directly with the same
    visibility-aware query the loader uses, so a Rust-side regression in
    the dismissal filter is caught by the default test run.
    """

    projects_root = tmp_path / "projects"
    _populate_fixture(projects_root)
    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, projects_root)
    replace_dismissed_agent_visibility(
        index_path,
        [
            DismissedAgentIdentityWire(
                agent_type="run",
                cl_name="cl_1",
                raw_suffix="20260101000001",
            )
        ],
    )

    inbox_query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=False,
        recent_completed_limit=None,
        include_hidden=False,
        include_dismissed=False,
    )
    snapshot = query_agent_artifact_index(index_path, projects_root, query=inbox_query)
    timestamps = {record.timestamp for record in snapshot.records}
    assert timestamps == {"20260101000000"}
