"""Phase 3E: `listing_snapshot` index query and source-scan fallback.

These tests pin bounded index queries (project pushdown, window limits)
and the missing/empty-index fallback onto a source scan.
"""

from __future__ import annotations

from pathlib import Path

from sase.agent.listing_snapshot import listing_snapshot
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactIndexStatusWire,
    AgentArtifactIndexWindowWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
)
from tests._running_agents_snapshot_helpers import (
    synthetic_record,
    synthetic_snapshot,
)


def test_listing_snapshot_uses_bounded_index_query_with_project_pushdown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    snapshot = AgentArtifactScanWire(
        schema_version=1,
        projects_root=str(tmp_path),
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        index_window=AgentArtifactIndexWindowWire(
            requested_limit=25,
            selected_candidate_count=3,
            returned_record_count=2,
            active_candidate_count=1,
            completed_candidate_count=2,
            has_more=True,
        ),
        records=[],
    )
    calls: list[
        tuple[
            Path,
            Path,
            AgentArtifactIndexQueryWire,
            AgentArtifactScanOptionsWire,
        ]
    ] = []

    def fake_query_agent_artifact_index(
        path: Path,
        projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire:
        calls.append((path, projects_root, query, options))
        return snapshot

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.default_agent_artifact_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(
        "sase.core.agent_scan_facade.query_agent_artifact_index",
        fake_query_agent_artifact_index,
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot.sase_projects_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot._scan_listing_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("source scan should not run when index query succeeds")
        ),
    )

    loaded, state = listing_snapshot(
        project="proj",
        index_freshness="revalidate",
        requested_limit=25,
    )

    assert loaded is snapshot
    assert state.used_artifact_index is True
    assert state.bounded_prefix is True
    assert state.requested_limit == 25
    assert state.returned_count == 2
    assert state.has_more is True
    [(path, projects_root, query, options)] = calls
    assert path == index_path
    assert projects_root == tmp_path
    assert query.include_active is True
    assert query.include_recent_completed is True
    assert query.include_full_history is False
    assert query.active_limit == 1000
    assert query.recent_completed_limit == 200
    assert query.include_hidden is False
    assert query.freshness == "revalidate"
    assert query.record_shape == "list"
    assert query.window_limit == 25
    assert query.candidate_filter == {
        "kind": "equals",
        "field": "project",
        "value": "proj",
    }
    assert options.only_projects == ("proj",)
    assert options.only_workflow_dirs == ("ace-run",)
    assert options.include_prompt_step_markers is False


def test_listing_snapshot_missing_index_uses_bounded_source_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    snapshot = synthetic_snapshot(tmp_path, [])
    scan_options: list[AgentArtifactScanOptionsWire | None] = []

    def fake_scan_listing_snapshot(
        options: AgentArtifactScanOptionsWire | None = None,
    ) -> AgentArtifactScanWire:
        scan_options.append(options)
        return snapshot

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.default_agent_artifact_index_path",
        lambda: tmp_path / "missing.sqlite",
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot.sase_projects_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot._scan_listing_snapshot",
        fake_scan_listing_snapshot,
    )

    loaded, state = listing_snapshot(project="proj")

    assert loaded is snapshot
    assert state.artifact_source == "source_scan"
    assert state.used_artifact_index is False
    assert state.repair_recommended is True
    assert state.repair_reason == "artifact_index_missing_bounded_fallback"
    [options] = scan_options
    assert options is not None
    assert options.max_records == 200
    assert options.newest_first is True
    assert options.only_projects == ("proj",)


def test_listing_snapshot_empty_index_uses_bounded_source_fallback(
    tmp_path: Path,
    monkeypatch,
) -> None:
    index_path = tmp_path / "agent_artifact_index.sqlite"
    index_path.touch()
    indexed = synthetic_snapshot(tmp_path, [])
    fallback = synthetic_snapshot(
        tmp_path,
        [synthetic_record(tmp_path, "20260717130005", "manual", done=True)],
    )
    scan_options: list[AgentArtifactScanOptionsWire | None] = []

    def fake_scan_listing_snapshot(
        options: AgentArtifactScanOptionsWire | None = None,
    ) -> AgentArtifactScanWire:
        scan_options.append(options)
        return fallback

    monkeypatch.setattr(
        "sase.core.agent_scan_facade.default_agent_artifact_index_path",
        lambda: index_path,
    )
    monkeypatch.setattr(
        "sase.core.agent_scan_facade.query_agent_artifact_index",
        lambda *_args, **_kwargs: indexed,
    )
    monkeypatch.setattr(
        "sase.core.agent_scan_facade.agent_artifact_index_status",
        lambda _path: AgentArtifactIndexStatusWire(
            schema_version=1,
            index_path=str(index_path),
            agent_artifacts_rows=0,
        ),
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot.sase_projects_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "sase.agent.listing_snapshot._scan_listing_snapshot",
        fake_scan_listing_snapshot,
    )

    loaded, state = listing_snapshot()

    assert loaded is fallback
    assert state.artifact_source == "source_scan"
    assert state.used_artifact_index is False
    assert state.repair_recommended is True
    assert state.repair_reason == "artifact_index_empty_bounded_fallback"
    [options] = scan_options
    assert options is not None
    assert options.max_records == 200
    assert options.newest_first is True
