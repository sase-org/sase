"""Receipt-derived approval labels and honest commit status."""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sase._plan_archive_approval import _ApprovedPlanArchive
from sase.ace.tui.models._loaders._meta_enrichment_status import plan_enrichment_status
from sase.notification_gates.approval_projection import (
    _decision_projection,
    _failure_projection,
    project_accepted_decision,
    project_execution_failure,
    project_plan_committed,
    projected_gate_status,
)
from sase.notification_gates.decision import (
    DECISION_RECEIPT_FILENAME,
    accept_gate_decision,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.models import GateError
from sase.notification_gates.service import create_gate
from sase.plan_approval_actions import PlanApprovalActionError
from sase.plan_gate import build_plan_approval_gate_spec
from tests._plan_gate_fixtures import (
    plan_gate_home,  # noqa: F401
    wait_for_archive_start,
    write_plan,
)
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


def _write_planner(root: Path) -> Path:
    planner = root / "planner"
    planner.mkdir()
    (planner / "agent_meta.json").write_text(
        json.dumps({"name": "planner", "plan": True}),
        encoding="utf-8",
    )
    return planner


def _planner_meta(planner: Path) -> dict[str, object]:
    return json.loads((planner / "agent_meta.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("kind", "selected", "action", "label"),
    [
        ("plan", ("approve",), "approve", "PLAN APPROVED"),
        ("plan", ("approve", "commit"), "tale", "TALE APPROVED"),
        ("plan", ("commit",), "commit", None),
        ("plan", ("reject",), None, "PLAN REJECTED"),
        ("plan", ("feedback",), None, "FEEDBACK"),
        ("epic_plan", ("approve",), "epic", "EPIC APPROVED"),
        ("epic_plan", ("reject",), None, "EPIC REJECTED"),
        ("epic_plan", ("feedback",), None, "FEEDBACK"),
        ("custom", ("accept",), None, None),
    ],
)
def test_decision_projection_maps_plan_selections(
    kind: str,
    selected: tuple[str, ...],
    action: str | None,
    label: str | None,
) -> None:
    assert _decision_projection(kind, selected) == (action, label)


def test_failure_projection_is_distinct_from_approved_labels() -> None:
    assert _failure_projection("plan") == ("failed", "PLAN FAILED")
    assert _failure_projection("epic_plan") == ("epic_failed", "EPIC FAILED")


def test_plan_enrichment_status_hides_commit_until_archive() -> None:
    assert (
        plan_enrichment_status(
            plan_approved=True,
            plan_action="commit",
            plan_submitted=True,
            auto_approved=False,
            plan_committed=False,
        )
        is None
    )
    assert (
        plan_enrichment_status(
            plan_approved=True,
            plan_action="commit",
            plan_submitted=True,
            auto_approved=False,
            plan_committed=True,
        )
        == "PLAN COMMITTED"
    )


def test_plan_enrichment_status_failure_replaces_approved_label() -> None:
    assert (
        plan_enrichment_status(
            plan_approved=True,
            plan_action="failed",
            plan_submitted=True,
            auto_approved=False,
        )
        == "PLAN FAILED"
    )
    assert (
        plan_enrichment_status(
            plan_approved=True,
            plan_action="epic_failed",
            plan_submitted=True,
            auto_approved=False,
        )
        == "EPIC FAILED"
    )


def test_accept_approve_commit_projects_tale_approved_not_committed(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _write_planner(gate_home)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(planner))
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "tale.md", VALID_TALE_PLAN),
            "proj-approve-commit",
        )
    )

    accept_gate_decision(gate.bundle_path, ["approve", "commit"])

    meta = _planner_meta(planner)
    assert meta["plan_approved"] is True
    assert meta["plan_action"] == "tale"
    assert meta.get("plan_committed") is not True
    assert projected_gate_status(gate.bundle_path) == "TALE APPROVED"


