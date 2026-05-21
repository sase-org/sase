"""Regression tests for Tier 1 visibility of anonymous workflow rows.

These tests pin the contract that the persistent agent artifact index
treats ``workflow_state.is_anonymous`` as a naming/grouping signal, not
a visibility signal. A `tmp_*` workflow with ``appears_as_agent: true``
and ``hidden: false`` must remain in the visible inbox returned by
``query_agent_artifact_index`` so the Tier 1 ACE Agents tab does not
need a ``,y`` Tier 2 reconcile to surface real agents on startup.

Exercises the real ``sase_core_rs`` binding end-to-end so the Rust
projection (``RecordSummary::from_record``) stays in lock-step with the
Python loader's visibility expectations.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from sase.core.agent_scan_facade import (
    query_agent_artifact_index,
    rebuild_agent_artifact_index,
    scan_agent_artifacts,
)
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
)
from sase.core.rust import RUST_EXTENSION_MODULE_NAME


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec(RUST_EXTENSION_MODULE_NAME) is None,
    reason="sase_core_rs is required for artifact index regression tests.",
)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _write_anonymous_workflow_artifact(
    projects_root: Path,
    timestamp: str,
    *,
    workflow_state_hidden: bool = False,
) -> Path:
    """Materialize a `tmp_*` workflow artifact that should appear as an agent.

    Mirrors the on-disk shape `workflow_runner.py` emits for an auto-named
    workflow that the user expects to see in the Tier 1 Agents tab.
    """
    artifact_dir = projects_root / "proj" / "artifacts" / "ace-run" / timestamp
    _write_json(
        artifact_dir / "workflow_state.json",
        {
            "workflow_name": f"tmp_{timestamp}",
            "status": "completed",
            "appears_as_agent": True,
            "is_anonymous": True,
            "hidden": workflow_state_hidden,
            "current_step_index": 0,
            "start_time": "2026-05-21T10:05:33Z",
            "steps": [],
        },
    )
    _write_json(
        artifact_dir / "done.json",
        {
            "outcome": "completed",
            "finished_at": 1779999999.0,
            "name": f"tmp_{timestamp}",
            "cl_name": "cl_anon",
        },
    )
    return artifact_dir


def _visible_inbox_query() -> AgentArtifactIndexQueryWire:
    """Same query shape the TUI loader issues for a Tier 1 refresh."""
    return AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=False,
        active_limit=None,
        recent_completed_limit=200,
        include_hidden=False,
    )


def test_tier1_visible_inbox_includes_anonymous_appears_as_agent_workflow(
    tmp_path: Path,
) -> None:
    """Anonymous workflows with ``appears_as_agent`` must reach the inbox.

    Regression for the Tier 1 startup bug where ``is_anonymous`` was
    treated as a visibility signal in the indexer's ``hidden`` projection.
    """
    projects_root = tmp_path / "projects"
    artifact_dir = _write_anonymous_workflow_artifact(projects_root, "20260521100533")
    index_path = tmp_path / "agent_artifact_index.sqlite"

    rebuild_agent_artifact_index(
        index_path,
        projects_root,
        AgentArtifactScanOptionsWire(),
    )

    snapshot = query_agent_artifact_index(
        index_path,
        projects_root,
        query=_visible_inbox_query(),
        options=AgentArtifactScanOptionsWire(),
    )

    artifact_dirs = {record.artifact_dir for record in snapshot.records}
    assert str(artifact_dir) in artifact_dirs


def test_tier1_visible_inbox_still_filters_explicit_workflow_state_hidden(
    tmp_path: Path,
) -> None:
    """Explicit ``workflow_state.hidden`` is still honored after the fix.

    Proves we narrowed the predicate, not removed it: a workflow that
    sets ``hidden: true`` in its ``workflow_state.json`` stays out of the
    visible inbox even when ``is_anonymous`` is also true.
    """
    projects_root = tmp_path / "projects"
    _write_anonymous_workflow_artifact(
        projects_root, "20260521100600", workflow_state_hidden=True
    )
    index_path = tmp_path / "agent_artifact_index.sqlite"

    rebuild_agent_artifact_index(
        index_path,
        projects_root,
        AgentArtifactScanOptionsWire(),
    )

    snapshot = query_agent_artifact_index(
        index_path,
        projects_root,
        query=_visible_inbox_query(),
        options=AgentArtifactScanOptionsWire(),
    )

    assert snapshot.records == []


def test_tier1_visible_inbox_matches_source_scan_for_anonymous_workflows(
    tmp_path: Path,
) -> None:
    """Tier 1 (index) and Tier 2 (source scan) return the same `tmp_*` rows.

    This is the regression-prevention assertion that generalizes the bug:
    a Tier 1 visible-inbox refresh and a Tier 2 full reconcile should
    agree on which anonymous workflows are visible, so users don't need a
    ``,y`` keypress to recover their Agents tab.
    """
    projects_root = tmp_path / "projects"
    for timestamp in ("20260521100100", "20260521100200", "20260521100300"):
        _write_anonymous_workflow_artifact(projects_root, timestamp)
    index_path = tmp_path / "agent_artifact_index.sqlite"

    rebuild_agent_artifact_index(
        index_path,
        projects_root,
        AgentArtifactScanOptionsWire(),
    )

    indexed = query_agent_artifact_index(
        index_path,
        projects_root,
        query=_visible_inbox_query(),
        options=AgentArtifactScanOptionsWire(),
    )
    source = scan_agent_artifacts(projects_root, AgentArtifactScanOptionsWire())

    assert {record.artifact_dir for record in indexed.records} == {
        record.artifact_dir for record in source.records
    }
