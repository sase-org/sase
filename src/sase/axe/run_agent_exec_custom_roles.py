"""Custom agent-family role spawning for the execution loop."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agent_family import CustomRoleTransition
from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.axe.run_agent_helpers import (
    create_followup_artifacts,
    promote_to_workflow,
)
from sase.plan_chain import plan_chain_agent_name

if TYPE_CHECKING:
    from sase.agent_family.custom_definitions import AgentFamilyRoleDefinition
    from sase.axe.run_agent_exec_types import AgentExecContext, LoopState


class _MissingFormatValue(defaultdict[str, str]):
    def __missing__(self, key: str) -> str:
        return ""


def read_agent_meta(artifacts_dir: str) -> dict[str, Any]:
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with meta_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def custom_role_snapshot_from_meta(
    artifacts_dir: str,
) -> dict[str, object] | None:
    data = read_agent_meta(artifacts_dir).get("agent_family_custom_role")
    return data if isinstance(data, dict) else None


def _render_custom_role_prompt(
    role: AgentFamilyRoleDefinition,
    *,
    plan_file: str | None = None,
    source_artifacts: str | None = None,
    outcome: str | None = None,
    source_role: str | None = None,
) -> str:
    values = _MissingFormatValue(
        str,
        plan_file=plan_file or "",
        source_artifacts=source_artifacts or "",
        artifacts_ref=source_artifacts or "",
        outcome=outcome or "",
        source_role=source_role or "",
        role=role.id,
    )
    rendered = role.prompt_template.format_map(values).strip()
    if rendered.startswith(("#", "@", "%")):
        return rendered
    return f"#{rendered}"


def spawn_custom_role_followup(
    transition: CustomRoleTransition,
    ctx: AgentExecContext,
    state: LoopState,
    *,
    base_meta: dict[str, Any] | None = None,
    plan_file: str | None = None,
    source_artifacts: str | None = None,
    outcome: str | None = None,
    source_role: str | None = None,
    extra_relationships: dict[str, Any] | None = None,
) -> None:
    """Mutate *state* so the next loop iteration runs a custom role."""

    role = transition.role
    state.current_role_suffix = role.suffix
    state.custom_role_visit_counts.update(
        {
            key: int(value)
            for key, value in transition.runtime_metadata.family_state.visit_counts.items()
            if isinstance(value, int)
        }
    )
    state.agent_step += 1
    if state.agent_step == 2 and ctx.agent_name:
        promote_to_workflow(ctx.artifacts_dir, ctx.agent_name)

    source_artifacts_dir = source_artifacts or state.current_artifacts_dir
    inherited_meta = dict(base_meta or read_agent_meta(source_artifacts_dir))
    prev_timestamp = (
        Path(source_artifacts_dir).name
        if source_artifacts_dir
        else convert_timestamp_to_artifacts_format(ctx.timestamp)
    )
    relationships = {
        "custom_role_source_artifacts_dir": source_artifacts_dir,
        "custom_role_source_role": source_role,
        "custom_role_outcome": outcome,
        "plan_path": plan_file,
        **transition.runtime_metadata.as_followup_relationships(),
    }
    if extra_relationships:
        relationships.update(extra_relationships)

    state.current_artifacts_dir = create_followup_artifacts(
        ctx.project_name,
        inherited_meta,
        role.suffix,
        prev_timestamp,
        workspace_num=ctx.workspace_num,
        agent_name_override=(
            plan_chain_agent_name(ctx.agent_name, role.suffix)
            if ctx.agent_name
            else None
        ),
        workflow_name=ctx.agent_name,
        agent_family_role=role.id,
        relationships=relationships,
    )
    state.current_prompt = _render_custom_role_prompt(
        role,
        plan_file=plan_file,
        source_artifacts=source_artifacts_dir,
        outcome=outcome,
        source_role=source_role,
    )
    state.question_base_prompt = state.current_prompt
