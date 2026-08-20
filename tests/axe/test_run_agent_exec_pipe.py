"""Tests for runner adoption of ``.sase_pipe_pending``."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

from sase.axe.run_agent_exec_pipe import handle_pipe_marker
from sase.axe.run_agent_successor import FollowupModel
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


def test_handle_pipe_marker_default_suffix_and_fork(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    create = Mock(return_value="/tmp/pipe-followup")
    store = Mock()
    save_chat = Mock(return_value="/tmp/parent.md")
    allocate = Mock(return_value="--1")

    with (
        patch("sase.axe.run_agent_exec_pipe.normalize_handoff_interruption_state"),
        patch("sase.axe.run_agent_exec_pipe.finalize_handoff_artifacts_as_completed"),
        patch("sase.axe.run_agent_exec_pipe.save_chat_history", save_chat),
        patch("sase.axe.run_agent_exec_pipe.update_meta_field"),
        patch("sase.axe.run_agent_exec_pipe.update_step_marker_chat_path"),
        patch(
            "sase.axe.run_agent_exec_pipe.allocate_agent_family_child_suffix",
            allocate,
        ),
        patch("sase.axe.run_agent_exec_pipe.create_followup_artifacts", create),
        patch("sase.axe.run_agent_exec_pipe.promote_to_workflow"),
        patch(
            "sase.axe.run_agent_exec_pipe._store_followup_prompt_artifact",
            store,
        ),
        patch("sase.axe.run_agent_exec_pipe.reset_killed") as reset,
    ):
        outcome = handle_pipe_marker(_pipe_data(), ctx, state)

    assert outcome is None
    assert state.current_role_suffix == "--1"
    assert state.current_prompt == "#fork:test_agent\ncontinue from here"
    assert create.call_args.kwargs["agent_name_override"] == "test_agent--1"
    assert create.call_args.kwargs["agent_family_role"] == "feedback"
    assert create.call_args.kwargs["relationships"]["pipe_depth"] == 1
    assert create.call_args.kwargs["relationships"]["piped_from"] == "test_agent"
    assert create.call_args.kwargs["relationships"]["pipe_reason"] == "hand off"
    store.assert_called_once_with(
        "/tmp/pipe-followup",
        "#fork:test_agent\ncontinue from here",
        label="Piped prompt",
    )
    assert save_chat.call_args.kwargs["agent"] == "test_agent"
    assert "# Pipe hand-off" in save_chat.call_args.kwargs["response"]
    assert "test_agent--1" in save_chat.call_args.kwargs["response"]
    reset.assert_called_once()
    allocate.assert_called_once()


def test_handle_pipe_marker_saves_parent_chat_before_successor(
    tmp_path: Path,
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    order: list[str] = []

    def save_chat(**_kwargs: object) -> str:
        order.append("chat")
        return "/tmp/parent.md"

    def create(*_args: object, **_kwargs: object) -> str:
        order.append("successor")
        return "/tmp/pipe-followup"

    with (
        patch("sase.axe.run_agent_exec_pipe.normalize_handoff_interruption_state"),
        patch("sase.axe.run_agent_exec_pipe.finalize_handoff_artifacts_as_completed"),
        patch("sase.axe.run_agent_exec_pipe.save_chat_history", side_effect=save_chat),
        patch("sase.axe.run_agent_exec_pipe.update_meta_field"),
        patch("sase.axe.run_agent_exec_pipe.update_step_marker_chat_path"),
        patch(
            "sase.axe.run_agent_exec_pipe.allocate_agent_family_child_suffix",
            return_value="--1",
        ),
        patch("sase.axe.run_agent_exec_pipe.create_followup_artifacts", create),
        patch("sase.axe.run_agent_exec_pipe.promote_to_workflow"),
        patch("sase.axe.run_agent_exec_pipe._store_followup_prompt_artifact"),
        patch("sase.axe.run_agent_exec_pipe.reset_killed"),
    ):
        handle_pipe_marker(_pipe_data(), ctx, state)

    assert order == ["chat", "successor"]


def test_repeated_default_pipe_transitions_reserve_unique_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    monkeypatch.setattr(
        "sase.core.time.generate_timestamp",
        lambda: "260820_161407",
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
        patch("sase.axe.run_agent_exec_pipe.normalize_handoff_interruption_state"),
        patch("sase.axe.run_agent_exec_pipe.finalize_handoff_artifacts_as_completed"),
        patch(
            "sase.axe.run_agent_exec_pipe.save_chat_history",
            side_effect=["/tmp/parent.md", "/tmp/first.md"],
        ),
        patch("sase.axe.run_agent_exec_pipe.update_step_marker_chat_path"),
        patch("sase.axe.run_agent_exec_pipe.reset_killed"),
    ):
        assert (
            handle_pipe_marker(_pipe_data(prompt="first handoff"), ctx, state) is None
        )
        first_dir = Path(state.current_artifacts_dir)
        assert (
            handle_pipe_marker(
                _pipe_data(prompt="second handoff", pipe_depth=1),
                ctx,
                state,
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
    assert first_meta["agent_family"] == "test_agent"
    assert first_meta["workspace_dir"] == str(tmp_path)
    assert first_meta["workspace_num"] == 1
    assert first_prompt.startswith("#fork:test_agent\n")
    assert first_prompt.endswith("first handoff")

    assert second_meta["name"] == "test_agent--2"
    assert second_meta["piped_from"] == "test_agent--1"
    assert second_meta["pipe_depth"] == 2
    assert second_meta["agent_family"] == "test_agent"
    assert second_meta["workspace_dir"] == str(tmp_path)
    assert second_meta["workspace_num"] == 1
    assert second_prompt.startswith("#fork:test_agent--1\n")
    assert second_prompt.endswith("second handoff")


def test_handle_pipe_marker_explicit_name_fresh_and_model(tmp_path: Path) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    create = Mock(return_value="/tmp/pipe-followup")
    followup = FollowupModel(
        model_prefix="%model:opus\n",
        meta=("claude", "opus"),
        model_alias="opus",
    )
    write_model = Mock()

    with (
        patch("sase.axe.run_agent_exec_pipe.normalize_handoff_interruption_state"),
        patch("sase.axe.run_agent_exec_pipe.finalize_handoff_artifacts_as_completed"),
        patch(
            "sase.axe.run_agent_exec_pipe.save_chat_history",
            return_value="/tmp/parent.md",
        ),
        patch("sase.axe.run_agent_exec_pipe.update_meta_field"),
        patch("sase.axe.run_agent_exec_pipe.update_step_marker_chat_path"),
        patch(
            "sase.axe.run_agent_exec_pipe._resolve_pipe_model",
            return_value=followup,
        ),
        patch("sase.axe.run_agent_exec_pipe.create_followup_artifacts", create),
        patch("sase.axe.run_agent_exec_pipe.promote_to_workflow"),
        patch("sase.axe.run_agent_exec_pipe._store_followup_prompt_artifact"),
        patch(
            "sase.axe.run_agent_successor.write_followup_model_meta",
            write_model,
        ),
        patch("sase.axe.run_agent_exec_pipe.reset_killed"),
    ):
        handle_pipe_marker(
            _pipe_data(name_token="review", fresh=True, model="opus", pipe_depth=2),
            ctx,
            state,
        )

    assert state.current_role_suffix == "--review"
    assert state.current_prompt == "%model:opus\ncontinue from here"
    assert "#fork:" not in state.current_prompt
    assert create.call_args.kwargs["agent_name_override"] == "test_agent--review"
    assert create.call_args.kwargs["agent_family_role"] == "review"
    assert create.call_args.kwargs["relationships"]["pipe_depth"] == 3
    write_model.assert_called_once()
    assert write_model.call_args.args[1] is followup
