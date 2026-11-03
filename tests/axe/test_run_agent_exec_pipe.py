"""Tests for staged pipe adoption."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from tests._staged_handoff_adoption import handle_pipe_marker
from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state


def _pipe_data(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "prompt": "continue from here",
        "reason": "hand off",
        "model": None,
        "name_token": None,
        "fresh": False,
        "pipe_depth": 0,
        "timestamp": 1.0,
    }
    payload.update(overrides)
    return payload


def test_handle_staged_pipe_marker_keeps_real_response(tmp_path: Path) -> None:
    from sase.axe.run_agent_exec_pipe import handle_staged_pipe_marker

    ctx = replace(make_ctx(tmp_path), agent_name=None)
    state = make_state(tmp_path)
    save_chat = Mock(return_value="/tmp/parent.md")

    with (
        patch(
            "sase.axe.run_agent_exec_pipe_handoff.finalize_handoff_artifacts_as_completed"
        ),
        patch("sase.axe.run_agent_exec_pipe_handoff.save_chat_history", save_chat),
        patch("sase.axe.run_agent_exec_pipe_handoff.update_meta_field"),
        patch("sase.axe.run_agent_exec_pipe_handoff.update_step_marker_chat_path"),
        patch(
            "sase.axe.run_agent_exec_pipe_staged.allocate_agent_session_child_suffix",
            return_value="--1",
        ),
        patch(
            "sase.axe.run_agent_exec_pipe_staged.reserve_launch_timestamp_batch",
            return_value=["20261031010101"],
        ),
        patch(
            "sase.artifacts.launch_artifacts_dir",
            return_value="/tmp/pipe-followup",
        ),
        patch(
            "sase.axe.run_agent_exec_pipe_handoff.create_followup_artifacts",
            return_value="/tmp/pipe-followup",
        ),
        patch("sase.axe.run_agent_exec_pipe_handoff.promote_to_workflow"),
        patch("sase.axe.run_agent_exec_pipe_handoff._store_followup_prompt_artifact"),
    ):
        outcome = handle_staged_pipe_marker(
            _pipe_data(),
            ctx,
            state,
            provider_response="The model's actual final response.",
            staged_id="test-staged-id",
        )

    assert outcome is None
    assert save_chat.call_args.kwargs["response"] == (
        "The model's actual final response."
    )
    assert "## Pipe Hand-off" in (save_chat.call_args.kwargs["extra_sections"] or "")


def test_staged_pipe_two_hops_reserve_unique_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    from sase.agent._agent_session_attach_types import (
        AgentSessionAttachDirective,
        AgentSessionAttachLaunchPlan,
    )

    def _fake_attach_plan(
        directive: AgentSessionAttachDirective, **_kwargs: object
    ) -> AgentSessionAttachLaunchPlan:
        agent_name = f"{directive.parent}{directive.suffix}"
        return AgentSessionAttachLaunchPlan(
            parent_arg=directive.parent,
            suffix_arg=directive.suffix,
            parent_name=directive.parent,
            parent_base=directive.parent,
            parent_timestamp="20260820161407",
            parent_artifacts_dir=str(tmp_path / "artifacts"),
            role_suffix=directive.suffix,
            agent_name=agent_name,
            agent_session_role="feedback",
            parent_agent_session_member_name=directive.parent,
            parent_agent_session_role_suffix="",
            parent_needs_rename=False,
            parent_project_name="test_proj",
            parent_is_running=True,
        )

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(
        "sase.core.time.generate_timestamp",
        lambda: "260820_161407",
    )
    monkeypatch.setattr(
        "sase.agent._agent_session_attach_resolution.resolve_agent_session_attach_plan",
        _fake_attach_plan,
    )
    ctx = make_ctx(tmp_path)
    ctx.agent_meta.update(
        {
            "name": "test_agent",
            "model": "fakey-large",
            "llm_provider": "fakey",
            "workspace_dir": str(tmp_path),
        }
    )
    state = make_state(tmp_path)
    parent_dir = Path(state.current_artifacts_dir)
    (parent_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "test_agent",
                "model": "fakey-large",
                "llm_provider": "fakey",
                "workspace_dir": str(tmp_path),
                "workspace_num": 1,
            }
        ),
        encoding="utf-8",
    )

    with (
        patch(
            "sase.axe.run_agent_exec_pipe_handoff.finalize_handoff_artifacts_as_completed"
        ),
        patch(
            "sase.axe.run_agent_exec_pipe_handoff.save_chat_history",
            side_effect=["/tmp/parent.md", "/tmp/first.md"],
        ),
        patch("sase.axe.run_agent_exec_pipe_handoff.update_step_marker_chat_path"),
    ):
        assert (
            handle_pipe_marker(
                _pipe_data(prompt="first handoff"),
                ctx,
                state,
                provider_response="first response",
                staged_id="test-staged-1",
            )
            is None
        )
        first_dir = Path(state.current_artifacts_dir)
        assert (
            handle_pipe_marker(
                _pipe_data(prompt="second handoff", pipe_depth=1),
                ctx,
                state,
                provider_response="second response",
                staged_id="test-staged-2",
            )
            is None
        )
        second_dir = Path(state.current_artifacts_dir)

    first_meta = json.loads((first_dir / "agent_meta.json").read_text())
    second_meta = json.loads((second_dir / "agent_meta.json").read_text())
    first_prompt = (first_dir / "followup_prompt.md").read_text(encoding="utf-8")
    second_prompt = (second_dir / "followup_prompt.md").read_text(encoding="utf-8")

    assert first_dir != second_dir
    assert first_dir.name == "20260820161407"
    assert second_dir.name == "20260820161408"

    assert first_meta["name"] == "test_agent--1"
    assert first_meta["piped_from"] == "test_agent"
    assert first_meta["pipe_depth"] == 1
    assert first_meta["agent_session"] == "test_agent"
    assert "agent_family" not in first_meta
    assert first_meta["workspace_dir"] == str(tmp_path)
    assert first_meta["workspace_num"] == 1
    assert first_prompt.startswith("#fork:test_agent\n")
    assert first_prompt.endswith("first handoff")

    assert second_meta["name"] == "test_agent--2"
    assert second_meta["piped_from"] == "test_agent--1"
    assert second_meta["pipe_depth"] == 2
    assert second_meta["agent_session"] == "test_agent"
    assert "agent_family" not in second_meta
    assert second_meta["workspace_dir"] == str(tmp_path)
    assert second_meta["workspace_num"] == 1
    assert second_prompt.startswith("#fork:test_agent--1\n")
    assert second_prompt.endswith("second handoff")