def test_accept_commit_only_does_not_show_plan_committed(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _write_planner(gate_home)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(planner))
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "commit.md", VALID_TALE_PLAN),
            "proj-commit-only",
        )
    )

    accept_gate_decision(gate.bundle_path, ["commit"])

    meta = _planner_meta(planner)
    assert meta.get("plan_action") != "commit"
    assert meta.get("plan_committed") is not True
    assert projected_gate_status(gate.bundle_path) is None


def test_accept_epic_projects_epic_approved(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _write_planner(gate_home)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(planner))
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "epic.md", VALID_EPIC_PLAN),
            "proj-epic",
        )
    )

    accept_gate_decision(gate.bundle_path, ["approve"])

    meta = _planner_meta(planner)
    assert meta["plan_approved"] is True
    assert meta["plan_action"] == "epic"
    assert projected_gate_status(gate.bundle_path) == "EPIC APPROVED"


def test_archive_barrier_keeps_approved_label_without_committed(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _write_planner(gate_home)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(planner))
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "archive-held.md", VALID_TALE_PLAN),
            "proj-archive-held",
        )
    )
    started = Event()
    release = Event()
    saved = gate_home / "archived.md"

    def archive(*_args: object, required: bool = False, **_kwargs: object) -> object:
        del required
        started.set()
        assert not gate.response_path.exists()
        assert _planner_meta(planner)["plan_action"] == "tale"
        assert projected_gate_status(gate.bundle_path) == "TALE APPROVED"
        assert release.wait(timeout=5)
        saved.write_text(VALID_TALE_PLAN, encoding="utf-8")
        return _ApprovedPlanArchive(saved, "plan:202608/archived.md")

    with patch(
        "sase.plan_approval_actions._archive_plan_for_approval",
        side_effect=archive,
    ):
        with ThreadPoolExecutor(max_workers=1) as executor:
            try:
                future = executor.submit(
                    execute_gate_selection,
                    gate.bundle_path,
                    ["approve", "commit"],
                )
                wait_for_archive_start(started, future)
                assert not gate.response_path.exists()
                assert _planner_meta(planner).get("plan_committed") is not True
                release.set()
                future.result(timeout=10)
            finally:
                release.set()

    meta = _planner_meta(planner)
    assert meta["plan_action"] == "tale"
    assert meta["plan_committed"] is True
    assert projected_gate_status(gate.bundle_path) == "TALE APPROVED"


def test_commit_only_archive_success_projects_plan_committed(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _write_planner(gate_home)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(planner))
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "commit-ok.md", VALID_TALE_PLAN),
            "proj-commit-ok",
        )
    )
    saved = gate_home / "saved.md"
    saved.write_text(VALID_TALE_PLAN, encoding="utf-8")

    with patch(
        "sase.plan_approval_actions._archive_plan_for_approval",
        return_value=_ApprovedPlanArchive(saved, "plan:202608/saved.md"),
    ):
        execute_gate_selection(gate.bundle_path, ["commit"])

    meta = _planner_meta(planner)
    assert meta["plan_approved"] is True
    assert meta["plan_action"] == "commit"
    assert meta["plan_committed"] is True
    assert projected_gate_status(gate.bundle_path) == "PLAN COMMITTED"


def test_archive_failure_rolls_back_to_plan_failed(
    gate_home: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    planner = _write_planner(gate_home)
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(planner))
    gate = create_gate(
        build_plan_approval_gate_spec(
            write_plan(gate_home, "archive-fails.md", VALID_TALE_PLAN),
            "proj-archive-fails",
        )
    )

    with (
        patch(
            "sase.plan_approval_actions._archive_plan_for_approval",
            side_effect=PlanApprovalActionError(
                "plan_archive_failed", "plan", "archive boom"
            ),
        ),
        pytest.raises(GateError) as exc_info,
    ):
        execute_gate_selection(gate.bundle_path, ["commit"])

    assert exc_info.value.code == "plan_archive_failed"
    assert not gate.response_path.exists()
    meta = _planner_meta(planner)
    assert meta["plan_action"] == "failed"
    assert meta["plan_committed"] is False
    assert (gate.bundle_path / DECISION_RECEIPT_FILENAME).is_file()


