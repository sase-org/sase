"""Revalidating Tier 1 index queries pick up mid-run metadata mutations.

The persistent agent artifact index caches a serialized
``AgentArtifactRecordWire`` per artifact directory. When state-transition
code paths append a new timestamp to ``agent_meta.json`` (for example a
``plan_submitted_at`` entry on plan submission) they do not call the
explicit upsert lifecycle hook. Without the revalidating query path in
the Rust index, the deferred post-paint reconcile returns stale wire data
and the Agents tab detail panel cannot show the new PLAN/FEEDBACK/etc.
row until a full ``,y`` rebuild.

These tests exercise the real ``sase_core_rs`` binding end-to-end across
the FFI boundary so the self-healing query path stays wired up for the
TUI's deferred revalidating reconcile.
"""

from __future__ import annotations

import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

from sase.ace.tui.models._loaders._meta_enrichment import (
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.core.agent_scan_facade import (
    query_agent_artifact_index,
    rebuild_agent_artifact_index,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec(RUST_EXTENSION_MODULE_NAME) is None,
    reason="sase_core_rs is required for Tier 1 self-heal regression tests.",
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _tier1_query() -> AgentArtifactIndexQueryWire:
    return AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=False,
        active_limit=None,
        recent_completed_limit=200,
        include_hidden=False,
        freshness="revalidate",
    )


def test_tier1_index_query_picks_up_appended_plan_submitted_at(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    artifact_dir = projects_root / "proj" / "artifacts" / "ace-run" / "20260521160000"
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": "active",
            "run_started_at": "2026-05-21T16:00:00Z",
            "plan_submitted_at": [],
        },
    )

    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(
        index_path,
        projects_root,
        AgentArtifactScanOptionsWire(),
    )

    # Mid-run state transition: write the new plan timestamp directly to
    # agent_meta.json without invoking the index upsert. This is exactly
    # what ``update_meta_field`` -> ``_record_workflow_metadata`` does on
    # plan submission.
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": "active",
            "run_started_at": "2026-05-21T16:00:00Z",
            "plan_submitted_at": ["2026-05-21T16:05:00Z"],
        },
    )

    snapshot = query_agent_artifact_index(
        index_path,
        projects_root,
        query=_tier1_query(),
        options=AgentArtifactScanOptionsWire(),
    )

    assert len(snapshot.records) == 1
    record = snapshot.records[0]
    assert record.agent_meta is not None
    assert record.agent_meta.plan_submitted_at == ["2026-05-21T16:05:00Z"]


def test_tier1_loader_agent_plan_times_reflects_mid_run_update(
    tmp_path: Path,
) -> None:
    """End-to-end: refreshed wire flows through enrichment into Agent."""
    projects_root = tmp_path / "projects"
    artifact_dir = projects_root / "proj" / "artifacts" / "ace-run" / "20260521161500"
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": "active",
            "run_started_at": "2026-05-21T16:15:00Z",
            "plan_submitted_at": [],
        },
    )

    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(
        index_path,
        projects_root,
        AgentArtifactScanOptionsWire(),
    )

    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": "active",
            "run_started_at": "2026-05-21T16:15:00Z",
            "plan_submitted_at": ["2026-05-21T16:20:00Z"],
        },
    )

    snapshot = query_agent_artifact_index(
        index_path,
        projects_root,
        query=_tier1_query(),
        options=AgentArtifactScanOptionsWire(),
    )
    assert len(snapshot.records) == 1
    record = snapshot.records[0]

    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/r/p/p.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 21, 16, 15, 0),
        raw_suffix=record.timestamp,
    )
    enrich_agent_from_meta_wire(agent, record.agent_meta, waiting=None)

    # The exact local-time representation depends on the test host's
    # timezone; what we care about is that exactly one PLAN entry made
    # it across the FFI boundary and into the Agent without a full
    # rebuild.
    assert len(agent.plan_times) == 1


def test_tier1_index_query_picks_up_appended_feedback_submitted_at(
    tmp_path: Path,
) -> None:
    projects_root = tmp_path / "projects"
    artifact_dir = projects_root / "proj" / "artifacts" / "ace-run" / "20260521163000"
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": "active",
            "run_started_at": "2026-05-21T16:30:00Z",
            "feedback_submitted_at": [],
        },
    )

    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(
        index_path,
        projects_root,
        AgentArtifactScanOptionsWire(),
    )

    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": "active",
            "run_started_at": "2026-05-21T16:30:00Z",
            "feedback_submitted_at": ["2026-05-21T16:33:00Z"],
        },
    )

    snapshot = query_agent_artifact_index(
        index_path,
        projects_root,
        query=_tier1_query(),
        options=AgentArtifactScanOptionsWire(),
    )

    assert len(snapshot.records) == 1
    record = snapshot.records[0]
    assert record.agent_meta is not None
    assert record.agent_meta.feedback_submitted_at == ["2026-05-21T16:33:00Z"]
