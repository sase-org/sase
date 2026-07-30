"""Tests for the cross-agent ``agents`` output-variable Jinja context."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.agent.output_variable_context import (
    SASE_AGENT_VAR_UPSTREAMS_ENV,
    _agent_key_for_output_variables,
    build_agent_output_variable_context,
    build_agent_var_upstream_record,
    encode_agent_var_upstreams,
)
from sase.axe.run_agent_exec import _build_named_args
from sase.axe.run_agent_exec_types import AgentExecContext
from sase.xprompt.workflow_models import Workflow, WorkflowStep
from sase.xprompt.workflow_runner import execute_workflow
from tests._agent_names_fixtures import make_agent


def _consumer_ctx(
    output_variable_namespaces: dict[str, object],
) -> AgentExecContext:
    return AgentExecContext(
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
        output_variable_namespaces=output_variable_namespaces,
    )


def test_agent_name_template_exposes_base_key() -> None:
    assert (
        _agent_key_for_output_variables(
            agent_name="build-7",
            agent_name_template="build-@",
        )
        == "build"
    )


def test_dotted_agent_name_template_exposes_flat_dotted_key() -> None:
    assert (
        _agent_key_for_output_variables(
            agent_name="research.2.final",
            agent_name_template="research.@.final",
        )
        == "research.final"
    )


def test_plain_hyphenated_agent_name_is_used_verbatim() -> None:
    assert _agent_key_for_output_variables(agent_name="build-agent") == "build-agent"


def test_digit_leading_dotted_agent_name_is_used_verbatim() -> None:
    assert _agent_key_for_output_variables(agent_name="0n.cld") == "0n.cld"


def test_named_producer_loads_under_agents_dict(tmp_path: Path) -> None:
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
                "output_variables": {"report_path": "reports/final.md"},
            }
        ),
        encoding="utf-8",
    )

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {"agents": {"build": {"report_path": "reports/final.md"}}}


def test_agent_name_template_upstream_uses_stable_base_key(tmp_path: Path) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="build-1",
            agent_name_template="build-@",
            project_name="proj",
            workflow_timestamp="260501_120000",
        )

    artifacts_dir = Path(str(upstream["artifacts_dir"]))
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "build-1",
                "agent_name_template": "build-@",
                "output_variables": {"report_path": "reports/final.md"},
            }
        ),
        encoding="utf-8",
    )

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {"agents": {"build": {"report_path": "reports/final.md"}}}


def test_dotted_agent_name_template_uses_flat_dotted_key(tmp_path: Path) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="research.1.final",
            agent_name_template="research.@.final",
            project_name="proj",
            workflow_timestamp="260501_120000",
        )

    artifacts_dir = Path(str(upstream["artifacts_dir"]))
    artifacts_dir.mkdir(parents=True)
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "research.1.final",
                "agent_name_template": "research.@.final",
                "output_variables": {"report_path": "reports/final.md"},
            }
        ),
        encoding="utf-8",
    )

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {
        "agents": {"research.final": {"report_path": "reports/final.md"}}
    }


def test_digit_leading_dotted_fanout_uses_raw_key(tmp_path: Path) -> None:
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
                "output_variables": {"report_path": "reports/final.md"},
            }
        ),
        encoding="utf-8",
    )

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {"agents": {"0n.cld": {"report_path": "reports/final.md"}}}


def test_later_upstream_overrides_same_key(tmp_path: Path) -> None:
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

    assert context == {"agents": {"build": {"path": "new.txt"}}}


def test_empty_producers_create_no_agents_entry(tmp_path: Path) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="build",
            project_name="proj",
            workflow_timestamp="260501_120000",
        )

    # No agent_meta.json on disk: producer wrote nothing.
    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {}


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

    assert context == {"agents": {"build": {"report_path": "reports/build.md"}}}


_PLAN_PATH = "sdd/plans/202606/example.md"


def _augment_submitted_plan_meta(
    artifacts_dir: Path,
    *,
    name: str = "planner",
    role_suffix: str = "--plan",
    output_variables: dict[str, str] | None = None,
    write_plan_path_json: bool = True,
    plan_path: str | None = _PLAN_PATH,
) -> None:
    """Write a submitted-and-waiting planner ``agent_meta.json`` (no done.json)."""
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    meta: dict[str, object] = {
        "name": name,
        "role_suffix": role_suffix,
        "plan": True,
        "plan_submitted_at": ["2026-06-25T18:47:16+00:00"],
    }
    if plan_path is not None:
        meta["plan_path"] = plan_path
    if output_variables is not None:
        meta["output_variables"] = output_variables
    (artifacts_dir / "agent_meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if write_plan_path_json and plan_path is not None:
        (artifacts_dir / "plan_path.json").write_text(
            json.dumps({"plan_path": plan_path}), encoding="utf-8"
        )


def test_submitted_plan_wait_exposes_plan_file_under_row_key(tmp_path: Path) -> None:
    agent_dir = make_agent(
        tmp_path,
        "proj",
        "20260625184716",
        "planner",
        workflow_name="planner",
        agent_family="planner",
        role_suffix="--plan",
    )
    _augment_submitted_plan_meta(agent_dir)

    with patch.object(Path, "home", return_value=tmp_path):
        context = build_agent_output_variable_context(
            upstreams_json=None,
            wait_names=["planner--plan"],
        )

    assert context == {"agents": {"planner--plan": {"plan_file": _PLAN_PATH}}}
    assert "plan_file" not in context


def test_upstream_submitted_planner_exposes_plan_file_under_base_key(
    tmp_path: Path,
) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="planner",
            project_name="proj",
            workflow_timestamp="260625_184716",
        )

    _augment_submitted_plan_meta(Path(str(upstream["artifacts_dir"])))

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {"agents": {"planner": {"plan_file": _PLAN_PATH}}}


def test_submitted_planner_plan_file_merges_with_stored_variables(
    tmp_path: Path,
) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="planner",
            project_name="proj",
            workflow_timestamp="260625_184716",
        )

    _augment_submitted_plan_meta(
        Path(str(upstream["artifacts_dir"])),
        output_variables={"report_path": "reports/plan.md"},
    )

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {
        "agents": {
            "planner": {
                "report_path": "reports/plan.md",
                "plan_file": _PLAN_PATH,
            }
        }
    }


def test_explicit_plan_file_variable_is_not_overwritten_by_synthesis(
    tmp_path: Path,
) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="planner",
            project_name="proj",
            workflow_timestamp="260625_184716",
        )

    _augment_submitted_plan_meta(
        Path(str(upstream["artifacts_dir"])),
        output_variables={"plan_file": "explicit/override.md"},
    )

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {"agents": {"planner": {"plan_file": "explicit/override.md"}}}


def test_submitted_planner_populates_both_base_and_row_keys(tmp_path: Path) -> None:
    agent_dir = make_agent(
        tmp_path,
        "proj",
        "20260625184716",
        "planner",
        workflow_name="planner",
        agent_family="planner",
        role_suffix="--plan",
    )
    _augment_submitted_plan_meta(agent_dir)
    upstream = {
        "name": "planner",
        "agent_key": "planner",
        "agent_name_template": None,
        "artifacts_dir": str(agent_dir),
    }

    with patch.object(Path, "home", return_value=tmp_path):
        context = build_agent_output_variable_context(
            upstreams_json=encode_agent_var_upstreams([upstream]),
            wait_names=["planner--plan"],
        )

    assert context == {
        "agents": {
            "planner": {"plan_file": _PLAN_PATH},
            "planner--plan": {"plan_file": _PLAN_PATH},
        }
    }


def test_submitted_plan_wait_without_plan_path_exposes_nothing(
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
    _augment_submitted_plan_meta(agent_dir, plan_path=None)

    with patch.object(Path, "home", return_value=tmp_path):
        context = build_agent_output_variable_context(
            upstreams_json=None,
            wait_names=["planner--plan"],
        )

    assert context == {}


def test_build_named_args_injects_single_agents_arg() -> None:
    ctx = _consumer_ctx(
        {"agents": {"build": {"report_path": "reports/build.md"}}},
    )

    named_args = _build_named_args(ctx)

    assert named_args["agents"] == {"build": {"report_path": "reports/build.md"}}
    assert named_args["cl_name"] == "cl"
    assert named_args["workspace_num"] == 3


def test_build_named_args_raises_on_agents_collision() -> None:
    ctx = _consumer_ctx({"cl_name": {"build": {}}})

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

    ctx = _consumer_ctx(output_variable_namespaces)
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
    ctx = _consumer_ctx(context)
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
    _augment_submitted_plan_meta(agent_dir)

    with patch.object(Path, "home", return_value=tmp_path):
        output_variable_namespaces = build_agent_output_variable_context(
            upstreams_json=None,
            wait_names=["planner--plan"],
        )

    ctx = _consumer_ctx(output_variable_namespaces)
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
    assert rendered_workflow.steps[0].agent == (f"Implement {_PLAN_PATH}.")


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

    ctx = _consumer_ctx(output_variable_namespaces)
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


def test_spawn_env_scrubber_removes_inherited_upstream_context() -> None:
    from sase.agent.launch_spawn import _remove_inherited_agent_identity_env

    env = {SASE_AGENT_VAR_UPSTREAMS_ENV: "[]", "OTHER": "1"}

    _remove_inherited_agent_identity_env(env)

    assert env == {"OTHER": "1"}
