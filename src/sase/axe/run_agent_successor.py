"""In-process agent-session-successor engine for the agent execution loop.

Plan-approval coder hand-off and questions follow-up both become the next
agent-session member with this six-step sequence. The order is load-bearing:

1. Bump ``state.agent_step`` and ``promote_to_workflow`` when the step
   reaches 2 and the agent is named. Promotion turns a lone agent into an
   agent-session root and must happen before follow-up artifacts are created.
2. Resolve the successor suffix: ``request.suffix`` verbatim, otherwise
   ``allocate_agent_session_child_suffix`` on ``request.suffix_template``,
   otherwise an unnamed-agent template render (``fallback_token``).
3. Set ``state.current_role_suffix``, then ``create_followup_artifacts``
   with ``agent_name_override=plan_chain_agent_name(...)``.
4. Write follow-up model metadata when ``request.model`` is set.
5. Set ``state.current_prompt`` to the request prompt.
6. ``store_followup_prompt_artifact`` under ``request.prompt_artifact_label``.

Callers assemble the prompt, relationships, and (for questions) the
promote role-suffix. This module only sequences the hand-off.

Optional hook kwargs honor caller-module test doubles: plan-accept and
questions tests patch ``create_followup_artifacts``,
``promote_to_workflow``, ``_store_followup_prompt_artifact``, and
``_write_followup_model_meta`` on those modules.
"""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.axe.agent_meta import write_agent_meta_atomic
from sase.axe.run_agent_exec_plan_artifacts import store_followup_prompt_artifact
from sase.axe.runner_lifecycle_phase import mark_lifecycle_phase
from sase.axe.run_agent_helpers import (
    create_followup_artifacts,
    promote_to_workflow,
    update_meta_field,
)
from sase.core.agent_artifact_index_lifecycle import (
    update_agent_artifact_index_for_marker_mutation,
)
from sase.plan_chain import (
    allocate_agent_session_child_suffix,
    plan_chain_agent_name,
)

STAGED_SUCCESSOR_ORIGIN_DIR_ENV = "SASE_STAGED_SUCCESSOR_ORIGIN_DIR"
STAGED_SUCCESSOR_ID_ENV = "SASE_STAGED_SUCCESSOR_ID"

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import AgentExecContext, LoopState

_PLAN_ACCEPT_MODULE = "sase.axe.run_agent_exec_plan_accept"


@dataclass(frozen=True)
class FollowupModel:
    """The follow-up agent's model directive prefix and metadata.

    ``model_prefix`` is prepended to the generated follow-up prompt (for
    example, ``"%model:codex/gpt-6.1-sol\\n"``). ``meta`` is the
    ``(provider_or_none, model)`` written to the follow-up's
    ``agent_meta.json``. It is ``None`` when the inherited planner metadata is
    already correct and does not need to be rewritten.
    """

    model_prefix: str
    meta: tuple[str | None, str] | None = None
    model_alias: str | None = None
    model_alias_trail: tuple[str, ...] = ()
    model_alias_origin: str | None = None


@dataclass(frozen=True)
class SuccessorRequest:
    """Inputs for :func:`continue_as_successor`.

    Exactly one of ``suffix`` or ``suffix_template`` must be set. An
    ``@``-bearing template is allocated when the agent is named and rendered
    with ``fallback_token`` when it is not.
    """

    base_meta: dict[str, Any]
    prompt: str
    suffix: str | None = None
    suffix_template: str | None = None
    extra_reserved_suffixes: tuple[str, ...] = ()
    agent_session_role: str | None = None
    relationships: dict[str, Any] = field(default_factory=dict)
    prompt_artifact_label: str = "Full follow-up prompt"
    model: FollowupModel | None = None
    promote_role_suffix: str | None = None
    fallback_token: str = "0"
    reserved_timestamp: str | None = None
    before_state_change: Callable[[str, str], None] | None = None
    before_create: Callable[[str, str], None] | None = None

    def __post_init__(self) -> None:
        if (self.suffix is None) == (self.suffix_template is None):
            raise ValueError("exactly one of suffix or suffix_template must be set")


