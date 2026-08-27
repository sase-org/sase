"""Plan-gate validation, hash-integrity, and spec-forgery rejection coverage."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.edits import refresh_gate_after_edit
from sase.notification_gates.service import create_gate
from sase.plan_approval_actions import (
    PlanApprovalValidationError,
    require_plan_approval_validation,
)
from sase.plan_gate import (
    _build_plan_gate_spec,
    build_plan_approval_gate_spec,
)
from sase.plan_shell.create import plan_gate_shell_block

from tests._plan_gate_fixtures import (
    plan_gate_home,  # noqa: F401 (registers the gate_home fixture)
    write_plan,
)
from tests.plan_validation_helpers import (
    MALFORMED_HEADER_EPIC_PLAN,
    VALID_TALE_PLAN,
)


def test_edit_revalidates_tier_then_refreshes_review_hashes(gate_home: Path) -> None:
    plan = write_plan(gate_home, "edit.md", VALID_TALE_PLAN)
    gate = create_gate(build_plan_approval_gate_spec(plan, "edit-request"))
    reviewed = gate.bundle_path / "plan.md"
    request_before = json.loads(gate.request_path.read_text(encoding="utf-8"))
    reviewed.write_text("# missing frontmatter\n", encoding="utf-8")

    with pytest.raises(PlanApprovalValidationError):
        refresh_gate_after_edit(gate.bundle_path, "edit_plan")
    assert json.loads(gate.request_path.read_text())["review_revision"] == 1

    edited = VALID_TALE_PLAN.replace(
        "Implement the requested change.", "Implement and verify the requested change."
    )
    reviewed.write_text(edited, encoding="utf-8")
    hashes = refresh_gate_after_edit(gate.bundle_path, "edit_plan")
    request_after = json.loads(gate.request_path.read_text(encoding="utf-8"))
    assert request_after["review_revision"] == 2
    assert hashes["request"] != request_before["hashes"]["request"]
    assert (
        hashes["resources"]["plan.md"]
        != request_before["hashes"]["resources"]["plan.md"]
    )
    assert execute_gate_selection(gate.bundle_path, ["approve"]).response[
        "selected_option_ids"
    ] == ["approve"]
    assert plan.read_text(encoding="utf-8") == edited


def test_require_plan_approval_validation_rejects_malformed_header_block(
    gate_home: Path,
) -> None:
    plan = write_plan(gate_home, "malformed-header.md", MALFORMED_HEADER_EPIC_PLAN)

    with pytest.raises(PlanApprovalValidationError) as exc_info:
        require_plan_approval_validation(plan, "epic")

    error = exc_info.value
    assert error.code == "plan_validation_failed"
    assert any(
        diagnostic.code == "header-invalid"
        for diagnostic in error.validation.diagnostics
    )
    assert "header-invalid" in str(error)
    assert "trailing text in PARENT plan header section" in str(error)


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        pytest.param(
            VALID_TALE_PLAN.replace("size: small\n", ""),
            "tale-size-missing",
            id="missing",
        ),
        pytest.param(
            VALID_TALE_PLAN.replace("size: small", "size: large"),
            "tale-size-invalid",
            id="large",
        ),
    ],
)
def test_require_plan_approval_validation_launch_normalizes_legacy_tale_size(
    gate_home: Path,
    content: str,
    expected_code: str,
) -> None:
    plan = write_plan(
        gate_home,
        "legacy-tale.md",
        content,
    )

    validation = require_plan_approval_validation(plan, "tale")

    assert validation.ok
    assert [diagnostic.severity.value for diagnostic in validation.diagnostics] == [
        "warning"
    ]
    assert [diagnostic.code for diagnostic in validation.diagnostics] == [expected_code]
    assert validation.plan is not None
    assert validation.plan.size == "medium"


def test_plan_toctou_and_unregistered_command_contract_are_rejected(
    gate_home: Path,
) -> None:
    plan = write_plan(gate_home, "toctou.md", VALID_TALE_PLAN)
    gate = create_gate(build_plan_approval_gate_spec(plan, "toctou-request"))
    (gate.bundle_path / "plan.md").write_text(
        VALID_TALE_PLAN + "\nUnreviewed mutation\n", encoding="utf-8"
    )
    with pytest.raises(GateError) as exc_info:
        execute_gate_selection(gate.bundle_path, ["approve"])
    assert exc_info.value.code == "hash_mismatch"
    assert not gate.response_path.exists()

    forged = _build_plan_gate_spec(
        plan,
        "forged-request",
        tier="tale",
        validation=require_plan_approval_validation(plan, "tale"),
        auto_enabled=False,
        auto_argument=None,
        agent_name=None,
        agent_model=None,
        agent_llm_provider=None,
        agent_runtime=None,
        agent_vcs_tag=None,
    )
    commands = forged["resources"]
    assert isinstance(commands, list)
    commands[1]["content"] = "#!/bin/sh\nexit 0\n"
    with pytest.raises(GateError) as exc_info:
        create_gate(forged)
    assert exc_info.value.code == "invalid_plan_command"


def test_plan_adapter_rejects_non_registered_query_shape(
    gate_home: Path,
) -> None:
    plan = write_plan(gate_home, "forged-query.md", VALID_TALE_PLAN)
    spec = _build_plan_gate_spec(
        plan,
        "forged-query",
        tier="tale",
        validation=require_plan_approval_validation(plan, "tale"),
        auto_enabled=False,
        auto_argument=None,
        agent_name=None,
        agent_model=None,
        agent_llm_provider=None,
        agent_runtime=None,
        agent_vcs_tag=None,
    )
    spec["query"] = "approve OR commit OR reject OR feedback"
    spec["primary_branch"] = ["approve"]
    spec["groups"] = []

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)
    assert exc_info.value.code == "invalid_plan_query"


def test_plan_adapter_rejects_forged_shell_block(gate_home: Path) -> None:
    plan = write_plan(gate_home, "forged-shell.md", VALID_TALE_PLAN)
    spec = _build_plan_gate_spec(
        plan,
        "forged-shell",
        tier="tale",
        validation=require_plan_approval_validation(plan, "tale"),
        auto_enabled=False,
        auto_argument=None,
        agent_name=None,
        agent_model=None,
        agent_llm_provider=None,
        agent_runtime=None,
        agent_vcs_tag=None,
    )
    spec["shell"] = plan_gate_shell_block("tale")
    spec["shell"]["branches"]["approve+commit"]["suffix"] = "--plan-@"

    with pytest.raises(GateError) as exc_info:
        create_gate(spec)
    assert exc_info.value.code == "invalid_plan_shell"


def test_plan_adapter_accepts_tale_group_and_rejects_stale_label(
    gate_home: Path,
) -> None:
    plan = write_plan(gate_home, "group-label.md", VALID_TALE_PLAN)
    canonical = _build_plan_gate_spec(
        plan,
        "canonical-group-label",
        tier="tale",
        validation=require_plan_approval_validation(plan, "tale"),
        auto_enabled=False,
        auto_argument=None,
        agent_name=None,
        agent_model=None,
        agent_llm_provider=None,
        agent_runtime=None,
        agent_vcs_tag=None,
    )

    result = create_gate(canonical)
    request = json.loads(result.request_path.read_text(encoding="utf-8"))
    assert request["groups"] == [
        {"options": ["approve", "commit"], "label": "Tale", "icon": "✅"}
    ]

    stale = _build_plan_gate_spec(
        plan,
        "stale-group-label",
        tier="tale",
        validation=require_plan_approval_validation(plan, "tale"),
        auto_enabled=False,
        auto_argument=None,
        agent_name=None,
        agent_model=None,
        agent_llm_provider=None,
        agent_runtime=None,
        agent_vcs_tag=None,
    )
    stale["groups"][0]["label"] = "Approve"

    with pytest.raises(GateError) as exc_info:
        create_gate(stale)
    assert exc_info.value.code == "invalid_plan_group"
    assert exc_info.value.target == "groups[0].label"
    assert str(exc_info.value) == "tale plan submit group label must be 'Tale'"
