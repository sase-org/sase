"""Tests for cross-agent output-variable Jinja context."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.output_variable_context import (
    SASE_AGENT_VAR_UPSTREAMS_ENV,
    _AgentOutputVariableNamespaceError,
    _namespace_path_for_agent_output_variables,
    build_agent_output_variable_context,
    build_agent_var_upstream_record,
    encode_agent_var_upstreams,
)
from sase.axe.run_agent_exec import _build_named_args
from sase.axe.run_agent_exec_types import AgentExecContext
from sase.xprompt.workflow_models import Workflow, WorkflowStep
from sase.xprompt.workflow_runner import execute_workflow
from tests._agent_names_fixtures import make_agent


def test_indexed_name_template_exposes_base_namespace() -> None:
    assert _namespace_path_for_agent_output_variables(
        agent_name="build-7",
        agent_name_template="build-@",
    ) == ("build",)


def test_dotted_indexed_name_template_exposes_nested_namespace() -> None:
    assert _namespace_path_for_agent_output_variables(
        agent_name="research_swarm.final-2",
        agent_name_template="research_swarm.final-@",
    ) == ("research_swarm", "final")


def test_plain_hyphenated_agent_name_exposes_underscore_namespace() -> None:
    assert _namespace_path_for_agent_output_variables(
        agent_name="build-agent",
    ) == ("build_agent",)


def test_invalid_namespace_raises_instead_of_silent_skip() -> None:
    with pytest.raises(_AgentOutputVariableNamespaceError, match="Jinja identifier"):
        _namespace_path_for_agent_output_variables(agent_name="1bad")


def test_scoped_upstream_variables_load_into_nested_context(tmp_path: Path) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="research_swarm.final-1",
            agent_name_template="research_swarm.final-@",
            project_name="proj",
            workflow_timestamp="260501_120000",
        )

    artifacts_dir = Path(str(upstream["artifacts_dir"]))
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "research_swarm.final-1",
                "agent_name_template": "research_swarm.final-@",
                "output_variables": {"report_path": "reports/final.md"},
            }
        ),
        encoding="utf-8",
    )

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {"research_swarm": {"final": {"report_path": "reports/final.md"}}}


def test_later_upstream_overrides_same_namespace_key(tmp_path: Path) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        first = build_agent_var_upstream_record(
            agent_name="build",
            project_name="proj",
            workflow_timestamp="260501_120000",
        )
        second = build_agent_var_upstream_record(
            agent_name="build",
            project_name="proj",
            workflow_timestamp="260501_120001",
        )

    for record, value in ((first, "old.txt"), (second, "new.txt")):
        artifacts_dir = Path(str(record["artifacts_dir"]))
        artifacts_dir.mkdir(parents=True)
        (artifacts_dir / "agent_meta.json").write_text(
            json.dumps({"name": "build", "output_variables": {"path": value}}),
            encoding="utf-8",
        )

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([first, second]),
    )

    assert context == {"build": {"path": "new.txt"}}


def test_waited_agent_variables_load_as_fallback_context(tmp_path: Path) -> None:
    agent_dir = make_agent(
        tmp_path,
        "proj",
        "20260501120000",
        "build-1",
        done=True,
        outcome="completed",
    )
    meta_path = agent_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["agent_name_template"] = "build-@"
    meta["output_variables"] = {"report_path": "reports/build.md"}
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with patch.object(Path, "home", return_value=tmp_path):
        context = build_agent_output_variable_context(
            upstreams_json=None,
            wait_names=["build-1"],
        )

    assert context == {"build": {"report_path": "reports/build.md"}}


def test_build_named_args_includes_output_variable_namespaces() -> None:
    ctx = AgentExecContext(
        cl_name="cl",
        project_file="/tmp/project.sase",
        workspace_dir="/tmp/ws",
        output_path="/tmp/out.txt",
        workspace_num=3,
        timestamp="260501_120000",
        update_target="",
        project_name="proj",
        is_home_mode=False,
        artifacts_dir="/tmp/artifacts",
        artifacts_timestamp="20260501120000",
        vcs_tag=None,
        agent_name="consumer",
        agent_model=None,
        agent_llm_provider=None,
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta={},
        local_xprompts={},
        output_variable_namespaces={"build": {"report_path": "reports/build.md"}},
    )

    named_args = _build_named_args(ctx)

    assert named_args["build"] == {"report_path": "reports/build.md"}
    assert named_args["cl_name"] == "cl"
    assert named_args["workspace_num"] == 3


def test_build_named_args_rejects_builtin_output_variable_collision() -> None:
    ctx = AgentExecContext(
        cl_name="cl",
        project_file="/tmp/project.sase",
        workspace_dir="/tmp/ws",
        output_path="/tmp/out.txt",
        workspace_num=3,
        timestamp="260501_120000",
        update_target="",
        project_name="proj",
        is_home_mode=False,
        artifacts_dir="/tmp/artifacts",
        artifacts_timestamp="20260501120000",
        vcs_tag=None,
        agent_name="consumer",
        agent_model=None,
        agent_llm_provider=None,
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta={},
        local_xprompts={},
        output_variable_namespaces={"cl_name": {"status": "bad"}},
    )

    with pytest.raises(ValueError, match="collides with a built-in workflow argument"):
        _build_named_args(ctx)


def test_waited_producer_variables_render_in_later_workflow_prompt(
    tmp_path: Path,
) -> None:
    agent_dir = make_agent(
        tmp_path,
        "proj",
        "20260501120000",
        "build-1",
        done=True,
        outcome="completed",
    )
    meta_path = agent_dir / "agent_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["agent_name_template"] = "build-@"
    meta["output_variables"] = {
        "report_path": "reports/build.md",
        "status": "ok",
    }
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="build-1",
            agent_name_template="build-@",
            project_name="proj",
            workflow_timestamp="260501_120000",
        )
        output_variable_namespaces = build_agent_output_variable_context(
            upstreams_json=encode_agent_var_upstreams([upstream]),
            wait_names=["build-1"],
        )

    ctx = AgentExecContext(
        cl_name="cl",
        project_file="/tmp/project.sase",
        workspace_dir="/tmp/ws",
        output_path="/tmp/out.txt",
        workspace_num=3,
        timestamp="260501_120001",
        update_target="",
        project_name="proj",
        is_home_mode=False,
        artifacts_dir=str(tmp_path / "consumer_artifacts"),
        artifacts_timestamp="20260501120001",
        vcs_tag=None,
        agent_name="consumer",
        agent_model=None,
        agent_llm_provider=None,
        agent_vcs_provider=None,
        agent_hidden=False,
        agent_meta={},
        local_xprompts={},
        wait_chats=[],
        output_variable_namespaces=output_variable_namespaces,
    )
    workflow = Workflow(
        name="consumer",
        steps=[
            WorkflowStep(
                name="main",
                prompt_part=(
                    "Read {{ build.report_path }} after producer status "
                    "{{ build.status }}."
                ),
            )
        ],
    )

    with patch("sase.xprompt.workflow_executor.WorkflowExecutor") as executor_cls:
        executor = executor_cls.return_value
        executor.execute.return_value = True
        executor.state.steps = []

        execute_workflow(
            name=workflow.name,
            positional_args=[],
            named_args=_build_named_args(ctx),
            artifacts_dir=str(tmp_path / "consumer_workflow"),
            workflow_obj=workflow,
            silent=True,
        )

    rendered_workflow = executor_cls.call_args.kwargs["workflow"]
    assert rendered_workflow.steps[0].agent == (
        "Read reports/build.md after producer status ok."
    )


def test_spawn_env_scrubber_removes_inherited_upstream_context() -> None:
    from sase.agent.launch_spawn import _remove_inherited_agent_var_context_env

    env = {SASE_AGENT_VAR_UPSTREAMS_ENV: "[]", "OTHER": "1"}

    _remove_inherited_agent_var_context_env(env)

    assert env == {"OTHER": "1"}
