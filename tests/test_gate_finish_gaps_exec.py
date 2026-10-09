"""Gate finish gaps: stale review, authored-order stamping, restamp, refusal.

Covers plan section 3 items 1, 2, 3, and 9: the ``stale_review`` rejection
through the executor and both ``sase gate answer`` transports, authored-order
stamping on every route, the agent memory refusal end to end, and the
single-record restamp failure.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.plan_gate import build_plan_approval_gate_spec
from tests._plan_gate_fixtures import (
    plan_gate_home,  # noqa: F401 (registers the gate_home fixture)
)
from tests.plan_validation_helpers import VALID_TALE_PLAN

ORDERED_TALE = """---
tier: tale
title: Order check
goal: Keep author order.
size: small
decisions:
  zeta:
    ask: Pick zeta value?
    choices:
      b: Second choice
      a: First choice
    default: b
    why: zeta why
  alpha:
    ask: Turn alpha on?
    default: false
---
# Plan

> [!decision] zeta = b Zeta b branch.
> [!decision] alpha Alpha yes branch.
"""

ORDERED_EPIC = """---
tier: epic
title: Epic order
goal: Ship it in order.
phases:
  - id: implementation
    title: Implement
    depends_on: []
    description: "implementation: build it."
    size: small
decisions:
  zeta:
    ask: Pick zeta value?
    choices:
      b: Second choice
      a: First choice
    default: b
    why: zeta why
  alpha:
    ask: Turn alpha on?
    default: false
---
# Plan

> [!decision] zeta = b Zeta b branch.
> [!decision] alpha Alpha yes branch.
"""

MEMORY_TALE = """---
tier: tale
title: Keymap help overlay
goal: Pressing ? shows bindings.
size: small
decisions:
  tui_note:
    ask: Record conventions in the tui memory note?
    memory: [tui.md]
    requested: "and note the convention in the tui memory"
    default: true
---
# Plan

