"""Tests for output variables flowing into workflow Jinja contexts."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.output_variable_context import (
    build_agent_output_variable_context,
    build_agent_var_upstream_record,
    encode_agent_var_upstreams,
)
from sase.axe.run_agent_exec import _build_named_args
from sase.xprompt.workflow_models import Workflow, WorkflowStep
from sase.xprompt.workflow_runner import execute_workflow
from tests._agent_names_fixtures import make_agent
from tests._agent_output_variable_context_fixtures import (
    PLAN_PATH,
    augment_submitted_plan_meta,
    make_consumer_context,
)


def test_build_named_args_injects_single_agents_arg() -> None:
    ctx = make_consumer_context(
        {"agents": {"build": {"report_path": "reports/build.md"}}},
    )

    named_args = _build_named_args(ctx)

    assert named_args["agents"] == {"build": {"report_path": "reports/build.md"}}
    assert named_args["cl_name"] == "cl"
    assert named_args["workspace_num"] == 3


def test_build_named_args_raises_on_agents_collision() -> None:
    ctx = make_consumer_context({"cl_name": {"build": {}}})

    with pytest.raises(ValueError, match="Reserved agent-run Jinja name"):
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

    ctx = make_consumer_context(output_variable_namespaces)
    workflow = Workflow(
        name="consumer",
        steps=[
            WorkflowStep(
                name="main",
                prompt_part=(
                    'Read {{ agents["build"].report_path }} after producer '
                    'status {{ agents["build"].status }}.'
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


def test_structured_variables_reach_jinja_as_json_stringifying_containers(
    tmp_path: Path,
) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="build",
            project_name="proj",
            workflow_timestamp="260501_120000",
        )

    artifacts_dir = Path(str(upstream["artifacts_dir"]))
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "build",
                "output_variables": {
                    "cfg": {
                        "retries": 3,
                        "hosts": ["beta", "alpha"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )
    ctx = make_consumer_context(context)
    workflow = Workflow(
        name="consumer",
        steps=[
            WorkflowStep(
                name="main",
                prompt_part=(
                    'cfg={{ agents["build"].cfg }}; '
                    'retries={{ agents["build"].cfg.retries }}; '
                    '{% for host in agents["build"].cfg.hosts %}'
                    "{{ host }}{% if not loop.last %},{% endif %}{% endfor %}; "
                    'json={{ agents["build"].cfg | tojson }}'
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

    rendered = executor_cls.call_args.kwargs["workflow"].steps[0].agent
    assert rendered == (
        'cfg={"hosts":["beta","alpha"],"retries":3}; '
        "retries=3; beta,alpha; "
        'json={"hosts": ["beta", "alpha"], "retries": 3}'
    )


def test_submitted_plan_file_renders_in_later_workflow_prompt(
    tmp_path: Path,
) -> None:
    agent_dir = make_agent(
        tmp_path,
        "proj",
        "20260625184716",
        "planner",
        workflow_name="planner",
        agent_family="planner",
        role_suffix="--plan",
    )
    augment_submitted_plan_meta(agent_dir)

    with patch.object(Path, "home", return_value=tmp_path):
        output_variable_namespaces = build_agent_output_variable_context(
            upstreams_json=None,
            wait_names=["planner--plan"],
        )

    ctx = make_consumer_context(output_variable_namespaces)
    workflow = Workflow(
        name="consumer",
        steps=[
            WorkflowStep(
                name="main",
                prompt_part='Implement {{ agents["planner--plan"].plan_file }}.',
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
    assert rendered_workflow.steps[0].agent == (f"Implement {PLAN_PATH}.")


def test_raw_key_producer_renders_via_bracket_access(tmp_path: Path) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="0n.cld",
            project_name="proj",
            workflow_timestamp="260501_120000",
        )

    artifacts_dir = Path(str(upstream["artifacts_dir"]))
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "0n.cld",
                "output_variables": {"report_path": "reports/cld.md"},
            }
        ),
        encoding="utf-8",
    )

    with patch.object(Path, "home", return_value=tmp_path):
        output_variable_namespaces = build_agent_output_variable_context(
            upstreams_json=encode_agent_var_upstreams([upstream]),
        )

    ctx = make_consumer_context(output_variable_namespaces)
    workflow = Workflow(
        name="consumer",
        steps=[
            WorkflowStep(
                name="main",
                prompt_part='Read {{ agents["0n.cld"].report_path }}.',
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
    assert rendered_workflow.steps[0].agent == "Read reports/cld.md."
