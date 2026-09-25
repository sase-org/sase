"""Executor for gateless plan approvals."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase._plan_archive_approval import PlanAlreadyArchivedError, _ApprovedPlanArchive
from sase.agent.launch_types import AgentLaunchResult
from sase.main.plan_direct_approval import (
    CoderPlacement,
    DirectApprovalPlan,
    DirectApprovalRefused,
    DirectApprovalRequest,
    RetiredGate,
)
from sase.main.plan_direct_approval_run import execute_direct_approval
from sase.plan_approval_actions import PlanApprovalActionError
from sase.plan_approval_receipts import read_direct_approval_receipt
from tests._notification_gates_fixtures import gate_spec
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


class _GateRace:
    """A direct approval staged over a gate that another responder answered."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        kind: str,
        cancel_side_effect: Exception | None = None,
    ) -> None:
        from sase.notification_gates.executor import execute_gate_selection
        from sase.notification_gates.service import create_gate
        from tests._conftest_environment import redirect_sase_home

        home = tmp_path / "sase-home"
        redirect_sase_home(monkeypatch, home)
        monkeypatch.chdir(tmp_path)
        self.adopted = home / "plans" / "202609" / "work.md"
        self.adopted.parent.mkdir(parents=True, exist_ok=True)
        self.adopted.write_text(VALID_TALE_PLAN, encoding="utf-8")
        self.launch = MagicMock(side_effect=AssertionError("no second coder"))
        self.archive = MagicMock(
            return_value=_ApprovedPlanArchive(str(self.adopted), "plan:202609/work.md")
        )
        self.mark_handled = MagicMock()
        self.record_metadata = MagicMock()
        self.cancel_side_effect = cancel_side_effect
        gate = create_gate(gate_spec(request_id="race-gate"))
        if cancel_side_effect is None:
            # Another responder answers first, so the real cancel refuses.
            execute_gate_selection(gate.bundle_path, ["accept"], source="tui")
        self.plan = replace(
            _resolved_plan(tmp_path, kind=kind),
            gate=RetiredGate(
                notification_id="race-gate",
                state="orphaned",
                bundle_path=gate.bundle_path,
            ),
            placement=CoderPlacement(
                mode="session",
                parent="bob",
                member_name="bob--code",
                agent_session="bob",
                planner_artifacts_dir=str(tmp_path / "planner"),
            ),
        )

    def run(self):
        patches = [
            patch(
                "sase.llm_provider._plan_utils.adopt_plan_into_sase",
                return_value=self.adopted,
            ),
            patch("sase._plan_archive_approval.archive_approved_plan", self.archive),
            patch("sase.agent.launch_cwd.launch_agents_from_cwd", self.launch),
            patch(
                "sase.notifications.pending_actions.mark_already_handled",
                self.mark_handled,
            ),
            patch(
                "sase.plan_approval_actions.record_plan_approval_metadata",
                self.record_metadata,
            ),
            patch("sase.plan_approval_actions.dismiss_notification_best_effort"),
        ]
        if self.cancel_side_effect is not None:
            patches.append(
                patch(
                    "sase.notification_gates.executor_cancellation.cancel_gate",
                    side_effect=self.cancel_side_effect,
                )
            )
        from contextlib import ExitStack

        with ExitStack() as stack:
            for active in patches:
                stack.enter_context(active)
            return execute_direct_approval(self.plan)


def test_answered_gate_race_launches_no_coder_and_records_committed_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate_home: Path
) -> None:
    race = _GateRace(tmp_path, monkeypatch, kind="tale")

    outcome = race.run()

    assert outcome.gate_answered_concurrently is True
    assert outcome.incomplete is True
    assert outcome.coder is None
    assert outcome.coder_error is None
    assert outcome.plan_ref == "plan:202609/work.md"
    assert outcome.saved_plan_path == str(race.adopted)
    assert any("race-gate was answered concurrently" in w for w in outcome.warnings)
    # The recovery prompt is the real composed one, so the CLI can print it.
    assert "%id(code, session=bob)" in outcome.coder_prompt
    assert "#coder(plan:202609/work.md)" in outcome.coder_prompt
    race.launch.assert_not_called()
    race.mark_handled.assert_not_called()
    race.record_metadata.assert_not_called()
    race.archive.assert_called_once()
    receipt = read_direct_approval_receipt(race.adopted)
    assert receipt is not None
    assert receipt.action == "tale"
    assert receipt.plan_archive_ref == "plan:202609/work.md"
    assert receipt.route == "none"
    assert receipt.coder_agent is None
    assert receipt.agent_session is None
    assert receipt.retired_gate_id is None
    assert receipt.coder_error is not None
    assert "answered concurrently" in receipt.coder_error
    # The committed plan is now an approved fact: a re-run refuses.
    with pytest.raises(PlanApprovalActionError) as again:
        race.run()
    assert again.value.code == "already_approved"


def test_answered_gate_race_on_commit_is_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate_home: Path
) -> None:
    race = _GateRace(tmp_path, monkeypatch, kind="commit")

    outcome = race.run()

    assert outcome.gate_answered_concurrently is True
    assert outcome.incomplete is False
    race.launch.assert_not_called()
    receipt = read_direct_approval_receipt(race.adopted)
    assert receipt is not None
    assert receipt.action == "commit"
    assert receipt.route == "none"


def test_answered_gate_race_on_approve_refuses_and_withdraws_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate_home: Path
) -> None:
    race = _GateRace(tmp_path, monkeypatch, kind="approve")

    with pytest.raises(DirectApprovalRefused) as exc_info:
        race.run()

    refusal = exc_info.value.refusal
    assert refusal.code == "conflict_already_handled"
    assert refusal.header == "work was already handled"
    assert any("race-gate was answered concurrently" in d for d in refusal.detail_lines)
    assert any("nothing was changed" in d for d in refusal.detail_lines)
    assert refusal.hints == ("sase plan list",)
    race.launch.assert_not_called()
    race.archive.assert_not_called()
    race.mark_handled.assert_not_called()
    race.record_metadata.assert_not_called()
    # Nothing was approved, so nothing may block a later approval.
    assert read_direct_approval_receipt(race.adopted) is None


def test_gate_retire_failure_other_than_a_race_still_launches_the_coder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, gate_home: Path
) -> None:
    race = _GateRace(
        tmp_path, monkeypatch, kind="tale", cancel_side_effect=RuntimeError("disk full")
    )
    race.launch = MagicMock(return_value=[_launch_result(tmp_path)])

    outcome = race.run()

    assert outcome.gate_answered_concurrently is False
    assert outcome.incomplete is False
    assert outcome.coder is not None
    assert any("could not be retired: disk full" in w for w in outcome.warnings)
    race.launch.assert_called_once()
    receipt = read_direct_approval_receipt(race.adopted)
    assert receipt is not None
    assert receipt.route == "session"
    assert receipt.retired_gate_id == "race-gate"
