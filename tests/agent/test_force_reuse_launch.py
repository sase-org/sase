"""Tests for the shared forced agent-name-reuse launch pipeline."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.agent.force_reuse_bead import SASE_AGENT_FORCE_REUSE_BEAD_ENV
from sase.agent.force_reuse_launch import (
    _ForceReuseLaunchFanoutError,
    apply_force_reuse_launch,
    plan_force_reuse_launch,
)
from sase.agent.launch_validation import AgentNameReuseConfirmationRequiredError


def test_plan_returns_none_without_forced_reuse() -> None:
    assert plan_force_reuse_launch("%id:foo\nDo work") is None
    assert plan_force_reuse_launch("Just a plain prompt") is None


def test_plan_rewrites_prompt_and_collects_owner_name() -> None:
    plan = plan_force_reuse_launch("%id:!foo\nDo work")

    assert plan is not None
    assert plan.rewritten_prompt == "%id:foo\nDo work"
    assert plan.owner_names == ["foo"]
    assert plan.segment_envs == [None]


def test_plan_collects_clan_member_owner_name() -> None:
    plan = plan_force_reuse_launch("%id(!2, clan=sase-op, bead=sase-op.2)\nDo work")

    assert plan is not None
    assert plan.rewritten_prompt == "%id(2, clan=sase-op, bead=sase-op.2)\nDo work"
    assert plan.owner_names == ["sase-op.2"]
    assert plan.segment_envs[0] is not None
    assert plan.segment_envs[0][SASE_AGENT_FORCE_REUSE_BEAD_ENV] == (
        '{"bead_id":"sase-op.2","owner_name":"sase-op.2"}'
    )


def test_plan_collects_family_member_owner_name() -> None:
    plan = plan_force_reuse_launch(
        "%id(!plan, family=sase-oc.4, bead=sase-oc.4)\nDo work"
    )

    assert plan is not None
    assert plan.owner_names == ["sase-oc.4--plan"]
    assert plan.segment_envs[0] is not None
    assert plan.segment_envs[0][SASE_AGENT_FORCE_REUSE_BEAD_ENV] == (
        '{"bead_id":"sase-oc.4","owner_name":"sase-oc.4--plan"}'
    )


def test_plan_threads_per_segment_owner_names_and_envs() -> None:
    prompt = (
        "%id(!a, bead=sase-1)\nFirst\n---\n"
        "%id:ordinary\nSecond\n---\n"
        "%i(!b, clan=crew, bead=sase-2)\nThird"
    )

    plan = plan_force_reuse_launch(prompt)

    assert plan is not None
    assert plan.rewritten_prompt == (
        "%id(a, bead=sase-1)\nFirst\n---\n"
        "%id:ordinary\nSecond\n---\n"
        "%i(b, clan=crew, bead=sase-2)\nThird"
    )
    assert plan.owner_names == ["a", "crew.b"]
    assert plan.segment_envs[0] is not None
    assert plan.segment_envs[1] is None
    assert plan.segment_envs[2] is not None


def test_plan_raises_confirmation_required_error_never_reaches_here() -> None:
    # preflight is always invoked with allow_force_reuse=True from this
    # pipeline, so the confirmation-required error can never surface here;
    # that error is reserved for unauthorized callers of
    # preflight_launch_name_requests() directly.
    with pytest.raises(AgentNameReuseConfirmationRequiredError):
        from sase.agent.launch_validation import preflight_launch_name_requests

        preflight_launch_name_requests(["%id:!foo\nDo work"])


def test_plan_raises_fanout_contradiction_when_no_owner_name_resolves() -> None:
    prompt = "%id(!2, clan=sase-op)\n%{%m:claude/opus | %m:claude/sonnet}"

    with pytest.raises(_ForceReuseLaunchFanoutError):
        plan_force_reuse_launch(prompt)


def test_apply_wipes_planned_owner_names() -> None:
    plan = plan_force_reuse_launch("%id:!foo\nDo work")
    assert plan is not None

    with patch(
        "sase.agent.launch_validation.wipe_names_for_forced_reuse"
    ) as wipe_names:
        apply_force_reuse_launch(plan)

    wipe_names.assert_called_once_with(["foo"])


def test_apply_propagates_wipe_failure() -> None:
    plan = plan_force_reuse_launch("%id:!foo\nDo work")
    assert plan is not None

    with patch(
        "sase.agent.launch_validation.wipe_names_for_forced_reuse",
        side_effect=RuntimeError("boom"),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            apply_force_reuse_launch(plan)
