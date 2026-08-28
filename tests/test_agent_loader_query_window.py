from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from sase.ace.tui.models._agent_loader_artifacts import query_artifact_index_for_loader
from sase.ace.tui.models.agent_loader import AgentLoadState, load_tiered_agents
from sase.core.agent_scan_facade import (
    query_agent_artifact_index,
    rebuild_agent_artifact_index,
    scan_agent_artifacts,
)
from tests._agents_tab_query_helpers import _make_agent


def test_load_tiered_agents_uses_bounded_safe_query_pushdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = _make_agent(cl_name="target")
    later_target = _make_agent(cl_name="target-later")
    calls: list[dict[str, object]] = []

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            agents=[target, later_target],
            workflow_agent_steps=[],
            state=AgentLoadState(
                tier="tier1",
                complete_history=False,
                artifact_source="artifact_index",
                used_artifact_index=True,
                bounded_prefix=True,
                requested_limit=1,
                returned_count=2,
                has_more=False,
            ),
        )

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._load_agents_with_load_state",
        fake_load_agents_with_state,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._normalize_loaded_agents",
        lambda agents, _steps: list(agents),
    )

    agents, state = load_tiered_agents(search_query="cl:target", requested_limit=1)

    assert agents == [target]
    assert state.returned_count == 1
    assert state.has_more is True
    assert calls == [
        {
            "patch_snapshot": None,
            "full_history": False,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "requested_limit": 1,
            "candidate_filter": {
                "kind": "contains",
                "field": "cl",
                "value": "target",
            },
        }
    ]


def test_load_tiered_agents_unsupported_query_uses_full_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def fake_load_agents_with_state(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            agents=[],
            workflow_agent_steps=[],
            state=AgentLoadState(
                tier="tier2",
                complete_history=True,
                artifact_source="source_scan",
                used_artifact_index=False,
            ),
        )

    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._load_agents_with_load_state",
        fake_load_agents_with_state,
    )
    monkeypatch.setattr(
        "sase.ace.tui.models.agent_loader._normalize_loaded_agents",
        lambda agents, _steps: list(agents),
    )

    _agents, state = load_tiered_agents(
        search_query="status:failed",
        requested_limit=25,
    )

    assert state.complete_history is True
    assert calls == [
        {
            "patch_snapshot": None,
            "full_history": True,
            "use_artifact_index": True,
            "index_freshness": "cached",
            "requested_limit": None,
            "candidate_filter": None,
        }
    ]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _artifact_dir(projects: Path, timestamp: str) -> Path:
    return projects / "proj" / "artifacts" / "ace-run" / timestamp


def test_windowed_loader_keeps_completed_when_active_exceeds_limit(
    tmp_path: Path,
) -> None:
    projects = tmp_path / "projects"
    for timestamp in (
        "20260827090000",
        "20260827090100",
        "20260827090200",
        "20260827090300",
        "20260827090400",
    ):
        _write_json(
            _artifact_dir(projects, timestamp) / "agent_meta.json",
            {"name": f"active-{timestamp}"},
        )
    for timestamp in ("20260827090500", "20260827090600", "20260827090700"):
        artifact_dir = _artifact_dir(projects, timestamp)
        _write_json(
            artifact_dir / "agent_meta.json",
            {"name": f"done-{timestamp}"},
        )
        _write_json(
            artifact_dir / "done.json",
            {"outcome": "completed", "name": f"done-{timestamp}"},
        )

    index_path = tmp_path / "agent_artifact_index.sqlite"
    rebuild_agent_artifact_index(index_path, projects)

    snapshot, state = query_artifact_index_for_loader(
        full_history=False,
        freshness="cached",
        requested_limit=2,
        default_index_path=lambda: index_path,
        projects_root=lambda: projects,
        query_index=query_agent_artifact_index,
        scan_artifacts=lambda options=None: scan_agent_artifacts(projects, options),
    )

    timestamps = {record.timestamp for record in snapshot.records}
    assert timestamps == {
        "20260827090000",
        "20260827090100",
        "20260827090200",
        "20260827090300",
        "20260827090400",
        "20260827090600",
        "20260827090700",
    }
    assert "20260827090500" not in timestamps
    assert state.bounded_prefix is True
    assert state.has_more is True
    assert state.record_count == 7
    window = snapshot.index_window
    assert window is not None
    assert window.active_candidate_count == 5
    assert window.completed_candidate_count == 3
    assert window.selected_candidate_count == 7
