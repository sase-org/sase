"""Tests for the ``sase xprompt`` command handler."""

from __future__ import annotations

import argparse
import json
from unittest.mock import patch

import pytest

from sase.main.xprompt_handler import _handle_expand, _handle_explain, _handle_list
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.workflow_models import Workflow, WorkflowStep


def _simple_workflow(name: str) -> Workflow:
    return Workflow(name=name, steps=[WorkflowStep(name="prompt", prompt_part="body")])


def _xprompt_swarm_workflow(name: str) -> Workflow:
    return Workflow(
        name=name,
        steps=[WorkflowStep(name="prompt", prompt_part="one\n---\ntwo")],
    )


def _embeddable_workflow(name: str) -> Workflow:
    return Workflow(
        name=name,
        steps=[
            WorkflowStep(name="setup", bash="true"),
            WorkflowStep(name="prompt", prompt_part="body"),
        ],
    )


def _standalone_workflow(name: str) -> Workflow:
    return Workflow(name=name, steps=[WorkflowStep(name="run", agent="do it")])


def test_xprompt_list_includes_kind_and_insertion(
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompts = {
        "commit": _simple_workflow("commit"),
        "memory/glossary": Workflow(
            name="memory/glossary",
            source_path="/tmp/sase/memory/glossary.md",
            memory_type="reference",
            steps=[WorkflowStep(name="prompt", prompt_part="Glossary body")],
        ),
        "multi": _xprompt_swarm_workflow("multi"),
        "gh": _embeddable_workflow("gh"),
        "sync": _standalone_workflow("sync"),
    }
    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=prompts),
        patch("sase.xprompt.loader.get_all_xprompts", return_value={}),
        patch("sase.xprompt.loader.get_all_workflows", return_value={}),
        pytest.raises(SystemExit) as exc_info,
    ):
        _handle_list()

    assert exc_info.value.code == 0
    rows = {row["name"]: row for row in json.loads(capsys.readouterr().out)}

    assert rows["commit"]["type"] == "xprompt"
    assert rows["commit"]["kind"] == "xprompt"
    assert rows["commit"]["prefix"] == "#"
    assert rows["commit"]["insertion"] == "#commit"
    assert rows["commit"]["is_skill"] is False
    assert rows["commit"]["memory_type"] is None

    assert rows["memory/glossary"]["type"] == "xprompt"
    assert rows["memory/glossary"]["kind"] == "memory"
    assert rows["memory/glossary"]["prefix"] == "#"
    assert rows["memory/glossary"]["insertion"] == "#memory/glossary"
    assert rows["memory/glossary"]["memory_type"] == "reference"
    assert rows["memory/glossary"]["source"] == "/tmp/sase/memory/glossary.md"

    assert rows["multi"]["type"] == "xprompt"
    assert rows["multi"]["kind"] == "xprompt"
    assert rows["multi"]["prefix"] == "#"
    assert rows["multi"]["insertion"] == "#multi"

    assert rows["gh"]["type"] == "workflow"
    assert rows["gh"]["kind"] == "embeddable_workflow"
    assert rows["gh"]["prefix"] == "#"
    assert rows["gh"]["insertion"] == "#gh"

    assert rows["sync"]["type"] == "workflow"
    assert rows["sync"]["kind"] == "standalone_workflow"
    assert rows["sync"]["prefix"] == "#!"
    assert rows["sync"]["insertion"] == "#!sync"


