"""Staged successor continuation for the successor engine."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.axe._run_agent_successor_shared import read_successor_json, resolved_suffix
from sase.axe.run_agent_exec_plan_artifacts import store_followup_prompt_artifact
from sase.axe.run_agent_successor_inprocess import continue_as_inprocess_successor
from sase.axe.run_agent_successor_model import write_followup_model_meta
from sase.axe.run_agent_successor_staged_identity import (
    build_staged_successor_identity,
    restore_staged_successor_in_loop,
    staged_followup_model,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import AgentExecContext, LoopState
    from sase.axe.run_agent_successor_types import SuccessorRequest


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

    return continue_as_inprocess_successor(
        ctx,
        state,
        request,
        create_artifacts=create_artifacts,
        promote=promote,
        store_prompt=store_prompt,
        write_model_meta=write_model_meta,
    )


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
            meta = read_successor_json(destination / "agent_meta.json")
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
            saved_model = staged_followup_model(successor.get("followup_model"))
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
        stored_model = staged_followup_model(successor.get("followup_model"))
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
        suffix = resolved_suffix(ctx, request)
        timestamp = request.reserved_timestamp or reserve_launch_timestamp_batch(1)[0]
        successor = build_staged_successor_identity(
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

    successor_name = continue_as_inprocess_successor(
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


__all__ = ["continue_as_successor"]
