"""Plan gate shell request policy and creation metadata tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.gate_shell.models import GateShellRecord
from sase.gate_shell.transaction import GateShellCreation
from sase.notification_gates.model_results import GateCreationResult
from sase.notification_gates.model_shell import GateShellSpec
from sase.plan_chain import PLAN_CHAIN_CODER_SUFFIX, PLAN_CHAIN_PLAN_SUFFIX
from sase.plan_shell.create import create_plan_gate_shell, plan_gate_shell_block
from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state
from tests._plan_gate_fixtures import write_plan
from tests.plan_validation_helpers import VALID_TALE_PLAN


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr("sase.plan_shell.create.list_gate_shells", lambda **_kwargs: [])
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.send_desktop_notification",
        lambda _title, _message: None,
    )
    monkeypatch.setattr("sase.main.plan_approve_handler.get_tmux_prefix", lambda: "")


def test_tale_shell_block_covers_all_supported_approval_subsets() -> None:
    shell = plan_gate_shell_block("tale")

    parsed = GateShellSpec.from_mapping(
        shell,
        branches=(("approve", "commit"), ("reject",), ("feedback",)),
        allow_branch_subsets=True,
    )

    assert parsed.pending_status == "TALE"
    assert parsed.settled_status == "TALE APPROVED"
    assert set(parsed.branches) == {
        "approve+commit",
        "approve",
        "commit",
        "reject",
        "feedback",
        "timeout",
        "stopped",
        "failed",
    }
    launch_branch = parsed.branches["approve+commit"]
    assert launch_branch.suffix == PLAN_CHAIN_CODER_SUFFIX
    assert launch_branch.role == "code"
    assert launch_branch.fork == "none"
    assert launch_branch.raw_prompt is True
    assert parsed.branches["feedback"].suffix == f"{PLAN_CHAIN_PLAN_SUFFIX}-@"
    assert parsed.branches["feedback"].raw_prompt is True
    assert parsed.branches["commit"].prompt is None


def test_create_plan_shell_records_context_before_auto_settlement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    state.current_role_suffix = PLAN_CHAIN_PLAN_SUFFIX
    state.qa_rounds = []
    plan = write_plan(tmp_path, "plan.md", VALID_TALE_PLAN)
    member = tmp_path / "gate-member"
    bundle = tmp_path / "bundle"
    member.mkdir()
    bundle.mkdir()
    (member / "agent_meta.json").write_text(
        json.dumps(
            {
                "gate_kind": "plan",
                "gate_id": "plan-1",
                "agent_family": "test_agent",
                "name": "test_agent--gate",
            }
        ),
        encoding="utf-8",
    )
    pre_auto_meta: dict[str, Any] = {}

    def fake_create_gate_shell(
        request: dict[str, Any], *, before_auto_settle: Any = None
    ) -> GateShellCreation:
        gate = GateCreationResult(
            schema_version=3,
            notification_id=None,
            request_id="plan-1",
            kind="plan",
            bundle_path=bundle,
            request_path=bundle / "request.json",
            response_path=bundle / "response.json",
            preview_path=None,
            continuation_mode="plan_approval",
            auto_resolution={"state": "resolved"},
            hashes={},
        )
        record = GateShellRecord(
            gate_id="plan-1",
            member_agent_name="test_agent--gate",
            lane="test_agent",
            project_name="test_proj",
            artifacts_dir=str(member),
            timestamp="20260827120000",
            kind="plan",
            gate_state="answered",
            start_status="TALE",
            stop_status="TALE APPROVED",
            accent="#FFD75F",
            label="Plan",
            reason="wait for reviewer",
            creator_agent="test_agent--plan",
            bundle_path=str(bundle),
            notification_id=None,
            timeout_seconds=86400.0,
            request_fingerprint=None,
            workspace_policy="inherit",
        )
        if before_auto_settle is not None:
            before_auto_settle(record, gate)
            pre_auto_meta.update(
                json.loads((member / "agent_meta.json").read_text(encoding="utf-8"))
            )
        return GateShellCreation(
            gate=gate,
            record=record,
            project_file=None,
            claim_move=None,
            cl_name=None,
        )

    monkeypatch.setattr(
        "sase.plan_shell.create.create_gate_shell", fake_create_gate_shell
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.get_auto_plan_approval_action",
        lambda: "tale",
    )
    monkeypatch.setattr(
        "sase.main.plan_approve_handler.get_auto_plan_approval_argument",
        lambda: None,
    )
    monkeypatch.setattr(
        "sase.llm_provider._plan_utils.mark_auto_approved_plan_handled",
        lambda *_args, **_kwargs: None,
    )

    creation = create_plan_gate_shell(
        str(plan),
        session_id="plan-1",
        ctx=ctx,
        state=state,
        agent_runtime="1m",
    )

    assert creation.record.artifacts_dir == str(member)
    assert pre_auto_meta["plan_shell_session_id"] == "plan-1"
    assert pre_auto_meta["plan_shell_source_role_suffix"] == PLAN_CHAIN_PLAN_SUFFIX
    assert pre_auto_meta["plan_shell_source_plan_agent_name"] == "test_agent--plan"
    assert (
        Path(pre_auto_meta["plan_shell_current_prompt_path"]).read_text(
            encoding="utf-8"
        )
        == state.current_prompt
    )
    final_meta = json.loads((member / "agent_meta.json").read_text(encoding="utf-8"))
    assert final_meta["plan_shell_plan_path"] == str(plan)
    assert final_meta["patch_name"] == ctx.cl_name
