"""Tests for Rust-backed agent-launch fanout planning."""

from __future__ import annotations

import pytest

from sase.core.agent_launch_facade import plan_agent_launch_fanout
from sase.core.agent_launch_wire import (
    AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
    LaunchFanoutPlanWire,
    LaunchFanoutSlotWire,
    agent_launch_wire_to_json_dict,
    launch_fanout_plan_from_dict,
)


def test_fanout_plan_round_trips_slots() -> None:
    plan = LaunchFanoutPlanWire(
        schema_version=AGENT_LAUNCH_WIRE_SCHEMA_VERSION,
        launch_kind="multi_prompt",
        slots=[
            LaunchFanoutSlotWire(
                prompt="first",
                launch_kind="multi_prompt",
                slot_index=0,
                alt_id="first",
                bead_id="sase-8f.2",
            ),
            LaunchFanoutSlotWire(
                prompt="%wait\nsecond",
                launch_kind="multi_prompt",
                slot_index=1,
                alt_id="second",
            ),
        ],
        fanout_sleep_seconds=0.0,
        requires_sequential_naming_wait=True,
    )
    payload = agent_launch_wire_to_json_dict(plan)

    assert payload["schema_version"] == AGENT_LAUNCH_WIRE_SCHEMA_VERSION
    assert payload["slots"][0]["alt_id"] == "first"
    assert payload["slots"][0]["bead_id"] == "sase-8f.2"
    assert payload["slots"][1]["prompt"] == "%wait\nsecond"
    assert launch_fanout_plan_from_dict(payload) == plan


def test_plan_agent_launch_fanout_rust_multi_prompt() -> None:
    pytest.importorskip("sase_core_rs")

    plan = plan_agent_launch_fanout(
        "one\n```\n---\n```\n---\n%wait\ntwo",
        launch_kind="multi_prompt",
    )

    assert plan.launch_kind == "multi_prompt"
    assert [slot.prompt for slot in plan.slots] == ["one\n```\n---\n```", "%wait\ntwo"]
    assert plan.slots[1].wait_for_previous is True
    assert plan.requires_sequential_naming_wait is True


def test_plan_agent_launch_fanout_rust_rejects_repeated_models() -> None:
    pytest.importorskip("sase_core_rs")

    with pytest.raises(
        ValueError,
        match=r"use %\{%m:opus \| %m:sonnet\} instead",
    ):
        plan_agent_launch_fanout(
            "%i:foo\n%model:opus\n%model:sonnet %alt(x,y)\nReview",
            launch_kind="model",
        )


def test_plan_agent_launch_fanout_rust_model_branches_and_alt() -> None:
    pytest.importorskip("sase_core_rs")

    plan = plan_agent_launch_fanout(
        "%i:foo\n%{%model:opus | %model:sonnet} %alt(x,y)\nReview",
        launch_kind="model",
    )

    assert plan.launch_kind == "model"
    assert len(plan.slots) == 4
    assert plan.slots[0].model == "opus"
    assert plan.slots[0].alt_id == "1.1"
    assert plan.slots[0].prompt == "%i:foo\n%model:opus x\nReview"
    assert plan.slots[3].model == "sonnet"
    assert plan.slots[3].alt_id == "2.2"
    assert plan.slots[3].prompt == "%i:foo\n%model:sonnet y\nReview"


def test_plan_agent_launch_fanout_rust_strips_model_effort_suffix() -> None:
    pytest.importorskip("sase_core_rs")

    plan = plan_agent_launch_fanout(
        "%i:foo\n%{%m:opus@xhigh | %m:sonnet@low} %alt(x,y)\nReview",
        launch_kind="model",
    )

    assert plan.launch_kind == "model"
    assert len(plan.slots) == 4
    # Slots are named by the clean model (the `@effort` suffix is split off),
    # mirroring the Python xprompt `split_model_effort` rule.
    assert plan.slots[0].model == "opus"
    assert plan.slots[3].model == "sonnet"
    # The branch body retains the `@effort` token for the launched agent's own
    # directive parsing.
    assert "%m:opus@xhigh" in plan.slots[0].prompt
    assert "%m:sonnet@low" in plan.slots[3].prompt