@dataclass(frozen=True)
class SuccessorDeliveryResult:
    """Observed result of detached successor delivery."""

    state: str
    agent_name: str
    artifacts_dir: str
    pid: int | None = None
    reason: str | None = None


def _accept_binding[T](name: str, default: T) -> T:
    """Prefer a plan-accept module binding so its test doubles still apply."""
    module = sys.modules.get(_PLAN_ACCEPT_MODULE)
    if module is None:
        return default
    return getattr(module, name, default)


def _write_followup_model_alias_meta(
    artifacts_dir: str,
    model_alias: str | None,
    model_alias_trail: tuple[str, ...],
    model_alias_origin: str | None,
) -> None:
    """Set or clear the follow-up agent's launch-time alias provenance."""
    write_atomic = _accept_binding("write_agent_meta_atomic", write_agent_meta_atomic)
    index_updater = _accept_binding(
        "update_agent_artifact_index_for_marker_mutation",
        update_agent_artifact_index_for_marker_mutation,
    )
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        with meta_path.open(encoding="utf-8") as handle:
            meta = json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(meta, dict):
        return
    if model_alias:
        meta["model_alias"] = model_alias
    else:
        meta.pop("model_alias", None)
    if model_alias_trail:
        meta["model_alias_trail"] = list(model_alias_trail)
        if model_alias_origin:
            meta["model_alias_origin"] = model_alias_origin
        else:
            meta.pop("model_alias_origin", None)
    elif model_alias:
        meta.pop("model_alias_trail", None)
        if model_alias_origin:
            meta["model_alias_origin"] = model_alias_origin
        else:
            meta.pop("model_alias_origin", None)
    else:
        meta.pop("model_alias_trail", None)
        meta.pop("model_alias_origin", None)
    write_atomic(
        artifacts_dir,
        meta,
        index_updater=index_updater,
    )


def write_followup_model_meta(state: LoopState, followup: FollowupModel) -> None:
    """Record the follow-up agent's resolved model in its ``agent_meta.json``."""
    if followup.meta is None:
        return
    update = _accept_binding("update_meta_field", update_meta_field)
    resolved_provider, resolved_model = followup.meta
    update(state.current_artifacts_dir, "model", resolved_model)
    if resolved_provider:
        update(state.current_artifacts_dir, "llm_provider", resolved_provider)
    _write_followup_model_alias_meta(
        state.current_artifacts_dir,
        followup.model_alias,
        followup.model_alias_trail,
        followup.model_alias_origin,
    )


def _fallback_successor_suffix(template: str, *, token: str) -> str:
    from sase.agent.names import render_agent_name_template

    return render_agent_name_template(template, token)


def _resolved_suffix(
    ctx: AgentExecContext,
    request: SuccessorRequest,
) -> str:
    if request.suffix is not None:
        return request.suffix
    assert request.suffix_template is not None
    if ctx.agent_name:
        return allocate_agent_session_child_suffix(
            ctx.agent_name,
            request.suffix_template,
            extra_reserved_suffixes=request.extra_reserved_suffixes,
        )
    return _fallback_successor_suffix(
        request.suffix_template,
        token=request.fallback_token,
    )


def _explicit_autonomy_selection(prompt: str) -> str | None:
    """Extract the agent-authored ``%auto`` selection from a successor prompt.

    Returns ``""`` for bare ``%auto``, the argument for enabled spellings,
    ``"manual"`` for explicit ``:manual``/``:off``, and None when the prompt
    carries no ``%auto``. Invalid spellings fail closed to None (pure
    inherit); Python only extracts and transports, core decides narrowing.
    """
    try:
        from sase.macro.directives import extract_prompt_directives
    except Exception:
        return None
    try:
        _, directives = extract_prompt_directives(prompt)
    except Exception:
        return None
    try:
        if directives.auto_enabled and directives.auto_argument is not None:
            return str(directives.auto_argument)
        if directives.auto_enabled:
            return ""
        if bool(getattr(directives, "auto_present", False)):
            return "manual"
    except Exception:
        return None
    return None


