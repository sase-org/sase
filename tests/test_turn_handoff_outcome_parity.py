"""Parity guards for shell handoff loop outcomes."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.axe.run_agent_exec import LoopState
from sase.axe.run_agent_exec_finalize import _COMPLETED_MARKER_LOOP_OUTCOMES
from sase.axe.run_agent_exec_gate import handle_gate_marker
from sase.axe.run_agent_exec_monitor import handle_monitor_marker
from sase.axe.run_agent_runner_finalize import (
    _COMPLETION_NOTIFICATION_SUPPRESSED_OUTCOMES,
)
from sase.core.dismissed_agent_completion import SHELL_HANDOFF_OUTCOMES

from tests._axe_run_agent_exec_helpers import make_exec_ctx


def _state(artifacts_dir: Path) -> LoopState:
    return LoopState(
        current_prompt="handoff",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts_dir),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="handoff",
    )


def _prepare_case(root: Path) -> tuple[object, Path, Path]:
    root.mkdir()
    ctx = make_exec_ctx(root, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "agent--0", "workflow_name": "agent"}),
        encoding="utf-8",
    )
    member_artifacts = root / "member"
    member_artifacts.mkdir()
    return ctx, artifacts, member_artifacts


def test_marker_handler_outcomes_are_registered_shell_handoffs(
    tmp_path: Path,
) -> None:
    monitor_ctx, monitor_artifacts, monitor_member = _prepare_case(tmp_path / "mon")
    (monitor_member / "agent_meta.json").write_text(
        json.dumps({"name": "agent--mon", "monitor_id": "m1"}),
        encoding="utf-8",
    )
    gate_ctx, gate_artifacts, gate_member = _prepare_case(tmp_path / "gate")
    (gate_member / "agent_meta.json").write_text(
        json.dumps({"name": "agent--gate", "gate_id": "g1"}),
        encoding="utf-8",
    )

    with (
        patch(
            "sase.axe.run_agent_exec_monitor.save_chat_history",
            return_value=str(tmp_path / "monitor-chat.md"),
        ),
        patch(
            "sase.axe.run_agent_exec_monitor.format_extra_sections",
            return_value="",
        ),
        patch(
            "sase.axe.run_agent_exec_gate.save_chat_history",
            return_value=str(tmp_path / "gate-chat.md"),
        ),
        patch("sase.axe.run_agent_exec_gate.format_extra_sections", return_value=""),
    ):
        outcomes = {
            handle_monitor_marker(
                {
                    "monitor_id": "m1",
                    "member_artifacts_dir": str(monitor_member),
                    "member_agent_name": "agent--mon",
                },
                monitor_ctx,
                _state(monitor_artifacts),
            ),
            handle_gate_marker(
                {
                    "gate_id": "g1",
                    "member_artifacts_dir": str(gate_member),
                    "member_agent_name": "agent--gate",
                },
                gate_ctx,
                _state(gate_artifacts),
            ),
        }

    assert outcomes == SHELL_HANDOFF_OUTCOMES


def test_shell_handoff_outcomes_are_suppressed_and_write_completed_markers() -> None:
    assert SHELL_HANDOFF_OUTCOMES <= _COMPLETION_NOTIFICATION_SUPPRESSED_OUTCOMES
    assert SHELL_HANDOFF_OUTCOMES <= _COMPLETED_MARKER_LOOP_OUTCOMES
