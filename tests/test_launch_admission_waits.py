"""Launch-admission wait dependency behavior."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.core.agent_launch_wire import (
    AgentUnitWire,
    LaunchConditionWire,
    LaunchPlanWire,
    LaunchUnitWire,
    WaitTargetWire,
)
from tests._launch_admission_helpers import (
    agent_result as _agent_result,
    agent_unit as _agent_unit,
    code as _code,
    plan as _plan,
    run_plan as _run_plan,
)


def test_waiting_does_not_claim_resources(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")
    claims: list[str] = []

    def wait_resolver(
        plan: LaunchPlanWire,
        states: dict[str, dict[str, Any]],
        *,
        now: float,
        waiting_since: Any,
    ) -> list[dict[str, Any]]:
        del plan, states, now, waiting_since
        claims.append("wait")
        return [
            {
                "target": {"kind": "agent", "name": "builder"},
                "resolved": False,
            }
        ]

    with (
        patch("sase.running_field.claim_workspace") as claim_workspace,
        patch("sase.procs.store.reserve_proc") as reserve_proc,
    ):
        progress, _ = _run_plan(
            tmp_path,
            _plan(
                _agent_unit(
                    "unit-1",
                    waits=[WaitTargetWire(kind="agent", name="builder")],
                )
            ),
            request_id="req-wait",
            wait_resolver=wait_resolver,
            agent_dispatcher=lambda unit, fingerprint: (
                True,
                "x",
                None,
                [_agent_result(tmp_path)],
            ),
        )

    assert not progress.admission_complete
    assert progress.summary is not None
    assert progress.summary.launched == 0
    assert claims
    claim_workspace.assert_not_called()
    reserve_proc.assert_not_called()


def test_skipped_predecessor_does_not_retarget(tmp_path: Path) -> None:
    pytest.importorskip("sase_core_rs")

    def evaluator(
        unit: LaunchUnitWire,
        waited: list[dict[str, Any]],
        context: Any,
    ) -> tuple[str, str | None]:
        del waited, context
        if unit.logical_id == "unit-1":
            return "skipped", "predicate exited 1"
        return "eligible", None

    progress, response_dir = _run_plan(
        tmp_path,
        _plan(
            LaunchUnitWire(
                logical_id="unit-1",
                source_order=0,
                payload=AgentUnitWire(prompt="First"),
                condition=LaunchConditionWire(code=_code()),
            ),
            _agent_unit(
                "unit-2",
                source_order=1,
                waits=[
                    WaitTargetWire(kind="logical", logical_id="unit-1", source="%wait")
                ],
            ),
        ),
        request_id="req-skip",
        condition_evaluator=evaluator,
        agent_dispatcher=lambda unit, fingerprint: (
            True,
            unit.logical_id,
            None,
            [_agent_result(tmp_path, unit.logical_id)],
        ),
    )
    assert progress.summary is not None
    assert progress.summary.skipped == 1
    assert progress.summary.launched == 1
    journal = (response_dir / "launch_admission" / "journal.jsonl").read_text(
        encoding="utf-8"
    )
    waited = None
    for line in journal.splitlines():
        entry = json.loads(line)
        if entry.get("logical_id") == "unit-2" and entry.get("waited_outcomes"):
            waited = entry["waited_outcomes"]
    assert waited is not None
    assert waited[0]["outcome"] == "skipped"
    assert waited[0]["target"]["logical_id"] == "unit-1"
