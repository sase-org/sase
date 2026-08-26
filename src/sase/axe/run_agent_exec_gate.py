"""Gate-shell marker handling for the agent execution loop."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.axe.run_agent_helpers import (
    finalize_handoff_artifacts_as_completed,
    normalize_handoff_interruption_state,
    update_meta_field,
    update_meta_suffix,
    update_step_marker_chat_path,
)
from sase.axe.runner_signals import reset_killed
from sase.history.chat import save_chat_history
from sase.history.chat_extras import format_extra_sections
from sase.notification_gates.durability import read_json_object
from sase.plan_chain import AGENT_FAMILY_SEPARATOR, canonical_plan_chain_suffix

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState


def handle_gate_marker(
    gate_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
) -> str:
    """Adopt a ``.sase_gate_pending`` marker after runner SIGTERM."""
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
    bundle_path = _text(gate_meta.get("gate_bundle_path"))

    response = _format_gate_response(
        gate_id=gate_id,
        member_agent_name=member_agent_name,
        kind=_text(gate_meta.get("gate_kind")),
        title=_gate_title(bundle_path, gate_meta),
    )
    extra = format_extra_sections(state.current_artifacts_dir)
    chat_path = save_chat_history(
        prompt=state.current_prompt,
        response=response,
        workflow="ace-run",
        agent=starter_agent,
        timestamp=ctx.timestamp,
        extra_sections=extra,
        branch_or_workspace=ctx.cl_name,
        metadata_agent=starter_agent,
        metadata_model=ctx.agent_model,
        metadata_llm_provider=ctx.agent_llm_provider,
        metadata_multi_agent_prompt=ctx.multi_agent_prompt_file,
    )

    state.saved_chat_paths.append(
        (starter_suffix or state.current_role_suffix, chat_path)
    )
    update_meta_field(state.current_artifacts_dir, "chat_path", chat_path)
    if gate_id:
        update_meta_field(state.current_artifacts_dir, "gate_id", gate_id)
    if member_agent_name:
        update_meta_field(
            state.current_artifacts_dir,
            "gate_member_agent_name",
            member_agent_name,
        )
    update_step_marker_chat_path(state.current_artifacts_dir, chat_path)

    if member_artifacts_dir and starter_agent:
        update_meta_field(member_artifacts_dir, "gate_creator_agent", starter_agent)

    reset_killed()
    return "gated"


def _format_gate_response(
    *,
    gate_id: str | None,
    member_agent_name: str | None,
    kind: str | None,
    title: str | None,
) -> str:
    lines = [
        "# Gate handoff",
        "",
        "This agent handed the remaining decision to a gate shell.",
    ]
    if title:
        lines.append(f"Decision: {title}")
    if gate_id:
        lines.append(f"Gate ID: {gate_id}")
        if kind:
            lines.append(f"Inspect with: sase gate show --id {gate_id} --kind {kind}")
    if member_agent_name:
        lines.append(f"Gate shell: {member_agent_name}")
    return "\n".join(lines).rstrip() + "\n"


def _gate_member_meta(gate_data: dict[str, Any]) -> dict[str, Any]:
    artifacts_dir = _text(gate_data.get("member_artifacts_dir"))
    if not artifacts_dir:
        return {}
    return _read_json_object(Path(artifacts_dir) / "agent_meta.json")


def _gate_title(bundle_path: str | None, meta: dict[str, Any]) -> str | None:
    if bundle_path:
        try:
            envelope = read_json_object(Path(bundle_path) / "request.json")
            presentation = envelope.get("presentation")
            if isinstance(presentation, dict) and presentation.get("title"):
                return str(presentation["title"])
        except Exception:
            pass
    return _text(meta.get("gate_label"))


def _promoted_starter_suffix(
    ctx_agent_name: str | None,
    starter_meta: dict[str, Any],
) -> str | None:
    name = _text(starter_meta.get("name"))
    if not name or not ctx_agent_name:
        return None
    prefix = f"{ctx_agent_name}{AGENT_FAMILY_SEPARATOR}"
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
