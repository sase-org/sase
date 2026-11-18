"""Projected-detail metadata and asynchronous hydration worker tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from threading import Event
from typing import Any

import pytest

from sase.ace.tui.actions.agents._display_detail_render import (
    AgentDetailRenderMixin,
)
from sase.ace.tui.actions.agents import _display_detail_render as detail_render
from sase.ace.tui.models import _projected_record as projected_record
from sase.ace.tui.models._loaders._compact_meta_enrichment import (
    enrich_agent_from_compact_meta,
)
from sase.ace.tui.models.agent import Agent
from sase.core.agent_scan_list_wire import AgentArtifactListMetaWire
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentSessionTurnMonitorWire,
    AgentSessionTurnWire,
)
from ._projected_detail_retention_support import (
    full_record,
    list_agent,
    stamp,
)


class _HydrationOwner(AgentDetailRenderMixin):
    def __init__(self, selected: Agent) -> None:
        self.selected = selected
        self.current_tab = "agents"
        self.invalidations = 0
        self.detail_updates = 0

    def _get_selected_agent(self) -> Agent:
        return self.selected

    def _invalidate_agent_panel_cache(self) -> None:
        self.invalidations += 1


async def _wait_thread_event(event: Event) -> None:
    assert await asyncio.to_thread(event.wait, 5)


def test_monitor_identity_uses_compact_scalar_without_metadata_file_read(
    monkeypatch: Any,
) -> None:
    def reject_meta_read(path: str | Path) -> Any:
        if Path(path).name == "agent_meta.json":
            raise AssertionError("compact metadata must not reread agent_meta.json")
        raise FileNotFoundError(path)

    monkeypatch.setattr(
        "sase.ace.tui.models._loaders._json_cache.load_json_cached",
        reject_meta_read,
    )
    timestamp = stamp(20260519115000, 0)
    agent = list_agent(
        timestamp,
        f"/tmp/projects/retention-proj/artifacts/ace-run/{timestamp}",
        cl_name="monitor-proj",
    )
    meta = AgentArtifactListMetaWire(
        process_identity="boot:9",
        agent_session_role="monitor",
        agent_session_turn=AgentSessionTurnWire(
            kind="monitor",
            id="monitor-id",
            monitor=AgentSessionTurnMonitorWire(exit_code=None),
        ),
    )

    enrich_agent_from_compact_meta(agent, meta, None)

    assert agent.process_identity == "boot:9"
    assert agent.monitor_id == "monitor-id"


async def test_hydration_worker_drops_result_for_equal_identity_replacement(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    projected_record._detail_owner.clear()
    timestamp = stamp(20260519120000, 0)
    artifact_dir = f"/tmp/projects/retention-proj/artifacts/ace-run/{timestamp}"
    row = list_agent(timestamp, artifact_dir, cl_name="hydration-replace")
    replacement = list_agent(timestamp, artifact_dir, cl_name="hydration-replace")
    owner = _HydrationOwner(row)
    record = full_record(artifact_dir, timestamp)
    started = Event()
    release = Event()

    def load_detached(_artifact_dir: str) -> tuple[AgentArtifactRecordWire, bool]:
        started.set()
        assert release.wait(timeout=5)
        return record, False

    monkeypatch.setattr(projected_record, "load_projected_agent_record", load_detached)
    task = asyncio.create_task(
        owner._hydrate_projected_record_detail(
            row.identity,
            row,
            detail_render._projected_detail_row_version(row),
            0,
            owner.current_tab,
        )
    )
    await _wait_thread_event(started)
    assert row.record_shape == "list"
    assert "_raw" not in (row.step_output or {})

    owner.selected = replacement
    release.set()
    await task

    assert row.record_shape == "list"
    assert replacement.record_shape == "list"
    assert "_raw" not in (replacement.step_output or {})
    assert owner.invalidations == 0
    assert owner.detail_updates == 0
    assert len(projected_record._detail_owner) == 0


async def test_hydration_worker_drops_result_after_tab_switch(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    projected_record._detail_owner.clear()
    timestamp = stamp(20260519130000, 0)
    artifact_dir = f"/tmp/projects/retention-proj/artifacts/ace-run/{timestamp}"
    row = list_agent(timestamp, artifact_dir, cl_name="hydration-tab")
    owner = _HydrationOwner(row)
    started = Event()
    release = Event()

    def load_detached(_artifact_dir: str) -> tuple[AgentArtifactRecordWire, bool]:
        started.set()
        assert release.wait(timeout=5)
        return full_record(artifact_dir, timestamp), False

    monkeypatch.setattr(projected_record, "load_projected_agent_record", load_detached)
    task = asyncio.create_task(
        owner._hydrate_projected_record_detail(
            row.identity,
            row,
            detail_render._projected_detail_row_version(row),
            0,
            owner.current_tab,
        )
    )
    await _wait_thread_event(started)
    owner.current_tab = "patches"
    release.set()
    await task

    assert row.record_shape == "list"
    assert "_raw" not in (row.step_output or {})
    assert owner.invalidations == 0
    assert len(projected_record._detail_owner) == 0


async def test_canceled_hydration_worker_never_applies_detached_payload(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    projected_record._detail_owner.clear()
    timestamp = stamp(20260519140000, 0)
    artifact_dir = f"/tmp/projects/retention-proj/artifacts/ace-run/{timestamp}"
    row = list_agent(timestamp, artifact_dir, cl_name="hydration-cancel")
    owner = _HydrationOwner(row)
    started = Event()
    release = Event()
    finished = Event()

    def load_detached(_artifact_dir: str) -> tuple[AgentArtifactRecordWire, bool]:
        started.set()
        assert release.wait(timeout=5)
        finished.set()
        return full_record(artifact_dir, timestamp), False

    monkeypatch.setattr(projected_record, "load_projected_agent_record", load_detached)
    task = asyncio.create_task(
        owner._hydrate_projected_record_detail(
            row.identity,
            row,
            detail_render._projected_detail_row_version(row),
            0,
            owner.current_tab,
        )
    )
    await _wait_thread_event(started)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    release.set()
    await _wait_thread_event(finished)

    assert row.record_shape == "list"
    assert "_raw" not in (row.step_output or {})
    assert owner.invalidations == 0
    assert len(projected_record._detail_owner) == 0
