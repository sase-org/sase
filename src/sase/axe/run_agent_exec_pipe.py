"""Pipe marker handling for the agent execution loop."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.axe.run_agent_exec_plan_accept_models import (
    resolve_model_alias_provenance,
    resolve_model_meta,
)
from sase.axe.run_agent_exec_plan_artifacts import store_followup_prompt_artifact
from sase.axe.run_agent_helpers import (
    create_followup_artifacts,
    finalize_handoff_artifacts_as_completed,
    normalize_handoff_interruption_state,
    promote_to_workflow,
    update_meta_field,
    update_step_marker_chat_path,
)
from sase.axe.run_agent_successor import (
    FollowupModel,
    SuccessorRequest,
    continue_as_successor,
)
from sase.agent.staged_handoff import (
    STAGED_HANDOFF_RESPONSE_FILENAME,
    STAGED_SUCCESSOR_ORIGIN_PROMPT_FILENAME,
    read_staged_successor,
    successor_prompt_digest,
    update_staged_successor_locked,
    write_staged_successor_locked,
    write_successor_prompt,
)
from sase.axe.runner_lifecycle_phase import mark_lifecycle_phase
from sase.axe.runner_signals import reset_killed
from sase.history.chat import save_chat_history
from sase.history.chat_extras import format_extra_sections
from sase.llm_provider.config import (
    format_model_directive_value,
    normalize_model_alias_reference,
)
from sase.plan_chain import (
    allocate_agent_session_child_suffix,
    plan_chain_agent_name,
)
from sase.core.agent_launch_facade import reserve_launch_timestamp_batch

if TYPE_CHECKING:
    from sase.axe.run_agent_exec import AgentExecContext, LoopState

_store_followup_prompt_artifact = store_followup_prompt_artifact


def handle_pipe_marker(
    pipe_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    """Adopt a ``.sase_pipe_pending`` marker after runner SIGTERM.

    Returns ``None`` so the execution loop runs the successor.
    """
    return _handle_pipe_handoff(
        pipe_data,
        ctx,
        state,
        provider_response=None,
        interrupted=True,
    )


def handle_staged_pipe_marker(
    pipe_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
    *,
    provider_response: str,
    staged_id: str,
) -> str | None:
    """Adopt a settled staged pipe handoff without the legacy kill."""
    return _handle_pipe_handoff(
        pipe_data,
        ctx,
        state,
        provider_response=provider_response,
        interrupted=False,
        staged_id=staged_id,
    )


def _handle_pipe_handoff(
    pipe_data: dict[str, Any],
    ctx: AgentExecContext,
    state: LoopState,
    *,
    provider_response: str | None,
    interrupted: bool,
    staged_id: str | None = None,
) -> str | None:
    parent_dir = state.current_artifacts_dir
    staged_plan: dict[str, Any] | None = None
    if staged_id is not None:
        staged_plan = _prepare_staged_pipe_successor(
            pipe_data,
            ctx,
            state,
            staged_id=staged_id,
            provider_response=provider_response or "",
        )
    mark_lifecycle_phase(parent_dir, "handoff")
    if interrupted:
        normalize_handoff_interruption_state(parent_dir)
    finalize_handoff_artifacts_as_completed(parent_dir)
    base_meta = _interrupted_phase_meta(parent_dir, ctx.agent_meta)
    parent_name = _text(base_meta.get("name")) or ctx.agent_name
    name_token = _text(pipe_data.get("name_token"))
    fresh = bool(pipe_data.get("fresh"))
    reason = _text(pipe_data.get("reason"))
    model_spec = _text(pipe_data.get("model"))
    piped_prompt = pipe_data.get("prompt")
    if not isinstance(piped_prompt, str):
        piped_prompt = ""
    current_depth = _pipe_depth(pipe_data, base_meta)

    if staged_plan is not None:
        planned_successor = staged_plan["successor"]
        suffix = planned_successor["role_suffix"]
        successor_name = planned_successor["agent_name"]
        pipe_role = planned_successor.get("agent_session_role") or "feedback"
        followup_model = _followup_model_from_record(planned_successor)
        successor_prompt = _read_successor_prompt(planned_successor)
    else:
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

    extra = format_extra_sections(parent_dir)
    pipe_summary = _format_pipe_response(
        successor_name=successor_name,
        reason=reason,
        piped_prompt=piped_prompt,
    )
    if provider_response is None:
        response_content = pipe_summary
    else:
        response_content = provider_response
        sections = [
            section
            for section in (extra, f"## Pipe Hand-off\n\n{pipe_summary.strip()}")
            if isinstance(section, str) and section.strip()
        ]
        extra = "\n\n".join(sections) or None
    chat_path = None
    if staged_plan is not None:
        existing_chat = staged_plan["successor"]["continuation_refs"].get("chat_path")
        if isinstance(existing_chat, str) and existing_chat:
            chat_path = existing_chat
    if chat_path is None:
        chat_path = save_chat_history(
            prompt=state.current_prompt,
            response=response_content,
            workflow="ace-run",
            agent=parent_name,
            timestamp=ctx.timestamp,
            extra_sections=extra,
            branch_or_workspace=ctx.cl_name,
            metadata_agent=parent_name,
            metadata_model=ctx.agent_model,
            metadata_llm_provider=ctx.agent_llm_provider,
            metadata_multi_agent_prompt=ctx.multi_agent_prompt_file,
        )
        if staged_plan is not None:
            planned_successor = staged_plan["successor"]
            continuation_refs = {
                **planned_successor["continuation_refs"],
                "chat_path": chat_path,
            }
            loop_state = dict(planned_successor["loop_state"])
            saved_chat_paths = list(loop_state.get("saved_chat_paths") or [])
            saved_chat_paths.append([state.current_role_suffix, chat_path])
            loop_state["saved_chat_paths"] = saved_chat_paths
            staged_plan = update_staged_successor_locked(
                parent_dir,
                staged_id or "",
                delivery_state=staged_plan["delivery_state"],
                updates={
                    "continuation_refs": continuation_refs,
                    "loop_state": loop_state,
                },
            )
    if not any(path == chat_path for _suffix, path in state.saved_chat_paths):
        state.saved_chat_paths.append((state.current_role_suffix, chat_path))
    update_meta_field(parent_dir, "chat_path", chat_path)
    update_step_marker_chat_path(parent_dir, chat_path)

    if staged_plan is None:
        followup_model = _resolve_pipe_model(model_spec) if model_spec else None
        successor_prompt = _build_pipe_successor_prompt(
            piped_prompt,
            parent_name=parent_name,
            fresh=fresh,
            model_prefix=followup_model.model_prefix if followup_model else "",
        )
    if staged_plan is None or staged_plan["delivery_state"] in {"prepared"}:
        request = SuccessorRequest(
            base_meta=base_meta,
            prompt=successor_prompt,
            suffix=suffix,
            reserved_timestamp=(
                staged_plan["successor"]["launch_timestamp"]
                if staged_plan is not None
                else None
            ),
            extra_reserved_suffixes=tuple(
                saved_suffix
                for saved_suffix, _path in state.saved_chat_paths
                if saved_suffix
            ),
            agent_session_role=pipe_role,
            relationships=(
                staged_plan["successor"]["relationships"]
                if staged_plan is not None
                else {
                    "piped_from": parent_name,
                    "pipe_reason": reason,
                    "pipe_depth": current_depth + 1,
                    "patch_name": ctx.cl_name,
                    "changespec_name": ctx.cl_name,
                }
            ),
            prompt_artifact_label="Piped prompt",
            model=followup_model,
            before_state_change=(
                (
                    lambda chosen_suffix, chosen_name: _assert_staged_pipe_identity(
                        staged_plan, chosen_suffix, chosen_name
                    )
                )
                if staged_plan is not None
                else None
            ),
        )
        continue_as_successor(
            ctx,
            state,
            request,
            create_artifacts=create_followup_artifacts,
            promote=promote_to_workflow,
            store_prompt=_store_followup_prompt_artifact,
        )
        state.question_base_prompt = state.current_prompt
        if staged_plan is not None:
            successor_dir = staged_plan["successor"]["artifacts_dir"]
            if str(Path(state.current_artifacts_dir)) != str(Path(successor_dir)):
                raise RuntimeError(
                    "pipe successor artifacts differ from the persisted identity"
                )
            update_staged_successor_locked(
                parent_dir,
                staged_id or "",
                delivery_state="created",
            )
            state.pending_staged_successor = {
                "origin_artifacts_dir": parent_dir,
                "staged_id": staged_id or "",
            }
    elif staged_plan["delivery_state"] in {"created"}:
        _restore_staged_pipe_loop_state(state, staged_plan)
    else:
        raise RuntimeError(
            "staged pipe successor is already submitted and cannot be adopted inline"
        )
    if interrupted:
        reset_killed()
    return None


def _build_pipe_successor_prompt(
    piped_prompt: str,
    *,
    parent_name: str | None,
    fresh: bool,
    model_prefix: str = "",
) -> str:
    """Assemble the successor prompt: model, optional fork, then piped text."""
    parts: list[str] = []
    if model_prefix:
        prefix = model_prefix if model_prefix.endswith("\n") else f"{model_prefix}\n"
        parts.append(prefix)
    if not fresh and parent_name:
        parts.append(f"#fork:{parent_name}\n")
    parts.append(piped_prompt)
    return "".join(parts)


def _resolve_pipe_model(model_spec: str) -> FollowupModel:
    directive = format_model_directive_value(model_spec)
    model_alias, _ = normalize_model_alias_reference(directive)
    trail, origin = resolve_model_alias_provenance(directive)
    return FollowupModel(
        model_prefix=f"%model:{directive}\n",
        meta=resolve_model_meta(directive),
        model_alias=model_alias,
        model_alias_trail=trail,
        model_alias_origin=origin,
    )


def _format_pipe_response(
    *,
    successor_name: str,
    reason: str | None,
    piped_prompt: str,
) -> str:
    lines = [
        "# Pipe hand-off",
        "",
        "This agent handed the remaining work to its next agent-session member.",
        f"Successor: {successor_name}",
    ]
    if reason:
        lines.extend(["", "Reason:", "", reason])
    if piped_prompt:
        lines.extend(["", "Piped prompt:", "", piped_prompt])
    return "\n".join(lines).rstrip() + "\n"


def _interrupted_phase_meta(
    artifacts_dir: str,
    fallback_meta: dict[str, Any],
) -> dict[str, Any]:
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        loaded = json.loads(meta_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return fallback_meta
    return loaded if isinstance(loaded, dict) and loaded else fallback_meta


def _pipe_depth(pipe_data: dict[str, Any], base_meta: dict[str, Any]) -> int:
    for source in (pipe_data, base_meta):
        raw = source.get("pipe_depth")
        if type(raw) is int and raw >= 0:
            return raw
    return 0


def _prepare_staged_pipe_successor(
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
        prompt = _read_successor_prompt(existing_successor)
        target = Path(existing_successor["artifacts_dir"])
        if target.exists():
            meta = _read_json_meta(target / "agent_meta.json")
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

    base_meta = _interrupted_phase_meta(origin_dir, ctx.agent_meta)
    parent_name = _text(base_meta.get("name")) or ctx.agent_name
    name_token = _text(pipe_data.get("name_token"))
    reason = _text(pipe_data.get("reason"))
    fresh = bool(pipe_data.get("fresh"))
    model_spec = _text(pipe_data.get("model"))
    piped_prompt = pipe_data.get("prompt")
    if not isinstance(piped_prompt, str):
        piped_prompt = ""
    current_depth = _pipe_depth(pipe_data, base_meta)

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
    followup_model = _resolve_pipe_model(model_spec) if model_spec else None
    successor_prompt = _build_pipe_successor_prompt(
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
        else _text(base_meta.get("model")) or ctx.agent_model
    )
    effective_provider = (
        followup_model.meta[0]
        if followup_model is not None and followup_model.meta is not None
        else _text(base_meta.get("llm_provider")) or ctx.agent_llm_provider
    )
    if followup_model is None and effective_model:
        directive = (
            f"{effective_provider}/{effective_model}"
            if effective_provider
            else effective_model
        )
        launch_prefix = format_model_directive_value(directive)
        launch_prompt = _build_pipe_successor_prompt(
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


def _followup_model_from_record(successor: Mapping[str, Any]) -> FollowupModel | None:
    raw = successor.get("followup_model")
    if not isinstance(raw, Mapping):
        return None
    meta_raw = raw.get("meta")
    meta = (
        (meta_raw[0], meta_raw[1])
        if isinstance(meta_raw, list)
        and len(meta_raw) == 2
        and all(value is None or isinstance(value, str) for value in meta_raw)
        else None
    )
    trail = raw.get("model_alias_trail")
    return FollowupModel(
        model_prefix=str(raw.get("model_prefix") or ""),
        meta=meta,
        model_alias=(
            raw.get("model_alias") if isinstance(raw.get("model_alias"), str) else None
        ),
        model_alias_trail=tuple(value for value in trail if isinstance(value, str))
        if isinstance(trail, list)
        else (),
        model_alias_origin=(
            raw.get("model_alias_origin")
            if isinstance(raw.get("model_alias_origin"), str)
            else None
        ),
    )


def _read_successor_prompt(successor: Mapping[str, Any]) -> str:
    path = Path(str(successor["prompt_ref"]))
    prompt = path.read_text(encoding="utf-8")
    if successor.get("prompt_digest") != successor_prompt_digest(prompt):
        raise RuntimeError("persisted pipe successor prompt digest does not match")
    return prompt


def _assert_staged_pipe_identity(
    record: Mapping[str, Any],
    suffix: str,
    successor_name: str,
) -> None:
    successor = record["successor"]
    if suffix != successor["role_suffix"] or successor_name != successor["agent_name"]:
        raise RuntimeError("pipe successor identity changed after it was persisted")


def _restore_staged_pipe_loop_state(
    state: LoopState,
    record: Mapping[str, Any],
) -> None:
    successor = record["successor"]
    artifacts_dir = str(successor["artifacts_dir"])
    meta = _read_json_meta(Path(artifacts_dir) / "agent_meta.json")
    if meta is None or meta.get("name") != successor["agent_name"]:
        raise RuntimeError("persisted pipe successor destination cannot be proven")
    if (
        meta.get("staged_handoff_id") != record["staged_id"]
        or meta.get("staged_successor_launch_id") != successor["launch_identity"]
    ):
        raise RuntimeError("pipe successor destination belongs to another handoff")
    prompt = _read_successor_prompt(successor)
    loop_state = successor["loop_state"]
    agent_step = loop_state.get("agent_step")
    role_suffix = loop_state.get("current_role_suffix")
    if type(agent_step) is not int or not isinstance(role_suffix, str):
        raise RuntimeError("persisted pipe successor loop identity is malformed")
    state.agent_step = agent_step
    state.current_role_suffix = role_suffix
    state.current_artifacts_dir = artifacts_dir
    state.current_prompt = prompt
    state.question_base_prompt = prompt
    original_prompt = loop_state.get("original_prompt")
    if isinstance(original_prompt, str):
        state.original_prompt = original_prompt
    sdd_spec_path = loop_state.get("sdd_spec_path")
    state.sdd_spec_path = sdd_spec_path if isinstance(sdd_spec_path, str) else None
    from sase.main.qa_markdown import QARound

    qa_rounds = loop_state.get("qa_rounds")
    if isinstance(qa_rounds, list):
        if not all(isinstance(item, dict) for item in qa_rounds):
            raise RuntimeError("persisted pipe successor Q&A state is malformed")
        state.qa_rounds = [QARound(**item) for item in qa_rounds]
    feedback_bullets = loop_state.get("feedback_bullets")
    if isinstance(feedback_bullets, list):
        if not all(isinstance(item, str) for item in feedback_bullets):
            raise RuntimeError("persisted pipe successor feedback state is malformed")
        state.feedback_bullets = list(feedback_bullets)
    feedback_round = loop_state.get("feedback_round")
    if type(feedback_round) is int:
        state.feedback_round = feedback_round
    original_agent_timestamp = loop_state.get("original_agent_timestamp")
    if original_agent_timestamp is None or isinstance(original_agent_timestamp, str):
        state.original_agent_timestamp = original_agent_timestamp
    for field in ("question_gate_artifacts_dir", "plan_gate_artifacts_dir"):
        value = loop_state.get(field)
        setattr(state, field, value if isinstance(value, str) else None)
    loop_outcome = loop_state.get("loop_outcome")
    if isinstance(loop_outcome, str):
        state.loop_outcome = loop_outcome
    kill_source = loop_state.get("kill_source")
    state.kill_source = kill_source if isinstance(kill_source, str) else None
    kill_evidence = loop_state.get("kill_evidence")
    state.kill_evidence = kill_evidence if isinstance(kill_evidence, dict) else None
    paths = loop_state.get("saved_chat_paths")
    if isinstance(paths, list):
        state.saved_chat_paths = [
            (str(item[0]), str(item[1]))
            for item in paths
            if isinstance(item, list)
            and len(item) == 2
            and all(isinstance(value, str) for value in item)
        ]
    for field in (
        "continuation_workspace_ref",
        "continuation_prepared_ref",
        "continuation_node_id",
        "continuation_manifest_ref",
    ):
        setattr(state, field, loop_state.get(field))
    state.pending_staged_successor = {
        "origin_artifacts_dir": record["origin_artifacts_dir"],
        "staged_id": record["staged_id"],
    }


def restore_staged_pipe_successor(
    state: LoopState,
    record: Mapping[str, Any],
) -> None:
    """Restore an adopted pipe's saved successor without allocating again."""
    _restore_staged_pipe_loop_state(state, record)


def _read_json_meta(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "handle_pipe_marker",
    "handle_staged_pipe_marker",
]
