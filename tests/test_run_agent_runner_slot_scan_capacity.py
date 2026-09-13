"""Runner-slot admission against parked markers read back by the Rust agent scan.

Other runner-slot tests build scan records from marker JSON in Python. These run
the real scanner, which is how every other waiter sees a parked launch's
authored capacity.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.models._loaders._meta_enrichment_wire import (
    enrich_agent_from_meta_wire,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from sase.ace.tui.widgets.prompt_panel._agent_display_parts import build_header_text
from sase.axe import run_agent_wait_markers, run_agent_wait_slots
from sase.core.agent_scan_wire import AgentArtifactRecordWire
from sase.feature_flags import override_flags

from tests._runner_slot_fixtures import artifact


def _render_agent_from_record(
    record: AgentArtifactRecordWire,
    *,
    name: str = "capacity-render",
) -> Agent:
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/project/project.sase",
        status="RUNNING",
        start_time=datetime(2026, 9, 13, 9, 10),
        raw_suffix=record.timestamp,
        artifacts_dir=record.artifact_dir,
        agent_name=name,
        pid=record.agent_meta.pid if record.agent_meta is not None else None,
    )
    enrich_agent_from_meta_wire(
        agent,
        record.agent_meta,
        record.waiting,
        record.pending_question,
    )
    return agent


@pytest.mark.parametrize(
    ("budget_enabled", "drain_capacity"),
    [(True, 1), (False, 0)],
)
def test_capacity_blocked_waiter_does_not_park_the_queue_behind_it(
    tmp_path: Path,
    budget_enabled: bool,
    drain_capacity: int,
) -> None:
    artifact(
        tmp_path,
        "20260913090000",
        100,
        run_started_at="2026-09-13T09:00:00+00:00",
    )
    drain = artifact(tmp_path, "20260913090001", 101)
    later = artifact(tmp_path, "20260913090002", 102)

    with (
        override_flags(queue_capacity_budget=budget_enabled),
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            side_effect=run_agent_wait_slots._collect_runner_slot_records,
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=8),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        drained, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(drain),
            cl_name="cl",
            timestamp=drain.name,
            directive_threshold=drain_capacity,
            claim=lambda: "unexpected",
        )
        assert drained is None
        assert parked
        (scanned,) = [
            record.waiting
            for record in run_agent_wait_slots._collect_runner_slot_records()
            if record.artifact_dir == str(drain)
        ]
        assert scanned is not None
        assert scanned.queue_capacity == drain_capacity
        assert scanned.queue_capacity_explicit is True
        marker = json.loads((drain / "waiting.json").read_text())
        assert marker["queue_capacity"] == drain_capacity
        assert "wait_runners" not in marker

        started, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(later),
            cl_name="cl",
            timestamp=later.name,
            directive_threshold=100,
            claim=lambda: "started",
        )

    assert started == "started"
    assert not parked
    assert not (later / "waiting.json").exists()


def test_canonical_only_metadata_survives_real_scan_without_waiting_marker(
    tmp_path: Path,
) -> None:
    running = artifact(
        tmp_path,
        "20260913091000",
        200,
        queue_capacity=100,
        queue_capacity_explicit=True,
        queue_weight=2,
        queue_weight_explicit=True,
        run_started_at="2026-09-13T09:10:00+00:00",
    )
    with patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}):
        (scanned,) = [
            record
            for record in run_agent_wait_slots._collect_runner_slot_records()
            if record.artifact_dir == str(running)
        ]
    assert scanned.waiting is None
    assert scanned.agent_meta is not None
    assert scanned.agent_meta.queue_capacity == 100
    assert scanned.agent_meta.queue_capacity_explicit is True
    assert scanned.agent_meta.queue_weight == 2

    rendered = _render_agent_from_record(scanned)
    refresh_runner_slot_context([rendered], effective_limit=1.0)
    left, _, _ = format_agent_option(rendered, 0, is_selected=False)
    header, _ = build_header_text(rendered, cheap=True)
    assert "capacity-render w2 c100 (RUNNING)" in left.plain
    assert "Weight: 2.0 capacity units" in header.plain
    assert "Capacity: 100 capacity units" in header.plain


def test_index_rebuild_keeps_metadata_capacity_after_waiting_marker_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.core.agent_scan_facade import (
        default_agent_artifact_index_path,
        query_agent_artifact_index,
        rebuild_agent_artifact_index,
    )
    from sase.core.agent_scan_wire import AgentArtifactIndexQueryWire

    waiter = artifact(
        tmp_path,
        "20260913092000",
        201,
        queue_capacity=100,
        queue_capacity_explicit=True,
    )
    run_agent_wait_markers.write_waiting_marker(
        str(waiter),
        {
            "cl_name": "cl",
            "timestamp": waiter.name,
            **run_agent_wait_markers.queue_capacity_marker_fields(100, explicit=True),
            "slot_requested_at": "2026-09-13T09:20:00+00:00",
        },
    )
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    projects_root = tmp_path / ".sase" / "projects"
    index_path = default_agent_artifact_index_path()
    rebuild_agent_artifact_index(index_path, projects_root)
    run_agent_wait_markers.remove_waiting_marker(str(waiter))
    rebuild_agent_artifact_index(index_path, projects_root)
    snapshot = query_agent_artifact_index(
        index_path,
        projects_root,
        AgentArtifactIndexQueryWire(
            include_active=True,
            include_recent_completed=False,
            freshness="cached",
        ),
    )
    (indexed,) = [
        record for record in snapshot.records if record.artifact_dir == str(waiter)
    ]
    assert indexed.waiting is None
    assert indexed.agent_meta is not None
    assert indexed.agent_meta.queue_capacity == 100
    assert indexed.agent_meta.queue_capacity_explicit is True

    rendered = _render_agent_from_record(indexed, name="indexed-render")
    refresh_runner_slot_context([rendered], effective_limit=1.0)
    left, _, _ = format_agent_option(rendered, 0, is_selected=False)
    header, _ = build_header_text(rendered, cheap=True)
    assert "indexed-render c100 (RUNNING)" in left.plain
    assert "Capacity: 100 capacity units" in header.plain


@pytest.mark.parametrize("budget_enabled", [True, False])
def test_capacity_blocked_head_then_high_budget_launch_uses_real_scan(
    tmp_path: Path,
    budget_enabled: bool,
) -> None:
    artifact(
        tmp_path,
        "20260913093000",
        300,
        run_started_at="2026-09-13T09:30:00+00:00",
    )
    drain = artifact(tmp_path, "20260913093001", 301)
    later = artifact(tmp_path, "20260913093002", 302)

    with (
        override_flags(queue_capacity_budget=budget_enabled),
        patch.object(
            run_agent_wait_slots,
            "_scan_runner_slot_records",
            side_effect=run_agent_wait_slots._collect_runner_slot_records,
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(run_agent_wait_slots, "get_max_running_agents", return_value=1),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        drained, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(drain),
            cl_name="cl",
            timestamp=drain.name,
            directive_threshold=1 if budget_enabled else 0,
            claim=lambda: "unexpected",
        )
        assert drained is None
        assert parked

        started, parked = run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(later),
            cl_name="cl",
            timestamp=later.name,
            directive_threshold=100,
            claim=lambda: "started",
        )

    if budget_enabled:
        assert started == "started"
        assert not parked
        assert not (later / "waiting.json").exists()
    else:
        assert started is None
        assert parked
        later_marker = json.loads((later / "waiting.json").read_text())
        assert later_marker["queue_capacity"] == 100
        assert later_marker["queue_capacity_explicit"] is True
        assert "wait_runners" not in later_marker