def test_receiptless_legacy_commit_waits_for_archive(tmp_path: Path) -> None:
    bundle = tmp_path / "legacy"
    bundle.mkdir()
    (bundle / "request.json").write_text(
        json.dumps({"kind": "plan", "request_id": "legacy-commit"}),
        encoding="utf-8",
    )
    planner = _write_planner(tmp_path)
    envelope = {
        "kind": "plan",
        "request_id": "legacy-commit",
        "producer": {"artifacts_dir": str(planner)},
        "presentation": {"action_data": {"artifacts_dir": str(planner)}},
    }

    project_accepted_decision(
        bundle,
        envelope,
        {"selected_option_ids": ["commit"]},
    )
    assert _planner_meta(planner).get("plan_action") != "commit"
    assert projected_gate_status(bundle) is None

    (bundle / "response.json").write_text(
        json.dumps({"plan_archive_state": "archived"}),
        encoding="utf-8",
    )
    project_plan_committed(bundle, envelope, action="commit")
    meta = _planner_meta(planner)
    assert meta["plan_action"] == "commit"
    assert meta["plan_committed"] is True
    # Receiptless bundles keep using planner metadata, not the receipt loader.
    assert projected_gate_status(bundle) is None


def test_execution_failure_replaces_approved_label(tmp_path: Path) -> None:
    bundle = tmp_path / "failed"
    bundle.mkdir()
    (bundle / "request.json").write_text(
        json.dumps({"kind": "plan", "request_id": "failed-gate"}),
        encoding="utf-8",
    )
    planner = _write_planner(tmp_path)
    envelope = {
        "kind": "plan",
        "request_id": "failed-gate",
        "producer": {"artifacts_dir": str(planner)},
        "presentation": {"action_data": {"artifacts_dir": str(planner)}},
    }
    project_accepted_decision(
        bundle,
        envelope,
        {"selected_option_ids": ["approve", "commit"]},
    )
    assert _planner_meta(planner)["plan_action"] == "tale"

    project_execution_failure(bundle, envelope)
    meta = _planner_meta(planner)
    assert meta["plan_action"] == "failed"
    assert meta["plan_committed"] is False


def test_epic_launch_publishes_terminal_state_before_prepare(
    gate_home: Path,
) -> None:
    from sase.notification_gates.registry import adapter_for_kind

    plan = write_plan(gate_home, "epic-order.md", VALID_EPIC_PLAN)
    gate = create_gate(build_plan_approval_gate_spec(plan, "epic-order"))
    response = {
        "selected_option_ids": ["approve"],
        "input": {"epic_launch_mode": "launch"},
        "option_results": [
            {
                "id": "approve",
                "result": {
                    "action": "epic",
                    "commit_plan": True,
                    "run_coder": True,
                    "epic_launch_owner": "host",
                },
            }
        ],
        "source": "cli",
    }
    order: list[str] = []

    with (
        patch("sase.plan_approval_actions.run_plan_side_effects"),
        patch(
            "sase.notification_gates.adapters._publish_shell_terminal_before_epic_launch",
            side_effect=lambda *_args, **_kwargs: order.append("terminal"),
        ),
        patch(
            "sase.plan_approval_actions.prepare_epic_launch",
            side_effect=lambda *_args, **_kwargs: (
                order.append("launch"),
                SimpleNamespace(monitor_id="mon-order"),
            )[1],
        ),
    ):
        adapter_for_kind("epic_plan").apply_side_effects(
            bundle_path=gate.bundle_path,
            response=response,
        )

    assert order == ["terminal", "launch"]
    assert response["epic_launch_monitor_id"] == "mon-order"
