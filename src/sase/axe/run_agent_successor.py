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
from collections.abc import Callable
from dataclasses import dataclass, field
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
) -> str:
    """Become the next in-process agent-session member and return its agent name."""
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
