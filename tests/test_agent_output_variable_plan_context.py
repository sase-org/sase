"""Tests for submitted-plan output variables in the cross-agent context."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from sase.agent.output_variable_context import (
    build_agent_output_variable_context,
    build_agent_var_upstream_record,
    encode_agent_var_upstreams,
)
from tests._agent_names_fixtures import make_agent
from tests._agent_output_variable_context_fixtures import (
    PLAN_PATH,
    augment_submitted_plan_meta,
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
    augment_submitted_plan_meta(agent_dir)

    with patch.object(Path, "home", return_value=tmp_path):
        context = build_agent_output_variable_context(
            upstreams_json=None,
            wait_names=["planner--plan"],
        )

    assert context == {"agents": {"planner--plan": {"plan_file": PLAN_PATH}}}
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

    augment_submitted_plan_meta(Path(str(upstream["artifacts_dir"])))

    context = build_agent_output_variable_context(
        upstreams_json=encode_agent_var_upstreams([upstream]),
    )

    assert context == {"agents": {"planner": {"plan_file": PLAN_PATH}}}


def test_submitted_planner_plan_file_merges_with_stored_variables(
    tmp_path: Path,
) -> None:
    with patch.object(Path, "home", return_value=tmp_path):
        upstream = build_agent_var_upstream_record(
            agent_name="planner",
            project_name="proj",
            workflow_timestamp="260625_184716",
        )

    augment_submitted_plan_meta(
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
                "plan_file": PLAN_PATH,
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

    augment_submitted_plan_meta(
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
    augment_submitted_plan_meta(agent_dir)
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
            "planner": {"plan_file": PLAN_PATH},
            "planner--plan": {"plan_file": PLAN_PATH},
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
    augment_submitted_plan_meta(agent_dir, plan_path=None)

    with patch.object(Path, "home", return_value=tmp_path):
        context = build_agent_output_variable_context(
            upstreams_json=None,
            wait_names=["planner--plan"],
        )

    assert context == {}
