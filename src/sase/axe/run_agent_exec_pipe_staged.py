"""Persist a pipe successor identity before mutating loop or artifacts."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agent.staged_handoff import (
    STAGED_HANDOFF_RESPONSE_FILENAME,
    STAGED_SUCCESSOR_ORIGIN_PROMPT_FILENAME,
    read_staged_successor,
    successor_prompt_digest,
    update_staged_successor_locked,
    write_staged_successor_locked,
    write_successor_prompt,
)
from sase.axe._run_agent_exec_pipe_shared import (
    build_pipe_successor_prompt,
    interrupted_phase_meta,
    pipe_depth,
    read_json_meta,
    read_successor_prompt,
    resolve_pipe_model,
    text,
)
from sase.axe.run_agent_successor import FollowupModel
from sase.core.agent_launch_facade import reserve_launch_timestamp_batch
from sase.llm_provider.config import format_model_directive_value
from sase.plan_chain import (
    allocate_agent_session_child_suffix,
    plan_chain_agent_name,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState


def prepare_staged_pipe_successor(
    pipe_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
    *,
    staged_id: str,
    provider_response: str,
) -> dict[str, Any]:
    """Persist one pipe successor identity before mutating loop or artifacts."""
    origin_dir = state.current_artifacts_dir
    existing = read_staged_successor(origin_dir, staged_id=staged_id)
    if existing is not None:
        existing_successor = existing["successor"]
        expected_response = existing_successor["continuation_refs"].get(
            "provider_response_digest"
        )
        if isinstance(
            expected_response, str
        ) and expected_response != successor_prompt_digest(provider_response):
            raise RuntimeError("persisted pipe response differs from the staged turn")
        prompt = read_successor_prompt(existing_successor)
        target = Path(existing_successor["artifacts_dir"])
        if target.exists():
            meta = read_json_meta(target / "agent_meta.json")
            if meta is None:
                raise RuntimeError(
                    "pipe successor artifacts exist without readable identity metadata"
                )
            if (
                meta.get("name") != existing_successor["agent_name"]
                or meta.get("staged_handoff_id") != staged_id
                or meta.get("staged_successor_launch_id")
                != existing_successor["launch_identity"]
            ):
                raise RuntimeError(
                    "pipe successor artifacts do not match the persisted identity"
                )
            if existing["delivery_state"] == "prepared":
                existing = update_staged_successor_locked(
                    origin_dir, staged_id, delivery_state="created"
                )
        if existing["delivery_state"] in {"submitted", "started", "terminal"}:
            raise RuntimeError(
                "pipe successor is already owned outside the originating loop"
            )
        if not prompt:
            raise RuntimeError("persisted pipe successor prompt is empty")
        return existing

    base_meta = interrupted_phase_meta(origin_dir, ctx.agent_meta)
    parent_name = text(base_meta.get("name")) or ctx.agent_name
    name_token = text(pipe_data.get("name_token"))
    reason = text(pipe_data.get("reason"))
    fresh = bool(pipe_data.get("fresh"))
    model_spec = text(pipe_data.get("model"))
    piped_prompt = pipe_data.get("prompt")
    if not isinstance(piped_prompt, str):
        piped_prompt = ""
    current_depth = pipe_depth(pipe_data, base_meta)

    if name_token:
        suffix = f"--{name_token}"
        pipe_role = name_token
    elif ctx.agent_name:
        suffix = allocate_agent_session_child_suffix(
            ctx.agent_name,
            "--@",
            extra_reserved_suffixes=tuple(
                saved_suffix
                for saved_suffix, _path in state.saved_chat_paths
                if saved_suffix
            ),
        )
        pipe_role = "feedback"
    else:
        from sase.agent.names import render_agent_name_template

        suffix = render_agent_name_template("--@", "0")
        pipe_role = "feedback"

    successor_name = (
        plan_chain_agent_name(ctx.agent_name, suffix) if ctx.agent_name else suffix
    )
    followup_model = resolve_pipe_model(model_spec) if model_spec else None
    successor_prompt = build_pipe_successor_prompt(
        piped_prompt,
        parent_name=parent_name,
        fresh=fresh,
        model_prefix=followup_model.model_prefix if followup_model else "",
    )
    relationships: dict[str, Any] = {
        "piped_from": parent_name,
        "pipe_reason": reason,
        "pipe_depth": current_depth + 1,
        "patch_name": ctx.cl_name,
        "changespec_name": ctx.cl_name,
        "staged_handoff_id": staged_id,
    }
    timestamp = reserve_launch_timestamp_batch(1)[0]
    from sase.artifacts import (
        convert_timestamp_to_artifacts_format,
        launch_artifacts_dir,
    )

    successor_artifacts_dir = launch_artifacts_dir(ctx.project_name, timestamp)
    attach_plan: dict[str, Any] | None = None
    if ctx.agent_name:
        from sase.agent._agent_session_attach_resolution import (
            resolve_agent_session_attach_plan,
        )
        from sase.agent._agent_session_attach_types import AgentSessionAttachDirective

        resolved = resolve_agent_session_attach_plan(
            AgentSessionAttachDirective(parent=ctx.agent_name, suffix=suffix),
            project_name=ctx.project_name,
        )
        if resolved.agent_name != successor_name:
            raise RuntimeError(
                "pipe successor name differs from the host attach identity"
            )
        attach_plan = asdict(
            replace(resolved, parent_is_running=False, host_composed=True)
        )

    launch_prompt = successor_prompt
    effective_model = (
        followup_model.meta[1]
        if followup_model is not None and followup_model.meta is not None
        else text(base_meta.get("model")) or ctx.agent_model
    )
    effective_provider = (
        followup_model.meta[0]
        if followup_model is not None and followup_model.meta is not None
        else text(base_meta.get("llm_provider")) or ctx.agent_llm_provider
    )
    if followup_model is None and effective_model:
        directive = (
            f"{effective_provider}/{effective_model}"
            if effective_provider
            else effective_model
        )
        launch_prefix = format_model_directive_value(directive)
        launch_prompt = build_pipe_successor_prompt(
            piped_prompt,
            parent_name=parent_name,
            fresh=fresh,
            model_prefix=launch_prefix,
        )

    prompt_path = write_successor_prompt(origin_dir, successor_prompt)
    launch_prompt_path = (
        prompt_path
        if launch_prompt == successor_prompt
        else write_successor_prompt(
            origin_dir,
            launch_prompt,
            filename="staged_successor_launch_prompt.md",
        )
    )
    origin_prompt_path = write_successor_prompt(
        origin_dir,
        state.current_prompt,
        filename=STAGED_SUCCESSOR_ORIGIN_PROMPT_FILENAME,
    )
    vcs_ref = base_meta.get("vcs_ref")
    if not (
        isinstance(vcs_ref, list)
        and len(vcs_ref) == 2
        and all(isinstance(value, str) and value for value in vcs_ref)
    ):
        vcs_ref = None
    launch_identity = f"{staged_id}:{timestamp}"
    relationships["staged_successor_launch_id"] = launch_identity
    loop_state = {
        "agent_step": state.agent_step + 1,
        "current_role_suffix": suffix,
        "current_artifacts_dir": successor_artifacts_dir,
        "prompt_ref": str(prompt_path),
        "question_base_prompt_ref": str(prompt_path),
        "original_prompt": state.original_prompt,
        "sdd_spec_path": state.sdd_spec_path,
        "qa_rounds": [asdict(round_) for round_ in state.qa_rounds],
        "feedback_bullets": list(state.feedback_bullets),
        "feedback_round": state.feedback_round,
        "original_agent_timestamp": state.original_agent_timestamp,
        "question_gate_artifacts_dir": state.question_gate_artifacts_dir,
        "plan_gate_artifacts_dir": state.plan_gate_artifacts_dir,
        "loop_outcome": state.loop_outcome,
        "kill_source": state.kill_source,
        "kill_evidence": state.kill_evidence,
        "saved_chat_paths": [list(item) for item in state.saved_chat_paths],
        "continuation_workspace_ref": state.continuation_workspace_ref,
        "continuation_prepared_ref": state.continuation_prepared_ref,
        "continuation_node_id": state.continuation_node_id,
        "continuation_manifest_ref": state.continuation_manifest_ref,
    }
    successor: dict[str, Any] = {
        "agent_name": successor_name,
        "role_suffix": suffix,
        "agent_session_role": pipe_role,
        "artifacts_dir": successor_artifacts_dir,
        "artifacts_timestamp": convert_timestamp_to_artifacts_format(timestamp),
        "launch_timestamp": timestamp,
        "launch_identity": launch_identity,
        "prompt_ref": str(prompt_path),
        "launch_prompt_ref": str(launch_prompt_path),
        "origin_prompt_ref": str(origin_prompt_path),
        "prompt_digest": successor_prompt_digest(successor_prompt),
        "launch_prompt_digest": successor_prompt_digest(launch_prompt),
        "prompt_artifact_label": "Piped prompt",
        "project_name": ctx.project_name,
        "project_file": ctx.project_file,
        "workspace_dir": ctx.workspace_dir,
        "workspace_num": ctx.workspace_num,
        "is_home_mode": ctx.is_home_mode,
        "cl_name": ctx.cl_name,
        "update_target": ctx.update_target,
        "history_sort_key": ctx.cl_name,
        "workflow_name": ctx.agent_name,
        "origin_artifacts_timestamp": ctx.artifacts_timestamp,
        "model": effective_model,
        "provider": effective_provider,
        "vcs_ref": vcs_ref,
        "relationships": relationships,
        "continuation_refs": {
            "provider_response_ref": str(
                Path(origin_dir) / STAGED_HANDOFF_RESPONSE_FILENAME
            ),
            "provider_response_digest": successor_prompt_digest(provider_response),
            "origin_prompt_ref": str(origin_prompt_path),
            "chat_path": None,
        },
        "loop_state": loop_state,
        "followup_model": _followup_model_record(followup_model),
        "attach_plan": attach_plan,
    }
    record = {
        "schema_version": 1,
        "staged_id": staged_id,
        "kind": "pipe",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "origin_artifacts_dir": origin_dir,
        "delivery_state": "prepared",
        "successor": successor,
    }
    return write_staged_successor_locked(record, artifacts_dir=origin_dir)


def _followup_model_record(model: FollowupModel | None) -> dict[str, Any] | None:
    if model is None:
        return None
    return {
        "model_prefix": model.model_prefix,
        "meta": list(model.meta) if model.meta is not None else None,
        "model_alias": model.model_alias,
        "model_alias_trail": list(model.model_alias_trail),
        "model_alias_origin": model.model_alias_origin,
    }


__all__ = [
    "prepare_staged_pipe_successor",
]
