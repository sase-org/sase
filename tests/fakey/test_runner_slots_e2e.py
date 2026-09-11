"""End-to-end runner-slot lifecycle coverage with the fakey provider.

These scenarios exercise the production filesystem scan, global flock, marker
mutations, live config reload, and a real bundled ``fakey`` subprocess.  The
only shortened production behavior is the two-second parked-agent poll.

Real monitor and gate-shell lifecycle acceptance lives in the sibling
``test_monitor_capacity_e2e.py`` and ``test_gate_capacity_e2e.py``, which
share this module's harness.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.fakey._runner_slot_harness import _RunnerSlotFakeyHarness


def test_fakey_agents_respect_cap_and_release_in_fifo_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=2)
    agents = [harness.create_agent(index) for index in range(5)]

    for agent in agents[:2]:
        harness.start(agent)
        harness.wait_started(agent)
    for agent in agents[2:]:
        harness.start(agent)
        harness.wait_parked(agent)

    for finished, admitted in zip(agents, agents[2:], strict=False):
        harness.release_agent(finished)
        harness.join(finished)
        harness.wait_started(admitted)

    for agent in agents[3:]:
        harness.release_agent(agent)
    harness.join_all(agents)

    assert harness.claim_order == [agent.name for agent in agents]
    assert harness.max_active_roots == 2


def test_fakey_drain_barrier_blocks_later_launch_until_capacity_is_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    running = harness.create_agent(0, name="running")
    barrier = harness.create_agent(1, name="barrier", wait_runners=0)
    later = harness.create_agent(2, name="later", wait_runners=25)

    harness.start(running)
    harness.wait_started(running)
    harness.start(barrier)
    harness.wait_parked(barrier)
    harness.start(later)
    harness.wait_parked(later)
    assert not later.started.exists()

    harness.release_agent(running)
    harness.join(running)
    harness.wait_started(barrier)
    assert not later.started.exists()

    harness.release_agent(barrier)
    harness.join(barrier)
    harness.wait_started(later)

    assert harness.claim_order == ["running", "barrier", "later"]
    barrier_meta = json.loads(
        (barrier.artifacts_dir / "agent_meta.json").read_text(encoding="utf-8")
    )
    assert isinstance(barrier_meta.get("run_started_at"), str)
    harness.release_agent(later)
    harness.join(later)


def test_fakey_priority_admission_differs_from_park_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    running = harness.create_agent(0, name="running")
    older = harness.create_agent(1, name="older", wait_priority=20)
    newer = harness.create_agent(2, name="newer", wait_priority=1)

    harness.start(running)
    harness.wait_started(running)
    harness.start(older)
    harness.wait_parked(older)
    harness.start(newer)
    harness.wait_parked(newer)

    harness.release_agent(running)
    harness.join(running)
    harness.wait_started(newer)
    assert not older.started.exists()

    harness.release_agent(newer)
    harness.join(newer)
    harness.wait_started(older)
    harness.release_agent(older)
    harness.join(older)

    assert harness.claim_order == ["running", "newer", "older"]


def test_fractional_fakey_agents_fill_capacity_exactly_and_live_reload_allows_heavy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    quarter_agents = [
        harness.create_agent(
            index,
            name=f"quarter-{index}",
            queue_weight=0.25,
            queue_weight_explicit=True,
        )
        for index in range(4)
    ]

    for agent in quarter_agents:
        harness.start(agent)
        harness.wait_started(agent)

    heavy = harness.create_agent(
        10,
        name="heavy",
        wait_priority=0,
        queue_weight=2.0,
        queue_weight_explicit=True,
    )
    lighter = harness.create_agent(
        11,
        name="lighter",
        queue_weight=0.25,
        queue_weight_explicit=True,
    )
    harness.start(heavy)
    harness.wait_parked(heavy)
    harness.start(lighter)
    harness.wait_parked(lighter)

    heavy_marker = harness.waiting_marker(heavy)
    assert heavy_marker["queue_weight"] == pytest.approx(2.0)
    assert heavy_marker["queue_weight_explicit"] is True
    assert heavy_marker["wait_priority"] == 0
    assert heavy_marker["wait_priority_explicit"] is True

    harness.release_agent(quarter_agents[0])
    harness.join(quarter_agents[0])
    harness.wait_started(lighter)
    assert not heavy.started.exists(), harness._diagnostics(heavy)

    harness.release_agent(lighter)
    harness.join(lighter)
    assert not heavy.started.exists(), harness._diagnostics(heavy)

    for agent in quarter_agents[1:]:
        harness.release_agent(agent)
        harness.join(agent)
    harness.assert_parked_not_started(heavy)

    harness.write_cap(2)
    harness.wait_started(heavy)
    harness.release_agent(heavy)
    harness.join(heavy)

    assert harness.claim_order == [
        *(agent.name for agent in quarter_agents),
        "lighter",
        "heavy",
    ]
    assert harness.max_active_roots == 4
    assert harness.agent_meta(heavy)["queue_weight"] == pytest.approx(2.0)
    assert (
        harness.agent_meta(heavy)["runner_claim_owner_key"] == heavy.artifacts_dir.name
    )


def test_explicit_zero_runner_priority_and_weight_survive_real_parking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    running = harness.create_agent(0, name="running")
    barrier = harness.create_agent(
        1,
        name="zero-directives",
        wait_runners=0,
        wait_priority=0,
        queue_weight=0.25,
        queue_weight_explicit=True,
    )

    harness.start(running)
    harness.wait_started(running)
    harness.start(barrier)
    harness.wait_parked(barrier)

    marker = harness.waiting_marker(barrier)
    assert marker["wait_runners"] == 0
    assert marker["wait_runners_explicit"] is True
    assert marker["wait_priority"] == 0
    assert marker["wait_priority_explicit"] is True
    assert marker["queue_weight"] == pytest.approx(0.25)
    assert marker["queue_weight_explicit"] is True

    harness.release_agent(running)
    harness.join(running)
    harness.wait_started(barrier)

    meta = harness.agent_meta(barrier)
    assert meta["wait_runners"] == 0
    assert meta["wait_priority"] == 0
    assert meta["queue_weight"] == pytest.approx(0.25)
    assert meta["queue_weight_explicit"] is True
    assert meta["runner_claim_owner_key"] == barrier.artifacts_dir.name
    harness.release_agent(barrier)
    harness.join(barrier)


def test_installed_research_swarm_quarter_weights_fill_one_fakey_capacity_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("sase_research_artifacts")

    from sase.agent.launch_request_planning import expand_prompt_for_typed_launch
    from sase.core.agent_launch_facade import plan_typed_launch_units
    from sase.xprompt.loader import get_all_xprompts

    catalog = get_all_xprompts()
    research_swarm = catalog["research_swarm"]
    assert (
        research_swarm.source_path == "plugin:sase_research_artifacts/research_swarm.md"
    )

    default_plan = plan_typed_launch_units(
        expand_prompt_for_typed_launch("#research_swarm:: weighted queue acceptance"),
        selected_project="sase",
    )
    assert len(default_plan.units) == 4
    assert [
        (unit.payload.queue_weight, unit.payload.queue_weight_explicit)
        for unit in default_plan.units
    ] == [(0.25, True)] * 4
    assert [unit.payload.wait_runners for unit in default_plan.units] == [None] * 4
    assert [unit.payload.wait_priority for unit in default_plan.units] == [None] * 4
    assert [
        [wait.logical_id for wait in unit.waits] for unit in default_plan.units
    ] == [
        [],
        [],
        ["unit-1", "unit-2"],
        ["unit-3"],
    ]

    explicit_zero_plan = plan_typed_launch_units(
        expand_prompt_for_typed_launch(
            "#research_swarm("
            "prompt='weighted queue acceptance', "
            "runners=0, priority=0, wait='upstream'"
            ")"
        ),
        selected_project="sase",
    )
    assert len(explicit_zero_plan.units) == 4
    for unit in explicit_zero_plan.units:
        assert unit.payload.queue_weight == pytest.approx(0.25)
        assert unit.payload.queue_weight_explicit is True
        assert unit.payload.wait_runners == 0
        assert unit.payload.wait_priority == 0
    assert [wait.name for wait in explicit_zero_plan.units[0].waits] == ["upstream"]
    assert [wait.name for wait in explicit_zero_plan.units[1].waits] == ["upstream"]

    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    agents = [
        harness.create_agent(
            40 + index,
            name=f"research-unit-{index + 1}",
            queue_weight=float(unit.payload.queue_weight),
            queue_weight_explicit=unit.payload.queue_weight_explicit,
        )
        for index, unit in enumerate(default_plan.units)
    ]

    for agent in agents:
        harness.start(agent)
        harness.wait_started(agent)
    assert harness.max_active_roots == 4
    assert [
        harness.agent_meta(agent)["queue_weight"] for agent in agents
    ] == pytest.approx([0.25, 0.25, 0.25, 0.25])

    for agent in agents:
        harness.release_agent(agent)
    harness.join_all(agents)


def test_live_config_raise_releases_fakey_waiter_without_axe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    running = harness.create_agent(0, name="running")
    waiter = harness.create_agent(1, name="config-waiter")

    harness.start(running)
    harness.wait_started(running)
    harness.start(waiter)
    harness.wait_parked(waiter)
    harness.write_cap(2)
    harness.wait_started(waiter)

    assert harness.claim_order == ["running", "config-waiter"]
    assert harness.max_active_roots == 2
    for agent in (running, waiter):
        harness.release_agent(agent)
    harness.join_all([running, waiter])


def test_killing_parked_fakey_agent_keeps_queue_healthy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    running = harness.create_agent(0, name="running")
    killed = harness.create_agent(1, name="killed-waiter")
    survivor = harness.create_agent(2, name="survivor")

    harness.start(running)
    harness.wait_started(running)
    harness.start(killed)
    harness.wait_parked(killed)
    harness.start(survivor)
    harness.wait_parked(survivor)
    harness.kill_parked(killed)

    harness.release_agent(running)
    harness.join(running)
    harness.wait_started(survivor)
    harness.release_agent(survivor)
    harness.join(survivor)

    assert harness.claim_order == ["running", "survivor"]


def test_crashed_fakey_runner_frees_slot_without_done_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    crashed = harness.create_agent(0, name="crashed", crash=True)
    survivor = harness.create_agent(1, name="survivor")

    harness.start(crashed)
    harness.wait_started(crashed)
    harness.start(survivor)
    harness.wait_parked(survivor)
    harness.release_agent(crashed)
    harness.join(crashed)
    harness.wait_started(survivor)

    assert not (crashed.artifacts_dir / "done.json").exists()
    assert harness.claim_order == ["crashed", "survivor"]
    harness.release_agent(survivor)
    harness.join(survivor)


def test_child_is_exempt_while_repeat_roots_stay_capped(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = _RunnerSlotFakeyHarness(tmp_path, monkeypatch, cap=1)
    parent = harness.create_agent(0, name="parent", agent_family="parent")
    child = harness.create_agent(
        1,
        name="parent.child",
        parent_timestamp=parent.artifacts_dir.name,
        agent_family="parent",
    )
    repeats = [harness.create_agent(index, name=f"repeat-{index}") for index in (2, 3)]

    harness.start(parent)
    harness.wait_started(parent)
    harness.start(child)
    harness.wait_started(child)
    for repeat in repeats:
        harness.start(repeat)
        harness.wait_parked(repeat)

    harness.release_agent(parent)
    harness.join(parent)
    # The family (parent + child) still holds its one slot while the exempt
    # child is alive, even though parent's own record is now done.
    harness.assert_parked_not_started(repeats[0])

    harness.release_agent(child)
    harness.join(child)
    harness.wait_started(repeats[0])
    harness.release_agent(repeats[0])
    harness.join(repeats[0])
    harness.wait_started(repeats[1])

    harness.release_agent(repeats[1])
    harness.join(repeats[1])

    assert harness.claim_order == ["parent", "parent.child", "repeat-2", "repeat-3"]
    assert harness.max_active_roots == 1
