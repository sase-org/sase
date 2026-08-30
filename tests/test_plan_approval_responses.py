"""Tests for neutral plan approval response projection.

``plan_approval_result_from_gate_response`` is the single implementation that
projects a settled plan gate's response back into the runner's
``PlanApprovalResult`` contract, used both by ``plan_shell.followup`` (the
gate-shell path) and, historically, by the deleted blocking
``handle_plan_approval`` wait loop. These tests drive it directly: build a
real gate spec, execute a host response against it exactly as
``execute_gate_selection`` would, then project that response.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from sase.llm_provider._plan_utils import (
    PlanApprovalResult,
    plan_approval_result_from_gate_response,
)
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.service import create_gate
from sase.plan_gate import build_plan_approval_gate_spec

from tests.conftest import redirect_sase_home
from tests.plan_validation_helpers import VALID_EPIC_PLAN, VALID_TALE_PLAN


def _approve(
    plan_file: str,
    session_id: str,
    choice: str,
    *,
    input_data: dict[str, Any] | None = None,
    captured: dict[str, Any] | None = None,
    **gate_kwargs: Any,
) -> Any:
    """Create a plan gate, execute a host response, and project the result.

    Mirrors what the deleted ``handle_plan_approval`` did end to end, minus
    its own notification/polling machinery (now owned by
    ``plan_shell.create_plan_gate_shell``, tested separately).
    """
    spec = build_plan_approval_gate_spec(plan_file, session_id, **gate_kwargs)
    gate = create_gate(spec)
    if captured is not None:
        captured["gate"] = gate
        captured["request"] = json.loads(gate.request_path.read_text(encoding="utf-8"))
    plan = Path(plan_file).expanduser()
    saved = plan.parent / "sdd" / "plans" / "202608" / plan.name

    def archive(*_args: object, **_kwargs: object) -> Any:
        saved.parent.mkdir(parents=True)
        saved.write_text(plan.read_text(encoding="utf-8"), encoding="utf-8")
        from sase._plan_archive_approval import _ApprovedPlanArchive

        return _ApprovedPlanArchive(saved, f"plan:202608/{plan.name}")

    with patch(
        "sase.plan_approval_actions._archive_plan_for_approval",
        side_effect=archive,
    ):
        execution = execute_gate_selection(
            gate.bundle_path,
            ["approve" if choice == "epic" else choice],
            input_data or {},
            source="test_host",
        )
    return plan_approval_result_from_gate_response(gate.bundle_path, execution.response)


def test_handle_plan_approval_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The neutral commit command maps back to the runner's no-coder result."""
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")

    result = _approve(str(plan), "test-commit-session", "commit")

    assert result == PlanApprovalResult(
        action="approve",
        plan_file=str(plan),
        commit_plan=True,
        run_coder=False,
        saved_plan_path=str(tmp_path / "sdd" / "plans" / "202608" / "plan.md"),
    )
    assert result.plan_archive_protocol == "host_v2"
    assert result.plan_archive_ref == "plan:202608/plan.md"


def test_handle_plan_approval_threads_saved_plan_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    saved = str(tmp_path / "sdd" / "plans" / "202608" / "plan.md")
    from sase.plan_gate import translate_plan_gate_response as real_translate

    def translate(bundle_path: Path, payload: Any) -> dict[str, Any]:
        data = real_translate(bundle_path, payload)
        data["saved_plan_path"] = saved
        return data

    with patch("sase.plan_gate.translate_plan_gate_response", side_effect=translate):
        result = _approve(str(plan), "saved-path-session", "commit")

    assert result is not None
    assert result.saved_plan_path == saved


def test_handle_plan_approval_reads_host_epic_launch_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = tmp_path / "epic.md"
    plan.write_text(VALID_EPIC_PLAN, encoding="utf-8")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")

    result = _approve(
        str(plan),
        "host-owned-epic",
        "epic",
        input_data={"epic_launch_mode": "skip"},
    )

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

    result = _approve(
        str(plan),
        "session",
        "approve",
        captured=captured,
        **{keyword: value},
    )

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

    result = _approve(str(plan), "session", "approve", captured=captured)

    assert result is not None
    action_data = captured["request"]["presentation"]["action_data"]
    assert action_data["agent_timestamp"] == "20260512094333"
    assert action_data["agent_root_timestamp"] == "20260512090000"


def test_handle_plan_approval_approve_with_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Custom approval fields survive the neutral command boundary."""
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")

    result = _approve(
        str(plan),
        "test-options-session",
        "approve",
        input_data={"coder_prompt": "  #review+  "},
    )

    assert result is not None
    assert result.action == "approve"
    assert result.commit_plan is False
    assert result.run_coder is True
    assert result.coder_prompt == "#review+"
    assert result.wait_agents == ()
    assert result.wait_beads == ()


def _approve_with_translated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    extra: dict[str, Any],
) -> PlanApprovalResult | None:
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")
    from sase.plan_gate import translate_plan_gate_response as real_translate

    def translate(bundle_path: Path, payload: Any) -> dict[str, Any]:
        data = real_translate(bundle_path, payload)
        data.update(extra)
        return data

    with patch("sase.plan_gate.translate_plan_gate_response", side_effect=translate):
        return _approve(str(plan), "wait-fields-session", "approve")


def test_handle_plan_approval_parses_wait_input_into_result_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = tmp_path / "plan.md"
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    redirect_sase_home(monkeypatch, tmp_path / ".sase")

    result = _approve(
        str(plan),
        "wait-input-session",
        "approve",
        input_data={"wait": "sase-s7.2,bead=sase-64.3"},
    )

    assert result is not None
    assert result.wait_agents == ("sase-s7.2",)
    assert result.wait_beads == ("sase-64.3",)


def test_handle_plan_approval_reads_wait_agents_and_beads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = _approve_with_translated(
        tmp_path,
        monkeypatch,
        {
            "wait_agents": ["sase-s7.2", "sase-vs.1"],
            "wait_beads": ["sase-64.3"],
        },
    )

    assert result is not None
    assert result.wait_agents == ("sase-s7.2", "sase-vs.1")
    assert result.wait_beads == ("sase-64.3",)


@pytest.mark.parametrize(
    ("extra", "expected_agents", "expected_beads"),
    [
        ({"wait_agents": ["sase-s7.2"]}, ("sase-s7.2",), ()),
        ({"wait_beads": ["sase-64.3"]}, (), ("sase-64.3",)),
        ({"wait_agents": [], "wait_beads": []}, (), ()),
        ({"wait_agents": "sase-s7.2", "wait_beads": "sase-64.3"}, (), ()),
        ({"wait_agents": [""], "wait_beads": ["sase-64.3"]}, (), ("sase-64.3",)),
        ({"wait_agents": ["sase-s7.2"], "wait_beads": [""]}, ("sase-s7.2",), ()),
        ({"wait_agents": [1], "wait_beads": ["sase-64.3"]}, (), ("sase-64.3",)),
        ({"wait_agents": ["sase-s7.2"], "wait_beads": [None]}, ("sase-s7.2",), ()),
        ({"wait_agents": ("sase-s7.2",), "wait_beads": ("sase-64.3",)}, (), ()),
    ],
)
def test_handle_plan_approval_accepts_only_nonempty_string_wait_lists(
    extra: dict[str, Any],
    expected_agents: tuple[str, ...],
    expected_beads: tuple[str, ...],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _approve_with_translated(tmp_path, monkeypatch, extra)

    assert result is not None
    assert result.wait_agents == expected_agents
    assert result.wait_beads == expected_beads
