"""Agent-delta continuation record publication."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import time
from typing import TYPE_CHECKING, Any, cast

from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    AgentDeltaStatus,
    AgentDeltaWire,
    ContinuationExecutionIdentityWire,
    ContinuationNodeWire,
)

from ._constants import (
    MANIFEST_FILENAME,
    PREPARED_PROMPT_FILENAME,
    WORKSPACE_FACTS_FILENAME,
)
from ._storage import (
    continuation_root,
    iter_string_list,
    local_ref,
    read_json_object,
    required_text,
    safe_identifier,
    sha_json,
    sha_text,
    unique_identifiers,
    unique_refs,
    update_agent_meta_fields,
    write_json_atomic,
    write_text_blob,
    record_capture_error,
)
from ._validation import (
    validate_agent_delta_capture,
    validate_continuation_node_capture,
)
from .models import ContinuationPublishResult
from .prompt import ensure_prepared_prompt
from .segments import wire_segments_from_prepared
from .workspace import owner, run_id, persist_workspace_facts

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import AgentExecContext, LoopState


def persist_agent_delta_best_effort(
    ctx: AgentExecContext,
    state: LoopState,
    *,
    status: AgentDeltaStatus,
    final_response: str | None = None,
    handoff_checkpoint_ref: str | None = None,
    extra_source_refs: Sequence[str] = (),
) -> ContinuationPublishResult | None:
    """Best-effort wrapper for publishing a local agent-delta node."""

    try:
        return persist_agent_delta(
            ctx,
            state,
            status=status,
            final_response=final_response,
            handoff_checkpoint_ref=handoff_checkpoint_ref,
            extra_source_refs=extra_source_refs,
            allow_missing_validation=True,
        )
    except Exception as exc:
        artifacts_dir = state.current_artifacts_dir or ctx.artifacts_dir
        record_capture_error(artifacts_dir, f"agent_delta:{status}", exc)
        return None


def persist_agent_delta(
    ctx: AgentExecContext,
    state: LoopState,
    *,
    status: AgentDeltaStatus,
    final_response: str | None = None,
    handoff_checkpoint_ref: str | None = None,
    extra_source_refs: Sequence[str] = (),
    allow_missing_validation: bool = False,
) -> ContinuationPublishResult:
    """Publish an agent-delta wire record and graph node for this local turn."""

    artifacts_dir = state.current_artifacts_dir or ctx.artifacts_dir
    root = continuation_root(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    prepared = ensure_prepared_prompt(
        artifacts_dir,
        state,
        authored_local_request=state.original_prompt or state.current_prompt,
    )
    workspace_ref = _read_workspace_ref(artifacts_dir)
    if workspace_ref is None:
        workspace_ref = persist_workspace_facts(ctx, state)

    final_response_ref: str | None = None
    if final_response:
        final_response_ref, _, _, _ = write_text_blob(root, final_response)

    prepared_payload = read_json_object(root / PREPARED_PROMPT_FILENAME)
    authored_local_request = required_text(
        prepared_payload.get("authored_local_request"),
        state.original_prompt or state.current_prompt,
    )
    segments = wire_segments_from_prepared(prepared_payload)
    source_refs = unique_refs(
        [
            prepared.prepared_ref,
            workspace_ref,
            final_response_ref,
            handoff_checkpoint_ref,
            *(
                segment.get("source_ref")
                for segment in segments
                if isinstance(segment.get("source_ref"), str)
            ),
            *extra_source_refs,
        ]
    )
    node_id = _agent_delta_node_id(
        ctx=ctx,
        artifacts_dir=artifacts_dir,
        status=status,
        authored_local_request=authored_local_request,
        final_response_ref=final_response_ref,
        handoff_checkpoint_ref=handoff_checkpoint_ref,
        source_refs=source_refs,
    )
    delta: AgentDeltaWire = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "node_id": node_id,
        "authored_local_request": authored_local_request,
        "materialized_local_prompt_segments": segments,
        "status": status,
        "source_refs": source_refs,
    }
    if final_response_ref:
        delta["final_response_ref"] = final_response_ref
    if handoff_checkpoint_ref:
        delta["handoff_checkpoint_ref"] = handoff_checkpoint_ref
    delta_validation = validate_agent_delta_capture(
        delta,
        allow_missing_validation=allow_missing_validation,
    )

    delta_filename = f"{node_id}.json"
    delta_path = root / "records" / "agent_delta" / delta_filename
    delta_sha = write_json_atomic(delta_path, delta)
    delta_ref = local_ref("records", "agent_delta", delta_filename)

    node: ContinuationNodeWire = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "node_id": node_id,
        "kind": "agent_delta",
        "parent_ids": _parent_node_ids(ctx.agent_meta, artifacts_dir, exclude=node_id),
        "owner": cast(ContinuationExecutionIdentityWire, owner(ctx, artifacts_dir)),
        "content_ref": delta_ref,
        "content_sha256": delta_sha,
        "workspace_ref": workspace_ref,
    }
    if handoff_checkpoint_ref:
        node["checkpoint_ref"] = handoff_checkpoint_ref
    node_validation = validate_continuation_node_capture(
        node,
        allow_missing_validation=allow_missing_validation,
    )

    node_path = root / "nodes" / delta_filename
    node_sha = write_json_atomic(node_path, node)
    node_ref = local_ref("nodes", delta_filename)
    manifest: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "local_continuation_capture",
        "node_id": node_id,
        "status": status,
        "agent_delta_ref": delta_ref,
        "agent_delta_sha256": delta_sha,
        "node_ref": node_ref,
        "node_sha256": node_sha,
        "prepared_prompt_ref": prepared.prepared_ref,
        "workspace_ref": workspace_ref,
        "source_refs": source_refs,
        "validation": {
            "agent_delta": delta_validation,
            "node": node_validation,
        },
        "recorded_at_epoch": time.time(),
    }
    if final_response_ref:
        manifest["final_response_ref"] = final_response_ref
    if handoff_checkpoint_ref:
        manifest["handoff_checkpoint_ref"] = handoff_checkpoint_ref
    manifest_path = root / MANIFEST_FILENAME
    write_json_atomic(manifest_path, manifest)
    manifest_ref = local_ref(MANIFEST_FILENAME)

    result = ContinuationPublishResult(
        node_id=node_id,
        manifest_ref=manifest_ref,
        manifest_path=str(manifest_path),
        node_ref=node_ref,
        agent_delta_ref=delta_ref,
        workspace_ref=workspace_ref,
    )
    update_agent_meta_fields(
        artifacts_dir,
        {
            "continuation_node_id": result.node_id,
            "continuation_manifest_ref": result.manifest_ref,
            "continuation_manifest_path": result.manifest_path,
            "continuation_agent_delta_ref": result.agent_delta_ref,
            "continuation_node_ref": result.node_ref,
            "continuation_status": status,
        },
    )
    state.continuation_node_id = result.node_id
    state.continuation_manifest_ref = result.manifest_ref
    return result


def read_latest_manifest_projection(
    artifacts_dir: str | os.PathLike[str] | None,
) -> dict[str, str] | None:
    """Return a done-marker-safe continuation projection, if one exists."""

    if artifacts_dir is None:
        return None
    manifest = read_json_object(continuation_root(artifacts_dir) / MANIFEST_FILENAME)
    node_id = manifest.get("node_id")
    manifest_ref = local_ref(MANIFEST_FILENAME)
    node_ref = manifest.get("node_ref")
    delta_ref = manifest.get("agent_delta_ref")
    if not isinstance(node_id, str) or not node_id:
        return None
    if not isinstance(node_ref, str) or not node_ref:
        return None
    if not isinstance(delta_ref, str) or not delta_ref:
        return None
    projection: dict[str, str] = {
        "node_id": node_id,
        "manifest_ref": manifest_ref,
        "node_ref": node_ref,
        "agent_delta_ref": delta_ref,
    }
    workspace_ref = manifest.get("workspace_ref")
    if isinstance(workspace_ref, str) and workspace_ref:
        projection["workspace_ref"] = workspace_ref
    return projection


def _agent_delta_node_id(
    *,
    ctx: AgentExecContext,
    artifacts_dir: str | os.PathLike[str],
    status: AgentDeltaStatus,
    authored_local_request: str,
    final_response_ref: str | None,
    handoff_checkpoint_ref: str | None,
    source_refs: Sequence[str],
) -> str:
    raw_run_id = run_id(ctx, artifacts_dir)
    raw_run_id = required_text(raw_run_id, "run")
    safe_run_id = safe_identifier(raw_run_id, max_len=96)
    seed = sha_json(
        {
            "run_id": safe_run_id,
            "status": status,
            "authored_sha256": sha_text(authored_local_request),
            "final_response_ref": final_response_ref,
            "handoff_checkpoint_ref": handoff_checkpoint_ref,
            "source_refs": list(source_refs),
        }
    )
    return f"agent-delta:{safe_run_id}:{seed[:16]}"


def _parent_node_ids(
    launch_meta: Mapping[str, Any],
    artifacts_dir: str | os.PathLike[str],
    *,
    exclude: str | None = None,
) -> list[str]:
    meta = dict(launch_meta)
    meta.update(read_json_object(Path(artifacts_dir) / "agent_meta.json"))
    return [
        node_id
        for node_id in unique_identifiers(
            [
                meta.get("continuation_node_id"),
                *iter_string_list(meta.get("continuation_parent_node_ids")),
                meta.get("continuation_parent_node_id"),
                meta.get("continuation_parent"),
            ]
        )
        if node_id != exclude
    ]


def _read_workspace_ref(artifacts_dir: str | os.PathLike[str]) -> str | None:
    meta = read_json_object(Path(artifacts_dir) / "agent_meta.json")
    raw = meta.get("continuation_workspace_ref")
    if isinstance(raw, str) and raw:
        return raw
    if (continuation_root(artifacts_dir) / WORKSPACE_FACTS_FILENAME).exists():
        return local_ref(WORKSPACE_FACTS_FILENAME)
    return None


__all__ = [
    "persist_agent_delta",
    "persist_agent_delta_best_effort",
    "read_latest_manifest_projection",
]
