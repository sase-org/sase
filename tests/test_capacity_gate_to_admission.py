"""Epic gate capacity through launch argv, rendering, expansion, and admission."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from sase.axe import run_agent_wait_markers, run_agent_wait_slots
from sase.bead.epic_launch import build_epic_launch_argv
from sase.bead.work import (
    EpicWorkPlan,
    _PhaseAssignment as PhaseAssignment,
    render_multi_prompt,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.service import create_gate
from sase.plan_gate import build_plan_approval_gate_spec, translate_plan_gate_response
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.processor import process_xprompt_references
from sase.xprompt.workflow_models import Workflow
from tests._plan_gate_fixtures import (
    plan_gate_home,  # noqa: F401 (registers the gate_home fixture)
    write_plan,
)
from tests._runner_slot_fixtures import artifact, record
from tests.plan_validation_helpers import VALID_EPIC_PLAN


def _capacity_from_argv(argv: list[str]) -> int | None:
    if "--capacity" not in argv:
        return None
    return int(argv[argv.index("--capacity") + 1])


def _epic_work_plan() -> EpicWorkPlan:
    return EpicWorkPlan(
        epic_id="sase-zp",
        launch_tag_id="sase-zp",
        total_phase_count=1,
        phase_bead_ids=("sase-zp.1",),
        waves=(
            (
                PhaseAssignment(
                    bead_id="sase-zp.1",
                    agent_name="sase-zp.1",
                    waits_on=(),
                    blocker_bead_ids=(),
                    wave=0,
                ),
            ),
        ),
        land_agent_name="sase-zp.land",
        land_waits_on=("sase-zp.1",),
    )


def _expanded_directives(segment: str) -> Any:
    expanded = process_xprompt_references(segment, raise_on_error=True)
    _cleaned, directives = extract_prompt_directives(expanded)
    return directives


def _try_admit(
    tmp_path: Path,
    occupied: list[Path],
    *,
    name: str,
    capacity: int | None,
    queue_weight: float,
    queue_weight_explicit: bool,
    global_limit: int,
) -> tuple[str | None, bool]:
    waiter = artifact(tmp_path, name, 900 + len(name))
    started = {str(path) for path in occupied}

    def scan() -> list[Any]:
        records = [record(path, started=True) for path in occupied]
        records.append(record(waiter, started=str(waiter) in started))
        return records

    with (
        patch.object(
            run_agent_wait_slots, "_scan_runner_slot_records", side_effect=scan
        ),
        patch.object(run_agent_wait_slots, "is_process_alive", return_value=True),
        patch.object(
            run_agent_wait_slots, "get_max_running_agents", return_value=global_limit
        ),
        patch.object(
            run_agent_wait_markers,
            "update_agent_artifact_index_for_marker_mutation",
        ),
        patch.dict("os.environ", {"SASE_HOME": str(tmp_path / ".sase")}),
    ):
        return run_agent_wait_slots._try_claim_runner_slot(
            artifacts_dir=str(waiter),
            cl_name="cl",
            timestamp=waiter.name,
            directive_threshold=capacity,
            directive_queue_weight=queue_weight,
            directive_queue_weight_explicit=queue_weight_explicit,
            claim=lambda: started.add(str(waiter)) or "started",
        )


def _gate_capacity(
    gate_home: Path, payload: dict[str, object], stem: str
) -> tuple[int | None, list[str], int | None]:
    plan = write_plan(gate_home, f"{stem}.md", VALID_EPIC_PLAN)
    gate = create_gate(build_plan_approval_gate_spec(plan, stem))
    with patch(
        "sase.plan_approval_actions.prepare_epic_launch",
        return_value=SimpleNamespace(monitor_id=f"mon-{stem}"),
    ) as prepare:
        execution = execute_gate_selection(gate.bundle_path, ["approve"], payload)
    translated = translate_plan_gate_response(gate.bundle_path, execution.response)
    argv = build_epic_launch_argv(
        str(plan), capacity=prepare.call_args.kwargs.get("capacity")
    )
    assert prepare.call_count == 1
    capacity = translated["capacity"] if "capacity" in translated else None
    return capacity, argv, prepare.call_args.kwargs.get("capacity")


def test_epic_gate_capacity_reaches_weighted_admission(
    gate_home: Path, tmp_path: Path
) -> None:
    translated_capacity, argv, launch_capacity = _gate_capacity(
        gate_home, {"capacity": 1, "epic_launch_mode": "launch"}, "epic-capacity-path"
    )
    assert translated_capacity == 1
    assert launch_capacity == 1
    assert "--capacity" in argv
    assert argv[argv.index("--capacity") + 1] == "1"
    capacity = _capacity_from_argv(argv)
    assert capacity == 1

    rendered = render_multi_prompt(
        _epic_work_plan(),
        work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
        land_epic_xprompt=Workflow(name="bd/land_epic"),
        capacity=capacity,
    )
    segments = rendered.split("\n---\n")
    assert len(segments) == 2
    phase, land = (_expanded_directives(segment) for segment in segments)

    assert phase.wait_runners == 1
    assert land.wait_runners == 1
    assert land.queue_weight == 2.0
    assert land.queue_weight_explicit is True
    assert phase.queue_weight_explicit is False

    light_occupied = [
        artifact(
            tmp_path,
            f"light{index}",
            100 + index,
            queue_weight=0.25,
            queue_weight_explicit=True,
        )
        for index in range(4)
    ]
    phase_ok, phase_parked = _try_admit(
        tmp_path,
        light_occupied,
        name="phase-light",
        capacity=phase.wait_runners,
        queue_weight=phase.queue_weight or 1.0,
        queue_weight_explicit=phase.queue_weight_explicit,
        global_limit=10,
    )
    land_ok, land_parked = _try_admit(
        tmp_path,
        light_occupied,
        name="land-light",
        capacity=land.wait_runners,
        queue_weight=land.queue_weight or 1.0,
        queue_weight_explicit=land.queue_weight_explicit,
        global_limit=10,
    )
    assert phase_ok == "started"
    assert not phase_parked
    assert land_ok == "started"
    assert not land_parked

    heavy = artifact(
        tmp_path, "heavy", 200, queue_weight=2.0, queue_weight_explicit=True
    )
    blocked, parked = _try_admit(
        tmp_path,
        [heavy],
        name="land-heavy",
        capacity=land.wait_runners,
        queue_weight=land.queue_weight or 1.0,
        queue_weight_explicit=land.queue_weight_explicit,
        global_limit=10,
    )
    assert blocked is None
    assert parked


def test_omitted_capacity_preserves_land_weight_and_global_budget(
    gate_home: Path, tmp_path: Path
) -> None:
    translated_capacity, argv, launch_capacity = _gate_capacity(
        gate_home, {"epic_launch_mode": "launch"}, "epic-capacity-omit"
    )
    assert translated_capacity is None
    assert launch_capacity is None
    assert "--capacity" not in argv
    assert _capacity_from_argv(argv) is None

    rendered = render_multi_prompt(
        _epic_work_plan(),
        work_phase_xprompt=Workflow(name="bd/work_phase_bead"),
        land_epic_xprompt=Workflow(name="bd/land_epic"),
        capacity=_capacity_from_argv(argv),
    )
    segments = rendered.split("\n---\n")
    assert all("%queue(capacity=" not in segment for segment in segments)
    phase, land = (_expanded_directives(segment) for segment in segments)

    assert phase.wait_runners is None
    assert land.wait_runners is None
    assert land.queue_weight == 2.0
    assert land.queue_weight_explicit is True

    occupied = [
        artifact(
            tmp_path,
            "quarter",
            100,
            queue_weight=0.25,
            queue_weight_explicit=True,
        )
    ]
    land_ok, land_parked = _try_admit(
        tmp_path,
        occupied,
        name="land-omit",
        capacity=land.wait_runners,
        queue_weight=land.queue_weight or 1.0,
        queue_weight_explicit=land.queue_weight_explicit,
        global_limit=2,
    )
    assert land_ok is None
    assert land_parked

    phase_ok, phase_parked = _try_admit(
        tmp_path,
        occupied,
        name="phase-omit",
        capacity=phase.wait_runners,
        queue_weight=phase.queue_weight or 1.0,
        queue_weight_explicit=phase.queue_weight_explicit,
        global_limit=2,
    )
    assert phase_ok == "started"
    assert not phase_parked
