"""Tests for monitor marker adoption in the agent execution loop."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from sase.axe.run_agent_exec import LoopState
from sase.axe.run_agent_exec_monitor import handle_monitor_marker

from tests._axe_run_agent_exec_helpers import make_exec_ctx


def _state(artifacts_dir: Path) -> LoopState:
    return LoopState(
        current_prompt="Run a slow verification.",
        current_role_suffix="",
        current_artifacts_dir=str(artifacts_dir),
        loop_outcome="completed",
        sdd_spec_path=None,
        original_prompt="Run a slow verification.",
    )


def test_handle_monitor_marker_saves_starter_chat_and_relationships(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    (artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent--0",
                "workflow_name": "agent",
                "agent_family": "agent",
                "role_suffix": "--0",
                "model": "sonnet",
                "llm_provider": "claude",
            }
        ),
        encoding="utf-8",
    )
    (artifacts / "workflow_state.json").write_text(
        json.dumps(
            {
                "status": "failed",
                "steps": [
                    {
                        "status": "failed",
                        "step_type": "agent",
                        "error": "SIGTERM",
                        "traceback": "trace",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monitor_artifacts = tmp_path / "monitor"
    monitor_artifacts.mkdir()
    (monitor_artifacts / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "agent--mon",
                "monitor_id": "m123",
                "monitor_command": "just check-full",
                "monitor_cwd": str(tmp_path),
                "monitor_reason": "verify before handoff",
                "monitor_next_action": "Fix any failures.",
            }
        ),
        encoding="utf-8",
    )

    captured: dict[str, object] = {}

    def capture_chat(**kwargs: object) -> str:
        captured.update(kwargs)
        return str(tmp_path / "starter-chat.md")

    with (
        patch(
            "sase.axe.run_agent_exec_monitor.save_chat_history",
            side_effect=capture_chat,
        ),
        patch(
            "sase.axe.run_agent_exec_monitor.format_extra_sections",
            return_value="",
        ),
    ):
        outcome = handle_monitor_marker(
            {
                "monitor_id": "m123",
                "member_artifacts_dir": str(monitor_artifacts),
                "member_agent_name": "agent--mon",
                "timestamp": 99.0,
            },
            ctx,
            _state(artifacts),
        )

    assert outcome == "monitored"
    assert captured["agent"] == "agent--0"
    assert captured["metadata_agent"] == "agent--0"
    response = str(captured["response"])
    assert "sase monitor show m123" in response
    assert "just check-full" in response
    assert "verify before handoff" in response
    assert "Fix any failures." in response

    starter_meta = json.loads((artifacts / "agent_meta.json").read_text())
    assert starter_meta["monitor_id"] == "m123"
    assert starter_meta["monitor_member_agent_name"] == "agent--mon"
    assert starter_meta["chat_path"] == str(tmp_path / "starter-chat.md")

    monitor_meta = json.loads((monitor_artifacts / "agent_meta.json").read_text())
    assert monitor_meta["monitor_starter_agent"] == "agent--0"

    workflow_state = json.loads((artifacts / "workflow_state.json").read_text())
    assert workflow_state["status"] == "completed"
    assert workflow_state["steps"][0]["status"] == "completed"
    assert workflow_state["steps"][0]["error"] is None


def test_handle_monitor_marker_tracks_promoted_suffix_in_loop_state(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    artifacts = Path(ctx.artifacts_dir)
    (artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "agent--0", "workflow_name": "agent"}),
        encoding="utf-8",
    )
    monitor_artifacts = tmp_path / "monitor"
    monitor_artifacts.mkdir()
    (monitor_artifacts / "agent_meta.json").write_text(
        json.dumps({"name": "agent--mon", "monitor_id": "m123"}),
        encoding="utf-8",
    )
    state = _state(artifacts)

    with (
        patch(
            "sase.axe.run_agent_exec_monitor.save_chat_history",
            return_value=str(tmp_path / "starter-chat.md"),
        ),
        patch(
            "sase.axe.run_agent_exec_monitor.format_extra_sections",
            return_value="",
        ),
    ):
        handle_monitor_marker(
            {
                "monitor_id": "m123",
                "member_artifacts_dir": str(monitor_artifacts),
                "member_agent_name": "agent--mon",
                "timestamp": 99.0,
            },
            ctx,
            state,
        )

    assert state.current_role_suffix == "--0"
    assert state.agent_step == 2
    assert state.saved_chat_paths == [
        ("--0", str(tmp_path / "starter-chat.md")),
    ]
