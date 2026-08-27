"""Plan gate shell follow-up prompt rebuild tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sase.axe.run_agent_exec_plan_accept import _AcceptedPlanPreparation
from sase.axe.run_agent_successor import SuccessorRequest
from sase.main.qa_markdown import QARound
from sase.plan_chain import PLAN_CHAIN_PLAN_SUFFIX
from sase.plan_shell.followup import (
    _plan_feedback_bullets,
    _plan_original_prompt,
    plan_next_action,
)
from tests.plan_validation_helpers import VALID_TALE_PLAN


def _write_feedback_shell(
    root: Path,
    name: str,
    feedback: str,
    *,
    prev: Path | None = None,
    original_prompt: str | None = None,
    qa_rounds: list[QARound] | None = None,
) -> tuple[Path, dict[str, Any]]:
    artifacts = root / f"{name}-artifacts"
    bundle = root / f"{name}-bundle"
    plan = root / f"{name}.md"
    artifacts.mkdir()
    bundle.mkdir()
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    (bundle / "request.json").write_text(
        json.dumps(
            {
                "kind": "plan",
                "payload": {
                    "original_plan_file": str(plan),
                    "plan_resource": "plan.md",
                },
            }
        ),
        encoding="utf-8",
    )
    response = {
        "selected_option_ids": ["feedback"],
        "feedback": feedback,
        "option_results": [
            {"id": "feedback", "result": {"action": "reject", "feedback": feedback}}
        ],
    }
    (bundle / "response.json").write_text(json.dumps(response), encoding="utf-8")
    meta: dict[str, Any] = {
        "gate_bundle_path": str(bundle),
        "gate_kind": "plan",
        "agent_family": "agent",
    }
    if prev is not None:
        meta["plan_shell_prev_artifacts_dir"] = str(prev)
    if original_prompt is not None:
        path = artifacts / "plan_shell_original_prompt.md"
        path.write_text(original_prompt, encoding="utf-8")
        meta["plan_shell_original_prompt_path"] = str(path)
    if qa_rounds is not None:
        qa_path = artifacts / "plan_shell_qa_rounds.json"
        qa_path.write_text(
            json.dumps(
                [
                    {
                        "questions": round_.questions,
                        "answers": round_.answers,
                        "global_note": round_.global_note,
                    }
                    for round_ in qa_rounds
                ]
            ),
            encoding="utf-8",
        )
        meta["plan_shell_qa_rounds_path"] = str(qa_path)
    (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    return artifacts, response


def test_feedback_bullets_walk_settled_plan_shell_chain(tmp_path: Path) -> None:
    first, _ = _write_feedback_shell(
        tmp_path,
        "first",
        "Tighten the migration scope.",
        original_prompt="Build it.",
    )
    second, head_response = _write_feedback_shell(
        tmp_path,
        "second",
        "Add regression coverage.",
        prev=first,
    )

    assert _plan_feedback_bullets(str(second), head_response=head_response) == [
        "Tighten the migration scope.",
        "Add regression coverage.",
    ]
    assert _plan_original_prompt(str(second)) == "Build it."


def test_feedback_next_action_rebuilds_original_prompt_with_all_feedback(
    tmp_path: Path,
) -> None:
    first, _ = _write_feedback_shell(
        tmp_path,
        "first",
        "Keep the old flag-off path.",
        original_prompt="Implement the migration.",
    )
    qa_round = QARound(
        questions=[{"question": "Which path?", "options": [{"label": "Shell"}]}],
        answers=[{"question": "Which path?", "selected": ["Shell"]}],
    )
    second, head_response = _write_feedback_shell(
        tmp_path,
        "second",
        "Include auto approval coverage.",
        prev=first,
        qa_rounds=[qa_round],
    )
    meta = json.loads((second / "agent_meta.json").read_text(encoding="utf-8"))

    prompt = plan_next_action(
        artifacts_dir=str(second),
        meta=meta,
        envelope={},
        response=head_response,
        declared="fallback",
    )

    assert prompt is not None
    assert prompt.startswith("Implement the migration.")
    assert "### Questions and Answers" in prompt
    assert "- Keep the old flag-off path." in prompt
    assert "- Include auto approval coverage." in prompt


def test_accepted_tale_next_action_uses_shared_successor_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts = tmp_path / "artifacts"
    bundle = tmp_path / "bundle"
    plan = tmp_path / "plan.md"
    artifacts.mkdir()
    bundle.mkdir()
    plan.write_text(VALID_TALE_PLAN, encoding="utf-8")
    current_prompt = artifacts / "plan_shell_current_prompt.md"
    original_prompt = artifacts / "plan_shell_original_prompt.md"
    current_prompt.write_text("Planner prompt", encoding="utf-8")
    original_prompt.write_text("Original prompt", encoding="utf-8")
    (bundle / "request.json").write_text(
        json.dumps(
            {
                "kind": "plan",
                "payload": {
                    "original_plan_file": str(plan),
                    "plan_resource": "plan.md",
                },
            }
        ),
        encoding="utf-8",
    )
    response = {
        "selected_option_ids": ["approve", "commit"],
        "feedback": None,
        "option_results": [
            {
                "id": "approve",
                "result": {
                    "action": "approve",
                    "commit_plan": False,
                    "run_coder": True,
                },
            },
            {
                "id": "commit",
                "result": {
                    "action": "approve",
                    "commit_plan": True,
                    "run_coder": False,
                },
            },
        ],
    }
    meta: dict[str, Any] = {
        "gate_bundle_path": str(bundle),
        "gate_kind": "plan",
        "plan_shell_project_name": "proj",
        "plan_shell_project_file": str(tmp_path / "proj.sase"),
        "plan_shell_workspace_dir": str(tmp_path),
        "plan_shell_workspace_num": 1,
        "plan_shell_output_path": str(tmp_path / "out.txt"),
        "plan_shell_timestamp": "20260827T120000",
        "plan_shell_artifacts_timestamp": "20260827_120000",
        "plan_shell_vcs_tag": "#gh:sase ",
        "plan_shell_agent_name": "agent",
        "plan_shell_source_role_suffix": PLAN_CHAIN_PLAN_SUFFIX,
        "plan_shell_agent_model": "gpt-5",
        "plan_shell_agent_llm_provider": "openai",
        "plan_shell_agent_vcs_provider": "github",
        "plan_shell_agent_meta": {"model": "gpt-5"},
        "plan_shell_current_prompt_path": str(current_prompt),
        "plan_shell_original_prompt_path": str(original_prompt),
        "patch_name": "demo",
    }
    (artifacts / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")

    def fake_prepare(plan_result: Any, ctx: Any, state: Any) -> Any:
        assert plan_result.action == "approve"
        assert plan_result.commit_plan is True
        assert plan_result.run_coder is True
        assert ctx.agent_name == "agent"
        assert state.current_prompt == "Planner prompt"
        assert state.current_role_suffix == PLAN_CHAIN_PLAN_SUFFIX
        return _AcceptedPlanPreparation(
            successor=SuccessorRequest(
                base_meta={},
                prompt="EXACT CODER PROMPT",
                suffix="--code",
            )
        )

    monkeypatch.setattr(
        "sase.axe.run_agent_exec_plan_accept.prepare_accepted_plan_successor",
        fake_prepare,
    )

    assert (
        plan_next_action(
            artifacts_dir=str(artifacts),
            meta=meta,
            envelope={},
            response=response,
            declared="fallback",
        )
        == "EXACT CODER PROMPT"
    )
