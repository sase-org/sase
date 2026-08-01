"""Prompt and model routing tests for task-bead work launches."""

from __future__ import annotations

import pytest

from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV
from sase.bead.model import PhaseSize
from sase.bead.work import (
    SASE_BEAD_ID_ENV,
    VCSLaunchContext,
    render_task_prompt,
    task_model_directive_value,
    task_work_segment_env,
)
from sase.xprompt.workflow_models import Workflow


def test_task_prompt_has_exact_single_segment_order_and_feedback_tail() -> None:
    rendered = render_task_prompt(
        "sase-42",
        work_task_xprompt=Workflow(name="custom/work_task"),
        vcs_context=VCSLaunchContext(vcs_workflow="gh", project_name="sase"),
        feedback="Please preserve the compatibility shim.",
    )

    assert rendered == (
        "#gh:sase #commit\n"
        "%id(!sase-42, bead=sase-42)\n"
        "%m:@small_phase_worker\n"
        "#custom/work_task:sase-42\n"
        "Please preserve the compatibility shim."
    )
    assert "\n---\n" not in rendered


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (PhaseSize.XSMALL, "@xsmall_phase_worker"),
        (PhaseSize.SMALL, "@small_phase_worker"),
        (PhaseSize.MEDIUM, "@medium_phase_worker"),
        (PhaseSize.LARGE, "@large_phase_worker"),
        (PhaseSize.XLARGE, "@xlarge_phase_worker"),
    ],
)
def test_task_model_uses_size_specific_phase_worker_alias(
    size: PhaseSize,
    expected: str,
) -> None:
    assert task_model_directive_value("", size=size) == expected


def test_task_model_precedence_prefers_alias_aware_explicit_model() -> None:
    assert task_model_directive_value("smart", size=PhaseSize.LARGE) == "@smart"
    assert task_model_directive_value("claude/opus", size=PhaseSize.LARGE) == (
        "claude/opus"
    )
    assert task_model_directive_value("", size=None) == "@small_phase_worker"


@pytest.mark.parametrize(
    ("size", "expects_plan"),
    [
        (PhaseSize.XSMALL, False),
        (PhaseSize.SMALL, False),
        (PhaseSize.MEDIUM, False),
        (PhaseSize.LARGE, True),
        (PhaseSize.XLARGE, True),
        (None, False),
    ],
)
def test_task_prompt_reuses_phase_plan_first_routing(
    size: PhaseSize | None,
    expects_plan: bool,
) -> None:
    rendered = render_task_prompt(
        "sase-42",
        size=size,
        work_task_xprompt=Workflow(name="bd/work_task"),
        vcs_context=VCSLaunchContext(vcs_workflow="git", project_name="sase"),
    )

    assert ("#plan" in rendered.splitlines()) is expects_plan
    assert "\n---\n" not in rendered


def test_task_feedback_rejects_top_level_segment_separator() -> None:
    with pytest.raises(ValueError, match="top-level '---'"):
        render_task_prompt(
            "sase-42",
            work_task_xprompt=Workflow(name="bd/work_task"),
            vcs_context=VCSLaunchContext(vcs_workflow="git", project_name="sase"),
            feedback="First instruction\n---\nSecond agent",
        )


def test_task_feedback_allows_fenced_segment_separator() -> None:
    rendered = render_task_prompt(
        "sase-42",
        work_task_xprompt=Workflow(name="bd/work_task"),
        vcs_context=VCSLaunchContext(vcs_workflow="git", project_name="sase"),
        feedback="Use this fixture:\n```\n---\n```",
    )

    assert rendered.endswith("Use this fixture:\n```\n---\n```")


def test_task_launch_environment_is_one_deterministic_bead_slot() -> None:
    assert task_work_segment_env("sase-42") == (
        {
            SASE_BEAD_ID_ENV: "sase-42",
            INTERNAL_AGENT_NAME_BYPASS_ENV: "1",
        },
    )
