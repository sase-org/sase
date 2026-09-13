"""Per-segment ``--capacity`` resolution for epic ``sase bead work``."""

from __future__ import annotations

from typing import Any

import pytest

from sase.bead.model import PhaseSize
from sase.bead.work import (
    EpicWorkPlan,
    _PhaseAssignment as PhaseAssignment,
    render_multi_prompt,
)
from sase.bead.work_queue_capacity import (
    EpicQueueCapacityConflictError,
    _RaisedQueueCapacity,
    _probe_segment_queue_fields,
    _queue_probe_text,
    resolve_epic_queue_capacities,
)
from sase.feature_flags import override_flags
from sase.xprompt.directives import extract_prompt_directives
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.processor import (
    LAUNCH_DEFERRED_XPROMPT_NAMES,
    process_xprompt_references,
)
from sase.xprompt.workflow_models import Workflow

_PHASE = Workflow(name="bd/work_phase_bead")
_LAND = Workflow(name="bd/land_epic")


def _plan(*, large_phase: bool = False) -> EpicWorkPlan:
    size = PhaseSize.LARGE if large_phase else None
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
                    size=size,
                ),
            ),
        ),
        land_agent_name="sase-zp.land",
        land_waits_on=("sase-zp.1",),
    )


def _land_xprompt(content: str) -> dict[str, XPrompt]:
    return {
        "bd/land_epic": XPrompt(
            name="bd/land_epic",
            content=content,
            inputs=[InputArg(name="bead_id", type=InputType.WORD)],
        )
    }


def _resolve(
    capacity: int | None,
    *,
    extra_xprompts: dict[str, XPrompt] | None = None,
    large_phase: bool = False,
) -> Any:
    return resolve_epic_queue_capacities(
        _plan(large_phase=large_phase),
        _PHASE,
        _LAND,
        capacity,
        extra_xprompts=extra_xprompts,
    )


def _extract_probe(probe_text: str) -> Any:
    expanded = process_xprompt_references(
        probe_text,
        defer_xprompt_names=LAUNCH_DEFERRED_XPROMPT_NAMES,
        raise_on_error=True,
    )
    _cleaned, directives = extract_prompt_directives(expanded)
    return directives


def test_flag_on_capacity_1_raises_only_land() -> None:
    with override_flags(queue_capacity_budget=True):
        result = _resolve(1)

    assert dict(result.segment_capacity) == {
        "sase-zp.1": 1,
        "sase-zp.land": 2,
    }
    assert result.raised == (_RaisedQueueCapacity("sase-zp.land", 1, 2, 2.0),)


def test_flag_on_capacity_3_raises_nothing() -> None:
    with override_flags(queue_capacity_budget=True):
        result = _resolve(3)

    assert dict(result.segment_capacity) == {
        "sase-zp.1": 3,
        "sase-zp.land": 3,
    }
    assert result.raised == ()


def test_flag_off_capacity_1_does_not_raise_land() -> None:
    with override_flags(queue_capacity_budget=False):
        result = _resolve(1)

    assert dict(result.segment_capacity) == {
        "sase-zp.1": 1,
        "sase-zp.land": 1,
    }
    assert result.raised == ()


def test_fractional_authored_weight_rounds_up() -> None:
    extras = _land_xprompt("%q(w=2.5)\nLand the epic.")
    with override_flags(queue_capacity_budget=True):
        result = _resolve(2, extra_xprompts=extras)

    assert result.segment_capacity["sase-zp.land"] == 3
    assert result.raised == (_RaisedQueueCapacity("sase-zp.land", 2, 3, 2.5),)


@pytest.mark.parametrize("budget_enabled", [True, False])
def test_xprompt_authored_capacity_conflicts_with_cli(budget_enabled: bool) -> None:
    extras = _land_xprompt("%q:4\nLand the epic.")
    with override_flags(queue_capacity_budget=budget_enabled):
        with pytest.raises(EpicQueueCapacityConflictError, match="capacity=4") as exc:
            _resolve(2, extra_xprompts=extras)
    assert exc.value.agent_name == "sase-zp.land"
    assert exc.value.xprompt_name == "bd/land_epic"
    assert "--capacity 2" in str(exc.value)


def test_omitted_capacity_does_not_expand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("capacity=None must not expand xprompts")

    monkeypatch.setattr(
        "sase.bead.work_queue_capacity.process_xprompt_references",
        boom,
    )
    result = _resolve(None)
    assert dict(result.segment_capacity) == {}
    assert result.raised == ()


def test_large_phase_probe_includes_plan_and_still_floors_land() -> None:
    with override_flags(queue_capacity_budget=True):
        result = _resolve(1, large_phase=True)

    assert result.segment_capacity["sase-zp.1"] == 1
    assert result.segment_capacity["sase-zp.land"] == 2


def test_runner_accepts_every_capacity_1_segment_after_floor() -> None:
    with override_flags(queue_capacity_budget=True):
        result = _resolve(1)
        rendered = render_multi_prompt(
            _plan(),
            work_phase_xprompt=_PHASE,
            land_epic_xprompt=_LAND,
            segment_capacity=result.segment_capacity,
        )

    phase, land = rendered.split("\n---\n")
    assert phase.count("%queue(capacity=1)") == 1
    assert land.count("%queue(capacity=2)") == 1

    probes = (
        _queue_probe_text(
            xprompt_name="bd/work_phase_bead",
            xprompt_arg="sase-zp.1",
            capacity=1,
        ),
        _queue_probe_text(
            xprompt_name="bd/land_epic",
            xprompt_arg="sase-zp",
            capacity=2,
        ),
    )
    for probe in probes:
        _extract_probe(probe)
        _probe_segment_queue_fields(probe)
