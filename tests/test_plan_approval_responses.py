"""Tests for neutral plan approval responses and notification metadata."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.llm_provider._plan_utils import PlanApprovalResult, handle_plan_approval
from sase.notification_gates.executor import execute_gate_choice
from sase.plan_gate import create_plan_approval_gate as _create_plan_approval_gate

from tests.conftest import redirect_sase_home
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


def _respond_after_gate_creation(
    choice: str,
    *,
    input_data: dict[str, Any] | None = None,
    captured: dict[str, Any] | None = None,
) -> Any:
    """Patch gate creation so a host response is ready before the runner polls."""

    def create(*args: Any, **kwargs: Any) -> Any:
        gate = _create_plan_approval_gate(*args, **kwargs)
        if captured is not None:
            captured["gate"] = gate
            captured["request"] = json.loads(
                gate.request_path.read_text(encoding="utf-8")
            )
        execute_gate_choice(
            gate.bundle_path,
            choice,
            input_data or {},
            source="test_host",
        )
        return gate

    return patch("sase.plan_gate.create_plan_approval_gate", side_effect=create)


def _ui_patches() -> tuple[Any, Any, Any]:
    return (
        patch("sase.main.plan_approve_handler.send_desktop_notification"),
        patch("sase.main.plan_approve_handler.ring_tmux_bell"),
        patch("sase.main.plan_approve_handler.get_tmux_prefix", return_value=""),
    )


def test_handle_plan_approval_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The neutral commit command maps back to the runner's no-coder result."""
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    desktop, bell, prefix = _ui_patches()

    with _respond_after_gate_creation("commit"), desktop, bell, prefix:
        result = handle_plan_approval(str(plan), "test-commit-session")

    assert result == PlanApprovalResult(
        action="approve",
        plan_file=str(plan),
        commit_plan=True,
        run_coder=False,
    )


def test_handle_plan_approval_reads_host_epic_launch_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = tmp_path / "epic.md"
    plan.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    desktop, bell, prefix = _ui_patches()

    with (
        _respond_after_gate_creation("epic", input_data={"epic_launch_mode": "skip"}),
        desktop,
        bell,
        prefix,
    ):
        result = handle_plan_approval(str(plan), "host-owned-epic")

    assert result is not None
    assert result.action == "epic"
    assert result.epic_launch_owner == "host"


@pytest.mark.parametrize(
    ("keyword", "value", "action_data_key"),
    [
        ("agent_runtime", "4m32s", "runtime"),
        ("agent_vcs_tag", "#gh:sase ", "agent_vcs_tag"),
    ],
)
def test_handle_plan_approval_forwards_agent_metadata(
    keyword: str,
    value: str,
    action_data_key: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    captured: dict[str, Any] = {}
    desktop, bell, prefix = _ui_patches()

    with (
        _respond_after_gate_creation("approve", captured=captured),
        desktop,
        bell,
        prefix,
    ):
        result = handle_plan_approval(str(plan), "session", **{keyword: value})

    assert result is not None
    action_data = captured["request"]["presentation"]["action_data"]
    assert action_data[action_data_key] == value


def test_handle_plan_approval_passes_agent_routing_timestamps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    monkeypatch.setenv("SASE_AGENT_TIMESTAMP", "20260512094333")
    monkeypatch.setenv("SASE_AGENT_ROOT_TIMESTAMP", "20260512090000")
    captured: dict[str, Any] = {}
    desktop, bell, prefix = _ui_patches()

    with (
        _respond_after_gate_creation("approve", captured=captured),
        desktop,
        bell,
        prefix,
    ):
        result = handle_plan_approval(str(plan), "session")

    assert result is not None
    action_data = captured["request"]["presentation"]["action_data"]
    assert action_data["agent_timestamp"] == "20260512094333"
    assert action_data["agent_root_timestamp"] == "20260512090000"


def test_handle_plan_approval_none_plan_file() -> None:
    assert handle_plan_approval(None, "session-123") is None


def test_handle_plan_approval_approve_with_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Custom approval fields survive the neutral command boundary."""
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    desktop, bell, prefix = _ui_patches()

    with (
        _respond_after_gate_creation(
            "approve",
            input_data={
                "commit_plan": False,
                "run_coder": True,
                "coder_prompt": "  #review+  ",
            },
        ),
        desktop,
        bell,
        prefix,
    ):
        result = handle_plan_approval(str(plan), "test-options-session")

    assert result is not None
    assert result.action == "approve"
    assert result.commit_plan is False
    assert result.run_coder is True
    assert result.coder_prompt == "#review+"
