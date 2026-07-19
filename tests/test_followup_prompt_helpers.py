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
    _qa_rounds_from_payload,
    assemble_question_followup_prompt,
    merge_qa_for_prompt,
)
from sase.main.query_handler import expand_embedded_workflows_in_query
from sase.xprompt.directives import extract_prompt_directives
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


def test_question_followup_prompt_golden_snapshot() -> None:
    """Byte-level golden for accumulated Q&A prompt reconstruction."""
    rounds = [
        QARound(
            questions=[
                {
                    "question": "Which API?",
                    "options": [
                        {"label": "REST", "description": "Stable"},
                        {"label": "GraphQL"},
                    ],
                    "header": "API",
                },
                {
                    "question": "Any concern?",
                    "options": [{"label": "Low risk"}],
                    "header": "Risk",
                    "multiSelect": True,
                },
            ],
            answers=[
                {"selected": ["REST"]},
                {
                    "selected": ["Other"],
                    "custom_feedback": "Migration #literal stays literal",
                },
            ],
            global_note="First note loses.",
        ),
        QARound(
            questions=[
                {
                    "question": "Where first?",
                    "options": [{"label": "Staging"}],
                    "header": "Deploy",
                }
            ],
            answers=[{"selected": ["Staging"]}],
            global_note="Final note wins.",
        ),
    ]

    assert assemble_question_followup_prompt("Base prompt", rounds) == (
        "Base prompt\n\n"
        "%xprompts_enabled:false\n"
        "### Questions and Answers\n\n"
        "#### Q1: API\n\n"
        "> Which API?\n\n"
        "- [x] **REST** — Stable\n"
        "- [ ] **GraphQL**\n\n"
        "#### Q2: Risk\n\n"
        "> Any concern?\n\n"
        "- [ ] **Low risk**\n"
        '- [x] **Other:** "Migration #literal stays literal"\n\n'
        "*Multi-select*\n\n"
        "#### Q3: Deploy\n\n"
        "> Where first?\n\n"
        "- [x] **Staging**\n\n"
        "---\n\n"
        "> **Global Note:** Final note wins.\n\n"
        "%xprompts_enabled:true"
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

    multi = _qa_rounds_from_payload(multi_round)
    single = _qa_rounds_from_payload(single_round)
    listed = _qa_rounds_from_payload(top_level_list)

    assert len(multi) == 2
    assert single[0].answers[0]["selected"] == ["C"]
    assert listed[0].answers[0]["selected"] == ["D"]
    assert listed[0].answers[1] == {}


def test_qa_rounds_from_payload_rejects_missing_questions() -> None:
    with pytest.raises(ValueError, match="questions"):
        _qa_rounds_from_payload({"answers": []})


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


def test_feedback_replan_prompt_golden_snapshot() -> None:
    """Byte-level golden for feedback plus prior Q&A reconstruction."""
    rounds = [
        QARound(
            questions=[
                {
                    "question": "Need DB?",
                    "options": [{"label": "SQLite"}, {"label": "Postgres"}],
                    "header": "Storage",
                }
            ],
            answers=[{"selected": ["SQLite"]}],
            global_note="Keep dependencies small.",
        )
    ]

    assert assemble_feedback_replan_prompt(
        "Original prompt",
        ["Add failure handling", "Add retries"],
        rounds,
    ) == (
        "Original prompt\n\n"
        "%xprompts_enabled:false\n"
        "### Questions and Answers\n\n"
        "#### Q1: Storage\n\n"
        "> Need DB?\n\n"
        "- [x] **SQLite**\n"
        "- [ ] **Postgres**\n\n"
        "---\n\n"
        "> **Global Note:** Keep dependencies small.\n\n"
        "%xprompts_enabled:true\n\n"
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
        _qa_rounds_from_payload(payload),
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


def test_with_feedback_xprompt_defaults_parent_from_family_attach(
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
        "%i(@, family=parent_agent) #with_feedback:: Add failure handling"
    )
    cleaned, directives = extract_prompt_directives(expanded)
    expected, _ = extract_prompt_directives(
        assemble_feedback_replan_prompt(
            "Original parent prompt",
            ["Add failure handling"],
        )
    )

    assert cleaned.lstrip() == expected
    assert directives.family_attach_parent == "parent_agent"
    assert directives.family_attach_suffix == "@"
    assert workflows[0].context["parent"] == "parent_agent"
    assert workflows[0].workflow_name == "with_feedback"


def test_with_feedback_parent_default_is_multi_prompt_segment_local(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sase_home = tmp_path / "sase-home"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    artifacts_dir = (
        sase_home / "projects" / "myproj" / "artifacts" / "ace-run" / "20260706020202"
    )
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps({"name": "parent_two", "stopped_at": "2026-07-06T02:02:02Z"}),
        encoding="utf-8",
    )
    (artifacts_dir / "done.json").write_text(
        json.dumps({"outcome": "completed", "name": "parent_two"}),
        encoding="utf-8",
    )
    (artifacts_dir / "workflow-main_prompt.md").write_text(
        "Original parent two prompt", encoding="utf-8"
    )

    expanded, workflows = expand_embedded_workflows_in_query(
        "%i(@, family=parent_one) unrelated segment\n"
        "---\n"
        "%i(@, family=parent_two) #with_feedback:: Add launch-prep coverage"
    )

    assert "Original parent two prompt" in expanded
    assert workflows[0].context["parent"] == "parent_two"


def test_with_q_and_a_xprompt_composes_with_family_attach_directive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    qa_file = tmp_path / "qa.json"
    payload = {
        "questions": [_q("Which API?", "REST")],
        "response": {
            "answers": [{"question": "Which API?", "selected": ["REST"]}],
            "global_note": "Keep it simple",
        },
    }
    qa_file.write_text(json.dumps(payload), encoding="utf-8")

    expanded, workflows = expand_embedded_workflows_in_query(
        f"%i(@, family=parent_agent) #with_q_and_a(qa_file={qa_file}):: Base prompt"
    )
    cleaned, directives = extract_prompt_directives(expanded)
    expected, _ = extract_prompt_directives(
        assemble_question_followup_prompt(
            "Base prompt",
            _qa_rounds_from_payload(payload),
        )
    )

    assert cleaned.lstrip() == expected
    assert directives.family_attach_parent == "parent_agent"
    assert directives.family_attach_suffix == "@"
    assert workflows[0].workflow_name == "with_q_and_a"


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
