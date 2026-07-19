"""Regression tests for lazy Agents-tab attempt-history hydration."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.actions.agents._loading_disk import AgentLoadingDiskMixin
from sase.ace.tui.actions.agents._loading_helpers import (
    hydrate_agent_attempt_history,
    load_agents_from_disk_with_state,
)
from sase.ace.tui.models.agent import Agent, AgentType, AttemptRecord
from sase.ace.tui.models.agent_content_search import AgentContentSearchCache
from sase.ace.tui.models.agent_loader import AgentLoadState


def _make_agent(artifacts_dir: Path) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="demo",
        project_file="/tmp/projects/demo/demo.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 21, 10, 0, 0),
        raw_suffix="20260521100000",
        artifacts_dir=str(artifacts_dir),
    )


def _make_record(artifacts_dir: Path, n: int = 1) -> AttemptRecord:
    return AttemptRecord(
        attempt_number=n,
        status="failed",
        start_epoch=100.0,
        end_epoch=120.0,
        model=None,
        used_fallback=False,
        error_snippet="boom",
        error_full="boom full",
        live_reply_path=str(artifacts_dir / "attempt_reply.md"),
        timestamps_path=str(artifacts_dir / "attempt_timestamps.jsonl"),
    )


def _load_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        artifact_source="artifact_index",
        complete_visible_inbox=True,
        complete_history=False,
        used_artifact_index=True,
    )


def test_normal_disk_load_does_not_hydrate_attempt_history(tmp_path: Path) -> None:
    agent = _make_agent(tmp_path)

    with (
        patch(
            "sase.ace.tui.models.agent_loader.load_tiered_agents",
            return_value=([agent], _load_state()),
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
        patch(
            "sase.ace.tui.actions.agents._snapshot_cache.AgentSnapshotCache"
            ".attempt_history_for"
        ) as attempt_history_for,
    ):
        result = load_agents_from_disk_with_state(set(), changespec_snapshot=[])

    attempt_history_for.assert_not_called()
    assert result.all_agents == [agent]
    assert agent.attempt_history == []


def test_lazy_hydration_populates_one_agent_attempt_history(tmp_path: Path) -> None:
    agent = _make_agent(tmp_path)
    record = _make_record(tmp_path)

    with patch(
        "sase.ace.tui.actions.agents._snapshot_cache.AgentSnapshotCache"
        ".attempt_history_for",
        return_value=[record],
    ) as attempt_history_for:
        changed = hydrate_agent_attempt_history(agent)

    assert changed is True
    attempt_history_for.assert_called_once_with(str(tmp_path))
    assert agent.attempt_history == [record]


def test_content_search_hydrates_attempts_before_indexing(tmp_path: Path) -> None:
    agent = _make_agent(tmp_path)
    record = _make_record(tmp_path)
    Path(record.live_reply_path).write_text(
        "needle from prior attempt", encoding="utf-8"
    )

    class Loader(AgentLoadingDiskMixin):
        pass

    loader = Loader()
    loader._agent_search_query = "needle"
    loader._agent_content_search_cache = AgentContentSearchCache()
    loader._agent_content_search_index = None

    with patch(
        "sase.ace.tui.actions.agents._loading_helpers.hydrate_agent_attempt_history",
        side_effect=lambda selected: selected.attempt_history.extend([record]) or True,
    ) as hydrate:
        index = loader._prepare_agent_content_search_index_sync([agent])

    hydrate.assert_called_once_with(agent)
    assert index is not None
    assert "needle from prior attempt" in index.get_haystack(agent)
