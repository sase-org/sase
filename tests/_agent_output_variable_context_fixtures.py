"""Shared fixtures for agent output-variable context tests."""

from __future__ import annotations

import json
from pathlib import Path

from sase.axe.run_agent_exec_types import AgentExecContext

PLAN_PATH = "sdd/plans/202606/example.md"


def make_consumer_context(
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


def augment_submitted_plan_meta(
    artifacts_dir: Path,
    *,
    name: str = "planner",
    role_suffix: str = "--plan",
    output_variables: dict[str, str] | None = None,
    write_plan_path_json: bool = True,
    plan_path: str | None = PLAN_PATH,
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
