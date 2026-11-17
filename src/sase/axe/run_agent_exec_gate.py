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
    *,
    response: str | None = None,
) -> str:
    """Adopt a staged gate-turn handoff for the execution loop.

    ``response`` is the already-persisted real model reply recorded as the
    continuation delta's final response; it is never overwritten by a summary.
    """
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

    _publish_gate_handoff_continuation(
        gate_data,
        gate_id=gate_id,
        member_artifacts_dir=member_artifacts_dir,
        member_agent_name=member_agent_name,
        starter_agent=starter_agent,
        starter_meta=starter_meta,
        ctx=ctx,
        state=state,
        response=response,
    )

    reset_killed()
    return "gated"


def _publish_gate_handoff_continuation(
    gate_data: dict[str, Any],
    *,
    gate_id: str | None,
    member_artifacts_dir: str | None,
    member_agent_name: str | None,
    starter_agent: str | None,
    starter_meta: dict[str, Any],
    ctx: Any,
    state: Any,
    response: str | None,
) -> None:
    """Publish the starter's ``agent_delta`` node for a gate handoff.

    Best-effort: failures are recorded to ``continuation/capture_errors.jsonl``
    and adoption still returns ``"gated"``. Without a node, replay degrades to
    today's legacy boundary, which is not worse.
    """
    artifacts_dir: str | None = getattr(state, "current_artifacts_dir", None)
    try:
        if not artifacts_dir:
            return
        if _reused_gate_handoff_node(
            artifacts_dir,
            starter_meta=starter_meta,
            gate_id=gate_id,
            member_artifacts_dir=member_artifacts_dir,
        ):
            return
        gate_kind = _text(gate_data.get("kind"))
        chat_path = starter_meta.get("chat_path")
        if not isinstance(chat_path, str) or not chat_path:
            chat_path = None
        from sase.continuation_capture import (
            persist_agent_delta_best_effort,
            publish_handoff_checkpoint_best_effort,
        )

        handoff_checkpoint_ref = publish_handoff_checkpoint_best_effort(
            artifacts_dir,
            checkpoint_kind="gate_handoff",
            payload={
                "gate_id": gate_id,
                "gate_kind": gate_kind,
                "member_artifacts_dir": member_artifacts_dir,
                "member_agent_name": member_agent_name,
                "starter_agent": starter_agent,
                "chat_path": chat_path,
            },
        )
        result = persist_agent_delta_best_effort(
            ctx,
            state,
            status="completed",
            final_response=response,
            handoff_checkpoint_ref=handoff_checkpoint_ref,
        )
        if result is None:
            return
        if member_artifacts_dir:
            update_meta_field(
                member_artifacts_dir,
                "continuation_parent_node_ids",
                [result.node_id],
            )
            update_meta_field(
                member_artifacts_dir,
                "continuation_parent_node_id",
                result.node_id,
            )
    except Exception as exc:
        # Best-effort wrappers already recorded the capture error; never fail
        # adoption because the continuation node could not be published.
        try:
            from sase.continuation_capture import record_capture_error

            record_capture_error(artifacts_dir, "gate_handoff", exc)
        except Exception:
            pass
        return


def _reused_gate_handoff_node(
    artifacts_dir: str,
    *,
    starter_meta: dict[str, Any],
    gate_id: str | None,
    member_artifacts_dir: str | None,
) -> bool:
    """Reuse the starter node when this gate was already captured.

    The staged path publishes the gate bundle before calling
    ``handle_gate_marker``, so failing adoption at this point would strand a
    published gate. Re-adoption must reuse the existing node instead of
    minting a second one (checkpoint payloads include ``recorded_at_epoch``,
    so a naive republish would mint a different node id).
    """
    if not gate_id:
        return False
    existing_node_ref = starter_meta.get("continuation_node_ref")
    if not isinstance(existing_node_ref, str) or not existing_node_ref:
        return False
    manifest = _read_json_object(Path(artifacts_dir) / "continuation" / "manifest.json")
    if manifest.get("node_ref") != existing_node_ref:
        return False
    manifest_handoff_ref = manifest.get("handoff_checkpoint_ref")
    if not isinstance(manifest_handoff_ref, str) or not manifest_handoff_ref:
        return False
    checkpoint = _read_local_ref_json(artifacts_dir, manifest_handoff_ref)
    if checkpoint.get("kind") != "gate_handoff":
        return False
    payload = checkpoint.get("payload")
    if not isinstance(payload, dict) or payload.get("gate_id") != gate_id:
        return False
    node_id = manifest.get("node_id")
    if not isinstance(node_id, str) or not node_id:
        return False
    if member_artifacts_dir:
        try:
            update_meta_field(
                member_artifacts_dir,
                "continuation_parent_node_ids",
                [node_id],
            )
            update_meta_field(
                member_artifacts_dir,
                "continuation_parent_node_id",
                node_id,
            )
        except Exception:
            return True
    return True


def _read_local_ref_json(artifacts_dir: str, ref: str) -> dict[str, Any]:
    if not ref.startswith("local:"):
        return {}
    rel = ref[len("local:") :].lstrip("/")
    return _read_json_object(Path(artifacts_dir) / rel)


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
