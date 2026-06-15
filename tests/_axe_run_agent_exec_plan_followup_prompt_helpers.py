"""Shared helpers for plan follow-up prompt construction tests."""

import contextlib
from unittest.mock import patch

import pytest

from sase.axe.run_agent_exec_plan import handle_plan_marker
from sase.llm_provider import WorkerModelResolution
from sase.llm_provider._plan_utils import PlanApprovalResult
from tests._axe_run_agent_exec_plan_helpers import (
    make_ctx,
    make_state,
    patched_plan_deps,
)


@pytest.fixture
def patch_plan_deps():
    with patched_plan_deps() as mocks:
        yield mocks


def _primary_lane_resolution(
    primary_provider: str, primary_model: str, *_args, **_kwargs
) -> WorkerModelResolution:
    """Stub worker resolution that echoes the planner lane (no config match)."""
    return WorkerModelResolution(
        provider=primary_provider,
        model=primary_model,
        source="primary",
        primary_provider=primary_provider,
        primary_model=primary_model,
    )


@pytest.fixture
def stub_worker_resolution():
    """Resolve the contextual worker lane to the planner lane by default.

    Individual tests override this patch to simulate ``worker_models`` config
    mappings; the default keeps prefixes deterministic regardless of the
    developer's real ``~/.config/sase/sase.yml``.
    """
    with patch(
        "sase.llm_provider.resolve_worker_provider_model_for_primary",
        side_effect=_primary_lane_resolution,
    ):
        yield


def write_plan_file(tmp_path, name: str = "plan.md") -> str:
    plan_file = tmp_path / name
    plan_file.write_text("# Plan")
    return str(plan_file)


def run_plan_approval(
    tmp_path,
    *,
    approval: PlanApprovalResult,
    ctx=None,
    state=None,
    agent_model: str | None = None,
    agent_llm_provider: str | None = "anthropic",
    resolution: WorkerModelResolution | None = None,
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
        if resolution is not None:
            stack.enter_context(
                patch(
                    "sase.llm_provider.resolve_worker_provider_model_for_primary",
                    return_value=resolution,
                )
            )
        outcome = handle_plan_marker({"plan_file": approval.plan_file}, ctx, state)
    return ctx, state, outcome


def run_followup_plan(
    tmp_path,
    *,
    action: str = "approve",
    agent_model: str | None,
    agent_llm_provider: str | None = "anthropic",
    resolution: WorkerModelResolution | None = None,
):
    plan_file = write_plan_file(tmp_path)
    approval = PlanApprovalResult(action=action, plan_file=plan_file)
    _, state, _ = run_plan_approval(
        tmp_path,
        approval=approval,
        agent_model=agent_model,
        agent_llm_provider=agent_llm_provider,
        resolution=resolution,
    )
    return state


def approve_followup_plan(
    tmp_path,
    *,
    agent_model: str | None,
    agent_llm_provider: str = "anthropic",
    resolution: WorkerModelResolution | None = None,
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
        resolution=resolution,
    )
    return ctx, state