def continue_as_successor(
    ctx: AgentExecContext,
    state: LoopState,
    request: SuccessorRequest,
    *,
    create_artifacts: Callable[..., str] | None = None,
    promote: Callable[..., None] | None = None,
    store_prompt: Callable[..., None] | None = None,
    write_model_meta: Callable[..., None] | None = None,
    staged_id: str | None = None,
    staged_kind: str | None = None,
) -> str | None:
    """Become the next in-process agent-session member and return its agent name."""
    if staged_id is not None:
        if staged_kind not in {"plan", "questions", "pipe"}:
            raise ValueError("staged successor kind must be plan, questions, or pipe")
        return _continue_as_staged_successor(
            ctx,
            state,
            request,
            staged_id=staged_id,
            staged_kind=staged_kind,
            create_artifacts=create_artifacts,
            promote=promote,
            store_prompt=store_prompt,
            write_model_meta=write_model_meta,
        )

    return _continue_as_successor(
        ctx,
        state,
        request,
        create_artifacts=create_artifacts,
        promote=promote,
        store_prompt=store_prompt,
        write_model_meta=write_model_meta,
    )


def _continue_as_successor(
    ctx: AgentExecContext,
    state: LoopState,
    request: SuccessorRequest,
    *,
    create_artifacts: Callable[..., str] | None = None,
    promote: Callable[..., None] | None = None,
    store_prompt: Callable[..., None] | None = None,
    write_model_meta: Callable[..., None] | None = None,
) -> str:
    """Run the ordinary in-process continuation after identity is chosen."""
    create = create_followup_artifacts if create_artifacts is None else create_artifacts
    promote_fn = promote_to_workflow if promote is None else promote
    store = store_followup_prompt_artifact if store_prompt is None else store_prompt
    write_model = (
        write_followup_model_meta if write_model_meta is None else write_model_meta
    )

    suffix = _resolved_suffix(ctx, request)
    successor_name = (
        plan_chain_agent_name(ctx.agent_name, suffix) if ctx.agent_name else suffix
    )
    if request.before_state_change is not None:
        request.before_state_change(suffix, successor_name)

    mark_lifecycle_phase(state.current_artifacts_dir, "handoff")
    state.agent_step += 1
    if state.agent_step == 2 and ctx.agent_name:
        if request.promote_role_suffix is None:
            promote_fn(ctx.artifacts_dir, ctx.agent_name)
        else:
            promote_fn(
                ctx.artifacts_dir,
                ctx.agent_name,
                role_suffix=request.promote_role_suffix,
            )

    state.current_role_suffix = suffix
    if request.before_create is not None:
        request.before_create(suffix, successor_name)
    relationships = dict(request.relationships or {})
    explicit_selection = _explicit_autonomy_selection(request.prompt)
    if (
        explicit_selection is not None
        and "autonomy_explicit_selection" not in relationships
    ):
        relationships["autonomy_explicit_selection"] = explicit_selection
    create_kwargs: dict[str, Any] = {
        "workspace_num": ctx.workspace_num,
        "agent_name_override": successor_name if ctx.agent_name else None,
        "workflow_name": ctx.agent_name,
        "relationships": relationships,
        "prev_artifacts_dir": state.current_artifacts_dir,
    }
    if request.agent_session_role is not None:
        create_kwargs["agent_session_role"] = request.agent_session_role
    if request.reserved_timestamp is not None:
        create_kwargs["timestamp"] = request.reserved_timestamp
    state.current_artifacts_dir = create(
        ctx.project_name,
        request.base_meta,
        suffix,
        convert_timestamp_to_artifacts_format(ctx.timestamp),
        **create_kwargs,
    )
    if request.model is not None:
        write_model(state, request.model)
    state.current_prompt = request.prompt
    store(
        state.current_artifacts_dir,
        state.current_prompt,
        label=request.prompt_artifact_label,
    )
    return successor_name


