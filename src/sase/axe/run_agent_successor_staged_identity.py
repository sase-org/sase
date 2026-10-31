"""Staged successor identity construction and loop restoration."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.axe._run_agent_successor_shared import read_successor_json
from sase.plan_chain import plan_chain_agent_name

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import AgentExecContext, LoopState
    from sase.axe.run_agent_successor_types import FollowupModel, SuccessorRequest


def build_staged_successor_identity(
    ctx: AgentExecContext,
    state: LoopState,
    request: SuccessorRequest,
    *,
    staged_id: str,
    staged_kind: str,
    suffix: str,
    timestamp: str,
    artifacts_dir: str,
    convert_timestamp: Callable[[str], str],
    launch_artifacts_dir: Callable[[str, str], str],
    write_successor_prompt: Callable[..., Path],
) -> dict[str, Any]:
    """Build the persisted identity record for a staged successor."""
    from dataclasses import asdict

    from sase.agent.staged_handoff import (
        STAGED_HANDOFF_RESPONSE_FILENAME,
        STAGED_SUCCESSOR_ORIGIN_PROMPT_FILENAME,
        successor_prompt_digest,
    )

    successor_name = (
        plan_chain_agent_name(ctx.agent_name, suffix) if ctx.agent_name else suffix
    )
    launch_identity = f"{staged_id}:{timestamp}"
    relationships = dict(request.relationships)
    relationships["staged_handoff_id"] = staged_id
    relationships["staged_successor_launch_id"] = launch_identity
    prompt_path = write_successor_prompt(artifacts_dir, request.prompt)
    origin_prompt_path = write_successor_prompt(
        artifacts_dir,
        state.current_prompt,
        filename=STAGED_SUCCESSOR_ORIGIN_PROMPT_FILENAME,
    )
    destination = launch_artifacts_dir(ctx.project_name, timestamp)

    attach_plan: dict[str, Any] | None = None
    if ctx.agent_name:
        from dataclasses import replace as dataclass_replace

        from sase.agent._agent_session_attach_resolution import (
            resolve_agent_session_attach_plan,
        )
        from sase.agent._agent_session_attach_types import AgentSessionAttachDirective

        resolved = resolve_agent_session_attach_plan(
            AgentSessionAttachDirective(parent=ctx.agent_name, suffix=suffix),
            project_name=ctx.project_name,
        )
        if resolved.agent_name != successor_name:
            raise RuntimeError("staged successor differs from the host attach identity")
        attach_plan = asdict(
            dataclass_replace(resolved, parent_is_running=False, host_composed=True)
        )

    model = request.model.meta[1] if request.model and request.model.meta else None
    provider = request.model.meta[0] if request.model and request.model.meta else None
    if model is None:
        candidate = request.base_meta.get("model")
        model = candidate if isinstance(candidate, str) and candidate else None
    if provider is None:
        candidate = request.base_meta.get("llm_provider")
        provider = candidate if isinstance(candidate, str) and candidate else None
    vcs_ref = request.base_meta.get("vcs_ref")
    if not (
        isinstance(vcs_ref, (list, tuple))
        and len(vcs_ref) == 2
        and all(isinstance(value, str) and value for value in vcs_ref)
    ):
        vcs_ref = None
    continuation_refs: dict[str, Any] = {"origin_prompt_ref": str(origin_prompt_path)}
    response_path = Path(artifacts_dir) / STAGED_HANDOFF_RESPONSE_FILENAME
    if response_path.is_file():
        continuation_refs["provider_response_ref"] = str(response_path)
        try:
            continuation_refs["provider_response_digest"] = successor_prompt_digest(
                response_path.read_text(encoding="utf-8")
            )
        except OSError:
            pass

    loop_state = _serialize_staged_loop_state(
        state,
        successor_dir=destination,
        suffix=suffix,
        prompt_ref=str(prompt_path),
        prompt=request.prompt,
    )
    followup_model = None
    if request.model is not None:
        followup_model = {
            "model_prefix": request.model.model_prefix,
            "meta": list(request.model.meta)
            if request.model.meta is not None
            else None,
            "model_alias": request.model.model_alias,
            "model_alias_trail": list(request.model.model_alias_trail),
            "model_alias_origin": request.model.model_alias_origin,
        }

    return {
        "agent_name": successor_name,
        "role_suffix": suffix,
        "agent_session_role": request.agent_session_role,
        "artifacts_dir": destination,
        "artifacts_timestamp": convert_timestamp(timestamp),
        "launch_timestamp": timestamp,
        "launch_identity": launch_identity,
        "prompt_ref": str(prompt_path),
        "launch_prompt_ref": str(prompt_path),
        "origin_prompt_ref": str(origin_prompt_path),
        "prompt_digest": successor_prompt_digest(request.prompt),
        "launch_prompt_digest": successor_prompt_digest(request.prompt),
        "prompt_artifact_label": request.prompt_artifact_label,
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
        "model": model,
        "provider": provider,
        "vcs_ref": list(vcs_ref) if vcs_ref is not None else None,
        "relationships": relationships,
        "continuation_refs": continuation_refs,
        "loop_state": loop_state,
        "followup_model": followup_model,
        "attach_plan": attach_plan,
        "base_meta": dict(request.base_meta),
        "successor_kind": staged_kind,
    }


def _serialize_staged_loop_state(
    state: LoopState,
    *,
    successor_dir: str,
    suffix: str,
    prompt_ref: str,
    prompt: str,
) -> dict[str, Any]:
    from dataclasses import asdict, is_dataclass

    qa_rounds = []
    for round_ in state.qa_rounds:
        if is_dataclass(round_):
            qa_rounds.append(asdict(round_))
        elif isinstance(round_, Mapping):
            qa_rounds.append(dict(round_))
    return {
        "agent_step": state.agent_step + 1,
        "current_role_suffix": suffix,
        "current_artifacts_dir": successor_dir,
        "prompt_ref": prompt_ref,
        "question_base_prompt_ref": prompt_ref,
        "question_base_prompt": prompt,
        "original_prompt": state.original_prompt,
        "sdd_spec_path": state.sdd_spec_path,
        "qa_rounds": qa_rounds,
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


def staged_followup_model(value: Any) -> FollowupModel | None:
    """Decode a persisted follow-up model record."""
    from sase.axe.run_agent_successor_types import FollowupModel

    if not isinstance(value, Mapping):
        return None
    raw_meta = value.get("meta")
    meta = (
        (raw_meta[0], raw_meta[1])
        if isinstance(raw_meta, list)
        and len(raw_meta) == 2
        and all(item is None or isinstance(item, str) for item in raw_meta)
        and isinstance(raw_meta[1], str)
        else None
    )
    trail = value.get("model_alias_trail")
    prefix = value.get("model_prefix")
    return FollowupModel(
        model_prefix=prefix if isinstance(prefix, str) else "",
        meta=meta,
        model_alias=(
            value.get("model_alias")
            if isinstance(value.get("model_alias"), str)
            else None
        ),
        model_alias_trail=(
            tuple(item for item in trail if isinstance(item, str))
            if isinstance(trail, list)
            else ()
        ),
        model_alias_origin=(
            value.get("model_alias_origin")
            if isinstance(value.get("model_alias_origin"), str)
            else None
        ),
    )


def restore_staged_successor_in_loop(
    state: LoopState, record: Mapping[str, Any]
) -> None:
    """Restore a prepared plan/question/pipe successor into a live loop."""
    successor = record.get("successor")
    if not isinstance(successor, Mapping):
        raise RuntimeError("staged successor identity is malformed")
    loop_state = successor.get("loop_state")
    if not isinstance(loop_state, Mapping):
        raise RuntimeError("staged successor loop state is malformed")
    prompt_path = successor.get("prompt_ref")
    if not isinstance(prompt_path, str) or not prompt_path:
        raise RuntimeError("staged successor prompt reference is missing")
    prompt = Path(prompt_path).read_text(encoding="utf-8")
    destination = Path(str(successor.get("artifacts_dir") or ""))
    meta = read_successor_json(destination / "agent_meta.json")
    if meta is None:
        raise RuntimeError("staged successor artifacts have no readable metadata")
    if (
        meta.get("name") != successor.get("agent_name")
        or meta.get("staged_handoff_id") != record.get("staged_id")
        or meta.get("staged_successor_launch_id") != successor.get("launch_identity")
    ):
        raise RuntimeError("staged successor artifacts do not match the manifest")
    from sase.main.qa_markdown import QARound

    raw_rounds = loop_state.get("qa_rounds")
    rounds = []
    if isinstance(raw_rounds, list):
        for item in raw_rounds:
            if isinstance(item, Mapping):
                questions = item.get("questions")
                answers = item.get("answers")
                if isinstance(questions, list) and isinstance(answers, list):
                    note = item.get("global_note")
                    rounds.append(
                        QARound(
                            questions=questions,
                            answers=answers,
                            global_note=note if isinstance(note, str) else None,
                        )
                    )
    state.agent_step = int(loop_state.get("agent_step") or state.agent_step + 1)
    state.current_role_suffix = str(successor["role_suffix"])
    state.current_artifacts_dir = str(successor["artifacts_dir"])
    state.current_prompt = prompt
    state.question_base_prompt = str(loop_state.get("question_base_prompt") or prompt)
    state.original_prompt = str(
        loop_state.get("original_prompt") or state.original_prompt
    )
    state.sdd_spec_path = loop_state.get("sdd_spec_path")
    state.qa_rounds = rounds
    raw_bullets = loop_state.get("feedback_bullets")
    state.feedback_bullets = (
        [item for item in raw_bullets if isinstance(item, str)]
        if isinstance(raw_bullets, list)
        else []
    )
    state.feedback_round = int(loop_state.get("feedback_round") or 0)
    state.original_agent_timestamp = loop_state.get("original_agent_timestamp")
    state.question_gate_artifacts_dir = loop_state.get("question_gate_artifacts_dir")
    state.plan_gate_artifacts_dir = loop_state.get("plan_gate_artifacts_dir")
    state.loop_outcome = str(loop_state.get("loop_outcome") or state.loop_outcome)
    state.kill_source = loop_state.get("kill_source")
    kill_evidence = loop_state.get("kill_evidence")
    state.kill_evidence = (
        dict(kill_evidence) if isinstance(kill_evidence, Mapping) else None
    )
    raw_chats = loop_state.get("saved_chat_paths")
    state.saved_chat_paths = (
        [
            (item[0], item[1])
            for item in raw_chats
            if isinstance(item, list)
            and len(item) == 2
            and all(isinstance(part, str) for part in item)
        ]
        if isinstance(raw_chats, list)
        else []
    )
    for field_name in (
        "continuation_workspace_ref",
        "continuation_prepared_ref",
        "continuation_node_id",
        "continuation_manifest_ref",
    ):
        value = loop_state.get(field_name)
        setattr(state, field_name, value if isinstance(value, str) else None)
    origin = record.get("origin_artifacts_dir")
    staged_id = record.get("staged_id")
    if isinstance(origin, str) and isinstance(staged_id, str):
        state.pending_staged_successor = {
            "origin_artifacts_dir": origin,
            "staged_id": staged_id,
        }


__all__ = [
    "build_staged_successor_identity",
    "restore_staged_successor_in_loop",
    "staged_followup_model",
]
