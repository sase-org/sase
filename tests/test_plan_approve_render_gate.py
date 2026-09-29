"""Gate-route render tests for ``sase plan approve``."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from sase.core.time import get_timezone
from sase.main.plan_approve_render import (
    render_gate_approval,
    render_gate_approval_dry_run,
)
from sase.main.plan_pending import PendingPlan
from sase.notifications.models import Notification
from sase.plan_approval_actions import PlanApprovalActionResult
from tests._plan_approve_render_helpers import (
    no_color,  # noqa: F401 (registers the autouse fixture)
    read_output,
)


def _pending_plan() -> PendingPlan:
    notification = Notification(
        id="a1b2c3d4e5f6",
        timestamp=datetime.now(get_timezone()).isoformat(),
        sender="plan",
        files=["/plans/updates_tab.md"],
        action="PlanApproval",
        action_data={},
    )
    return PendingPlan(
        notification=notification,
        name="updates_tab",
        display_name="updates_tab",
        archive_path=None,
        bundle_plan_path=None,
        title="Cache the Updates tab's first open",
        tier="tale",
        agent="planner",
        age="1m",
    )


def _gate_result(**overrides: object) -> PlanApprovalActionResult:
    fields: dict[str, object] = {
        "notification_id": "a1b2c3d4e5f6",
        "response_file": "plan_response.json",
        "response_path": Path("/r/plan_response.json"),
        "response_json": {},
        "message": "Tale approved",
    }
    fields.update(overrides)
    return PlanApprovalActionResult(**fields)  # type: ignore[arg-type]


def test_gate_success_card_names_coder_and_gate(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_gate_approval(
        _pending_plan(),
        _gate_result(coder_agent="bob--code", gate_turn_member="bob--gate"),
    )

    out, err = read_output(capsys)
    assert err == ""
    assert "✓ Tale approved · updates_tab" in out
    assert "Cache the Updates tab's first open" in out
    assert "coder   bob--code · launched by bob--gate" in out
    assert "gate    a1b2c3d4 → /r/plan_response.json" in out
    assert "follow  sase agent show bob--code" in out


def test_gate_success_without_result_fields_says_shell_launches_next(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_gate_approval(_pending_plan(), _gate_result())

    out, _ = read_output(capsys)
    assert "coder   the gate turn launches it next" in out
    assert "follow" not in out


def test_gate_success_reports_coder_launch_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_gate_approval(_pending_plan(), _gate_result(coder_error="no capacity"))

    out, _ = read_output(capsys)
    assert "! coder launch failed: no capacity" in out
    assert "follow" not in out


def test_gate_epic_approval_shows_monitor_launch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_gate_approval(
        _pending_plan(),
        _gate_result(message="Epic approved", epic_launch_monitor_id="42"),
    )

    out, _ = read_output(capsys)
    assert "launch  monitor 42 · sase monitor show 42 --follow" in out
    assert "coder" not in out


def test_gate_epic_approval_shows_proc_launch(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_gate_approval(
        _pending_plan(),
        _gate_result(message="Epic approved", epic_launch_task_id="7"),
    )

    out, _ = read_output(capsys)
    assert "launch  proc 7 · sase proc show 7 --follow" in out


def test_gate_dry_run_card_changes_nothing(
    capsys: pytest.CaptureFixture[str],
) -> None:
    render_gate_approval_dry_run(_pending_plan(), "tale")

    out, err = read_output(capsys)
    assert err == ""
    assert "◇ Dry run · updates_tab would be approved as a tale" in out
    assert "gate    a1b2c3d4 · the gate turn launches the coder" in out
    assert "Nothing was changed. Re-run without -n/--dry-run to approve." in out
