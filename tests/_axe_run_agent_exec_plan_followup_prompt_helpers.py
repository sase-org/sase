"""Shared helpers for plan follow-up prompt construction tests."""

import contextlib
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.llm_provider._plan_utils import PlanApprovalResult
from tests._axe_run_agent_exec_plan_helpers import (
    make_ctx,
    make_state,
    patched_plan_deps,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


@pytest.fixture
def patch_plan_deps():
    with patched_plan_deps() as mocks:
        yield mocks


def write_plan_file(
    tmp_path, name: str = "plan.md", *, size: str | None = "small"
) -> str:
    plan_file = tmp_path / name
    content = VALID_TALE_PLAN
    if size is None:
        content = content.replace("size: small\n", "")
    else:
        content = content.replace("size: small", f"size: {size}")
    plan_file.write_text(content, encoding="utf-8")
    return str(plan_file)


def run_plan_approval(
    tmp_path,
    *,
    approval: PlanApprovalResult,
    ctx=None,
    state=None,
    agent_model: str | None = None,
    agent_llm_provider: str | None = "claude",
):
    if ctx is None:
        ctx = make_ctx(
            tmp_path,
            agent_model=agent_model,
            agent_llm_provider=agent_llm_provider,
        )
    if state is None:
        state = make_state(tmp_path)

    with contextlib.ExitStack() as stack:
        stack.enter_context(
            patch(
                "sase.llm_provider._plan_utils.handle_plan_approval",
                return_value=approval,
            )
        )
        stack.enter_context(
            patch(
                "sase.sdd.files.write_sdd_files",
                return_value=(tmp_path / "spec.md", tmp_path / "plan.md"),
            )
        )
        outcome = handle_plan_marker({"plan_file": approval.plan_file}, ctx, state)
    return ctx, state, outcome


def run_followup_plan(
    tmp_path,
    *,
    action: str = "approve",
    agent_model: str | None,
    agent_llm_provider: str | None = "claude",
):
    plan_file = write_plan_file(tmp_path)
    if action == "epic":
        Path(plan_file).write_text(VALID_EPIC_PLAN, encoding="utf-8")
    approval = PlanApprovalResult(action=action, plan_file=plan_file)
    _, state, _ = run_plan_approval(
        tmp_path,
        approval=approval,
        agent_model=agent_model,
        agent_llm_provider=agent_llm_provider,
    )
    return state


def approve_followup_plan(
    tmp_path,
    *,
    agent_model: str | None,
    agent_llm_provider: str = "claude",
):
    """Approve a plan and return ``(ctx, state)`` after the code prompt builds.

    This returns the ctx too, so a follow-up ``handle_questions_marker`` can
    reuse the same ctx. ``make_ctx`` is not re-callable on the same ``tmp_path``
    because it creates the artifacts directory.
    """
    plan_file = write_plan_file(tmp_path)
    approval = PlanApprovalResult(action="approve", plan_file=plan_file)
    ctx, state, _ = run_plan_approval(
        tmp_path,
        approval=approval,
        agent_model=agent_model,
        agent_llm_provider=agent_llm_provider,
    )
    return ctx, state
