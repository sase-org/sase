"""Per-segment ``--capacity`` resolution for epic ``sase bead work``."""

from __future__ import annotations

from typing import Any

import pytest

from sase.bead.model import PhaseSize
from sase.bead.work import (
    EpicWorkPlan,
    render_multi_prompt,
)
from sase.bead.work_plan import _PhaseAssignment as PhaseAssignment
from sase.bead.work_queue_capacity import (
    EpicQueueCapacityConflictError,
    _RaisedQueueCapacity,
    _probe_segment_queue_fields,
    _queue_probe_text,
    _segment_specs,
    resolve_epic_queue_capacities,
)
from sase.macro.directives import extract_prompt_directives
from sase.macro.models import InputArg, InputType, Macro
from sase.macro.processor import (
    LAUNCH_DEFERRED_MACRO_NAMES,
    process_macro_references,
)
from sase.macro.workflow_models import Workflow

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


def _land_macro(content: str) -> dict[str, Macro]:
    return {
        "bd/land_epic": Macro(
            name="bd/land_epic",
            content=content,
            inputs=[InputArg(name="bead_id", type=InputType.WORD)],
        )
    }


def _resolve(
    capacity: int | None,
    *,
    extra_macros: dict[str, Macro] | None = None,
    large_phase: bool = False,
) -> Any:
    return resolve_epic_queue_capacities(
        _plan(large_phase=large_phase),
        _PHASE,
        _LAND,
        capacity,
        extra_macros=extra_macros,
    )


def _extract_probe(probe_text: str) -> Any:
    expanded = process_macro_references(
        probe_text,
        defer_macro_names=LAUNCH_DEFERRED_MACRO_NAMES,
        raise_on_error=True,
    )
    _cleaned, directives = extract_prompt_directives(expanded)
    return directives


def test_capacity_1_leaves_builtin_segments_at_1() -> None:
    result = _resolve(1)

    assert dict(result.segment_capacity) == {
        "sase-zp.1": 1,
        "sase-zp.land": 1,
    }
    assert result.raised == ()


def test_capacity_1_raises_land_override_weight() -> None:
    extras = _land_macro("%q(w=2.0)\nLand the epic.")
    result = _resolve(1, extra_macros=extras)

    assert dict(result.segment_capacity) == {
        "sase-zp.1": 1,
        "sase-zp.land": 2,
    }
    assert result.raised == (_RaisedQueueCapacity("sase-zp.land", 1, 2, 2.0),)


def test_capacity_3_raises_nothing() -> None:
    result = _resolve(3)

    assert dict(result.segment_capacity) == {
        "sase-zp.1": 3,
        "sase-zp.land": 3,
    }
    assert result.raised == ()


def test_fractional_authored_weight_rounds_up() -> None:
    extras = _land_macro("%q(w=2.5)\nLand the epic.")
    result = _resolve(2, extra_macros=extras)

    assert result.segment_capacity["sase-zp.land"] == 3
    assert result.raised == (_RaisedQueueCapacity("sase-zp.land", 2, 3, 2.5),)


def test_macro_authored_capacity_conflicts_with_cli() -> None:
    extras = _land_macro("%q:4\nLand the epic.")
    with pytest.raises(EpicQueueCapacityConflictError, match="capacity=4") as exc:
        _resolve(2, extra_macros=extras)
    assert exc.value.agent_name == "sase-zp.land"
    assert exc.value.macro_name == "bd/land_epic"
    assert "--capacity 2" in str(exc.value)


def test_omitted_capacity_does_not_expand(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("capacity=None must not expand xprompts")

    monkeypatch.setattr(
        "sase.bead.work_queue_capacity.process_macro_references",
        boom,
    )
    result = _resolve(None)
    assert dict(result.segment_capacity) == {}
    assert result.raised == ()


def test_large_phase_probe_includes_plan() -> None:
    specs = _segment_specs(_plan(large_phase=True), _PHASE, _LAND)
    _phase_name, phase_macro, phase_refs = specs[0]
    _land_name, land_macro, land_refs = specs[1]
    assert phase_macro == "bd/work_phase_bead"
    assert phase_refs == ("#bd/work_phase_bead:sase-zp.1", "#plan")
    assert land_macro == "bd/land_epic"
    assert land_refs == ("#bd/land_epic:sase-zp",)

    result = _resolve(1, large_phase=True)

    assert result.segment_capacity["sase-zp.1"] == 1
    assert result.segment_capacity["sase-zp.land"] == 1
    assert result.raised == ()


def test_runner_accepts_every_capacity_1_segment() -> None:
    result = _resolve(1)
    rendered = render_multi_prompt(
        _plan(),
        work_phase_macro=_PHASE,
        land_epic_macro=_LAND,
        segment_capacity=result.segment_capacity,
    )

    phase, land = rendered.split("\n---\n")
    assert phase.count("%queue(capacity=1)") == 1
    assert land.count("%queue(capacity=1)") == 1

    probes = (
        _queue_probe_text(
            macro_name="bd/work_phase_bead",
            macro_arg="sase-zp.1",
            capacity=1,
        ),
        _queue_probe_text(
            macro_name="bd/land_epic",
            macro_arg="sase-zp",
            capacity=1,
        ),
    )
    for probe in probes:
        _extract_probe(probe)
        _probe_segment_queue_fields(probe)