def test_xprompt_expand_canonicalizes_project_alias(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    late_kwargs = []

    def preprocess_late(prompt: str, **kwargs: object) -> str:
        late_kwargs.append(kwargs)
        return prompt

    monkeypatch.setattr(
        "sase.project_aliases.load_project_alias_map",
        lambda projects_root=None: {"bob": "bob-cli"},
    )
    with (
        patch("sase.config.load_merged_config", return_value={"xprompt_aliases": {}}),
        patch("sase.xprompt.loader.get_all_xprompts", return_value={}),
        patch(
            "sase.main.query_handler.expand_embedded_workflows_in_query",
            side_effect=lambda prompt: (prompt, []),
        ),
        patch(
            "sase.llm_provider.preprocessing.preprocess_prompt_late",
            side_effect=preprocess_late,
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        _handle_expand(argparse.Namespace(prompt="#gh:bob do it", trace=False))

    assert exc_info.value.code == 0
    assert capsys.readouterr().out == "#gh:bob-cli do it"
    assert late_kwargs
    assert late_kwargs[0].get("materialize_missing_roots", False) is False


def test_xprompt_expand_warns_on_unresolved_reference_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with (
        patch("sase.config.load_merged_config", return_value={"xprompt_aliases": {}}),
        patch("sase.xprompt.processor.get_all_xprompts", return_value={}),
        patch("sase.xprompt.loader.get_all_prompts", return_value={}),
        patch("sase.workspace_provider.get_workflow_names", return_value=set()),
        patch("sase.workspace_provider.get_ref_patterns", return_value={}),
        patch("sase.xprompt.loader.get_known_project_workspaces", return_value={}),
        patch(
            "sase.main.query_handler.expand_embedded_workflows_in_query",
            side_effect=lambda prompt: (prompt, []),
        ),
        patch(
            "sase.llm_provider.preprocessing.preprocess_prompt_late",
            side_effect=lambda prompt, **_kwargs: prompt,
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        _handle_expand(argparse.Namespace(prompt="#reviewww", trace=False))

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert captured.out == "#reviewww"
    assert "unknown xprompt reference '#reviewww'" in captured.err


def test_xprompt_list_marks_only_skill_xprompts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    skill = XPrompt(
        name="skill/sase_plan",
        content="Plan",
        skill=True,
        skill_name="sase_plan",
    )
    regular = XPrompt(name="review", content="Review")
    prompts = {
        "skill/sase_plan": _simple_workflow("skill/sase_plan"),
        "review": _simple_workflow("review"),
        "ship": _standalone_workflow("ship"),
    }

    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=prompts),
        patch(
            "sase.xprompt.loader.get_all_xprompts",
            return_value={"skill/sase_plan": skill, "review": regular},
        ),
        patch(
            "sase.xprompt.loader.get_all_workflows",
            return_value={"ship": prompts["ship"]},
        ),
        pytest.raises(SystemExit) as exc_info,
    ):
        _handle_list()

    assert exc_info.value.code == 0
    rows = {row["name"]: row for row in json.loads(capsys.readouterr().out)}

    # The row name is the ``#`` reference; ``skill_name`` is the ``/`` name.
    assert rows["skill/sase_plan"]["is_skill"] is True
    assert rows["skill/sase_plan"]["skill_name"] == "sase_plan"
    assert rows["review"]["is_skill"] is False
    assert rows["review"]["skill_name"] is None
    assert rows["ship"]["is_skill"] is False
    assert rows["ship"]["skill_name"] is None


def test_xprompt_list_prints_load_issues_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.xprompt.load_issues import record_load_issue

    def get_prompts_with_issue() -> dict[str, Workflow]:
        record_load_issue(
            "/tmp/bad.yml", "mapping values are not allowed", kind="workflow"
        )
        return {}

    with (
        patch(
            "sase.xprompt.loader.get_all_prompts", side_effect=get_prompts_with_issue
        ),
        patch("sase.xprompt.loader.get_all_xprompts", return_value={}),
        patch("sase.xprompt.loader.get_all_workflows", return_value={}),
        pytest.raises(SystemExit) as exc_info,
    ):
        _handle_list()

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert json.loads(captured.out) == []
    assert captured.err == "skipped: /tmp/bad.yml: mapping values are not allowed\n"


def test_xprompt_list_includes_prompt_and_input_descriptions(
    capsys: pytest.CaptureFixture[str],
) -> None:
    prompts = {
        "review": Workflow(
            name="review",
            description="Review a selected diff.",
            inputs=[
                InputArg(
                    name="diff",
                    type=InputType.PATH,
                    description="Diff file to inspect.",
                )
            ],
            steps=[WorkflowStep(name="prompt", prompt_part="body")],
        )
    }

    with (
        patch("sase.xprompt.loader.get_all_prompts", return_value=prompts),
        patch("sase.xprompt.loader.get_all_xprompts", return_value={}),
        patch("sase.xprompt.loader.get_all_workflows", return_value={}),
        pytest.raises(SystemExit) as exc_info,
    ):
        _handle_list()

    assert exc_info.value.code == 0
    rows = {row["name"]: row for row in json.loads(capsys.readouterr().out)}

    assert rows["review"]["description"] == "Review a selected diff."
    assert rows["review"]["inputs"][0]["description"] == "Diff file to inspect."


def test_builtin_followup_xprompts_registered_and_explainable(
    capsys: pytest.CaptureFixture[str],
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        _handle_explain(
            argparse.Namespace(
                workflow_name="with_q_and_a",
                args=[],
                named_args=["prompt=Base", "qa_file=/tmp/qa.json"],
            )
        )

    captured = capsys.readouterr()
    assert exc_info.value.code == 0
    assert "with_q_and_a" in captured.out
    assert "qa_file" in captured.out
