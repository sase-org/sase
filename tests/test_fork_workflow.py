"""Workflow-level coverage for the built-in ``#fork`` xprompt."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.axe.run_agent_runner_setup import expand_deferred_launch_xprompts
from sase.llm_provider.preprocessing import preprocess_prompt_late
from sase.xprompt.loader import get_sase_package_xprompts_dir
from sase.xprompt.models import UNSET
from sase.xprompt.tags import XPromptTag
from sase.xprompt.workflow_executor import WorkflowExecutor
from sase.xprompt.workflow_loader import _load_workflow_from_file
from sase.xprompt.workflow_models import Workflow, WorkflowStep
from sase.xprompt.workflow_validator import validate_workflow


def _load_fork_workflow() -> Workflow:
    workflow = _load_workflow_from_file(get_sase_package_xprompts_dir() / "fork.yml")
    assert workflow is not None
    return workflow


def _write_completed_agent(
    home: Path,
    suffix: str,
    name: str,
    *,
    response_path: Path,
    meta: dict[str, object] | None = None,
) -> None:
    artifacts_dir = (
        home / ".sase" / "projects" / "proj" / "artifacts" / "ace-run" / suffix
    )
    artifacts_dir.mkdir(parents=True)
    meta_data: dict[str, object] = {"name": name}
    if meta:
        meta_data.update(meta)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(meta_data),
        encoding="utf-8",
    )
    (artifacts_dir / "done.json").write_text(
        json.dumps({"outcome": "completed", "response_path": str(response_path)}),
        encoding="utf-8",
    )


def test_fork_workflow_name_input_is_optional() -> None:
    """The real ``fork.yml`` allows embedded ``#fork`` without a name."""
    workflow = _load_fork_workflow()

    validate_workflow(workflow)
    name_input = workflow.get_input_by_name("name")
    assert name_input is not None
    assert name_input.default is None
    assert name_input.repeatable is True
    assert all(
        input_arg.default is not UNSET
        for input_arg in workflow.inputs
        if not input_arg.is_step_input
    )


