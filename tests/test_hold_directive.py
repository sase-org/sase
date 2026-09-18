"""Coverage for the shared `%hold` directive surface."""

from __future__ import annotations

import pytest

from sase.core.agent_launch_facade import (
    agent_unit_dispatch_prompt,
    plan_typed_launch_units,
)
from sase.core.agent_launch_wire import (
    AgentUnitWire,
    HoldFieldsWire,
    agent_launch_wire_to_json_dict,
    launch_plan_from_dict,
)
from sase.feature_flags import override_flags
from sase.xprompt.directives import DirectiveError, extract_prompt_directives
from sase.xprompt.hold_directive import (
    collect_hold_fields,
    format_hold_directive,
    hold_fields_to_selectors,
)


pytest.importorskip("sase_core_rs")


def test_hold_ignores_retired_flag_override_and_requires_selector() -> None:
    with override_flags(agent_holds=False):
        with pytest.raises(DirectiveError, match="requires a selector"):
            extract_prompt_directives("%hold\nDo work")

        cleaned, directives = extract_prompt_directives("%hold:reviewer\nDo work")

    assert "%hold" not in cleaned
    assert cleaned.strip() == "Do work"
    assert directives.hold == {"names": ["reviewer"]}


def test_hold_extracts_repeatable_fields_and_formats_canonical_directive() -> None:
    with override_flags():
        cleaned, directives = extract_prompt_directives(
            "%hold:reviewer,planner\n"
            "%hold(pending, future, hood=sase-11l, tribe=nightly, "
            "ttl=1h30m, scope=host)\n"
            "Do work"
        )

    assert "%hold" not in cleaned
    assert cleaned.strip() == "Do work"
    assert directives.hold == {
        "names": ["planner", "reviewer"],
        "tribes": ["nightly"],
        "hoods": ["sase-11l"],
        "pending": True,
        "future": True,
        "ttl": "1h30m",
        "ttl_seconds": 5400,
        "scope": "host",
    }
    assert (
        format_hold_directive(directives.hold)
        == "%hold(planner, reviewer, @nightly, pending, future, "
        "hood=sase-11l, ttl=1h30m, scope=host)"
    )


def test_hold_adapter_reports_errors_and_expands_selectors() -> None:
    with override_flags():
        result = collect_hold_fields(
            [
                {
                    "source": "%hold(builder, builder--mon, pending, future)",
                    "source_span": [0, 45],
                    "args": [
                        {"value": "builder"},
                        {"value": "builder--mon"},
                        {"value": "pending"},
                        {"value": "future"},
                    ],
                    "has_plus_suffix": False,
                }
            ]
        )

    assert result["errors"] == []
    selectors = hold_fields_to_selectors(result["fields"], ["/tmp/a", "/tmp/a"])
    assert selectors["names"] == ["builder", "builder--mon"]
    assert selectors["families"] == ["builder"]
    assert selectors["artifact_dirs"] == ["/tmp/a"]
    assert selectors["future"] is True

    with override_flags():
        duplicate = collect_hold_fields(
            [
                {
                    "source": "%hold(planner, ttl=5m)",
                    "source_span": [0, 22],
                    "args": [{"value": "planner"}, {"name": "ttl", "value": "5m"}],
                    "has_plus_suffix": False,
                },
                {
                    "source": "%hold(future, ttl=5m)",
                    "source_span": [23, 44],
                    "args": [{"value": "future"}, {"name": "ttl", "value": "5m"}],
                    "has_plus_suffix": False,
                },
            ]
        )

    assert duplicate["fields"] is None
    assert duplicate["errors"][0]["code"] == "duplicate-hold-field"


def test_typed_launch_threads_hold_and_rebuilds_dispatch_prompt() -> None:
    with override_flags(typed_launch_units=True):
        plan = plan_typed_launch_units(
            "%hold(pending, hood=sase-11l, ttl=5m)\nDo work",
            selected_project="sase",
        )
        agent = plan.units[0].payload
        rebuilt = agent_unit_dispatch_prompt(agent)

    assert isinstance(agent, AgentUnitWire)
    assert isinstance(agent.hold, HoldFieldsWire)
    assert agent.hold.pending is True
    assert agent.hold.hoods == ["sase-11l"]
    assert agent.hold.ttl_seconds == 300
    assert "%hold(pending, hood=sase-11l, ttl=5m)" in rebuilt
    assert any(
        " hold=%hold(pending, hood=sase-11l, ttl=5m)" in line
        for line in plan.approval_preview
    )


def test_hold_wire_round_trips_and_omits_empty_hold() -> None:
    payload = agent_launch_wire_to_json_dict(
        AgentUnitWire(
            prompt="Do work",
            hold=HoldFieldsWire(
                names=["reviewer"],
                pending=True,
                ttl="5m",
                ttl_seconds=300,
                scope="project",
            ),
        )
    )

    assert payload["hold"] == {
        "names": ["reviewer"],
        "pending": True,
        "ttl": "5m",
        "ttl_seconds": 300,
        "scope": "project",
    }
    assert "hold" not in agent_launch_wire_to_json_dict(
        AgentUnitWire(prompt="Do work", hold=HoldFieldsWire())
    )

    plan = launch_plan_from_dict(
        {
            "schema_version": 1,
            "launch_kind": "single",
            "selected_project": "sase",
            "content_digest": "a" * 64,
            "units": [
                {
                    "logical_id": "unit-1",
                    "source_order": 0,
                    "waits": [],
                    "payload": payload,
                }
            ],
        }
    )
    restored = plan.units[0].payload
    assert isinstance(restored, AgentUnitWire)
    assert restored.hold == HoldFieldsWire(
        names=["reviewer"],
        pending=True,
        ttl="5m",
        ttl_seconds=300,
        scope="project",
    )


def test_hold_rejects_repeat_in_python_parser() -> None:
    with override_flags():
        with pytest.raises(DirectiveError, match="%hold with %repeat"):
            extract_prompt_directives("%repeat:2 %hold:reviewer\nDo work")
