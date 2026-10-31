"""Per-record capacity accounting attached to Agents-tab rows.

Occupancy marks and the ``Capacity:`` detail line read the accounting entries
the authoritative machine report (or the roster Rust snapshot before the first
report lands) carries for every request record. These tests pin the attach
rules: agent rows resolve by artifact dir, workflow-step rows never attach,
clan containers sum their members' distinct claims, and the member marks sum
to the chip total for the screenshot shape.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_runner_slots import refresh_runner_slot_context

from ._agent_runner_slots_helpers import _agent


def _holding(
    artifact_dir: str,
    *,
    name: str,
    weight: float = 1.0,
    source: str = "default",
    owner: str = "owner-a",
    reason: str | None = None,
) -> dict[str, object]:
    return {
        "artifact_dir": artifact_dir,
        "project_name": "demo",
        "agent_name": name,
        "state": "holding",
        "charged_weight": weight,
        "effective_weight": weight,
        "weight_source": source,
        "claim_owner_key": owner,
        "claim_holder_artifact_dir": artifact_dir,
        "reason_code": reason,
    }


def _entry(
    artifact_dir: str,
    *,
    name: str,
    state: str,
    reason: str | None = None,
    owner: str = "owner-a",
    holder_dir: str | None = None,
) -> dict[str, object]:
    return {
        "artifact_dir": artifact_dir,
        "project_name": "demo",
        "agent_name": name,
        "state": state,
        "charged_weight": 0.0,
        "effective_weight": 1.0,
        "weight_source": "default",
        "claim_owner_key": owner,
        "claim_holder_artifact_dir": holder_dir,
        "reason_code": reason,
    }


def _snapshot(accounting: list[dict[str, object]]) -> dict[str, object]:
    return {
        "occupied_lanes": 5,
        "occupied_capacity": 5.0,
        "effective_limit": 8.0,
        "claims": [],
        "waiters": [],
        "accounting": accounting,
    }


def _running(name: str, **overrides: object) -> object:
    defaults: dict[str, object] = {"status": "RUNNING"}
    defaults.update(overrides)
    return _agent(name, **defaults)  # type: ignore[arg-type]


def test_holding_rider_and_idle_rows_attach_by_artifact_dir() -> None:
    holder = _running("holder")
    rider = _running("rider")
    idle = _running("idle")
    snapshot = _snapshot(
        [
            _holding(holder.artifacts_dir or "", name="holder", owner="owner-a"),
            _entry(
                rider.artifacts_dir or "",
                name="rider",
                state="riding_claim",
                owner="owner-a",
                holder_dir=holder.artifacts_dir,
            ),
            _entry(
                idle.artifacts_dir or "",
                name="idle",
                state="not_holding",
                reason="not_started",
                owner="owner-b",
            ),
        ]
    )

    refresh_runner_slot_context(
        [holder, rider, idle], raw_snapshot=snapshot, report=None
    )

    assert (holder.capacity_state, holder.capacity_charged) == ("holding", 1.0)
    assert holder.capacity_weight_source == "default"
    assert holder.capacity_accounting_available is True
    assert rider.capacity_state == "riding_claim"
    assert rider.capacity_charged == 0.0
    assert rider.capacity_claim_holder_dir == holder.artifacts_dir
    assert rider.capacity_claim_holder_name == "holder"
    assert idle.capacity_state == "not_holding"
    assert idle.capacity_reason == "not_started"


def test_workflow_step_rows_never_attach() -> None:
    row = _running("worker")
    step = _agent(
        "worker",
        status="RUNNING",
        agent_type=AgentType.WORKFLOW,
        parent_workflow="demo",
        parent_timestamp="worker",
        step_type="bash",
        step_name="setup",
    )
    assert step.is_workflow_step_child
    snapshot = _snapshot([_holding(row.artifacts_dir or "", name="worker")])

    refresh_runner_slot_context([row, step], raw_snapshot=snapshot, report=None)

    assert row.capacity_state == "holding"
    assert step.capacity_state is None
    assert step.capacity_charged is None


def test_clan_container_sums_distinct_claims() -> None:
    container = _agent("bob-cli", status="RUNNING")
    container.is_clan_container = True
    container.agent_clan = "bob-cli"
    container.agent_clan_generation = "gen-1"
    first = _running("first", agent_clan="bob-cli", agent_clan_generation="gen-1")
    rider = _running("rider", agent_clan="bob-cli", agent_clan_generation="gen-1")
    second = _running("second", agent_clan="bob-cli", agent_clan_generation="gen-1")
    snapshot = _snapshot(
        [
            _holding(first.artifacts_dir or "", name="first", owner="owner-a"),
            _entry(
                rider.artifacts_dir or "",
                name="rider",
                state="riding_claim",
                owner="owner-a",
                holder_dir=first.artifacts_dir,
            ),
            _holding(
                second.artifacts_dir or "", name="second", weight=2.0, owner="owner-b"
            ),
        ]
    )

    refresh_runner_slot_context(
        [container, first, rider, second], raw_snapshot=snapshot, report=None
    )

    assert container.capacity_state == "holding"
    assert container.capacity_charged == 3.0


def test_screenshot_shape_member_marks_sum_to_chip_total() -> None:
    workers = [_running(f"worker-{i}") for i in range(3)]
    verify_a = _running("verify-a", status="TESTING")
    verify_b = _running("verify-b", status="TESTING")
    cutover = _running("cutover", status="WAITING CUTOVER")
    rows = [*workers, verify_a, verify_b, cutover]
    accounting: list[dict[str, object]] = [
        _holding(
            row.artifacts_dir or "", name=row.cl_name, owner=f"owner-{row.cl_name}"
        )
        for row in [*workers, verify_a, verify_b]
    ]
    accounting.append(
        _holding(
            cutover.artifacts_dir or "",
            name="cutover",
            weight=0.0,
            source="explicit_zero",
            owner="owner-cutover",
            reason="explicit_zero_weight",
        )
    )
    snapshot = _snapshot(accounting)
    snapshot["occupied_capacity"] = 5.0

    capacity = refresh_runner_slot_context(rows, raw_snapshot=snapshot, report=None)

    assert capacity.occupied_capacity == 5.0
    total = sum(
        row.capacity_charged or 0.0 for row in rows if row.capacity_state == "holding"
    )
    assert total == 5.0
    assert cutover.capacity_state == "holding"
    assert cutover.capacity_charged == 0.0
    assert cutover.capacity_weight_source == "explicit_zero"


def test_capacity_fields_propagate_to_live_rows_and_patch() -> None:
    from types import MethodType, SimpleNamespace

    from sase.ace.tui.actions.agents._loading_filter import AgentLoadingFilterMixin

    live = _running("worker")
    source = _running("worker")
    source.capacity_state = "holding"
    source.capacity_charged = 1.0
    source.capacity_weight_source = "default"
    source.capacity_reason = None
    source.capacity_claim_owner_key = "owner-a"
    source.capacity_claim_holder_dir = None
    source.capacity_claim_holder_name = None
    source.capacity_accounting_available = True
    unchanged = _running("unchanged")
    unchanged_source = _running("unchanged")
    source.status = "WAITING"
    live_second = _running("worker-second")
    source_second = _running("worker-second")
    source_second.capacity_state = "holding"
    source_second.capacity_charged = 1.0
    source_second.capacity_weight_source = "default"
    source_second.capacity_claim_owner_key = "owner-a"
    source_second.capacity_accounting_available = True
    source_second.status = "WAITING"
    patched: list[tuple[object, bool, bool]] = []
    refreshed_titles: list[str | None] = []
    info_refreshes: list[bool] = []

    def _patch_row(
        row: object,
        *,
        refresh_info: bool,
        refresh_title: bool,
    ) -> bool:
        patched.append((row, refresh_info, refresh_title))
        return True

    stub = SimpleNamespace(
        _agents_capacity_generation=7,
        _agents_capacity_applied_generation=6,
        _agents_with_children=[live, unchanged, live_second],
        _agents_capacity_with_children=(),
        _agents_query_result=(),
        _agents=[live, unchanged, live_second],
        _agent_info_metrics_cache=None,
        current_tab="agents",
        _try_patch_agent_row=_patch_row,
        _agent_panel_index=lambda: SimpleNamespace(keys_per_agent=[None, None, None]),
        _refresh_agent_panel_title_for_key=refreshed_titles.append,
        _update_agents_info_panel=lambda: info_refreshes.append(True),
    )
    stub._apply_agents_capacity_row_updates = MethodType(
        AgentLoadingFilterMixin._apply_agents_capacity_row_updates, stub
    )

    installed = AgentLoadingFilterMixin._apply_agents_capacity_snapshot(
        stub,
        object(),
        row_updates=[source, unchanged_source, source_second],
        generation=7,
    )

    assert installed is True
    assert live.capacity_state == "holding"
    assert live.capacity_charged == 1.0
    assert live.capacity_claim_owner_key == "owner-a"
    assert live.capacity_accounting_available is True
    assert live.status == "WAITING"
    assert live_second.capacity_state == "holding"
    assert patched == [(live, False, False), (live_second, False, False)]
    assert refreshed_titles == [None]
    assert info_refreshes == [True]


@pytest.mark.asyncio
async def test_unchanged_capacity_refresh_skips_row_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sase.ace.tui.actions.agents import _loading_filter as loading_filter
    from sase.ace.tui.actions.agents._loading_filter import AgentLoadingFilterMixin

    import sase.config.core as config_core
    import sase.core.agent_hold_facade as hold_facade
    import sase.ace.tui.models._agent_graph as agent_graph

    row = _running("worker")
    roster = [row]
    report = SimpleNamespace(
        token="same-occupancy",
        effective_limit=8.0,
        occupied_capacity=1.0,
        occupied_lanes=1,
        record_inputs=(),
    )
    active_holds: list[dict[str, object]] = []
    monkeypatch.setattr(hold_facade, "active_agent_hold_records", lambda: active_holds)
    monkeypatch.setattr(config_core, "get_max_running_agents", lambda: 8.0)

    def _unexpected_copy(_rows):  # type: ignore[no-untyped-def]
        pytest.fail("unchanged occupancy must skip graph row copies")

    monkeypatch.setattr(agent_graph, "copy_agent_rows_relinked", _unexpected_copy)
    last_inputs = loading_filter._agents_capacity_refresh_input_key(
        report=report,
        roster=roster,
        roster_generation=4,
        active_holds=active_holds,
        effective_limit=8.0,
    )
    stub = SimpleNamespace(
        _agents_first_load_done=True,
        _agents_capacity_generation=5,
        _agents_capacity_with_children=roster,
        _agents_roster_generation=4,
        _machine_capacity_report=report,
        _agents_capacity_last_applied_inputs=last_inputs,
        _agents_capacity_refresh_pending=False,
    )

    await AgentLoadingFilterMixin._run_agents_capacity_refresh_from_roster(
        stub,
        generation=5,
        source="test",
    )

    assert stub._agents_capacity_applied_generation == 5
    changed_report = SimpleNamespace(**{**vars(report), "token": "new-occupancy"})
    assert (
        loading_filter._agents_capacity_refresh_input_key(
            report=changed_report,
            roster=roster,
            roster_generation=4,
            active_holds=active_holds,
            effective_limit=8.0,
        )
        != last_inputs
    )


def test_snapshot_without_accounting_marks_everything_unknown() -> None:
    row = _running("worker")
    snapshot = {
        "occupied_lanes": 1,
        "occupied_capacity": 1.0,
        "effective_limit": 8.0,
        "claims": [],
        "waiters": [],
    }

    refresh_runner_slot_context([row], raw_snapshot=snapshot, report=None)

    assert row.capacity_state == "unknown"
    assert row.capacity_reason == "unavailable"
    assert row.capacity_accounting_available is False
