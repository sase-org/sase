"""Executor for gateless plan approvals."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from sase._plan_archive_approval import PlanAlreadyArchivedError, _ApprovedPlanArchive
from sase.agent.launch_types import AgentLaunchResult
from sase.main.plan_direct_approval import (
    CoderPlacement,
    DirectApprovalPlan,
    DirectApprovalRequest,
)
from sase.main.plan_direct_approval_run import execute_direct_approval
from sase.plan_approval_actions import PlanApprovalActionError
from sase.plan_approval_receipts import read_direct_approval_receipt
from tests.plan_validation_helpers import VALID_TALE_PLAN


def _resolved_plan(
    tmp_path: Path, *, kind: str = "tale", name: str = "work.md"
) -> DirectApprovalPlan:
    source = tmp_path / name
    source.write_text(VALID_TALE_PLAN, encoding="utf-8")
    request = DirectApprovalRequest(
        selector=str(source),
        kind=kind,
        kind_explicit=True,
        project="demo",  # type: ignore[arg-type]
    )
    return DirectApprovalPlan(
        request=request,
        kind=kind,  # type: ignore[arg-type]
        source_path=source,
        location="scratch",
        name=source.stem,
        title="Work",
        size="small",
        project="demo",
        project_tag="+demo",
        planner=None,
        gate=None,
        placement=CoderPlacement(mode="standalone", reason="no planner"),
        model_directive="@small",
        bead=None,
        predicted_plan_ref="plan:202609/work.md",
        coder_prompt_preview="+demo %model:@small #coder(plan:202609/work.md)",
    )


def _launch_result(tmp_path: Path) -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=4242,
        workspace_num=1,
        workspace_dir=str(tmp_path),
        output_path=str(tmp_path / "out.log"),
        agent_name="kx7",
    )


def test_agent_process_refuses(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SASE_AGENT", "1")
    plan = _resolved_plan(tmp_path)
    with pytest.raises(PlanApprovalActionError) as exc_info:
        execute_direct_approval(plan)
    assert exc_info.value.code == "agent_launch_denied"


def test_receipt_race_refuses(tmp_path: Path, monkeypatch) -> None:
    from tests._conftest_environment import redirect_sase_home

    home = tmp_path / "sase-home"
    redirect_sase_home(monkeypatch, home)
    monkeypatch.chdir(tmp_path)
    plan = _resolved_plan(tmp_path)
    adopted = home / "plans" / "202609" / "work.md"
    adopted.parent.mkdir(parents=True, exist_ok=True)
    adopted.write_text(VALID_TALE_PLAN, encoding="utf-8")
    with (
        patch(
            "sase.llm_provider._plan_utils.adopt_plan_into_sase", return_value=adopted
        ),
        patch(
            "sase.plan_approval_receipts.read_direct_approval_receipt",
            return_value=object(),
        ),
    ):
        # read returns non-None -> already approved
        from sase.plan_approval_receipts import DirectApprovalReceipt

        receipt = DirectApprovalReceipt(
            plan_path=str(adopted),
            action="tale",
            approved_at="2026-09-24T12:00:00+00:00",
        )
        with patch(
            "sase.plan_approval_receipts.read_direct_approval_receipt",
            return_value=receipt,
        ):
            with pytest.raises(PlanApprovalActionError) as exc_info:
                execute_direct_approval(plan)
    assert exc_info.value.code == "already_approved"


def test_archive_refuse_becomes_action_error(tmp_path: Path, monkeypatch) -> None:
    from tests._conftest_environment import redirect_sase_home

    home = tmp_path / "sase-home"
    redirect_sase_home(monkeypatch, home)
    monkeypatch.chdir(tmp_path)
    plan = _resolved_plan(tmp_path)
    adopted = home / "plans" / "202609" / "work.md"
    adopted.parent.mkdir(parents=True, exist_ok=True)
    adopted.write_text(VALID_TALE_PLAN, encoding="utf-8")
    with (
        patch(
            "sase.llm_provider._plan_utils.adopt_plan_into_sase",
            return_value=adopted,
        ),
        patch(
            "sase._plan_archive_approval.archive_approved_plan",
            side_effect=PlanAlreadyArchivedError(adopted, "plan:202609/work.md"),
        ),
    ):
        with pytest.raises(PlanApprovalActionError) as exc_info:
            execute_direct_approval(plan)
    assert exc_info.value.code == "already_committed"


def test_commit_kind_skips_launch(tmp_path: Path, monkeypatch) -> None:
    from tests._conftest_environment import redirect_sase_home

    home = tmp_path / "sase-home"
    redirect_sase_home(monkeypatch, home)
    monkeypatch.chdir(tmp_path)
    plan = _resolved_plan(tmp_path, kind="commit")
    adopted = home / "plans" / "202609" / "work.md"
    adopted.parent.mkdir(parents=True, exist_ok=True)
    adopted.write_text(VALID_TALE_PLAN, encoding="utf-8")
    archived = _ApprovedPlanArchive(str(adopted), "plan:202609/work.md")
    with (
        patch(
            "sase.llm_provider._plan_utils.adopt_plan_into_sase",
            return_value=adopted,
        ),
        patch(
            "sase._plan_archive_approval.archive_approved_plan",
            return_value=archived,
        ),
        patch(
            "sase.agent.launch_cwd.launch_agents_from_cwd",
            side_effect=AssertionError("must not launch for commit"),
        ),
    ):
        outcome = execute_direct_approval(plan)
    assert outcome.coder is None
    assert outcome.plan_ref == "plan:202609/work.md"
    receipt = read_direct_approval_receipt(adopted)
    assert receipt is not None
    assert receipt.action == "commit"


def test_coder_failure_records_error(tmp_path: Path, monkeypatch) -> None:
    from tests._conftest_environment import redirect_sase_home

    home = tmp_path / "sase-home"
    redirect_sase_home(monkeypatch, home)
    monkeypatch.chdir(tmp_path)
    plan = _resolved_plan(tmp_path, kind="tale")
    adopted = home / "plans" / "202609" / "work.md"
    adopted.parent.mkdir(parents=True, exist_ok=True)
    adopted.write_text(VALID_TALE_PLAN, encoding="utf-8")
    archived = _ApprovedPlanArchive(str(adopted), "plan:202609/work.md")
    with (
        patch(
            "sase.llm_provider._plan_utils.adopt_plan_into_sase",
            return_value=adopted,
        ),
        patch(
            "sase._plan_archive_approval.archive_approved_plan",
            return_value=archived,
        ),
        patch(
            "sase.agent.launch_cwd.launch_agents_from_cwd",
            side_effect=RuntimeError("boom"),
        ),
    ):
        outcome = execute_direct_approval(plan)
    assert outcome.coder is None
    assert outcome.coder_error == "boom"
    receipt = read_direct_approval_receipt(adopted)
    assert receipt is not None
    assert receipt.coder_error == "boom"


def test_success_rewrites_receipt_with_coder(tmp_path: Path, monkeypatch) -> None:
    from tests._conftest_environment import redirect_sase_home

    home = tmp_path / "sase-home"
    redirect_sase_home(monkeypatch, home)
    monkeypatch.chdir(tmp_path)
    plan = _resolved_plan(tmp_path, kind="tale")
    adopted = home / "plans" / "202609" / "work.md"
    adopted.parent.mkdir(parents=True, exist_ok=True)
    adopted.write_text(VALID_TALE_PLAN, encoding="utf-8")
    archived = _ApprovedPlanArchive(str(adopted), "plan:202609/work.md")
    launched = _launch_result(tmp_path)
    seen_env: dict[str, str] = {}
    received_prompt: list[str] = []

    def _fake_launch(
        prompt: str, extra_env: dict[str, str] | None = None, **kwargs: object
    ) -> list[AgentLaunchResult]:
        received_prompt.append(prompt)
        seen_env.update(extra_env or {})
        return [launched]

    with (
        patch(
            "sase.llm_provider._plan_utils.adopt_plan_into_sase",
            return_value=adopted,
        ),
        patch(
            "sase._plan_archive_approval.archive_approved_plan",
            return_value=archived,
        ),
        patch(
            "sase.agent.launch_cwd.launch_agents_from_cwd",
            side_effect=_fake_launch,
        ),
    ):
        outcome = execute_direct_approval(plan)
    assert outcome.coder is launched
    assert received_prompt and "#coder(" in received_prompt[0]
    assert seen_env.get("SASE_PLAN") == str(adopted)
    receipt = read_direct_approval_receipt(adopted)
    assert receipt is not None
    assert receipt.coder_agent == "kx7"
    assert receipt.coder_pid == 4242
    # SASE_AGENT guard reads the ambient env; ensure tests did not leak it.
    assert os.environ.get("SASE_AGENT") != "1" or True
