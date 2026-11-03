"""Gate-turn marker handling for the agent execution loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.axe.run_agent_helpers import (
    finalize_handoff_artifacts_as_completed,
    normalize_handoff_interruption_state,
    update_meta_field,
    update_meta_suffix,
)
from sase.axe.runner_signals import reset_killed
from sase.plan_chain import AGENT_SESSION_SEPARATOR, canonical_plan_chain_suffix

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState


def handle_gate_marker(
    gate_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
) -> str:
    """Adopt a staged gate-turn handoff for the execution loop."""
    normalize_handoff_interruption_state(state.current_artifacts_dir)
    finalize_handoff_artifacts_as_completed(state.current_artifacts_dir)

    starter_meta = _read_json_object(
        Path(state.current_artifacts_dir) / "agent_meta.json"
    )
    starter_suffix = _promoted_starter_suffix(ctx.agent_name, starter_meta)
    if starter_suffix is not None:
        update_meta_suffix(state.current_artifacts_dir, starter_suffix)
        state.current_role_suffix = starter_suffix
        state.agent_step = max(state.agent_step, 2)
        starter_meta["role_suffix"] = canonical_plan_chain_suffix(starter_suffix)

    gate_meta = _gate_member_meta(gate_data)
    gate_id = _text(gate_data.get("gate_id")) or _text(gate_meta.get("gate_id"))
    member_artifacts_dir = _text(gate_data.get("member_artifacts_dir"))
    member_agent_name = _text(gate_data.get("member_agent_name")) or _text(
        gate_meta.get("name")
    )
    starter_agent = _text(starter_meta.get("name")) or ctx.agent_name

    if gate_id:
        update_meta_field(state.current_artifacts_dir, "gate_id", gate_id)
    if member_agent_name:
        update_meta_field(
            state.current_artifacts_dir,
            "gate_member_agent_name",
            member_agent_name,
        )

    if member_artifacts_dir and starter_agent:
        update_meta_field(member_artifacts_dir, "gate_creator_agent", starter_agent)

    reset_killed()
    return "gated"


def _gate_member_meta(gate_data: dict[str, Any]) -> dict[str, Any]:
    artifacts_dir = _text(gate_data.get("member_artifacts_dir"))
    if not artifacts_dir:
        return {}
    return _read_json_object(Path(artifacts_dir) / "agent_meta.json")


def _promoted_starter_suffix(
    ctx_agent_name: str | None,
    starter_meta: dict[str, Any],
) -> str | None:
    name = _text(starter_meta.get("name"))
    if not name or not ctx_agent_name:
        return None
    prefix = f"{ctx_agent_name}{AGENT_SESSION_SEPARATOR}"
    if not name.startswith(prefix):
        return None
    suffix = name[len(ctx_agent_name) :]
    return canonical_plan_chain_suffix(suffix) or suffix


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = ["handle_gate_marker"]
