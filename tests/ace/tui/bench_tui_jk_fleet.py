"""Fleet fault j/k key-to-paint benchmark cases."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.actions.agents import _fleet as fleet_mod
from sase.ace.tui.app import AceApp
from sase.ace.tui.models.fleet_agents import project_fleet_agents
from sase.dispatch.federation import FederationConfig
from tests.ace.tui._bench_tui_jk_helpers import (
    _print_table,
    _read_samples,
    _summarize,
    _wait_for_startup,
    _warm_agents_navigation,
)
from tests.ace.tui.fleet_fixture import (
    ScriptedFleetFacade,
    fleet_config_for_hosts,
    fleet_fault_diagnostic,
    fleet_host_payload,
    fleet_installation_id,
    fleet_multi_host_response,
    fleet_summary,
)

pytest_plugins = ("tests.ace.tui._bench_tui_jk_helpers",)
pytestmark = pytest.mark.slow

_FLEET_FAULT_P95_BUDGET_MS = 16.0
_FLEET_FAULT_KEYS_PER_DIRECTION = 80
# Each background refresh awaits this delay per facade operation
# (summary + catalog), so one refresh cycle costs roughly twice this before
# its projection lands. Small enough that several refresh cycles resolve
# between triggers below without stacking concurrent reprojections.
_FLEET_FAULT_STEP_DELAY_SECONDS = 0.05
_FLEET_FAULT_STEPS = 4
# Trigger a fresh background refresh partway through each hammering
# direction (twice per direction), so the fault sequence is actually
# consumed *during* the measured j/k window instead of once beforehand.
_FLEET_FAULT_TRIGGER_EVERY_KEYS = _FLEET_FAULT_KEYS_PER_DIRECTION // 2


@pytest.mark.parametrize(
    "scenario",
    ("hung_host", "reconnect_churn", "event_burst"),
)
async def test_bench_agents_fleet_jk_fault_scenarios(
    _perf_jsonl: Path,
    monkeypatch: pytest.MonkeyPatch,
    scenario: str,
) -> None:
    """Keep Fleet j/k p95 below 16 ms while a live fault sequence lands."""
    apollo_id = fleet_installation_id("a")
    zeus_id = fleet_installation_id("b")
    config = fleet_config_for_hosts(("apollo", apollo_id), ("zeus", zeus_id))
    stable_response = _fleet_response(
        ("apollo", apollo_id, 18),
        ("zeus", zeus_id, 18),
    )
    fault_sequence = _fault_sequence(scenario, apollo_id=apollo_id, zeus_id=zeus_id)
    stable_facade = ScriptedFleetFacade(
        summary_response=stable_response,
        catalog_response=stable_response,
    )
    fault_facade = ScriptedFleetFacade(
        summary_response=fault_sequence[-1],
        catalog_response=fault_sequence[-1],
        scripts={"catalog": list(fault_sequence), "summary": list(fault_sequence)},
        delays={
            "catalog": _FLEET_FAULT_STEP_DELAY_SECONDS,
            "summary": _FLEET_FAULT_STEP_DELAY_SECONDS,
        },
    )

    monkeypatch.setattr(fleet_mod, "load_federation_config", lambda: config)
    monkeypatch.setattr(
        fleet_mod,
        "build_federation_facade",
        lambda _config: stable_facade,
    )

    app = AceApp(query="!!!", auto_start_axe=False, refresh_interval=0)
    async with app.run_test() as pilot:
        await _wait_for_startup(app, pilot)
        await pilot.press("ctrl+l")
        await pilot.pause()
        _install_fleet_rows(app, stable_response, config=config)
        await pilot.pause(0.2)
        await _warm_agents_navigation(pilot)

        monkeypatch.setattr(
            fleet_mod,
            "build_federation_facade",
            lambda _config: fault_facade,
        )
        # Seed the same row shape the first fault-sequence step will confirm,
        # so the measured window below starts from a settled layout: any
        # paint-timing cost comes from faults landing mid-navigation, not
        # from a one-off structural repaint.
        _install_fleet_rows(app, fault_sequence[0], config=config)
        await pilot.pause(0.2)
        await _warm_agents_navigation(pilot)

        before = len(_read_samples(_perf_jsonl))
        fault_start = time.perf_counter()
        app._schedule_agents_fleet_refresh(source=f"bench_{scenario}", force=True)
        key_count = 0
        for direction in ("j", "k"):
            for _ in range(_FLEET_FAULT_KEYS_PER_DIRECTION):
                await pilot.press(direction)
                await pilot.pause()
                key_count += 1
                if key_count % _FLEET_FAULT_TRIGGER_EVERY_KEYS == 0:
                    app._schedule_agents_fleet_refresh(
                        source=f"bench_{scenario}", force=False
                    )
        await _wait_for_fleet_refresh(app)
        fault_end = time.perf_counter()

    samples = [
        sample
        for sample in _read_samples(_perf_jsonl)[before:]
        if sample.get("tab") == "agents" and sample.get("action") in {"next", "prev"}
    ]
    summary = _summarize(samples)
    _print_table(f"Agents Fleet j/k fault scenario {scenario}:", summary)
    assert set(summary) == {"next", "prev"}
    assert all(
        stats["p95"] < _FLEET_FAULT_P95_BUDGET_MS for stats in summary.values()
    ), f"Fleet fault scenario {scenario} exceeded 16 ms p95: {summary}"
    stall_path = _perf_jsonl.with_name("tui_stalls.jsonl")
    assert not stall_path.exists() or not stall_path.read_text().strip()

    _assert_fault_sequence_overlapped_samples(
        scenario,
        fault_facade=fault_facade,
        samples=samples,
        window=(fault_start, fault_end),
    )


def _assert_fault_sequence_overlapped_samples(
    scenario: str,
    *,
    fault_facade: ScriptedFleetFacade,
    samples: list[dict[str, Any]],
    window: tuple[float, float],
) -> None:
    """Prove the fault sequence resolved during, not before, the sample run.

    ``ScriptedFleetFacade.call_windows`` records a real ``perf_counter()``
    span for every ``catalog``/``summary`` call, in the same clock as each
    sample's ``t_keypress``. This checks real evidence that the scripted
    fault sequence was still being delivered while j/k paint latency was
    being measured, rather than trusting that timings happened to line up.
    """
    fault_windows = fault_facade.call_windows.get("catalog", [])
    assert len(fault_windows) >= 2, (
        f"Fleet fault scenario {scenario} only delivered {len(fault_windows)} "
        "catalog response(s); expected a real sequence of multiple fault "
        f"responses, not one static response: {fault_windows}"
    )
    sample_times = [float(sample["t_keypress"]) for sample in samples]
    assert sample_times, f"Fleet fault scenario {scenario} recorded no samples"
    sample_start, sample_end = min(sample_times), max(sample_times)
    overlapping = [
        (start, end)
        for start, end in fault_windows
        if start <= sample_end and end >= sample_start
    ]
    assert overlapping, (
        f"Fleet fault scenario {scenario} fault call windows {fault_windows} "
        f"never overlapped the measured sample window "
        f"[{sample_start}, {sample_end}] (refresh window {window})"
    )


def _fleet_response(*host_specs: tuple[str, str, int]) -> dict[str, Any]:
    hosts = []
    for alias, installation_id, count in host_specs:
        hosts.append(
            fleet_host_payload(
                alias=alias,
                installation_id=installation_id,
                summaries=(
                    fleet_summary(
                        installation_id=installation_id,
                        agent_id=f"{alias}-agent-{index:03d}",
                        run_id=f"{alias}-run-{index:03d}",
                        revision=index + 1,
                        patch_name=f"{alias}-fleet",
                        bounded_intent="exercise Fleet j/k under faults",
                    )
                    for index in range(count)
                ),
            )
        )
    return fleet_multi_host_response(*hosts, configured_hosts=len(host_specs))


def _fault_sequence(
    scenario: str,
    *,
    apollo_id: str,
    zeus_id: str,
) -> list[dict[str, Any]]:
    """Build the ordered fault responses a scenario delivers while measured.

    Each entry is a distinct response (not a repeat of the last), so
    consuming the whole list through a ``ScriptedFleetFacade`` script proves
    a real sequence of faults landed rather than one static response sitting
    in flight for the whole bench.
    """
    if scenario == "hung_host":
        return [
            fleet_multi_host_response(
                fleet_host_payload(
                    alias="apollo",
                    installation_id=apollo_id,
                    summaries=(
                        fleet_summary(
                            installation_id=apollo_id,
                            agent_id=f"apollo-agent-{index:03d}",
                            run_id=f"apollo-run-{index:03d}",
                            revision=index + 2 + step,
                        )
                        for index in range(18)
                    ),
                ),
                configured_hosts=2,
                diagnostics=(
                    fleet_fault_diagnostic(
                        alias="zeus",
                        operation="catalog",
                        code="host_deadline_exceeded",
                        message=(
                            "zeus catalog exceeded the offline deadline "
                            f"(attempt {step + 1})"
                        ),
                    ),
                ),
                partial=True,
            )
            for step in range(_FLEET_FAULT_STEPS)
        ]
    if scenario == "reconnect_churn":
        return [
            fleet_multi_host_response(
                fleet_host_payload(
                    alias="apollo",
                    installation_id=apollo_id,
                    summaries=(
                        fleet_summary(
                            installation_id=apollo_id,
                            agent_id=f"apollo-agent-{index:03d}",
                            run_id=f"apollo-run-{index:03d}",
                            revision=index + 2 + step,
                        )
                        for index in range(18)
                    ),
                ),
                fleet_host_payload(
                    alias="zeus",
                    installation_id=zeus_id,
                    summaries=(
                        fleet_summary(
                            installation_id=zeus_id,
                            agent_id=f"zeus-agent-{index:03d}",
                            run_id=f"zeus-run-{index:03d}",
                            revision=index + 2 + step,
                            status=("starting" if index % 8 == step % 8 else "running"),
                        )
                        for index in range(18)
                    ),
                    freshness="aging" if step % 2 == 0 else "fresh",
                    connection_health="reconnecting" if step % 2 == 0 else "online",
                ),
                diagnostics=(
                    fleet_fault_diagnostic(
                        alias="zeus",
                        operation="summary",
                        code="host_reconnect_churn",
                        message=(
                            "zeus reconnected during the offline refresh "
                            f"(attempt {step + 1})"
                        ),
                    ),
                ),
                partial=True,
            )
            for step in range(_FLEET_FAULT_STEPS)
        ]
    if scenario == "event_burst":
        # Hold row counts fixed across steps (unlike a host gaining/losing
        # agents) and instead flip `status` for a rotating eighth of each
        # host's rows every step: a burst of a few agents starting/finishing
        # at once, not a fleet that is growing. Keep revision churn scoped
        # to the rows whose lifecycle state changes; dirtying every row
        # would measure a full-page update rather than an event burst.
        # `status` is a compared `Agent` field, so this drives the same
        # per-row patch path as `reconnect_churn`, just spread across both
        # hosts, rather than the far costlier full-list rebuild a row-count change
        # (`has_collection_changes`) triggers because Fleet rows from every
        # host share one merged, ungrouped panel. The rotation fraction is
        # narrower than `reconnect_churn`'s because this scenario touches
        # both hosts each step (double the per-step patch count for the
        # same fraction).
        return [
            fleet_multi_host_response(
                fleet_host_payload(
                    alias="apollo",
                    installation_id=apollo_id,
                    summaries=(
                        fleet_summary(
                            installation_id=apollo_id,
                            agent_id=f"apollo-agent-{index:03d}",
                            run_id=f"apollo-run-{index:03d}",
                            revision=_event_burst_revision(index, step),
                            status=_event_burst_status(index, step),
                            patch_name="apollo-fleet",
                            bounded_intent="exercise Fleet j/k under faults",
                        )
                        for index in range(24)
                    ),
                ),
                fleet_host_payload(
                    alias="zeus",
                    installation_id=zeus_id,
                    summaries=(
                        fleet_summary(
                            installation_id=zeus_id,
                            agent_id=f"zeus-agent-{index:03d}",
                            run_id=f"zeus-run-{index:03d}",
                            revision=_event_burst_revision(index, step),
                            status=_event_burst_status(index, step),
                            patch_name="zeus-fleet",
                            bounded_intent="exercise Fleet j/k under faults",
                        )
                        for index in range(24)
                    ),
                ),
                configured_hosts=2,
            )
            for step in range(_FLEET_FAULT_STEPS)
        ]
    raise AssertionError(f"unknown Fleet fault scenario: {scenario}")


def _event_burst_status(index: int, step: int) -> str:
    return "starting" if index % 8 == step % 8 else "running"


def _event_burst_revision(index: int, step: int) -> int:
    row_bucket = index % 8
    revision = index + 1
    for transition_step in range(1, step + 1):
        if row_bucket in {transition_step % 8, (transition_step - 1) % 8}:
            revision = index + 1 + transition_step
    return revision


def _install_fleet_rows(
    app: AceApp,
    response: dict[str, Any],
    *,
    config: FederationConfig,
) -> None:
    projection = project_fleet_agents(catalog_response=response)
    app._agents_local_with_children = []
    app._agents_local_visible = []
    app._agents_fleet_projection = projection
    app._agents_fleet_rows = list(projection.fleet_rows)
    app._agents_fleet_focus_rows = list(projection.focus_rows)
    app._agents_fleet_available = True
    app.current_idx = 0
    app._apply_fleet_projection(
        projection,
        config=config,
        generation=app._agents_fleet_refresh_generation,
    )
    app._refresh_agents_display(list_changed=True, defer_detail=True)


async def _wait_for_fleet_refresh(app: AceApp) -> None:
    deadline = asyncio.get_running_loop().time() + 5.0
    while any(not task.done() for task in app._agents_fleet_async_tasks):
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError("Fleet benchmark refresh did not settle within 5s")
        await asyncio.sleep(0.01)  # sase-test-wait: poll Fleet refresh task completion
