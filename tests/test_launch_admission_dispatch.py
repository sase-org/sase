"""Launch-admission agent dispatch behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.core.agent_launch_wire import LaunchUnitWire
from tests._launch_admission_helpers import (
    agent_result as _agent_result,
    agent_unit as _agent_unit,
    plan as _plan,
    run_plan as _run_plan,
)


def test_engine_dispatches_agent_after_empty_wait(
    tmp_path: Path,
) -> None:
    pytest.importorskip("sase_core_rs")
    dispatched: list[str] = []

    def dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str, str | None, list[AgentLaunchResult]]:
        dispatched.append(fingerprint)
        return True, "reviewer", None, [_agent_result(tmp_path)]

    progress, _response_dir = _run_plan(
        tmp_path,
        _plan(_agent_unit("unit-1")),
        request_id="req-1",
        agent_dispatcher=dispatcher,
        proc_dispatcher=lambda unit, fingerprint: (False, None, "unused", []),
    )
    assert progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert progress.summary.launch_errors == 0
    assert len(dispatched) == 1
    replay, _ = _run_plan(
        tmp_path,
        _plan(_agent_unit("unit-1")),
        request_id="req-1",
        agent_dispatcher=dispatcher,
    )
    assert replay.summary is not None
    assert replay.summary.launched == 1
    assert len(dispatched) == 1


def test_partial_success_keeps_launched_identity(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    identities: list[str] = []

    def dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
        if unit.logical_id == "unit-2":
            return False, None, "spawn failed", []
        identities.append(unit.logical_id)
        return True, unit.logical_id, None, [_agent_result(tmp_path, unit.logical_id)]

    progress, _ = _run_plan(
        tmp_path,
        _plan(_agent_unit("unit-1"), _agent_unit("unit-2", source_order=1)),
        request_id="req-partial",
        agent_dispatcher=dispatcher,
    )
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert progress.summary.launch_errors == 1
    assert identities == ["unit-1"]
    assert any(
        result.logical_id == "unit-1" and result.outcome == "launched"
        for result in progress.unit_results
    )


def test_cancel_open_units_does_not_erase_launched(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    cancelled = False

    def dispatcher(
        unit: LaunchUnitWire, fingerprint: str
    ) -> tuple[bool, str | None, str | None, list[AgentLaunchResult]]:
        nonlocal cancelled
        cancelled = True
        return True, "reviewer", None, [_agent_result(tmp_path)]

    progress, _ = _run_plan(
        tmp_path,
        _plan(_agent_unit("unit-1"), _agent_unit("unit-2", source_order=1)),
        request_id="req-cancel",
        cancelled=lambda: cancelled,
        agent_dispatcher=dispatcher,
    )
    assert progress.summary is not None
    assert progress.summary.launched == 1
    assert progress.summary.launch_errors == 1
    outcomes = {result.logical_id: result.outcome for result in progress.unit_results}
    assert outcomes["unit-1"] == "launched"
    assert outcomes["unit-2"] == "launch_error"