def test_embedded_bare_resume_loads_resolved_chat_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Embedded bare ``#fork`` resolves a chat path, then loads that transcript."""
    monkeypatch.setenv("HOME", str(tmp_path))
    chat_path = tmp_path / "previous-chat.md"
    chat_text = "Previous agent transcript from resolver output."
    chat_path.write_text(chat_text, encoding="utf-8")
    _write_completed_agent(
        tmp_path,
        "20260504010101",
        "builder",
        response_path=chat_path,
    )

    fork_workflow = _load_fork_workflow()
    parent_workflow = Workflow(
        name="parent",
        steps=[WorkflowStep(name="review", agent="Review\n#fork\nContinue")],
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    executor = WorkflowExecutor(parent_workflow, {}, str(artifacts_dir))

    with patch(
        "sase.xprompt.loader.get_all_workflows",
        return_value={"fork": fork_workflow},
    ):
        expanded_prompt, embedded_workflows, pre_step_count = (
            executor._expand_embedded_workflows_in_prompt("Review\n#fork\nContinue")
        )

    assert pre_step_count == 2
    assert embedded_workflows == []
    assert chat_text in expanded_prompt
    assert "# Previous Conversation" in expanded_prompt
    assert "Review" in expanded_prompt
    assert "Continue" in expanded_prompt


@pytest.mark.parametrize("reference", ["#fork:planner,coder", "#fork(planner, coder)"])
def test_embedded_multi_parent_fork_renders_provenance_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reference: str,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    planner_chat = tmp_path / "planner-chat.md"
    coder_chat = tmp_path / "coder-chat.md"
    planner_chat.write_text(
        "## Prompt\n\nPlan it\n\n## Response\n\nPlanner answer\n",
        encoding="utf-8",
    )
    coder_chat.write_text(
        "## Prompt\n\nCode it\n\n## Response\n\nCoder answer\n",
        encoding="utf-8",
    )
    _write_completed_agent(
        tmp_path,
        "20260504010101",
        "planner",
        response_path=planner_chat,
    )
    _write_completed_agent(
        tmp_path,
        "20260504020202",
        "coder",
        response_path=coder_chat,
    )
    fork_workflow = _load_fork_workflow()
    parent_workflow = Workflow(
        name="parent",
        steps=[WorkflowStep(name="review", agent=f"Review\n{reference}\nContinue")],
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    executor = WorkflowExecutor(parent_workflow, {}, str(artifacts_dir))

    with patch(
        "sase.xprompt.loader.get_all_workflows",
        return_value={"fork": fork_workflow},
    ):
        expanded_prompt, embedded_workflows, pre_step_count = (
            executor._expand_embedded_workflows_in_prompt(
                f"Review\n{reference}\nContinue"
            )
        )

    assert pre_step_count == 2
    assert embedded_workflows == []
    assert expanded_prompt.count("%xprompts_enabled:false") == 1
    assert expanded_prompt.count("%xprompts_enabled:true") == 1
    assert "# Previous Conversations" in expanded_prompt
    assert "forking from 2 prior agent conversations" in expanded_prompt
    assert "## Conversation 1 of 2 — agent `planner`" in expanded_prompt
    assert "## Conversation 2 of 2 — agent `coder`" in expanded_prompt
    assert expanded_prompt.index("Planner answer") < expanded_prompt.index(
        "Coder answer"
    )
    assert expanded_prompt.endswith("# New Query\nContinue")


def test_embedded_single_parent_fork_keeps_legacy_envelope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    chat_path = tmp_path / "previous-chat.md"
    chat_path.write_text(
        "## Prompt\n\nOld question\n\n## Response\n\nOld answer\n",
        encoding="utf-8",
    )
    _write_completed_agent(
        tmp_path,
        "20260504010101",
        "builder",
        response_path=chat_path,
    )
    fork_workflow = _load_fork_workflow()
    parent_workflow = Workflow(
        name="parent",
        steps=[WorkflowStep(name="review", agent="#fork:builder\nContinue")],
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    executor = WorkflowExecutor(parent_workflow, {}, str(artifacts_dir))

    with patch(
        "sase.xprompt.loader.get_all_workflows",
        return_value={"fork": fork_workflow},
    ):
        expanded_prompt, _, _ = executor._expand_embedded_workflows_in_prompt(
            "#fork:builder\nContinue"
        )

    assert expanded_prompt == (
        "%xprompts_enabled:false\n"
        "# Previous Conversation\n\n"
        "**User:**\n\nOld question\n\n"
        "**Assistant:**\n\nOld answer\n\n"
        "---\n\n"
        "%xprompts_enabled:true\n"
        "# New Query\n"
        "Continue"
    )


def test_embedded_clan_fork_injects_prompts_without_member_replies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    member_specs = (
        ("20260718010101", "review.alpha", "Alpha prompt", "ALPHA_SECRET"),
        ("20260718010202", "review.beta", "Beta prompt", "BETA_SECRET"),
    )
    for suffix, name, prompt, reply in member_specs:
        chat_path = tmp_path / f"{name}.md"
        chat_path.write_text(
            f"## Prompt\n\n{prompt}\n\n## Response\n\n{reply}\n",
            encoding="utf-8",
        )
        _write_completed_agent(
            tmp_path,
            suffix,
            name,
            response_path=chat_path,
            meta={
                "agent_clan": "review",
                "agent_clan_generation": "20260718010000",
                "model": "gpt-5",
                "llm_provider": "openai",
            },
        )

    fork_workflow = _load_fork_workflow()
    parent_workflow = Workflow(
        name="parent",
        steps=[WorkflowStep(name="review", agent="#fork:review\nContinue")],
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    executor = WorkflowExecutor(parent_workflow, {}, str(artifacts_dir))

    with patch(
        "sase.xprompt.loader.get_all_workflows",
        return_value={"fork": fork_workflow},
    ):
        expanded_prompt, _, _ = executor._expand_embedded_workflows_in_prompt(
            "#fork:review\nContinue"
        )

    assert "agent clan `review`" in expanded_prompt
    assert "Alpha prompt" in expanded_prompt
    assert "Beta prompt" in expanded_prompt
    assert "ALPHA_SECRET" not in expanded_prompt
    assert "BETA_SECRET" not in expanded_prompt
    assert expanded_prompt.count("**Reply summary:**") == 2
    assert expanded_prompt.endswith("# New Query\nContinue")


def test_completed_clan_fork_expands_during_post_wait_runner_setup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    for suffix, name, prompt in (
        ("20260718010101", "review.alpha", "Alpha prompt"),
        ("20260718010202", "review.beta", "Beta prompt"),
    ):
        chat_path = tmp_path / f"{name}.md"
        chat_path.write_text(
            f"## Prompt\n\n{prompt}\n\n## Response\n\nsecret\n",
            encoding="utf-8",
        )
        _write_completed_agent(
            tmp_path,
            suffix,
            name,
            response_path=chat_path,
            meta={
                "agent_clan": "review",
                "agent_clan_generation": "20260718010000",
            },
        )

    artifacts_dir = tmp_path / "runner-artifacts"
    artifacts_dir.mkdir()
    with patch(
        "sase.xprompt.loader.get_all_workflows",
        return_value={"fork": _load_fork_workflow()},
    ):
        expanded = expand_deferred_launch_xprompts(
            "#fork:review\nContinue",
            str(artifacts_dir),
        )

    assert "agent clan `review`" in expanded
    assert "Alpha prompt" in expanded
    assert "Beta prompt" in expanded
    assert "#fork:review" not in expanded
    assert expanded.endswith("# New Query\nContinue")


def test_inline_deferred_fork_survives_workspace_removal_and_late_preprocessing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    chat_path = tmp_path / "previous-chat.md"
    chat_path.write_text(
        "## Prompt\n\nOld question\n\n## Response\n\nOld answer\n",
        encoding="utf-8",
    )
    _write_completed_agent(
        tmp_path,
        "20260727010101",
        "builder",
        response_path=chat_path,
    )

    artifacts_dir = tmp_path / "runner-artifacts"
    artifacts_dir.mkdir()
    with (
        patch(
            "sase.xprompt.loader.get_all_workflows",
            return_value={"fork": _load_fork_workflow()},
        ),
        patch("sase.xprompt.used_xprompts.write_used_xprompts"),
    ):
        expanded_fork = expand_deferred_launch_xprompts(
            "#gh:sase #fork:builder Continue the work",
            str(artifacts_dir),
        )

    marker_index = expanded_fork.index("%xprompts_enabled:false")
    assert expanded_fork[marker_index - 1] == "\n"

    workspace_workflow = Workflow(
        name="gh",
        steps=[WorkflowStep(name="inject", prompt_part="")],
        tags=frozenset({XPromptTag.vcs}),
    )
    parent_workflow = Workflow(
        name="parent",
        steps=[WorkflowStep(name="review", agent=expanded_fork)],
    )
    executor = WorkflowExecutor(parent_workflow, {}, str(artifacts_dir))
    with patch(
        "sase.xprompt.loader.get_all_workflows",
        return_value={"gh": workspace_workflow},
    ):
        without_workspace, _, _ = executor._expand_embedded_workflows_in_prompt(
            expanded_fork
        )

    final_prompt = preprocess_prompt_late(without_workspace, file_ref_mode="skip")

    assert "%xprompts_enabled" not in final_prompt
    assert "\n # New Query" not in final_prompt
    assert final_prompt.endswith("# New Query\n\nContinue the work\n")


def test_embedded_family_fork_injects_each_completed_member_reply_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    planner_chat = tmp_path / "planner.md"
    planner_chat.write_text(
        "## Prompt\n\nPlan the change\n\n## Response\n\nPLANNER_REPLY\n",
        encoding="utf-8",
    )
    coder_chat = tmp_path / "coder.md"
    coder_chat.write_text(
        "## Prompt\n\n"
        f"#fork_by_chat:{planner_chat} Implement the change\n\n"
        "## Response\n\nCODER_REPLY\n",
        encoding="utf-8",
    )
    _write_completed_agent(
        tmp_path,
        "20260718010101",
        "cx--plan",
        response_path=coder_chat,
        meta={
            "agent_family": "cx",
            "chat_path": str(planner_chat),
            "model": "gpt-5",
            "llm_provider": "openai",
        },
    )
    _write_completed_agent(
        tmp_path,
        "20260718010202",
        "cx--code",
        response_path=coder_chat,
        meta={
            "agent_family": "cx",
            "parent_timestamp": "20260718010101",
            "model": "gpt-5",
            "llm_provider": "openai",
        },
    )

    fork_workflow = _load_fork_workflow()
    parent_workflow = Workflow(
        name="parent",
        steps=[WorkflowStep(name="review", agent="#fork:cx\nContinue")],
    )
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    executor = WorkflowExecutor(parent_workflow, {}, str(artifacts_dir))

    with patch(
        "sase.xprompt.loader.get_all_workflows",
        return_value={"fork": fork_workflow},
    ):
        expanded_prompt, _, _ = executor._expand_embedded_workflows_in_prompt(
            "#fork:cx\nContinue"
        )

    assert "agent family `cx`" in expanded_prompt
    assert "sequential chain" in expanded_prompt
    assert expanded_prompt.index("cx--plan") < expanded_prompt.index("cx--code")
    assert expanded_prompt.count("PLANNER_REPLY") == 1
    assert expanded_prompt.count("CODER_REPLY") == 1
    assert expanded_prompt.endswith("# New Query\nContinue")


def test_embedded_tribe_fork_dispatches_to_clan_context_builder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    current_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260718020000"
    current_dir.mkdir(parents=True)
    (current_dir / "agent_meta.json").write_text(
        json.dumps({"name": "waiter"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SASE_ARTIFACTS_DIR", str(current_dir))

    for suffix, name, prompt, reply in (
        ("20260718022000", "review.alpha", "Alpha prompt", "ALPHA_SECRET"),
        ("20260718023000", "review.beta", "Beta prompt", "BETA_SECRET"),
    ):
        chat_path = tmp_path / f"{name}.md"
        chat_path.write_text(
            f"## Prompt\n\n{prompt}\n\n## Response\n\n{reply}\n",
            encoding="utf-8",
        )
        _write_completed_agent(
            tmp_path,
            suffix,
            name,
            response_path=chat_path,
            meta={
                "agent_clan": "review",
                "agent_clan_generation": "20260718021000",
                "clan_tribe": "epic",
            },
        )

    fork_workflow = _load_fork_workflow()
    parent_workflow = Workflow(
        name="parent",
        steps=[WorkflowStep(name="review", agent="#fork:@epic\nContinue")],
    )
    executor_artifacts = tmp_path / "executor-artifacts"
    executor_artifacts.mkdir()
    executor = WorkflowExecutor(parent_workflow, {}, str(executor_artifacts))

    with patch(
        "sase.xprompt.loader.get_all_workflows",
        return_value={"fork": fork_workflow},
    ):
        expanded_prompt, _, _ = executor._expand_embedded_workflows_in_prompt(
            "#fork:@epic\nContinue"
        )

    assert "agent clan `review`" in expanded_prompt
    assert "Alpha prompt" in expanded_prompt
    assert "Beta prompt" in expanded_prompt
    assert "ALPHA_SECRET" not in expanded_prompt
    assert "BETA_SECRET" not in expanded_prompt
    assert expanded_prompt.endswith("# New Query\nContinue")