Body mentions tui_note.
"""

#: Reversed submission order: the stamp must still follow authored order.
REVERSED_INPUTS = {"decision_alpha": True, "decision_zeta": "a"}


def _needs_core(*names: str) -> None:
    pytest.importorskip("sase_core_rs")
    import sase_core_rs as core

    for name in names:
        if not hasattr(core, name):
            pytest.skip(f"stale core without {name}")


def _error_records(bundle: Path) -> list[dict]:
    errors_dir = bundle / "errors"
    if not errors_dir.is_dir():
        return []
    return [
        json.loads(item.read_text(encoding="utf-8"))
        for item in sorted(errors_dir.glob("*.json"))
    ]


def _stamped_frontmatter(plan: Path) -> dict:
    from sase.sdd.frontmatter import parse_frontmatter

    frontmatter, _, _ = parse_frontmatter(plan.read_text(encoding="utf-8"))
    return frontmatter


def test_stale_review_writes_one_record_and_no_response(gate_home: Path) -> None:
    plan = gate_home / "stale.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    gate = create_gate(build_plan_approval_gate_spec(plan, "stale-exec"))

    with pytest.raises(GateError) as excinfo:
        execute_gate_selection(
            gate.bundle_path, ["approve"], expected_review_revision=9
        )

    assert excinfo.value.code == "stale_review"
    assert "9" in str(excinfo.value) and "1" in str(excinfo.value)
    records = _error_records(gate.bundle_path)
    assert len(records) == 1
    assert records[0]["code"] == "stale_review"
    assert "9" in records[0]["message"] and "1" in records[0]["message"]
    assert not (gate.bundle_path / "response.json").exists()


def test_stale_review_cli_attached_writes_same_record(
    gate_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    from sase.main.gate_handler import handle_gate_command
    from sase.main.parser_gate import register_gate_parser
    from sase.ops.io import write_operation_request
    from sase.ops.models import DurableOperationRequest
    from sase.ops.names import GATE_ANSWER

    plan = gate_home / "stale-cli.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    gate = create_gate(build_plan_approval_gate_spec(plan, "stale-cli"))
    sidecar = tmp_path / "request.json"
    write_operation_request(
        sidecar,
        DurableOperationRequest(
            operation=GATE_ANSWER,
            payload={"option_ids": ["approve"], "review_revision": 9},
        ),
    )
    monkeypatch.setenv("SASE_PROC_REQUEST_PATH", str(sidecar))

    parser = argparse.ArgumentParser(prog="sase")
    register_gate_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        [
            "gate",
            "answer",
            "--id",
            "stale-cli",
            "--kind",
            "plan",
            "--option",
            "approve",
            "--no-detach",
        ]
    )
    with pytest.raises(SystemExit) as exitinfo:
        handle_gate_command(args)

    assert int(exitinfo.value.code or 0) != 0
    records = _error_records(gate.bundle_path)
    assert len(records) == 1
    assert records[0]["code"] == "stale_review"
    assert not (gate.bundle_path / "response.json").exists()


def test_stale_review_cli_detached_rerun_writes_same_record(
    gate_home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import argparse

    from sase.main.gate_handler import handle_gate_command
    from sase.main.parser_gate import register_gate_parser
    from sase.notification_gates import cli_answer_submit as submit_mod
    from sase.ops.io import write_operation_request
    from sase.ops.models import DurableOperationRequest
    from sase.ops.names import GATE_ANSWER

    monkeypatch.setenv("SASE_PROC_REQUEST_PATH", str(_write_revision_sidecar(tmp_path)))

    plan = gate_home / "stale-detached.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    gate = create_gate(build_plan_approval_gate_spec(plan, "stale-detached"))

    captured: dict = {}

    class _Proc:
        proc_id = "proc-stale"

    def _capture(request):  # type: ignore[no-untyped-def]
        captured["argv"] = list(request.argv)
        captured["payload"] = dict(request.operation_payload)
        return _Proc()

    parser = argparse.ArgumentParser(prog="sase")
    register_gate_parser(parser.add_subparsers(dest="command"))
    args = parser.parse_args(
        [
            "gate",
            "answer",
            "--id",
            "stale-detached",
            "--kind",
            "plan",
            "--option",
            "approve",
            "--detach",
        ]
    )
    with patch.object(submit_mod, "submit_proc_request", _capture):
        with pytest.raises(SystemExit) as exitinfo:
            handle_gate_command(args)

    assert int(exitinfo.value.code or 0) == 0
    # The detached proc re-runs the same command with --no-detach.
    assert "--no-detach" in captured["argv"]
    assert "--detach" not in captured["argv"]
    assert captured["payload"]["review_revision"] == 9

    # Drive that re-run: same payload through the attached path.
    rerun_sidecar = tmp_path / "rerun.json"
    write_operation_request(
        rerun_sidecar,
        DurableOperationRequest(
            operation=GATE_ANSWER, payload=dict(captured["payload"])
        ),
    )
    rerun = parser.parse_args(
        [
            "gate",
            "answer",
            "--id",
            "stale-detached",
            "--kind",
            "plan",
            "--option",
            "approve",
            "--no-detach",
        ]
    )
    monkeypatch.setenv("SASE_PROC_REQUEST_PATH", str(rerun_sidecar))
    with pytest.raises(SystemExit) as rerun_exit:
        handle_gate_command(rerun)

    assert int(rerun_exit.value.code or 0) != 0
    records = _error_records(gate.bundle_path)
    assert len(records) == 1
    assert records[0]["code"] == "stale_review"
    assert not (gate.bundle_path / "response.json").exists()


def _write_revision_sidecar(tmp_path: Path) -> Path:
    from sase.ops.io import write_operation_request
    from sase.ops.models import DurableOperationRequest
    from sase.ops.names import GATE_ANSWER

    sidecar = tmp_path / "detach-request.json"
    write_operation_request(
        sidecar,
        DurableOperationRequest(
            operation=GATE_ANSWER,
            payload={"option_ids": ["approve"], "review_revision": 9},
        ),
    )
    return sidecar


@pytest.mark.parametrize(
    "selected",
    [["approve"], ["commit"], ["approve", "commit"]],
)
def test_authored_order_tale_routes(gate_home: Path, selected: list[str]) -> None:
    _needs_core("plan_decisions_payload", "plan_decisions_resolve")
    from sase._plan_archive_approval import _ApprovedPlanArchive

    plan = gate_home / f"order-{len(selected)}.md"
    plan.write_text(ORDERED_TALE, encoding="utf-8")
    gate = create_gate(build_plan_approval_gate_spec(plan, f"order-{len(selected)}"))
    per_option = {option: dict(REVERSED_INPUTS) for option in selected}
    saved = gate_home / "archived.md"
    saved.write_text("# archived\n", encoding="utf-8")

    with (
        patch("sase.plan_approval_actions.run_plan_side_effects"),
        patch(
            "sase.plan_approval_actions._archive_plan_for_approval",
            return_value=_ApprovedPlanArchive(saved, "plan:202608/archived.md"),
        ),
    ):
        execute_gate_selection(
            gate.bundle_path, selected, option_inputs=per_option, source="cli"
        )

    frontmatter = _stamped_frontmatter(plan)
    assert list(frontmatter["decisions"].keys()) == ["zeta", "alpha"]
    assert frontmatter["decisions"]["zeta"]["answer"] == "a"
    assert frontmatter["decisions"]["alpha"]["answer"] is True
    assert frontmatter["decided_by"] == "reviewer"
    assert frontmatter["decided_via"] == "cli"


def test_authored_order_epic(gate_home: Path) -> None:
    _needs_core("plan_decisions_payload", "plan_decisions_resolve")

    plan = gate_home / "order-epic.md"
    plan.write_text(ORDERED_EPIC, encoding="utf-8")
    gate = create_gate(build_plan_approval_gate_spec(plan, "order-epic"))
    inputs = dict(REVERSED_INPUTS, epic_launch_mode="skip")

    with (
        patch("sase.plan_approval_actions.run_plan_side_effects"),
        patch(
            "sase.plan_approval_actions.prepare_epic_launch",
            return_value=SimpleNamespace(monitor_id="mon-order"),
        ),
    ):
        execute_gate_selection(
            gate.bundle_path,
            ["approve"],
            option_inputs={"approve": inputs},
            source="cli",
        )

    frontmatter = _stamped_frontmatter(plan)
    assert list(frontmatter["decisions"].keys()) == ["zeta", "alpha"]
    assert frontmatter["decided_by"] == "reviewer"
    assert frontmatter["decided_via"] == "cli"


def test_authored_order_bead_work(tmp_path: Path, monkeypatch) -> None:
    _needs_core("plan_decisions_payload", "plan_decisions_resolve")
    from sase.bead import cli_work_from_plan as bead_module
    from sase.sdd.plan_validate import validate_plan_file

    for env_name in ("SASE_AGENT", "SASE_AGENT_NAME"):
        monkeypatch.delenv(env_name, raising=False)
    monkeypatch.setattr("sase.agent.identity.discover_agent_identity", lambda: None)
    plan = tmp_path / "bead-order.md"
    plan.write_text(ORDERED_EPIC, encoding="utf-8")
    validation = validate_plan_file(plan, "epic", mode="launch")
    assert validation.ok

    bead_module._stamp_bead_work_decisions(plan, validation, dry_run=False)

    frontmatter = _stamped_frontmatter(plan)
    assert list(frontmatter["decisions"].keys()) == ["zeta", "alpha"]
    assert frontmatter["decided_by"] == "reviewer"
    assert frontmatter["decided_via"] == "cli"


def test_retry_restamp_keeps_authored_order(gate_home: Path) -> None:
    _needs_core("plan_decisions_payload", "plan_decisions_resolve")
    from sase.plan_gate_decisions import recover_plan_stamp_from_response

    plan = gate_home / "order-retry.md"
    plan.write_text(ORDERED_TALE, encoding="utf-8")
    gate = create_gate(build_plan_approval_gate_spec(plan, "order-retry"))
    with patch("sase.plan_approval_actions.run_plan_side_effects"):
        execute_gate_selection(
            gate.bundle_path,
            ["approve"],
            option_inputs={"approve": dict(REVERSED_INPUTS)},
            source="cli",
        )

    # Wipe the answers; the retry re-stamp must restore them in order.
    plan.write_text(ORDERED_TALE, encoding="utf-8")
    assert recover_plan_stamp_from_response(gate.bundle_path) is True
    frontmatter = _stamped_frontmatter(plan)
    assert list(frontmatter["decisions"].keys()) == ["zeta", "alpha"]
    assert frontmatter["decisions"]["zeta"]["answer"] == "a"
    assert frontmatter["decisions"]["alpha"]["answer"] is True


def test_recover_conflicting_stamp_raises(gate_home: Path) -> None:
    _needs_core("plan_decisions_payload", "plan_decisions_resolve")
    from sase.plan_approval_actions import PlanApprovalActionError
    from sase.plan_gate_decisions import recover_plan_stamp_from_response

    plan = gate_home / "order-conflict.md"
    plan.write_text(ORDERED_TALE, encoding="utf-8")
    gate = create_gate(build_plan_approval_gate_spec(plan, "order-conflict"))
    with patch("sase.plan_approval_actions.run_plan_side_effects"):
        execute_gate_selection(
            gate.bundle_path,
            ["approve"],
            option_inputs={"approve": dict(REVERSED_INPUTS)},
            source="cli",
        )

    conflicted = plan.read_text(encoding="utf-8").replace("answer: a", "answer: b")
    assert conflicted != plan.read_text(encoding="utf-8")
    plan.write_text(conflicted, encoding="utf-8")
    with pytest.raises(PlanApprovalActionError):
        recover_plan_stamp_from_response(gate.bundle_path)


def test_recover_missing_answers_returns_false(gate_home: Path) -> None:
    from sase.plan_gate_decisions import recover_plan_stamp_from_response

    bundle = gate_home / "missing-answers"
    bundle.mkdir()
    (bundle / "request.json").write_text(
        json.dumps({"payload": {"decisions": [{"id": "zeta"}]}}), encoding="utf-8"
    )
    (bundle / "response.json").write_text(
        json.dumps({"source": "cli", "caller": "human"}), encoding="utf-8"
    )
    assert recover_plan_stamp_from_response(bundle) is False


def test_retry_restamp_failure_records_stage_restamp_once(gate_home: Path) -> None:
    _needs_core("plan_decisions_payload", "plan_decisions_resolve")
    from sase.plan_approval_actions import PlanApprovalActionError

    plan = gate_home / "restamp-retry.md"
    plan.write_text(ORDERED_TALE, encoding="utf-8")
    gate = create_gate(build_plan_approval_gate_spec(plan, "restamp-retry"))
    with patch("sase.plan_approval_actions.run_plan_side_effects"):
        execute_gate_selection(
            gate.bundle_path,
            ["approve"],
            option_inputs={"approve": dict(REVERSED_INPUTS)},
            source="cli",
        )
    assert _error_records(gate.bundle_path) == []

    conflicted = plan.read_text(encoding="utf-8").replace("answer: a", "answer: b")
    plan.write_text(conflicted, encoding="utf-8")
    with pytest.raises(PlanApprovalActionError):
        execute_gate_selection(gate.bundle_path, ["approve"], source="cli")

    records = _error_records(gate.bundle_path)
    assert len(records) == 1
    assert records[0]["stage"] == "restamp"


def test_side_effects_restamp_failure_records_once(gate_home: Path) -> None:
    _needs_core("plan_decisions_payload", "plan_decisions_resolve")
    from sase.notification_gates.executor_side_effects import resume_side_effects
    from sase.notification_gates.registry import adapter_for_kind
    from sase.notification_gates.decision import (
        read_current_receipt,
        receipt_acceptance_id,
    )
    from sase.notification_gates.durability import read_json_object
    from sase.plan_approval_actions import PlanApprovalActionError

    plan = gate_home / "restamp-once.md"
    plan.write_text(ORDERED_TALE, encoding="utf-8")
    gate = create_gate(build_plan_approval_gate_spec(plan, "restamp-once"))
    with patch("sase.plan_approval_actions.run_plan_side_effects"):
        execute_gate_selection(
            gate.bundle_path,
            ["approve"],
            option_inputs={"approve": dict(REVERSED_INPUTS)},
            source="cli",
        )
    assert _error_records(gate.bundle_path) == []

    response = read_json_object(gate.bundle_path / "response.json")
    receipt = read_current_receipt(gate.bundle_path)
    with patch(
        "sase.plan_gate_decisions.recover_plan_stamp_from_response",
        side_effect=PlanApprovalActionError(
            "plan_archive_failed", "durable", "restamp boom"
        ),
    ):
        with pytest.raises(GateError):
            resume_side_effects(
                gate.bundle_path,
                adapter=adapter_for_kind("plan"),
                response=response,
                acceptance_id=receipt_acceptance_id(receipt),
                epic_launch_origin=None,
                source="cli",
            )

    assert len(_error_records(gate.bundle_path)) == 1


def test_agent_memory_refusal_end_to_end(
    gate_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _needs_core("plan_decisions_resolve")
    monkeypatch.setenv("SASE_AGENT", "1")

    plan = gate_home / "memory-refusal.md"
    plan.write_text(MEMORY_TALE, encoding="utf-8")
    gate = create_gate(build_plan_approval_gate_spec(plan, "memory-refusal"))

    with pytest.raises(GateError) as excinfo:
        execute_gate_selection(
            gate.bundle_path,
            ["approve"],
            {"decision_tui_note": True},
            source="cli",
        )

    assert excinfo.value.code == "memory_decision_requires_human"
    records = _error_records(gate.bundle_path)
    assert len(records) == 1
    assert records[0]["code"] == "memory_decision_requires_human"
    assert not (gate.bundle_path / "response.json").exists()
    assert "answer:" not in plan.read_text(encoding="utf-8")


# NOTE: the direct-file route's authored order is pinned by
# tests/test_plan_direct_approval_run.py; this phase reuses it and does not
# duplicate it.