def _continue_as_staged_successor(
    ctx: AgentExecContext,
    state: LoopState,
    request: SuccessorRequest,
    *,
    staged_id: str,
    staged_kind: str,
    create_artifacts: Callable[..., str] | None,
    promote: Callable[..., None] | None,
    store_prompt: Callable[..., None] | None,
    write_model_meta: Callable[..., None] | None,
) -> str | None:
    """Persist a staged continuation identity before creating its next member."""
    from dataclasses import asdict, replace

    from sase.agent.staged_handoff import (
        StagedHandoffError,
        read_staged_successor,
        successor_prompt_digest,
        update_staged_successor_locked,
        write_staged_successor_locked,
        write_successor_prompt,
    )
    from sase.artifacts import (
        convert_timestamp_to_artifacts_format,
        launch_artifacts_dir,
    )
    from sase.core.agent_launch_facade import reserve_launch_timestamp_batch

    origin_dir = state.current_artifacts_dir
    existing = read_staged_successor(origin_dir, staged_id=staged_id)
    if existing is not None:
        successor = existing["successor"]
        if existing.get("kind") != staged_kind:
            raise StagedHandoffError("staged successor belongs to a different kind")
        if successor.get("prompt_digest") != successor_prompt_digest(request.prompt):
            raise StagedHandoffError(
                "staged successor continuation prompt differs from the persisted prompt"
            )
        if existing["delivery_state"] in {"submitted", "started", "terminal"}:
            return None
        destination = Path(str(successor["artifacts_dir"]))
        if destination.exists():
            meta = _read_successor_json(destination / "agent_meta.json")
            if meta is None:
                raise StagedHandoffError(
                    "staged successor artifacts exist without readable identity metadata"
                )
            if (
                meta.get("name") != successor["agent_name"]
                or meta.get("staged_handoff_id") != staged_id
                or meta.get("staged_successor_launch_id")
                != successor["launch_identity"]
            ):
                raise StagedHandoffError(
                    "staged successor artifacts do not match the persisted identity"
                )
            if existing["delivery_state"] == "prepared":
                existing = update_staged_successor_locked(
                    origin_dir, staged_id, delivery_state="created"
                )
            restore_staged_successor_in_loop(state, existing)
            saved_model = _staged_followup_model(successor.get("followup_model"))
            model = saved_model if "followup_model" in successor else request.model
            model_writer = (
                write_followup_model_meta
                if write_model_meta is None
                else write_model_meta
            )
            if model is not None:
                model_writer(state, model)
            prompt_store = (
                store_followup_prompt_artifact if store_prompt is None else store_prompt
            )
            prompt_label = successor.get("prompt_artifact_label")
            prompt_store(
                state.current_artifacts_dir,
                state.current_prompt,
                label=(
                    prompt_label
                    if isinstance(prompt_label, str)
                    else request.prompt_artifact_label
                ),
            )
            state.pending_staged_successor = {
                "origin_artifacts_dir": origin_dir,
                "staged_id": staged_id,
            }
            return str(successor["agent_name"])
        if existing["delivery_state"] != "prepared":
            raise StagedHandoffError(
                "staged successor artifacts disappeared after creation"
            )
        suffix = str(successor["role_suffix"])
        timestamp = str(successor["launch_timestamp"])
        relationships = successor.get("relationships")
        if not isinstance(relationships, Mapping):
            raise StagedHandoffError("staged successor relationships are malformed")
        stored_base_meta = successor.get("base_meta")
        stored_model = _staged_followup_model(successor.get("followup_model"))
        request = replace(
            request,
            base_meta=(
                dict(stored_base_meta)
                if isinstance(stored_base_meta, Mapping)
                else request.base_meta
            ),
            prompt=Path(str(successor["prompt_ref"])).read_text(encoding="utf-8"),
            suffix=suffix,
            suffix_template=None,
            reserved_timestamp=timestamp,
            agent_session_role=(
                successor.get("agent_session_role")
                if isinstance(successor.get("agent_session_role"), str)
                else request.agent_session_role
            ),
            relationships=dict(relationships),
            prompt_artifact_label=(
                successor.get("prompt_artifact_label")
                if isinstance(successor.get("prompt_artifact_label"), str)
                else request.prompt_artifact_label
            ),
            model=stored_model if "followup_model" in successor else request.model,
        )
    else:
        suffix = _resolved_suffix(ctx, request)
        timestamp = request.reserved_timestamp or reserve_launch_timestamp_batch(1)[0]
        successor = _build_staged_successor_identity(
            ctx,
            state,
            request,
            staged_id=staged_id,
            staged_kind=staged_kind,
            suffix=suffix,
            timestamp=timestamp,
            artifacts_dir=origin_dir,
            convert_timestamp=convert_timestamp_to_artifacts_format,
            launch_artifacts_dir=launch_artifacts_dir,
            write_successor_prompt=write_successor_prompt,
        )
        record = {
            "schema_version": 1,
            "staged_id": staged_id,
            "kind": staged_kind,
            "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "origin_artifacts_dir": origin_dir,
            "delivery_state": "prepared",
            "successor": successor,
        }
        persisted = write_staged_successor_locked(record, artifacts_dir=origin_dir)
        successor = persisted["successor"]
        request = replace(
            request,
            suffix=suffix,
            suffix_template=None,
            reserved_timestamp=timestamp,
            relationships=dict(successor["relationships"]),
        )

    successor_name = _continue_as_successor(
        ctx,
        state,
        request,
        create_artifacts=create_artifacts,
        promote=promote,
        store_prompt=store_prompt,
        write_model_meta=write_model_meta,
    )
    update_staged_successor_locked(
        origin_dir,
        staged_id,
        delivery_state="created",
    )
    state.pending_staged_successor = {
        "origin_artifacts_dir": origin_dir,
        "staged_id": staged_id,
    }
    return successor_name


