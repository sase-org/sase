"""Shared builders for plan-approve render tests.

Not a conftest so files opt in by importing the helpers directly. Names are
public so the ``test_plan_approve_render_*`` split modules can share them
without importing ``_``-prefixed names across files.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.agent.launch_types import AgentLaunchResult
from sase.main.plan_direct_approval import (
    CoderPlacement,
    DirectApprovalPlan,
    DirectApprovalRequest,
    RetiredGate,
)
from sase.main.plan_direct_approval_run import DirectApprovalOutcome

PLAN_REF = "plan:202609/updates_tab.md"
PROMPT = f"+sase %model:@medium #coder({PLAN_REF})"


@pytest.fixture(autouse=True)
def no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    """Disable color for render assertions.

    Importing this fixture's name into a test module is enough for pytest to
    pick it up, since fixture discovery scans the module's own namespace.
    """
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)


def make_placement(mode: str = "standalone") -> CoderPlacement:
    """Build a coder placement for direct-approval render tests."""
    if mode == "session":
        return CoderPlacement(
            mode="session", parent="bob", member_name="bob--code", agent_session="bob"
        )
    return CoderPlacement(mode="standalone", reason="this plan records no planner")


def make_direct_plan(
    *,
    kind: str = "tale",
    mode: str = "standalone",
    gate: RetiredGate | None = None,
    prompt: str = PROMPT,
) -> DirectApprovalPlan:
    """Build a direct-approval plan for render tests."""
    return DirectApprovalPlan(
        request=DirectApprovalRequest(selector="updates_tab"),
        kind=kind,  # type: ignore[arg-type]
        source_path=Path("/plans/updates_tab.md"),
        location="proposal",
        name="updates_tab",
        title="Cache the Updates tab's first open",
        size="medium",
        project="sase",
        project_tag="+sase",
        planner=None,
        gate=gate,
        placement=make_placement(mode),
        model_directive="@medium",
        predicted_plan_ref=PLAN_REF,
        coder_prompt_preview=prompt,
    )


def make_outcome(
    plan: DirectApprovalPlan,
    *,
    coder: AgentLaunchResult | None = None,
    coder_error: str | None = None,
    warnings: tuple[str, ...] = (),
    gate_answered_concurrently: bool = False,
    prompt: str = PROMPT,
) -> DirectApprovalOutcome:
    """Build a direct-approval outcome for render tests."""
    return DirectApprovalOutcome(
        plan=plan,
        local_plan_path=Path("/home/u/.sase/plans/202609/updates_tab.md"),
        plan_ref=PLAN_REF,
        saved_plan_path=None if plan.kind == "approve" else "/sdd/updates_tab.md",
        coder_prompt=prompt,
        coder=coder,
        coder_error=coder_error,
        warnings=warnings,
        gate_answered_concurrently=gate_answered_concurrently,
    )


def make_launched(name: str | None = "bob--code", pid: int = 4242) -> AgentLaunchResult:
    """Build a successful coder-launch result for render tests."""
    return AgentLaunchResult(
        pid=pid,
        workspace_num=1,
        workspace_dir="/work",
        output_path="/work/out.log",
        agent_name=name,
    )


def make_retired_gate(state: str = "expired") -> RetiredGate:
    """Build a retired approval gate for render tests."""
    return RetiredGate(
        notification_id="a1b2c3d4e5f6",
        state=state,  # type: ignore[arg-type]
    )


def read_output(capsys: pytest.CaptureFixture[str]) -> tuple[str, str]:
    """Read captured output and assert rendering stayed color-free."""
    captured = capsys.readouterr()
    assert "\x1b" not in captured.out + captured.err
    return captured.out, captured.err