def test_plan_agent_launch_fanout_rust_exposes_alt_ids() -> None:
    pytest.importorskip("sase_core_rs")

    plan = plan_agent_launch_fanout(
        "%alt(sec=[[security]],perf=[[performance]])\nReview",
        launch_kind="alternatives",
    )

    assert [slot.alt_id for slot in plan.slots] == ["sec", "perf"]
    assert [slot.prompt for slot in plan.slots] == [
        "security\nReview",
        "performance\nReview",
    ]


def test_plan_agent_launch_fanout_rust_correlates_shared_alt_ids() -> None:
    pytest.importorskip("sase_core_rs")

    plan = plan_agent_launch_fanout(
        "#gh:sase %{a=Describe | b=Explain} how this repo works %{a=in detail}.",
        launch_kind="alternatives",
    )

    assert [slot.alt_id for slot in plan.slots] == ["a", "b"]
    assert [slot.prompt for slot in plan.slots] == [
        "#gh:sase Describe how this repo works in detail.",
        "#gh:sase Explain how this repo works.",
    ]


def test_plan_agent_launch_fanout_empty_alt_preserves_following_model() -> None:
    pytest.importorskip("sase_core_rs")

    plan = plan_agent_launch_fanout(
        "Do work. %{extra} %{%model:opus | %model:gpt-5.6-sol}",
        launch_kind="model",
    )

    assert [slot.model for slot in plan.slots] == [
        "opus",
        "gpt-5.6-sol",
        "opus",
        "gpt-5.6-sol",
    ]
    assert [slot.prompt for slot in plan.slots] == [
        "Do work. extra %model:opus",
        "Do work. extra %model:gpt-5.6-sol",
        "Do work. %model:opus",
        "Do work. %model:gpt-5.6-sol",
    ]


def test_plan_agent_launch_fanout_rust_allocates_named_and_numeric_alt_ids() -> None:
    pytest.importorskip("sase_core_rs")

    plan = plan_agent_launch_fanout(
        "%(fast=a,b) %alt(red=x,blue=y)",
        launch_kind="alternatives",
    )

    assert [slot.alt_id for slot in plan.slots] == [
        "fast.red",
        "fast.blue",
        "1.red",
        "1.blue",
    ]
    assert [slot.prompt for slot in plan.slots] == ["a x", "a y", "b x", "b y"]


def test_plan_agent_launch_fanout_rust_repeat_handles_id_shorthands_and_literals() -> (
    None
):
    pytest.importorskip("sase_core_rs")

    prompt = (
        "%xprompts_enabled:false\n"
        "%repeat:9 %id:disabled\n"
        "%xprompts_enabled:true\n"
        "```text\n%r:8 %i:fenced\n```\n"
        "keep `foo`/`%repeat:7` and prefix`%id:inline`suffix "
        "%r:3 %i:task %model:opus do work"
    )
    plan = plan_agent_launch_fanout(
        prompt,
        launch_kind="repeat",
    )

    assert plan.launch_kind == "repeat"
    assert len(plan.slots) == 3
    assert plan.slots[0].repeat_name == "task"
    assert plan.slots[0].prompt == (
        "%repeat:9 %id:disabled\n"
        "```text\n%r:8 %i:fenced\n```\n"
        "keep `foo`/`%repeat:7` and prefix`%id:inline`suffix "
        "  %model:opus do work"
    )
    assert [slot.wait_for_previous for slot in plan.slots] == [False, True, True]


def test_plan_agent_launch_fanout_rust_repeat_preserves_bead_association() -> None:
    pytest.importorskip("sase_core_rs")

    plan = plan_agent_launch_fanout(
        "%r:2 %id(task, clan=research, bead=sase-8f.2) do work",
        launch_kind="repeat",
    )

    assert [slot.repeat_name for slot in plan.slots] == ["task", "task"]
    assert [slot.bead_id for slot in plan.slots] == ["sase-8f.2", "sase-8f.2"]
    assert all("%id" not in slot.prompt for slot in plan.slots)