def _build_staged_successor_identity(
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


def _staged_followup_model(value: Any) -> FollowupModel | None:
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
    meta = _read_successor_json(destination / "agent_meta.json")
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


def mark_staged_successor_started(
    origin_artifacts_dir: str,
    staged_id: str,
) -> bool:
    """Record provider-start evidence for a previously prepared successor."""
    from sase.agent.staged_handoff import (
        acquire_adoption_lock,
        read_staged_successor,
        update_staged_successor_locked,
    )

    with acquire_adoption_lock(Path(origin_artifacts_dir)):
        record = read_staged_successor(origin_artifacts_dir, staged_id=staged_id)
        if record is None:
            return False
        if record["delivery_state"] in {"started", "terminal"}:
            return True
        update_staged_successor_locked(
            origin_artifacts_dir,
            staged_id,
            delivery_state="started",
        )
        return True


def mark_detached_successor_started_from_environment() -> bool:
    """Consume detached-successor provenance and mark it before provider work."""
    origin = os.environ.pop(STAGED_SUCCESSOR_ORIGIN_DIR_ENV, None)
    staged_id = os.environ.pop(STAGED_SUCCESSOR_ID_ENV, None)
    if not isinstance(origin, str) or not origin:
        return False
    if not isinstance(staged_id, str) or not staged_id:
        return False
    if not mark_staged_successor_started(origin, staged_id):
        raise RuntimeError("detached staged successor identity is missing")
    return True


def _read_successor_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _successor_destination_observation(
    record: dict[str, Any],
) -> tuple[str, int | None, str | None]:
    """Inspect only durable metadata for an existing successor destination."""
    from sase.agent.process_tree import process_is_running
    from sase.core.process_identity import process_identity_matches

    successor = record["successor"]
    artifacts_dir = Path(successor["artifacts_dir"])
    if not artifacts_dir.exists():
        return "absent", None, None
    meta = _read_successor_json(artifacts_dir / "agent_meta.json")
    if meta is None:
        return (
            "unknown",
            None,
            "successor artifacts exist without readable agent metadata",
        )
    if (
        meta.get("name") != successor["agent_name"]
        or meta.get("staged_handoff_id") != record["staged_id"]
        or meta.get("staged_successor_launch_id") != successor["launch_identity"]
    ):
        return (
            "unknown",
            None,
            "successor artifacts do not match the persisted identity",
        )
    if (artifacts_dir / "done.json").is_file():
        return "terminal", None, None
    pid = meta.get("pid")
    if type(pid) is not int or pid <= 0:
        return "created", None, None
    identity = meta.get("process_identity")
    if process_is_running(pid) and process_identity_matches(pid, identity):
        return "live", pid, None
    return "dead", pid, None


def deliver_staged_successor_detached(
    origin_artifacts_dir: str,
    staged_id: str,
) -> SuccessorDeliveryResult:
    """Launch a recorded successor once through the normal detached runner path.

    The submitted marker is written before invoking the launcher. If the
    runner dies in that window, a later caller observes the same identity and
    holds for evidence instead of submitting a second provider turn.
    """
    from dataclasses import asdict

    from sase.agent.staged_handoff import (
        acquire_adoption_lock,
        read_staged_successor,
        update_staged_successor_locked,
    )

    origin = Path(origin_artifacts_dir)
    with acquire_adoption_lock(origin):
        record = read_staged_successor(str(origin), staged_id=staged_id)
        if record is None:
            return SuccessorDeliveryResult(
                "held", "", "", reason="staged successor identity is missing"
            )
        successor = record["successor"]
        agent_name = successor["agent_name"]
        artifacts_dir = successor["artifacts_dir"]
        observed, pid, reason = _successor_destination_observation(record)
        if observed == "terminal":
            if record["delivery_state"] != "terminal":
                update_staged_successor_locked(
                    str(origin), staged_id, delivery_state="terminal"
                )
            return SuccessorDeliveryResult("terminal", agent_name, artifacts_dir)
        if observed == "live":
            return SuccessorDeliveryResult("owned", agent_name, artifacts_dir, pid=pid)
        if observed == "unknown":
            return SuccessorDeliveryResult(
                "held", agent_name, artifacts_dir, reason=reason
            )
        if record["delivery_state"] in {"submitted", "started"}:
            return SuccessorDeliveryResult(
                "held",
                agent_name,
                artifacts_dir,
                pid=pid,
                reason=(
                    "successor launch was already submitted but no live or terminal "
                    "destination can be proven"
                ),
            )

        if observed == "dead" and record["delivery_state"] in {
            "prepared",
            "created",
        }:
            # The originating runner made the child artifacts, but no provider
            # start was recorded. Reuse that exact timestamp and directory.
            if record["delivery_state"] == "prepared":
                record = update_staged_successor_locked(
                    str(origin), staged_id, delivery_state="created"
                )
                successor = record["successor"]
        elif observed == "created":
            pass
        elif observed == "absent":
            if record["delivery_state"] != "prepared":
                return SuccessorDeliveryResult(
                    "held",
                    agent_name,
                    artifacts_dir,
                    reason="successor artifacts disappeared after creation",
                )
            source_meta = _read_successor_json(origin / "agent_meta.json")
            if source_meta is None:
                return SuccessorDeliveryResult(
                    "held",
                    agent_name,
                    artifacts_dir,
                    reason="origin agent metadata is unavailable",
                )
            from sase.axe.run_agent_helpers import create_followup_artifacts
            from sase.axe.run_agent_exec_plan_artifacts import (
                store_followup_prompt_artifact,
            )

            try:
                creation_meta = dict(source_meta)
                followup_model = successor.get("followup_model")
                if isinstance(followup_model, dict):
                    model_meta = followup_model.get("meta")
                    if (
                        isinstance(model_meta, list)
                        and len(model_meta) == 2
                        and all(
                            value is None or isinstance(value, str)
                            for value in model_meta
                        )
                        and isinstance(model_meta[1], str)
                    ):
                        creation_meta["model"] = model_meta[1]
                        if model_meta[0]:
                            creation_meta["llm_provider"] = model_meta[0]
                        model_alias = followup_model.get("model_alias")
                        model_alias_trail = followup_model.get("model_alias_trail")
                        model_alias_origin = followup_model.get("model_alias_origin")
                        if isinstance(model_alias, str) and model_alias:
                            creation_meta["model_alias"] = model_alias
                        else:
                            creation_meta.pop("model_alias", None)
                        if isinstance(model_alias_trail, list) and model_alias_trail:
                            creation_meta["model_alias_trail"] = model_alias_trail
                        else:
                            creation_meta.pop("model_alias_trail", None)
                        if isinstance(model_alias_origin, str) and model_alias_origin:
                            creation_meta["model_alias_origin"] = model_alias_origin
                        else:
                            creation_meta.pop("model_alias_origin", None)
                created = create_followup_artifacts(
                    successor["project_name"],
                    creation_meta,
                    successor["role_suffix"],
                    successor["origin_artifacts_timestamp"],
                    workspace_num=successor.get("workspace_num"),
                    agent_name_override=agent_name,
                    workflow_name=successor.get("workflow_name"),
                    agent_session_role=successor.get("agent_session_role"),
                    relationships=successor["relationships"],
                    stamp_creating_process=False,
                    prev_artifacts_dir=str(origin),
                    timestamp=successor["launch_timestamp"],
                )
                if str(Path(created)) != str(Path(artifacts_dir)):
                    raise RuntimeError(
                        "created successor artifacts do not match the persisted identity"
                    )
                prompt = _read_staged_launch_prompt(successor)
                store_followup_prompt_artifact(
                    created,
                    prompt,
                    label=successor.get("prompt_artifact_label") or "Piped prompt",
                )
            except Exception as exc:  # noqa: BLE001 - keep the stage recoverable.
                return SuccessorDeliveryResult(
                    "held",
                    agent_name,
                    artifacts_dir,
                    reason=f"successor preparation failed: {type(exc).__name__}: {exc}",
                )
            record = update_staged_successor_locked(
                str(origin), staged_id, delivery_state="created"
            )
            successor = record["successor"]
        else:
            return SuccessorDeliveryResult(
                "held",
                agent_name,
                artifacts_dir,
                reason="successor destination state is unknown",
            )

        # A created-but-not-submitted directory may still be owned by the
        # originating runner. Do not launch while that process is live.
        source_meta = _read_successor_json(origin / "agent_meta.json") or {}
        origin_pid = source_meta.get("pid")
        origin_identity = source_meta.get("process_identity")
        if type(origin_pid) is int and origin_pid > 0:
            from sase.agent.process_tree import process_is_running
            from sase.core.process_identity import process_identity_matches

            if process_is_running(origin_pid) and process_identity_matches(
                origin_pid, origin_identity
            ):
                return SuccessorDeliveryResult(
                    "held",
                    agent_name,
                    artifacts_dir,
                    reason="originating runner is still live and may own the continuation",
                )

        record = update_staged_successor_locked(
            str(origin), staged_id, delivery_state="submitted"
        )
        successor = record["successor"]
        try:
            prompt = _read_staged_launch_prompt(successor)
            vcs_ref_raw = successor.get("vcs_ref")
            vcs_ref: tuple[str, str] | None = None
            if isinstance(vcs_ref_raw, list) and len(vcs_ref_raw) == 2:
                vcs_ref = (str(vcs_ref_raw[0]), str(vcs_ref_raw[1]))
            extra_env = {
                STAGED_SUCCESSOR_ORIGIN_DIR_ENV: str(origin),
                STAGED_SUCCESSOR_ID_ENV: staged_id,
            }
            attach_data = successor.get("attach_plan")
            if isinstance(attach_data, dict):
                from sase.agent._agent_session_attach_types import (
                    AgentSessionAttachDirective,
                    AgentSessionAttachLaunchPlan,
                )
                from sase.agent.detached_child import spawn_agent_session_successor

                attach_plan = AgentSessionAttachLaunchPlan(**attach_data)
                directive = AgentSessionAttachDirective(
                    parent=attach_plan.parent_arg,
                    suffix=attach_plan.suffix_arg,
                )
                spawn_result = spawn_agent_session_successor(
                    directive,
                    project_name=successor["project_name"],
                    project_file=successor["project_file"],
                    prompt=prompt,
                    workspace_dir=successor["workspace_dir"],
                    workspace_num=successor.get("workspace_num") or 0,
                    transfer_from_pid=None,
                    cl_name=successor["cl_name"],
                    agent_session_role=successor.get("agent_session_role"),
                    update_target=successor.get("update_target") or "",
                    history_sort_key=successor.get("history_sort_key") or "",
                    is_home_mode=bool(successor.get("is_home_mode")),
                    vcs_ref=vcs_ref,
                    timestamp=successor["launch_timestamp"],
                    extra_env=extra_env,
                    resolve_plan=lambda *_args, **_kwargs: attach_plan,
                )
            else:
                from sase.agent.detached_child import spawn_detached_child

                spawn_result = spawn_detached_child(
                    project_name=successor["project_name"],
                    project_file=successor["project_file"],
                    prompt=prompt,
                    workspace_dir=successor["workspace_dir"],
                    workspace_num=successor.get("workspace_num") or 0,
                    cl_name=successor["cl_name"],
                    transfer_from_pid=None,
                    update_target=successor.get("update_target") or "",
                    history_sort_key=successor.get("history_sort_key") or "",
                    is_home_mode=bool(successor.get("is_home_mode")),
                    vcs_ref=vcs_ref,
                    timestamp=successor["launch_timestamp"],
                    extra_env={
                        **extra_env,
                        "SASE_AGENT_PLANNED_NAME": agent_name,
                    },
                )
        except Exception as exc:  # noqa: BLE001 - submitted is deliberately sticky.
            return SuccessorDeliveryResult(
                "held",
                agent_name,
                artifacts_dir,
                reason=f"successor launch outcome is uncertain: {type(exc).__name__}: {exc}",
            )
        update_staged_successor_locked(
            str(origin),
            staged_id,
            delivery_state="submitted",
            updates={"launch_pid": int(spawn_result.pid)},
        )
        return SuccessorDeliveryResult(
            "submitted",
            agent_name,
            artifacts_dir,
            pid=int(spawn_result.pid),
        )


def _read_staged_launch_prompt(successor: dict[str, Any]) -> str:
    """Read the exact prompt destined for a detached successor launch."""
    prompt_ref = successor.get("launch_prompt_ref") or successor.get("prompt_ref")
    if not isinstance(prompt_ref, str) or not prompt_ref:
        raise RuntimeError("persisted staged successor launch prompt is missing")
    prompt = Path(prompt_ref).read_text(encoding="utf-8")
    expected = successor.get("launch_prompt_digest")
    if expected is not None:
        from sase.agent.staged_handoff import successor_prompt_digest

        if expected != successor_prompt_digest(prompt):
            raise RuntimeError(
                "persisted staged successor launch prompt digest differs"
            )
    return prompt


__all__ = [
    "FollowupModel",
    "SuccessorRequest",
    "SuccessorDeliveryResult",
    "STAGED_SUCCESSOR_ID_ENV",
    "STAGED_SUCCESSOR_ORIGIN_DIR_ENV",
    "continue_as_successor",
    "deliver_staged_successor_detached",
    "mark_detached_successor_started_from_environment",
    "mark_staged_successor_started",
    "write_followup_model_meta",
]
