"""Golden tests for marker handling and the current exec-loop seam."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sase.axe.run_agent_exec import run_execution_loop
from sase.axe.run_agent_exec_plan import handle_plan_marker
from tests._axe_run_agent_exec_helpers import make_exec_ctx
from tests._axe_run_agent_exec_plan_helpers import make_ctx, make_state


def test_handle_plan_marker_returns_killed_when_poll_exits_after_kill(
    tmp_path: Path,
) -> None:
    ctx = make_ctx(tmp_path)
    state = make_state(tmp_path)
    plan_file = tmp_path / "plan.md"
    plan_file.write_text("# Plan\n", encoding="utf-8")

    with (
        patch("sase.axe.run_agent_exec_plan.normalize_handoff_interruption_state"),
        patch("sase.axe.run_agent_exec_plan.finalize_handoff_artifacts_as_completed"),
        patch("sase.axe.run_agent_exec_plan.update_meta_suffix"),
        patch("sase.axe.run_agent_exec_plan.record_workflow_metadata"),
        patch(
            "sase.axe.run_agent_exec_plan.format_agent_run_runtime", return_value="1s"
        ),
        patch("sase.axe.run_agent_exec_plan.reset_killed"),
        patch("sase.axe.run_agent_exec_plan.was_killed", return_value=True),
        patch("sase.llm_provider._plan_utils.handle_plan_approval", return_value=None),
    ):
        outcome = handle_plan_marker({"plan_file": str(plan_file)}, ctx, state)

    assert outcome == "killed"


def test_normally_completing_followup_breaks_exec_loop_without_post_coder_seam(
    tmp_path: Path,
) -> None:
    ctx = make_exec_ctx(tmp_path, is_home_mode=False)
    executed_prompts: list[str] = []

    def execute_workflow(
        _name: str,
        _args: list[object],
        _kwargs: dict[str, object],
        *,
        workflow_obj: object,
        **_extra: object,
    ) -> MagicMock:
        executed_prompts.append(workflow_obj.steps[0].agent)
        return MagicMock(name=f"workflow-result-{len(executed_prompts)}")

    def first_kill_creates_coder_prompt(_ctx: object, state: object) -> None:
        state.current_prompt = "coder prompt"
        state.current_role_suffix = "--code"
        state.agent_step = 2
        return None

    with (
        patch(
            "sase.xprompt.workflow_runner.execute_workflow",
            side_effect=execute_workflow,
        ),
        patch("sase.axe.run_agent_exec.reset_killed"),
        patch("sase.axe.run_agent_exec.was_killed", side_effect=[True, False]),
        patch(
            "sase.axe.run_agent_exec._handle_killed_iteration",
            side_effect=first_kill_creates_coder_prompt,
        ) as handoff,
        patch(
            "sase.axe.run_agent_exec._finalize_loop", return_value="final"
        ) as finalize,
    ):
        result = run_execution_loop(ctx, "planner prompt")

    assert result == "final"
    assert executed_prompts == ["planner prompt", "coder prompt"]
    handoff.assert_called_once()
    finalize.assert_called_once()


@pytest.mark.parametrize("auto_action", ["legend", "commit"])
def test_auto_plan_action_rejects_legend_and_commit_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auto_action: str,
) -> None:
    from sase.main.plan_approve_handler import get_auto_plan_approval_action

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    (artifacts / "agent_meta.json").write_text(
        f'{{"auto_approve_plan_action": "{auto_action}"}}',
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(artifacts))
    monkeypatch.setenv("SASE_AGENT_AUTO_APPROVE_PLAN_ACTION", auto_action)

    assert get_auto_plan_approval_action() is None
