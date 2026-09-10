"""One-snapshot parity: runtime admission, ``sase agent list -j``, and the ACE
TUI capacity header/queue must all agree when built from the same records.

Every test in this module derives its runtime-admission, CLI, and TUI views
from one shared set of :class:`_EntitySpec` values so a divergence between
``_capacity_record_from_scan`` (admission/CLI) and ``_capacity_record_from_agent``
(TUI) -- the two independent adapters into the Rust capacity engine -- shows up
as a real test failure instead of staying latent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import patch

import sase.integrations.agent_list_entries as agent_list_entries_module
from sase.ace.tui.models._fold_filter import filter_agents_by_fold_state
from sase.ace.tui.models.agent import Agent as TuiAgent
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_runner_slots import (
    format_capacity_value,
    format_queue_weight_badge_value,
    refresh_runner_slot_context,
)
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.widgets.agent_info_panel import AgentInfoPanel
from sase.ace.tui.widgets.prompt_panel._agent_queue_section import (
    _queue_entry_capacity_detail,
)
from sase.agent._running_listing_types import RunningAgentInfo, RunningAgentListing
from sase.agents.cli_list import _agent_to_json
from sase.core.agent_scan_wire import (
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanStatsWire,
    AgentArtifactScanWire,
    AgentMetaWire,
    WaitingMarkerWire,
)
from sase.core.runner_slots import runner_capacity_snapshot
from sase.integrations.agent_list_entries import AgentListEntry, agent_list_entries

_LIMIT = 1.0
_ROOT = "/tmp/snapshot-parity/artifacts/ace-run"
_TZ = UTC


@dataclass(frozen=True)
class _EntitySpec:
    """One agent as it exists in the single captured source snapshot."""

    name: str
    project: str = "proj"
    running: bool = False
    weight: float | None = None
    weight_invalid: bool = False
    priority: int | None = None
    wait_runners: int | None = None
    wait_runners_explicit: bool = False
    requested_at: str | None = None


_QUARTERS = tuple(
    _EntitySpec(name=f"q{index}", running=True, weight=0.25) for index in range(3)
)
_HEAVY = _EntitySpec(
    name="heavy",
    weight=2.0,
    priority=0,
    wait_runners=0,
    wait_runners_explicit=True,
    requested_at="2026-07-12T12:01:00Z",
)
_UNKNOWN = _EntitySpec(
    name="unknown",
    weight_invalid=True,
    priority=10,
    wait_runners=0,
    requested_at="2026-07-12T12:01:05Z",
)
_LIGHTER = _EntitySpec(
    name="lighter",
    weight=0.25,
    priority=10,
    wait_runners=0,
    requested_at="2026-07-12T12:01:10Z",
)
_GHOST = _EntitySpec(name="ghost", running=True, weight_invalid=True)
_OTHER_PROJECT_WAITER = _EntitySpec(
    name="other-waiter",
    project="other",
    weight=0.25,
    priority=10,
    wait_runners=0,
    requested_at="2026-07-12T12:01:15Z",
)
_LOCAL_SPECS = (*_QUARTERS, _HEAVY, _UNKNOWN, _LIGHTER)


def _artifact_dir(spec: _EntitySpec) -> str:
    return f"{_ROOT}/{spec.name}"


def _wire_record(spec: _EntitySpec) -> AgentArtifactRecordWire:
    meta = AgentMetaWire(
        pid=100,
        queue_weight=spec.weight,
        queue_weight_explicit=True,
        queue_weight_invalid=spec.weight_invalid,
        run_started_at="2026-07-12T12:00:00Z" if spec.running else None,
    )
    waiting = (
        None
        if spec.running
        else WaitingMarkerWire(
            queue_weight=spec.weight,
            queue_weight_explicit=True,
            queue_weight_invalid=spec.weight_invalid,
            wait_priority=spec.priority,
            wait_runners=spec.wait_runners,
            wait_runners_explicit=spec.wait_runners_explicit,
            slot_requested_at=spec.requested_at,
        )
    )
    return AgentArtifactRecordWire(
        project_name=spec.project,
        project_dir=f"/tmp/{spec.project}",
        project_file=f"/tmp/{spec.project}/{spec.project}.gp",
        workflow_dir_name="ace-run",
        artifact_dir=_artifact_dir(spec),
        timestamp=spec.name,
        agent_meta=meta,
        waiting=waiting,
    )


def _running_info(spec: _EntitySpec) -> RunningAgentInfo:
    return RunningAgentInfo(
        name=spec.name,
        project=spec.project,
        pid=100,
        model="fakey-large",
        provider="fakey",
        workspace_num=1,
        duration="1m",
        approve=False,
        status="RUNNING" if spec.running else "WAITING",
        started_at=datetime(2026, 7, 12, 12, 0 if spec.running else 1, tzinfo=_TZ),
        duration_seconds=60,
        artifacts_dir=_artifact_dir(spec),
    )


def _tui_agent(spec: _EntitySpec) -> TuiAgent:
    return TuiAgent(
        agent_type=AgentType.RUNNING,
        cl_name=spec.name,
        project_file=f"/tmp/{spec.project}/{spec.project}.sase",
        status="RUNNING" if spec.running else "WAITING",
        start_time=datetime(2026, 7, 12, 12, 0 if spec.running else 1, tzinfo=_TZ),
        raw_suffix=spec.name,
        artifacts_dir=_artifact_dir(spec),
        pid=100,
        run_start_time=(
            datetime(2026, 7, 12, 12, 0, tzinfo=_TZ) if spec.running else None
        ),
        queue_weight=spec.weight,
        queue_weight_explicit=True,
        queue_weight_invalid=spec.weight_invalid,
        wait_priority=spec.priority,
        wait_runners=spec.wait_runners,
        wait_runners_explicit=spec.wait_runners_explicit,
        slot_requested_at=spec.requested_at,
    )


def _listing(specs: tuple[_EntitySpec, ...]) -> RunningAgentListing:
    snapshot = AgentArtifactScanWire(
        schema_version=1,
        projects_root="/tmp",
        options=AgentArtifactScanOptionsWire(),
        stats=AgentArtifactScanStatsWire(),
        records=[_wire_record(spec) for spec in specs],
    )
    return RunningAgentListing(
        [_running_info(spec) for spec in specs], artifact_snapshot=snapshot
    )


def _cli_entries(
    specs: tuple[_EntitySpec, ...], *, project: str | None = None
) -> list[AgentListEntry]:
    listing = _listing(specs)
    with (
        patch.object(
            agent_list_entries_module, "list_running_agents", return_value=listing
        ),
        patch.object(
            agent_list_entries_module, "get_max_running_agents", return_value=_LIMIT
        ),
    ):
        return agent_list_entries(project=project)


def _by_name(entries: list[AgentListEntry]) -> dict[str, AgentListEntry]:
    return {entry.name: entry for entry in entries if entry.name is not None}


def _ground_truth(specs: tuple[_EntitySpec, ...]) -> dict[str, Any]:
    records = [_wire_record(spec) for spec in specs]
    return runner_capacity_snapshot(
        records, lambda _record: True, effective_limit=_LIMIT
    )


def _waiters_by_dir(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {waiter["artifact_dir"]: waiter for waiter in snapshot["waiters"]}


def test_weighted_capacity_snapshot_matches_across_runtime_cli_and_tui() -> None:
    ground_truth = _ground_truth(_LOCAL_SPECS)
    assert ground_truth["occupied_capacity"] == 0.75
    assert ground_truth["effective_limit"] == _LIMIT
    assert ground_truth["occupied_lanes"] == 3
    truth_waiters = _waiters_by_dir(ground_truth)
    assert [
        waiter["artifact_dir"]
        for waiter in sorted(ground_truth["waiters"], key=lambda w: w["queue_position"])
    ] == [_artifact_dir(_LIGHTER), _artifact_dir(_UNKNOWN), _artifact_dir(_HEAVY)]

    cli_entries = _by_name(_cli_entries(_LOCAL_SPECS))
    tui_agents = [_tui_agent(spec) for spec in _LOCAL_SPECS]
    tui_snapshot = refresh_runner_slot_context(tui_agents, effective_limit=_LIMIT)
    tui_queue_by_name = {entry.identity[1]: entry for entry in tui_snapshot.queue}

    assert tui_snapshot.occupied_capacity == ground_truth["occupied_capacity"]
    assert tui_snapshot.effective_limit == ground_truth["effective_limit"]
    assert tui_snapshot.queued_count == len(ground_truth["waiters"])
    assert [entry.identity[1] for entry in tui_snapshot.queue] == [
        "lighter",
        "unknown",
        "heavy",
    ]
    assert [
        name
        for name, entry in sorted(
            cli_entries.items(),
            key=lambda item: item[1].wait.runner_slot_queue_position or 0,
        )
        if entry.wait.runner_slot_queue_position is not None
    ] == ["lighter", "unknown", "heavy"]

    for spec in (_LIGHTER, _UNKNOWN, _HEAVY):
        truth = truth_waiters[_artifact_dir(spec)]
        cli_wait = cli_entries[spec.name].wait
        tui_entry = tui_queue_by_name[spec.name]

        assert cli_wait.runner_occupied_capacity == ground_truth["occupied_capacity"]
        assert cli_wait.runner_effective_limit == ground_truth["effective_limit"]
        assert list(cli_wait.runner_capacity_blockers) == truth["blockers"]
        assert list(tui_entry.blockers) == truth["blockers"]
        assert tui_entry.eligible == truth["eligible"]
        assert tui_entry.requested_weight == truth["requested_weight"]

    unknown_json = _agent_to_json(cli_entries["unknown"])
    unknown_blockers = cast(
        list[dict[str, Any]], unknown_json["runner_capacity_blockers"]
    )
    assert unknown_json["queue_weight"] is None
    assert unknown_json["queue_weight_invalid"] is True
    assert unknown_blockers[0]["code"] == "invalid-request-weight"

    heavy_json = _agent_to_json(cli_entries["heavy"])
    heavy_blockers = cast(list[dict[str, Any]], heavy_json["runner_capacity_blockers"])
    assert heavy_json["queue_weight"] == 2.0
    assert heavy_blockers[0]["code"] == "weight-exceeds-limit"


def test_capacity_header_renders_shared_snapshot_numbers() -> None:
    tui_agents = [_tui_agent(spec) for spec in _LOCAL_SPECS]
    snapshot = refresh_runner_slot_context(tui_agents, effective_limit=_LIMIT)

    panel = AgentInfoPanel()
    panel._runner_limit = snapshot.effective_limit
    panel._runner_occupied_capacity = snapshot.occupied_capacity
    panel._runner_queue_count = snapshot.queued_count
    captured: list[str] = []
    with patch.object(
        panel, "update", lambda text, **_kwargs: captured.append(text.plain)
    ):
        panel._update_display()

    expected = (
        f"{format_capacity_value(snapshot.occupied_capacity)}/"
        f"{format_capacity_value(snapshot.effective_limit)}"
    )
    assert expected == "0.75/1.0"
    assert expected in captured[-1]


def test_queue_detail_and_badges_match_blockers_from_shared_snapshot() -> None:
    tui_agents = [_tui_agent(spec) for spec in _LOCAL_SPECS]
    snapshot = refresh_runner_slot_context(tui_agents, effective_limit=_LIMIT)
    entries = {entry.identity[1]: entry for entry in snapshot.queue}

    assert "invalid weight" in _queue_entry_capacity_detail(entries["unknown"])
    assert "weight exceeds current limit" in _queue_entry_capacity_detail(
        entries["heavy"]
    )
    assert "needs 0.25" in _queue_entry_capacity_detail(entries["lighter"])

    assert format_queue_weight_badge_value(entries["heavy"].requested_weight) == "2"
    assert (
        format_queue_weight_badge_value(entries["lighter"].requested_weight) == "0.25"
    )
    # An unrecognized weight is reported back at the default (1.0) for display
    # purposes only -- the badge helper suppresses it exactly like an
    # ordinary default weight so a corrupted record never shows a fabricated
    # "wN" badge.
    assert format_queue_weight_badge_value(entries["unknown"].requested_weight) is None


def test_remote_weight_badge_never_charges_local_snapshot() -> None:
    tui_agents = [_tui_agent(spec) for spec in _LOCAL_SPECS]
    baseline = refresh_runner_slot_context(list(tui_agents), effective_limit=_LIMIT)

    remote_agent = TuiAgent(
        agent_type=AgentType.RUNNING,
        cl_name="apollo.remote-heavy",
        project_file="/tmp/proj/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 12, 12, 0, tzinfo=_TZ),
        raw_suffix="remote-heavy",
        queue_weight=5.0,
        queue_weight_explicit=True,
    )

    combined = refresh_runner_slot_context(
        [*tui_agents, remote_agent],
        effective_limit=_LIMIT,
        capacity_agents=tui_agents,
    )

    assert combined.occupied_capacity == baseline.occupied_capacity == 0.75
    assert combined.effective_limit == baseline.effective_limit == _LIMIT
    assert combined.queued_count == baseline.queued_count
    assert format_queue_weight_badge_value(remote_agent.queue_weight) == "5"


def test_fold_filtering_never_recomputes_shared_queue_numbers() -> None:
    tui_agents = [_tui_agent(spec) for spec in _LOCAL_SPECS]
    parent = TuiAgent(
        agent_type=AgentType.WORKFLOW,
        cl_name="unrelated",
        project_file="/tmp/proj/proj.sase",
        status="RUNNING",
        start_time=datetime(2026, 7, 12, 12, 0, tzinfo=_TZ),
        raw_suffix="unrelated-ts",
    )
    child = TuiAgent(
        agent_type=AgentType.WORKFLOW,
        cl_name="step",
        project_file="/tmp/proj/proj.sase",
        status="DONE",
        start_time=None,
        parent_workflow="unrelated-workflow",
        parent_timestamp="unrelated-ts",
        step_name="step",
        is_hidden_step=True,
        raw_suffix="unrelated-ts",
    )
    # A second, non-hidden child keeps the parent out of the "workflow with
    # only internal steps" exclusion (see `_fold_filter.py`'s
    # `hidden_only_parents`), so this scenario tests plain fold-collapse of
    # a child under a visible parent rather than whole-workflow hiding.
    visible_child = TuiAgent(
        agent_type=AgentType.WORKFLOW,
        cl_name="visible-step",
        project_file="/tmp/proj/proj.sase",
        status="DONE",
        start_time=None,
        parent_workflow="unrelated-workflow",
        parent_timestamp="unrelated-ts",
        step_name="visible-step",
        is_hidden_step=False,
        raw_suffix="unrelated-ts",
    )
    all_agents = [*tui_agents, parent, child, visible_child]

    refresh_runner_slot_context(all_agents, effective_limit=_LIMIT)
    before = {
        agent.cl_name: (
            agent.runner_slot_queue_position,
            agent.runner_effective_limit,
            agent.runner_occupied_capacity,
        )
        for agent in tui_agents
        if agent.slot_requested_at
    }
    assert before, "expected at least one live slot waiter to compare"

    visible, _fold_counts = filter_agents_by_fold_state(all_agents, FoldStateManager())

    assert child not in visible
    assert parent in visible
    for name, snapshot_before in before.items():
        waiter = next(agent for agent in visible if agent.cl_name == name)
        after = (
            waiter.runner_slot_queue_position,
            waiter.runner_effective_limit,
            waiter.runner_occupied_capacity,
        )
        assert after == snapshot_before


def test_project_filter_preserves_shared_global_queue_numbers() -> None:
    specs = (*_LOCAL_SPECS, _OTHER_PROJECT_WAITER)
    unfiltered = _by_name(_cli_entries(specs))
    filtered = _by_name(_cli_entries(specs, project="proj"))

    assert set(filtered) == {"q0", "q1", "q2", "heavy", "unknown", "lighter"}
    assert "other-waiter" in unfiltered
    for name in ("heavy", "unknown", "lighter"):
        assert (
            filtered[name].wait.runner_slot_queue_position
            == unfiltered[name].wait.runner_slot_queue_position
        )
        assert (
            filtered[name].wait.runner_slot_queue_size
            == unfiltered[name].wait.runner_slot_queue_size
            == 4
        )


def test_unknown_live_claim_weight_blocks_admission_identically_everywhere() -> None:
    """A live agent with unrecognized (invalid) weight is a hazard: Rust

    excludes it from occupied capacity (so it never crashes accounting) but
    also fails the *whole* snapshot closed -- every other waiter, even one
    that was previously eligible, is blocked until it is fixed. Both the CLI
    and TUI adapters must carry the invalid flag through identically to the
    real runtime decision, or a user could see an agent as admittable in one
    surface while the real runtime refuses to start it.
    """
    specs = (*_LOCAL_SPECS, _GHOST)
    ground_truth = _ground_truth(specs)
    assert ground_truth["occupied_capacity"] == 0.75
    assert ground_truth["occupied_lanes"] == 3
    truth_waiters = _waiters_by_dir(ground_truth)
    for spec in (_LIGHTER, _UNKNOWN, _HEAVY):
        truth = truth_waiters[_artifact_dir(spec)]
        assert truth["eligible"] is False
        assert truth["blockers"][0]["code"] == "capacity-snapshot-invalid"

    cli_entries = _by_name(_cli_entries(specs))
    tui_agents = [_tui_agent(spec) for spec in specs]
    tui_snapshot = refresh_runner_slot_context(tui_agents, effective_limit=_LIMIT)
    tui_queue_by_name = {entry.identity[1]: entry for entry in tui_snapshot.queue}

    assert tui_snapshot.occupied_capacity == ground_truth["occupied_capacity"]
    assert cli_entries["lighter"].wait.runner_occupied_capacity == 0.75

    for spec in (_LIGHTER, _UNKNOWN, _HEAVY):
        truth = truth_waiters[_artifact_dir(spec)]
        cli_blockers = list(cli_entries[spec.name].wait.runner_capacity_blockers)
        tui_blockers = list(tui_queue_by_name[spec.name].blockers)
        assert cli_blockers == truth["blockers"]
        assert tui_blockers == truth["blockers"]
        assert tui_queue_by_name[spec.name].eligible is False
