from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.main.feedback_prompt import (
    _append_feedback_replan_prompt,
    _read_feedback_parent_prompt,
    _split_feedback_replan_prompt,
    _assemble_feedback_replan_prompt_from_parent,
    assemble_feedback_replan_prompt,
)
from sase.main.qa_markdown import QARound
from sase.main.qa_prompt import (
    assemble_question_followup_prompt,
    merge_qa_for_prompt,
    qa_rounds_from_payload,
)
from sase.main.query_handler import expand_embedded_workflows_in_query
from sase.xprompt.workflow_models import WorkflowExecutionError


def _q(question: str, label: str = "A") -> dict[str, object]:
    return {
        "question": question,
        "options": [{"label": label}],
        "header": "Choice",
    }


def test_assemble_question_followup_prompt_keeps_runner_byte_shape() -> None:
    rounds = [
        QARound(
            questions=[_q("Which API?", "REST")],
            answers=[{"selected": ["REST"]}],
            global_note="Keep it simple",
        )
    ]

    assert assemble_question_followup_prompt("Base prompt", rounds) == (
        "Base prompt\n\n" + merge_qa_for_prompt(rounds)
    )


def test_qa_rounds_from_payload_accepts_supported_shapes() -> None:
    multi_round = {
        "rounds": [
            {
                "questions": [_q("First?", "A")],
                "response": {
                    "answers": [{"question": "First?", "selected": ["A"]}],
                    "global_note": "",
                },
            },
            {
                "questions": [_q("Second?", "B")],
                "answers": [{"question": "Second?", "selected": ["B"]}],
                "global_note": "latest",
            },
        ]
    }
    single_round = {
        "questions": [_q("Only?", "C")],
        "response": {
            "answers": [{"question": "Only?", "selected": ["C"]}],
            "global_note": "",
        },
    }
    top_level_list = [
        {
            "questions": [_q("Mobile?", "D"), _q("Skipped?", "E")],
            "answers": [{"question": "Mobile?", "selected": ["D"]}],
            "global_note": "",
        }
    ]

    multi = qa_rounds_from_payload(multi_round)
    single = qa_rounds_from_payload(single_round)
    listed = qa_rounds_from_payload(top_level_list)

    assert len(multi) == 2
    assert single[0].answers[0]["selected"] == ["C"]
    assert listed[0].answers[0]["selected"] == ["D"]
    assert listed[0].answers[1] == {}


def test_qa_rounds_from_payload_rejects_missing_questions() -> None:
    with pytest.raises(ValueError, match="questions"):
        qa_rounds_from_payload({"answers": []})


def test_assemble_feedback_replan_prompt_matches_runner_shape() -> None:
    rounds = [
        QARound(
            questions=[_q("Need DB?", "SQLite")],
            answers=[{"selected": ["SQLite"]}],
        )
    ]

    out = assemble_feedback_replan_prompt(
        "Original prompt",
        ["Add failure handling", "Add retries"],
        rounds,
    )

    assert out == (
        "Original prompt\n\n"
        f"{merge_qa_for_prompt(rounds)}\n\n"
        "### Additional Requirements\n\n"
        "- Add failure handling\n"
        "- Add retries"
    )


def test_append_feedback_replan_prompt_preserves_prior_feedback() -> None:
    first = assemble_feedback_replan_prompt("Original prompt", ["First round"])

    second = _append_feedback_replan_prompt(first, "Second round")

    assert _split_feedback_replan_prompt(second) == (
        "Original prompt",
        ["First round", "Second round"],
    )
    assert second.endswith("- First round\n- Second round")


def test_read_feedback_parent_prompt_prefers_followup_prompt(tmp_path: Path) -> None:
    artifacts_dir = tmp_path / "agent"
    artifacts_dir.mkdir()
    (artifacts_dir / "workflow-main_prompt.md").write_text(
        "agent prompt", encoding="utf-8"
    )
    (artifacts_dir / "followup_prompt.md").write_text(
        "follow-up prompt", encoding="utf-8"
    )

    assert _read_feedback_parent_prompt(artifacts_dir) == "follow-up prompt"


def test_with_q_and_a_xprompt_expands_to_shared_helper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    qa_file = tmp_path / "qa.json"
    payload = {
        "rounds": [
            {
                "questions": [
                    {
                        "question": "Which path mentions #literal?",
                        "options": [
                            {"label": "A", "description": "Keep it"},
                            {"label": "Other"},
                        ],
                        "header": "Path",
                        "multiSelect": True,
                    }
                ],
                "response": {
                    "answers": [
                        {
                            "question": "Which path mentions #literal?",
                            "selected": ["Other", "Unknown"],
                            "custom_feedback": "Use #literal here",
                        }
                    ],
                    "global_note": "Prefer lower risk.",
                },
            }
        ]
    }
    qa_file.write_text(json.dumps(payload), encoding="utf-8")
    expected = assemble_question_followup_prompt(
        "Base prompt",
        qa_rounds_from_payload(payload),
    )

    expanded, workflows = expand_embedded_workflows_in_query(
        f"#with_q_and_a(qa_file={qa_file}):: Base prompt"
    )

    assert expanded == expected
    assert workflows[0].workflow_name == "with_q_and_a"
    assert expanded.count("### Questions and Answers") == 1
    assert "#literal" in expanded


def test_with_q_and_a_xprompt_missing_qa_file_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    missing = tmp_path / "missing.json"

    with pytest.raises(WorkflowExecutionError, match="qa_file not found"):
        expand_embedded_workflows_in_query(
            f"#with_q_and_a(qa_file={missing}):: Base prompt"
        )


def test_with_feedback_xprompt_expands_from_parent_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    artifacts_dir = (
        sase_home / "projects" / "myproj" / "artifacts" / "ace-run" / "20260706010101"
    )
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": "parent_agent", "stopped_at": "2026-07-06T01:01:01Z"}),
        encoding="utf-8",
    )
    (artifacts_dir / "done.json").write_text(
        json.dumps({"outcome": "completed", "name": "parent_agent"}),
        encoding="utf-8",
    )
    (artifacts_dir / "workflow-main_prompt.md").write_text(
        "Original parent prompt", encoding="utf-8"
    )

    expanded, workflows = expand_embedded_workflows_in_query(
        "#with_feedback(parent=parent_agent):: Add failure handling"
    )

    assert expanded == assemble_feedback_replan_prompt(
        "Original parent prompt",
        ["Add failure handling"],
    )
    assert workflows[0].workflow_name == "with_feedback"


def test_with_feedback_unknown_parent_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SASE_HOME", str(tmp_path / "sase-home"))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    with pytest.raises(WorkflowExecutionError, match="unknown parent agent"):
        expand_embedded_workflows_in_query(
            "#with_feedback(parent=missing_parent):: feedback"
        )


def test_feedback_parent_without_prompt_artifact_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.agent.names.resolve_resume_agent_name",
        lambda _parent: type(
            "Named",
            (),
            {"artifacts_dir": str(tmp_path / "no_prompt")},
        )(),
    )
    (tmp_path / "no_prompt").mkdir()

    with pytest.raises(ValueError, match="no prompt artifact"):
        _assemble_feedback_replan_prompt_from_parent("parent", "feedback")
