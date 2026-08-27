"""Golden shape of the composed follow-up for an answered question gate."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

import sase.gate_shell.followup as followup_module
from sase.agent.launch_types import AgentLaunchResult
from sase.axe.run_agent_helpers_artifacts import update_meta_fields
from sase.gate_shell.followup import launch_gate_followup_agent
from sase.gate_shell.followup_policy import resolve_gate_followup
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.gate_shell.member import create_gate_shell_member
from sase.notification_gates.executor import execute_gate_selection
from sase.notification_gates.hashing import load_and_verify_bundle
from sase.notification_gates.model_shell import GateShellSpec
from sase.notification_gates.service import create_gate
from sase.question_shell.create import _question_gate_shell_spec

from tests.monitor._fixtures import make_starter_agent, write_project_file

_SETTLE_TIMEOUT = 2.0


@pytest.fixture(autouse=True)
def _sandbox_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))


def _fake_spawn_result() -> AgentLaunchResult:
    return AgentLaunchResult(
        pid=999999,
        workspace_num=3,
        workspace_dir="/tmp/whatever",
        output_path="/tmp/whatever.txt",
        agent_name="lane--q",
    )


def _create_round(
    *,
    round_index: int,
    parent_artifacts_dir: str | None,
    base_prompt_path: Path,
    parent_timestamp: str,
    answer_note: str,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    session_id = f"round-{round_index}"
    questions = [
        {
            "question": f"Question {round_index}?",
            "options": [{"label": "Yes"}, {"label": "No"}],
        }
    ]
    request = _question_gate_shell_spec(
        questions,
        session_id=session_id,
        base_prompt="the base prompt",
        prior_rounds=[],
    )
    request["request_id"] = session_id
    gate = create_gate(request)
    shell = GateShellSpec.from_mapping(request["shell"], branches=(("submit",),))
    suffix = "--gate" if round_index == 1 else "--gate-0"
    artifacts_dir = create_gate_shell_member(
        "proj",
        {"name": "lane--0", "agent_family": "lane"},
        lane="lane",
        suffix=suffix,
        prev_artifacts_timestamp=parent_timestamp,
        workspace_num=None,
        gate_id=session_id,
        gate_kind="question",
        label="Question",
        reason="wait for reviewer",
        creator_agent="lane--0",
        timeout_seconds=86400.0,
        request_fingerprint=None,
        shell=shell,
    )
    fields: dict[str, Any] = {
        "gate_bundle_path": str(gate.bundle_path),
        "question_round_index": round_index,
        "question_session_id": session_id,
    }
    if parent_artifacts_dir is None:
        base_prompt_path.write_text("Implement the feature.", encoding="utf-8")
        fields["question_base_prompt_path"] = str(base_prompt_path)
    else:
        fields["question_prev_artifacts_dir"] = parent_artifacts_dir
        fields["question_base_prompt_path"] = str(base_prompt_path)
    update_meta_fields(artifacts_dir, fields)

    answer = {
        "answers": [
            {
                "question": f"Question {round_index}?",
                "selected": ["Yes"],
                "custom_feedback": None,
            }
        ],
        "global_note": answer_note,
    }
    execute_gate_selection(
        gate.bundle_path, ["submit"], answer, feedback=answer_note, source="test"
    )
    envelope, _adapter = load_and_verify_bundle(gate.bundle_path)
    response = json.loads((gate.bundle_path / "response.json").read_text())
    return artifacts_dir, envelope, response


def test_answered_followup_prompt_has_live_fork_and_no_leaked_markers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_project_file("proj")
    creator_timestamp = "20260812120000"
    creator_dir = make_starter_agent(
        "proj",
        creator_timestamp,
        "lane",
        agent_family="lane",
        agent_family_role="root",
    )
    (Path(creator_dir) / "done.json").write_text("{}", encoding="utf-8")
    update_agent_artifact_index_for_marker_mutation(creator_dir)

    base_prompt_path = tmp_path / "question_base_prompt.md"
    round1_dir, _envelope1, _response1 = _create_round(
        round_index=1,
        parent_artifacts_dir=None,
        base_prompt_path=base_prompt_path,
        parent_timestamp=creator_timestamp,
        answer_note="first note",
    )
    round2_dir, envelope, response = _create_round(
        round_index=2,
        parent_artifacts_dir=round1_dir,
        base_prompt_path=base_prompt_path,
        parent_timestamp=creator_timestamp,
        answer_note="second note",
    )

    policy = resolve_gate_followup(envelope, gate_state="answered", response=response)
    assert policy is not None
    raw_meta = json.loads((Path(round2_dir) / "agent_meta.json").read_text())

    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_spawn_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = launch_gate_followup_agent(
        round2_dir,
        raw_meta,
        project_name="proj",
        gate_state="answered",
        policy=policy,
        envelope=envelope,
        response=response,
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is True
    prompt = captured["prompt"]

    assert prompt.startswith("#fork:lane\n")
    assert "%xprompts_enabled:false" in prompt
    assert "%xprompts_enabled:true" in prompt
    assert "% xprompts_enabled:false" not in prompt
    assert "% xprompts_enabled:true" not in prompt
    assert "## Results" in prompt
    assert (
        "Question 2?" in prompt.split("## Results")[1].split("## Your next action")[0]
    )

    next_action_start = prompt.index("## Your next action")
    next_action = prompt[next_action_start:]
    assert "Implement the feature." in next_action
    assert "Question 1?" in next_action
    assert "Question 2?" in next_action
    assert next_action.index("Question 1?") < next_action.index("Question 2?")


def test_unreadable_chain_falls_back_to_declared_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_project_file("proj")
    creator_timestamp = "20260812120000"
    creator_dir = make_starter_agent(
        "proj",
        creator_timestamp,
        "lane",
        agent_family="lane",
        agent_family_role="root",
    )
    (Path(creator_dir) / "done.json").write_text("{}", encoding="utf-8")
    update_agent_artifact_index_for_marker_mutation(creator_dir)

    base_prompt_path = tmp_path / "question_base_prompt.md"
    round1_dir, envelope, response = _create_round(
        round_index=1,
        parent_artifacts_dir=None,
        base_prompt_path=base_prompt_path,
        parent_timestamp=creator_timestamp,
        answer_note="only note",
    )
    # Break the chain: the base-prompt file this round points at is missing.
    raw_meta = json.loads((Path(round1_dir) / "agent_meta.json").read_text())
    raw_meta["question_base_prompt_path"] = str(tmp_path / "does_not_exist.md")
    (Path(round1_dir) / "agent_meta.json").write_text(json.dumps(raw_meta))

    policy = resolve_gate_followup(envelope, gate_state="answered", response=response)
    assert policy is not None
    declared = policy.prompt

    captured: dict[str, Any] = {}

    def fake_spawn(**kwargs: Any) -> AgentLaunchResult:
        captured.update(kwargs)
        return _fake_spawn_result()

    monkeypatch.setattr(followup_module, "spawn_agent_subprocess", fake_spawn)

    result = launch_gate_followup_agent(
        round1_dir,
        raw_meta,
        project_name="proj",
        gate_state="answered",
        policy=policy,
        envelope=envelope,
        response=response,
        settle_timeout_seconds=_SETTLE_TIMEOUT,
    )

    assert result.launched is True
    prompt = captured["prompt"]
    next_action_start = prompt.index("## Your next action")
    next_action = prompt[next_action_start + len("## Your next action") :].strip()
    assert next_action.startswith(declared or "")
