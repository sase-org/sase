"""UI-default independence: auto never follows ``primary_branch`` order.

E1 target: the automatic option IDs never depend on ``primary_branch``,
``default_selected``, or option order. Today the plan adapter picks the
gate's ``primary_branch`` filtered by ``default_selected``, so turning the
defaults off drops ``commit`` from tale auto-approval. The tale cases fail
for that documented reason; the single-option epic and question cases
already pass and are plain tests. The ``gates`` phase removes the xfail
markers.
"""

from __future__ import annotations

import dataclasses
import uuid

import pytest

from . import harness
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


def _mutated_tale_spec(workdir, *, default_off: bool, reorder: bool):
    """Build a real tale spec, then mutate the UI defaults like a human."""
    from sase.plan_gate import build_plan_approval_gate_spec

    plan = harness.write_plan_file(workdir, "tale.md", VALID_TALE_PLAN)
    spec_dict = build_plan_approval_gate_spec(
        str(plan),
        f"base-{uuid.uuid4().hex[:8]}",
        auto_enabled=True,
        auto_argument="tale",
    )
    if default_off:
        for option in spec_dict["options"]:
            if option["id"] in ("approve", "commit"):
                option["default_selected"] = False
    if reorder:
        spec_dict["primary_branch"] = ["commit", "approve"]
    from sase.notification_gates.models import GateSpec

    spec = GateSpec.from_mapping(spec_dict)
    return dataclasses.replace(spec, request_id=f"ui-{uuid.uuid4().hex[:8]}")


@pytest.mark.xfail(strict=True, reason="E1 gates: auto ignores default_selected")
def test_tale_ignores_default_selected_off(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tale auto keeps ``[approve, commit]`` with defaults off."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()

    spec = _mutated_tale_spec(workdir, default_off=True, reorder=False)
    gate = harness.create_plan_gate_isolated(spec, workdir, spec.request_id)

    assert (gate.to_dict().get("auto_resolution") or {}).get("selected_option_ids") == [
        "approve",
        "commit",
    ]


@pytest.mark.xfail(strict=True, reason="E1 gates: auto ignores primary_branch order")
def test_tale_ignores_primary_branch_reorder(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tale auto keeps ``[approve, commit]`` when the branch is reordered."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()

    spec = _mutated_tale_spec(workdir, default_off=False, reorder=True)
    gate = harness.create_plan_gate_isolated(spec, workdir, spec.request_id)

    assert (gate.to_dict().get("auto_resolution") or {}).get("selected_option_ids") == [
        "approve",
        "commit",
    ]


def test_epic_ignores_default_selected_off(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single-option epic gate still auto-approves with defaults off."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    workdir = tmp_path / "work"
    workdir.mkdir()
    from sase.notification_gates.models import GateSpec
    from sase.notification_gates.service import create_gate
    from sase.plan_gate import build_plan_approval_gate_spec

    plan = harness.write_plan_file(workdir, "epic.md", VALID_EPIC_PLAN)
    spec_dict = build_plan_approval_gate_spec(
        str(plan),
        f"base-{uuid.uuid4().hex[:8]}",
        auto_enabled=True,
        auto_argument="epic",
    )
    for option in spec_dict["options"]:
        if option["id"] == "approve":
            option["default_selected"] = False
    spec = GateSpec.from_mapping(spec_dict)
    spec = dataclasses.replace(spec, request_id=f"ui-{uuid.uuid4().hex[:8]}")
    gate = harness.create_plan_gate_isolated(spec, workdir, spec.request_id)

    assert (gate.to_dict().get("auto_resolution") or {}).get("selected_option_ids") == [
        "approve"
    ]


def test_question_ignores_default_selected_off(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The single-option question gate still auto-answers with defaults off."""
    harness.isolated_gate_dirs(monkeypatch, tmp_path)
    from sase.notification_gates.models import GateSpec
    from sase.notification_gates.service import create_gate
    from sase.user_question_actions import user_question_gate_spec

    spec_dict = user_question_gate_spec(
        [dict(question) for question in harness.QUESTIONS],
        session_id=f"ui-{uuid.uuid4().hex[:8]}",
        producer={"agent": "contract-agent"},
        auto=True,
    )
    for option in spec_dict["options"]:
        option["default_selected"] = False
    gate = harness.create_plan_gate_isolated(
        spec_dict, tmp_path, spec_dict["request_id"]
    )

    assert (gate.to_dict().get("auto_resolution") or {}).get("selected_option_ids") == [
        "submit"
    ]
