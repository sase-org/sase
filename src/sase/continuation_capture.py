"""Local persistence for continuation capture records.

The Rust continuation contract owns the wire shapes and validation. This
module is only the artifacts-side persistence adapter: it records local prompt
provenance, workspace facts, checkpoints, and agent-delta nodes without trying
to interpret replay policy.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import tempfile
import time
from typing import TYPE_CHECKING, Any, cast

from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    AgentDeltaStatus,
    AgentDeltaWire,
    ContinuationIntentWire,
    ContinuationExecutionIdentityWire,
    ContinuationModelRouteWire,
    ContinuationNodeWire,
    ContinuationPromptSegmentProvenance,
    ContinuationPromptSegmentWire,
    MonitorResultWire,
)

if TYPE_CHECKING:
    from sase.axe.run_agent_exec_types import AgentExecContext, LoopState
    from sase.xprompt._trace import ExpansionTrace

CONTINUATION_DIRNAME = "continuation"
PREPARED_PROMPT_FILENAME = "prepared_prompt.json"
WORKSPACE_FACTS_FILENAME = "workspace_facts.json"
MANIFEST_FILENAME = "manifest.json"
CAPTURE_ERRORS_FILENAME = "capture_errors.jsonl"

_MAX_SEGMENTS = 512
_ID_SAFE_RE = re.compile(r"[^A-Za-z0-9_.:-]+")


@dataclass(frozen=True)
class ContinuationSegmentCapture:
    """Captured material that contributed to a local prompt."""

    text: str
    provenance: ContinuationPromptSegmentProvenance
    source_ref: str | None = None
    source_label: str | None = None


@dataclass(frozen=True)
class PreparedPromptCaptureResult:
    """Pointer to the last prepared prompt capture in an artifacts dir."""

    prepared_ref: str
    prepared_path: str
    materialized_prompt_ref: str
    materialized_prompt_sha256: str
    materialized_prompt_bytes: int
    segment_count: int


@dataclass(frozen=True)
class ContinuationPublishResult:
    """Pointers published for an agent-delta continuation node."""

    node_id: str
    manifest_ref: str
    manifest_path: str
    node_ref: str
    agent_delta_ref: str
    workspace_ref: str | None

    def marker_projection(self) -> dict[str, str]:
        """Return the compact continuation object stored on done markers."""

        projection = {
            "node_id": self.node_id,
            "manifest_ref": self.manifest_ref,
            "node_ref": self.node_ref,
            "agent_delta_ref": self.agent_delta_ref,
        }
        if self.workspace_ref:
            projection["workspace_ref"] = self.workspace_ref
        return projection


@dataclass(frozen=True)
class MonitorResultPublishResult:
    """Pointers published for a frozen monitor-result continuation node."""

    result_id: str
    node_id: str
    manifest_ref: str
    manifest_path: str
    result_ref: str
    result_path: str
    result_sha256: str
    node_ref: str

    def marker_projection(self) -> dict[str, str]:
        """Return the compact continuation object stored on monitor markers."""

        return {
            "continuation_monitor_result_id": self.result_id,
            "continuation_monitor_result_ref": self.result_ref,
            "continuation_monitor_result_path": self.result_path,
            "continuation_monitor_result_sha256": self.result_sha256,
            "continuation_monitor_result_node_id": self.node_id,
            "continuation_monitor_result_node_ref": self.node_ref,
            "continuation_monitor_result_manifest_ref": self.manifest_ref,
            "continuation_monitor_result_manifest_path": self.manifest_path,
            "continuation_node_id": self.node_id,
            "continuation_node_ref": self.node_ref,
            "continuation_manifest_ref": self.manifest_ref,
            "continuation_manifest_path": self.manifest_path,
        }


def local_authored_prompt_segment(text: str) -> ContinuationSegmentCapture:
    """Return a segment for the user's authored local request."""

    return ContinuationSegmentCapture(
        text=text,
        provenance="local_authored",
        source_ref="local:authored-request",
        source_label="authored local request",
    )


def local_materialized_prompt_segment(text: str) -> ContinuationSegmentCapture:
    """Return a segment for the exact local prompt sent to the provider."""

    return ContinuationSegmentCapture(
        text=text,
        provenance="local_materialized",
        source_ref="local:materialized-prompt",
        source_label="materialized local prompt",
    )


def xprompt_trace_segments(
    trace: ExpansionTrace,
    *,
    start_index: int = 0,
) -> tuple[ContinuationSegmentCapture, ...]:
    """Convert new xprompt expansion trace records into capture segments."""

    segments: list[ContinuationSegmentCapture] = []
    for index, record in enumerate(trace.records[start_index:], start=start_index):
        if not record.expanded_text:
            continue
        source_seed = f"{record.name}\0{record.source_path or ''}\0{index}"
        segments.append(
            ContinuationSegmentCapture(
                text=record.expanded_text,
                provenance="local_materialized",
                source_ref=_source_ref("xprompt", record.name, source_seed),
                source_label=record.source_path,
            )
        )
    return tuple(segments)


def embedded_workflow_prompt_segment(
    name: str,
    text: str,
    *,
    source_path: str | None = None,
) -> ContinuationSegmentCapture:
    """Return a segment for rendered embedded workflow prompt_part text."""

    return ContinuationSegmentCapture(
        text=text,
        provenance="local_materialized",
        source_ref=_source_ref("workflow", name, source_path or text),
        source_label=source_path,
    )


def record_prepared_prompt_capture(
    artifacts_dir: str | os.PathLike[str],
    *,
    authored_local_request: str,
    materialized_prompt: str,
    segments: Sequence[ContinuationSegmentCapture] = (),
    update_meta: bool = True,
) -> PreparedPromptCaptureResult:
    """Persist the prompt provenance prepared for one local agent invocation."""

    root = _continuation_root(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    normalized = _complete_prompt_segments(
        authored_local_request=authored_local_request,
        materialized_prompt=materialized_prompt,
        segments=segments,
    )

    materialized_ref, _, materialized_sha, materialized_bytes = _write_text_blob(
        root,
        materialized_prompt,
    )
    wire_segments: list[ContinuationPromptSegmentWire] = []
    source_details: list[dict[str, str]] = []
    for index, segment in enumerate(normalized[:_MAX_SEGMENTS]):
        text_ref, _, text_sha, text_bytes = _write_text_blob(root, segment.text)
        source_ref = _wire_reference_or_none(segment.source_ref)
        segment_id = f"seg:{index:03d}:{segment.provenance}:{text_sha[:16]}"
        wire_segment: ContinuationPromptSegmentWire = {
            "segment_id": segment_id,
            "provenance": segment.provenance,
            "text_ref": text_ref,
            "text_sha256": text_sha,
            "utf8_bytes": text_bytes,
        }
        if source_ref:
            wire_segment["source_ref"] = source_ref
        wire_segments.append(wire_segment)

        detail: dict[str, str] = {"segment_id": segment_id}
        if source_ref:
            detail["source_ref"] = source_ref
        if segment.source_label:
            detail["source_label"] = segment.source_label
        if detail.keys() != {"segment_id"}:
            source_details.append(detail)

    payload: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "prepared_prompt",
        "authored_local_request": authored_local_request,
        "materialized_prompt_ref": materialized_ref,
        "materialized_prompt_sha256": materialized_sha,
        "materialized_prompt_bytes": materialized_bytes,
        "materialized_local_prompt_segments": wire_segments,
        "recorded_at_epoch": time.time(),
    }
    if source_details:
        payload["source_details"] = source_details
    prepared_path = root / PREPARED_PROMPT_FILENAME
    _write_json_atomic(prepared_path, payload)
    result = PreparedPromptCaptureResult(
        prepared_ref=_local_ref(PREPARED_PROMPT_FILENAME),
        prepared_path=str(prepared_path),
        materialized_prompt_ref=materialized_ref,
        materialized_prompt_sha256=materialized_sha,
        materialized_prompt_bytes=materialized_bytes,
        segment_count=len(wire_segments),
    )
    if update_meta:
        _update_agent_meta_fields(
            artifacts_dir,
            {
                "continuation_prepared_prompt_ref": result.prepared_ref,
                "continuation_prepared_prompt_path": result.prepared_path,
                "continuation_materialized_prompt_ref": result.materialized_prompt_ref,
            },
        )
    return result


def record_prepared_prompt_capture_best_effort(
    artifacts_dir: str | os.PathLike[str] | None,
    *,
    authored_local_request: str,
    materialized_prompt: str,
    segments: Sequence[ContinuationSegmentCapture] = (),
) -> PreparedPromptCaptureResult | None:
    """Best-effort wrapper for prepared prompt capture."""

    if artifacts_dir is None:
        return None
    try:
        return record_prepared_prompt_capture(
            artifacts_dir,
            authored_local_request=authored_local_request,
            materialized_prompt=materialized_prompt,
            segments=segments,
        )
    except Exception as exc:
        record_capture_error(artifacts_dir, "prepared_prompt", exc)
        return None


def read_prepared_prompt_capture_ref(
    artifacts_dir: str | os.PathLike[str] | None,
) -> str | None:
    """Return the prepared prompt ref for an artifacts dir, if present."""

    if artifacts_dir is None:
        return None
    payload = _read_json_object(
        _continuation_root(artifacts_dir) / PREPARED_PROMPT_FILENAME
    )
    if not payload:
        return None
    ref = payload.get("prepared_ref") or _local_ref(PREPARED_PROMPT_FILENAME)
    if isinstance(ref, str):
        return ref
    return None


def persist_workspace_facts_best_effort(
    ctx: AgentExecContext,
    state: LoopState,
) -> str | None:
    """Persist host/workspace facts before an agent turn can terminate."""

    try:
        return persist_workspace_facts(ctx, state)
    except Exception as exc:
        record_capture_error(ctx.artifacts_dir, "workspace_facts", exc)
        return None


def persist_workspace_facts(ctx: AgentExecContext, state: LoopState) -> str:
    """Persist a local workspace-facts checkpoint and return its ref."""

    artifacts_dir = state.current_artifacts_dir or ctx.artifacts_dir
    root = _continuation_root(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    facts: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "workspace_facts",
        "project": ctx.project_name,
        "run_id": _run_id(ctx, artifacts_dir),
        "agent_name": _agent_name(ctx, artifacts_dir),
        "cwd": os.getcwd(),
        "workspace_dir": ctx.workspace_dir,
        "workspace_num": ctx.workspace_num,
        "current_artifacts_dir": state.current_artifacts_dir,
        "root_artifacts_dir": ctx.artifacts_dir,
        "cl_name": ctx.cl_name,
        "vcs_tag": ctx.vcs_tag,
        "prompt_sha256": _sha_text(state.current_prompt),
        "recorded_at_epoch": time.time(),
    }
    try:
        facts["machine_name"] = socket.gethostname()
    except OSError:
        pass
    path = root / WORKSPACE_FACTS_FILENAME
    _write_json_atomic(path, facts)
    workspace_ref = _local_ref(WORKSPACE_FACTS_FILENAME)
    _update_agent_meta_fields(
        artifacts_dir,
        {
            "continuation_workspace_ref": workspace_ref,
            "continuation_workspace_facts_path": str(path),
        },
    )
    state.continuation_workspace_ref = workspace_ref
    return workspace_ref


def publish_handoff_checkpoint_best_effort(
    artifacts_dir: str | os.PathLike[str] | None,
    *,
    checkpoint_kind: str,
    payload: Mapping[str, Any],
) -> str | None:
    """Best-effort wrapper for handoff checkpoint publication."""

    if artifacts_dir is None:
        return None
    try:
        return publish_handoff_checkpoint(
            artifacts_dir,
            checkpoint_kind=checkpoint_kind,
            payload=payload,
        )
    except Exception as exc:
        record_capture_error(artifacts_dir, f"checkpoint:{checkpoint_kind}", exc)
        return None


def publish_handoff_checkpoint(
    artifacts_dir: str | os.PathLike[str],
    *,
    checkpoint_kind: str,
    payload: Mapping[str, Any],
) -> str:
    """Persist a content-addressed checkpoint and return its local ref."""

    root = _continuation_root(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    checkpoint_payload = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": checkpoint_kind,
        "payload": _json_safe(payload),
        "recorded_at_epoch": time.time(),
    }
    digest = _sha_json(checkpoint_payload)
    filename = f"{_safe_identifier(checkpoint_kind)}-{digest[:16]}.json"
    path = root / "checkpoints" / filename
    _write_json_atomic(path, checkpoint_payload)
    return _local_ref("checkpoints", filename)


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
    root = _continuation_root(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    prepared = _ensure_prepared_prompt(
        artifacts_dir,
        state,
        authored_local_request=state.original_prompt or state.current_prompt,
    )
    workspace_ref = _read_workspace_ref(artifacts_dir)
    if workspace_ref is None:
        workspace_ref = persist_workspace_facts(ctx, state)

    final_response_ref: str | None = None
    if final_response:
        final_response_ref, _, _, _ = _write_text_blob(root, final_response)

    prepared_payload = _read_json_object(root / PREPARED_PROMPT_FILENAME)
    authored_local_request = _required_text(
        prepared_payload.get("authored_local_request"),
        state.original_prompt or state.current_prompt,
    )
    segments = _wire_segments_from_prepared(prepared_payload)
    source_refs = _unique_refs(
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
    delta_validation = _validate_agent_delta(
        delta,
        allow_missing_validation=allow_missing_validation,
    )

    delta_filename = f"{node_id}.json"
    delta_path = root / "records" / "agent_delta" / delta_filename
    delta_sha = _write_json_atomic(delta_path, delta)
    delta_ref = _local_ref("records", "agent_delta", delta_filename)

    node: ContinuationNodeWire = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "node_id": node_id,
        "kind": "agent_delta",
        "parent_ids": _parent_node_ids(ctx.agent_meta, artifacts_dir, exclude=node_id),
        "owner": cast(ContinuationExecutionIdentityWire, _owner(ctx, artifacts_dir)),
        "content_ref": delta_ref,
        "content_sha256": delta_sha,
        "workspace_ref": workspace_ref,
    }
    if handoff_checkpoint_ref:
        node["checkpoint_ref"] = handoff_checkpoint_ref
    node_validation = _validate_continuation_node(
        node,
        allow_missing_validation=allow_missing_validation,
    )

    node_path = root / "nodes" / delta_filename
    node_sha = _write_json_atomic(node_path, node)
    node_ref = _local_ref("nodes", delta_filename)
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
    _write_json_atomic(manifest_path, manifest)
    manifest_ref = _local_ref(MANIFEST_FILENAME)

    result = ContinuationPublishResult(
        node_id=node_id,
        manifest_ref=manifest_ref,
        manifest_path=str(manifest_path),
        node_ref=node_ref,
        agent_delta_ref=delta_ref,
        workspace_ref=workspace_ref,
    )
    _update_agent_meta_fields(
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
    manifest = _read_json_object(_continuation_root(artifacts_dir) / MANIFEST_FILENAME)
    node_id = manifest.get("node_id")
    manifest_ref = _local_ref(MANIFEST_FILENAME)
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


def persist_monitor_start_intent_best_effort(
    *,
    artifacts_dir: str | os.PathLike[str],
    monitor_id: str,
    member_agent_name: str,
    project_name: str,
    command: str,
    cwd: str,
    next_action: str | None,
    next_model: str | None,
    next_output: str,
    request_fingerprint: str,
    parent_node_ids: Sequence[str] = (),
    starter_agent: str | None = None,
) -> str | None:
    """Persist a passive continuation intent for a started monitor member."""

    if not next_action:
        return None
    try:
        return persist_monitor_start_intent(
            artifacts_dir=artifacts_dir,
            monitor_id=monitor_id,
            member_agent_name=member_agent_name,
            project_name=project_name,
            command=command,
            cwd=cwd,
            next_action=next_action,
            next_model=next_model,
            next_output=next_output,
            request_fingerprint=request_fingerprint,
            parent_node_ids=parent_node_ids,
            starter_agent=starter_agent,
            allow_missing_validation=True,
        )
    except Exception as exc:
        record_capture_error(artifacts_dir, "monitor_intent", exc)
        return None


def persist_monitor_start_intent(
    *,
    artifacts_dir: str | os.PathLike[str],
    monitor_id: str,
    member_agent_name: str,
    project_name: str,
    command: str,
    cwd: str,
    next_action: str,
    next_model: str | None,
    next_output: str,
    request_fingerprint: str,
    parent_node_ids: Sequence[str] = (),
    starter_agent: str | None = None,
    allow_missing_validation: bool = False,
) -> str:
    """Persist and validate a continuation intent for a monitor's next action."""

    checkpoint_ref = publish_handoff_checkpoint(
        artifacts_dir,
        checkpoint_kind="monitor_start",
        payload={
            "monitor_id": monitor_id,
            "member_agent_name": member_agent_name,
            "project_name": project_name,
            "command": command,
            "cwd": cwd,
            "next_output": next_output,
            "request_fingerprint": request_fingerprint,
            "parent_node_ids": list(parent_node_ids),
            "starter_agent": starter_agent,
        },
    )
    seed = f"{monitor_id}\0{next_action}\0{next_model or ''}\0{next_output}"
    intent_id = f"intent:{_safe_identifier(monitor_id)}:{_sha_text(seed)[:16]}"
    route: dict[str, Any] = {"inherit_effort": True}
    if next_model:
        route["model"] = _wire_reference(next_model, fallback_kind="model")
    else:
        route["inherit_model"] = True
    intent: ContinuationIntentWire = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "intent_id": intent_id,
        "next_action": next_action,
        "checkpoint_ref": checkpoint_ref,
        "route": cast(ContinuationModelRouteWire, route),
        "outcome_policy_ref": _source_ref(
            "monitor-policy",
            next_output or "default",
            request_fingerprint,
        ),
    }
    validation = _validate_continuation_intent(
        intent,
        allow_missing_validation=allow_missing_validation,
    )
    root = _continuation_root(artifacts_dir)
    filename = f"{intent_id}.json"
    intent_path = root / "intents" / filename
    intent_sha = _write_json_atomic(intent_path, intent)
    intent_ref = _local_ref("intents", filename)
    manifest: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "monitor_start_intent",
        "intent_id": intent_id,
        "intent_ref": intent_ref,
        "intent_sha256": intent_sha,
        "checkpoint_ref": checkpoint_ref,
        "parent_node_ids": list(parent_node_ids),
        "validation": {"intent": validation},
        "recorded_at_epoch": time.time(),
    }
    manifest_path = root / "monitor_intent_manifest.json"
    _write_json_atomic(manifest_path, manifest)
    fields: dict[str, Any] = {
        "continuation_intent_id": intent_id,
        "continuation_intent_ref": intent_ref,
        "continuation_intent_manifest_ref": _local_ref("monitor_intent_manifest.json"),
        "continuation_checkpoint_ref": checkpoint_ref,
    }
    if parent_node_ids:
        fields["continuation_parent_node_ids"] = list(parent_node_ids)
    _update_agent_meta_fields(artifacts_dir, fields)
    return intent_ref


def persist_monitor_result_best_effort(
    *,
    artifacts_dir: str | os.PathLike[str],
    meta: Mapping[str, Any],
    monitor_state: str,
    exit_code: int | None,
    elapsed_seconds: float | int | None,
    stopped_at: str | None,
    diagnostic_manifest: Mapping[str, Any] | None,
    retained_log: Mapping[str, Any] | None,
    timeout_kind: object = None,
    project_name: str | None = None,
    update_meta: bool = True,
) -> MonitorResultPublishResult | None:
    """Persist a terminal monitor result without interrupting settlement."""

    try:
        return persist_monitor_result(
            artifacts_dir=artifacts_dir,
            meta=meta,
            monitor_state=monitor_state,
            exit_code=exit_code,
            elapsed_seconds=elapsed_seconds,
            stopped_at=stopped_at,
            diagnostic_manifest=diagnostic_manifest,
            retained_log=retained_log,
            timeout_kind=timeout_kind,
            project_name=project_name,
            update_meta=update_meta,
            allow_missing_validation=True,
        )
    except Exception as exc:
        record_capture_error(artifacts_dir, "monitor_result", exc)
        return None


def persist_monitor_result(
    *,
    artifacts_dir: str | os.PathLike[str],
    meta: Mapping[str, Any],
    monitor_state: str,
    exit_code: int | None,
    elapsed_seconds: float | int | None,
    stopped_at: str | None,
    diagnostic_manifest: Mapping[str, Any] | None,
    retained_log: Mapping[str, Any] | None,
    timeout_kind: object = None,
    project_name: str | None = None,
    update_meta: bool = True,
    allow_missing_validation: bool = False,
) -> MonitorResultPublishResult:
    """Publish a frozen monitor-result record and graph node."""

    from sase.monitor.result_projection import build_monitor_result_wire

    root = _continuation_root(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    monitor_id = _required_text(meta.get("monitor_id"), "monitor")
    diagnostic_ref = (
        diagnostic_manifest.get("manifest_ref") if diagnostic_manifest else None
    ) or meta.get("monitor_diagnostic_manifest_ref")
    result = build_monitor_result_wire(
        monitor_id=monitor_id,
        monitor_state=monitor_state,
        exit_code=exit_code,
        command=_monitor_command(meta),
        cwd=_required_text(
            meta.get("monitor_cwd"), _required_text(meta.get("cwd"), "")
        ),
        started_at=_required_text(meta.get("run_started_at"), "unknown"),
        stopped_at=stopped_at,
        elapsed_seconds=elapsed_seconds,
        timeout_seconds=_optional_float(meta.get("monitor_timeout_seconds")),
        timeout_kind=timeout_kind or meta.get("monitor_timeout_kind"),
        starter_execution_id=(
            meta.get("monitor_starter_agent")
            or meta.get("parent_timestamp")
            or meta.get("name")
        ),
        workspace_identity=(
            meta.get("continuation_workspace_ref")
            or meta.get("workspace_dir")
            or meta.get("workspace_num")
        ),
        diagnostic_manifest_ref=diagnostic_ref,
        retained_log=retained_log,
        result_seed_extra={
            "artifacts_dir": Path(artifacts_dir).name,
            "request_fingerprint": meta.get("monitor_request_fingerprint"),
        },
    )
    result_validation = _validate_monitor_result(
        result,
        allow_missing_validation=allow_missing_validation,
    )

    result_filename = f"{result['result_id']}.json"
    result_path = root / "records" / "monitor_result" / result_filename
    result_sha = _write_json_atomic(result_path, result)
    result_ref = _local_ref("records", "monitor_result", result_filename)

    node_id = _monitor_result_node_id(result)
    node: ContinuationNodeWire = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "node_id": node_id,
        "kind": "monitor_result",
        "parent_ids": _parent_node_ids_from_meta(meta, exclude=node_id),
        "owner": cast(
            ContinuationExecutionIdentityWire,
            _owner_from_monitor_meta(
                meta,
                artifacts_dir,
                project_name=project_name,
            ),
        ),
        "content_ref": result_ref,
        "content_sha256": result_sha,
    }
    workspace_ref = _wire_reference_or_none(
        _optional_str(meta.get("continuation_workspace_ref"))
        or _optional_str(meta.get("workspace_dir"))
    )
    if workspace_ref:
        node["workspace_ref"] = workspace_ref
    checkpoint_ref = _optional_str(meta.get("continuation_checkpoint_ref"))
    if checkpoint_ref:
        node["checkpoint_ref"] = checkpoint_ref
    intent_ref = _optional_str(meta.get("continuation_intent_ref"))
    if intent_ref:
        node["intent_ref"] = intent_ref
    node_validation = _validate_continuation_node(
        node,
        allow_missing_validation=allow_missing_validation,
    )

    node_path = root / "nodes" / f"{node_id}.json"
    node_sha = _write_json_atomic(node_path, node)
    node_ref = _local_ref("nodes", f"{node_id}.json")
    manifest: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "monitor_result_capture",
        "result_id": result["result_id"],
        "node_id": node_id,
        "result_ref": result_ref,
        "result_sha256": result_sha,
        "node_ref": node_ref,
        "node_sha256": node_sha,
        "parent_node_ids": list(node.get("parent_ids", [])),
        "diagnostic_manifest_ref": result.get("diagnostic_manifest_ref"),
        "retained_log_ref": result.get("retained_log", {}).get("log_ref"),
        "evidence_policy": meta.get("monitor_next_output"),
        "validation": {
            "monitor_result": result_validation,
            "node": node_validation,
        },
        "recorded_at_epoch": time.time(),
    }
    manifest_path = root / "monitor_result_manifest.json"
    _write_json_atomic(manifest_path, manifest)
    manifest_ref = _local_ref("monitor_result_manifest.json")

    published = MonitorResultPublishResult(
        result_id=result["result_id"],
        node_id=node_id,
        manifest_ref=manifest_ref,
        manifest_path=str(manifest_path),
        result_ref=result_ref,
        result_path=str(result_path),
        result_sha256=result_sha,
        node_ref=node_ref,
    )
    fields = published.marker_projection()
    if isinstance(meta, dict):
        meta.update(fields)
    if update_meta:
        _update_agent_meta_fields(artifacts_dir, fields)
    return published


def record_capture_error(
    artifacts_dir: str | os.PathLike[str] | None,
    stage: str,
    exc: BaseException,
) -> None:
    """Append a continuation capture error without affecting caller behavior."""

    if artifacts_dir is None:
        return
    try:
        root = _continuation_root(artifacts_dir)
        root.mkdir(parents=True, exist_ok=True)
        with (root / CAPTURE_ERRORS_FILENAME).open("a", encoding="utf-8") as stream:
            json.dump(
                {
                    "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                    "stage": stage,
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "recorded_at_epoch": time.time(),
                },
                stream,
                sort_keys=True,
            )
            stream.write("\n")
    except OSError:
        pass


def _complete_prompt_segments(
    *,
    authored_local_request: str,
    materialized_prompt: str,
    segments: Sequence[ContinuationSegmentCapture],
) -> list[ContinuationSegmentCapture]:
    normalized = list(segments)
    if not any(segment.provenance == "local_authored" for segment in normalized):
        normalized.insert(0, local_authored_prompt_segment(authored_local_request))
    if not any(
        segment.provenance == "local_materialized"
        and segment.text == materialized_prompt
        for segment in normalized
    ):
        normalized.append(local_materialized_prompt_segment(materialized_prompt))
    return normalized


def _ensure_prepared_prompt(
    artifacts_dir: str | os.PathLike[str],
    state: LoopState,
    *,
    authored_local_request: str,
) -> PreparedPromptCaptureResult:
    root = _continuation_root(artifacts_dir)
    payload = _read_json_object(root / PREPARED_PROMPT_FILENAME)
    if payload:
        materialized_ref = _required_text(payload.get("materialized_prompt_ref"), "")
        materialized_sha = _required_text(
            payload.get("materialized_prompt_sha256"),
            "0" * 64,
        )
        materialized_bytes = (
            _optional_int(payload.get("materialized_prompt_bytes")) or 0
        )
        segments = payload.get("materialized_local_prompt_segments")
        segment_count = len(segments) if isinstance(segments, list) else 0
        return PreparedPromptCaptureResult(
            prepared_ref=_local_ref(PREPARED_PROMPT_FILENAME),
            prepared_path=str(root / PREPARED_PROMPT_FILENAME),
            materialized_prompt_ref=materialized_ref,
            materialized_prompt_sha256=materialized_sha,
            materialized_prompt_bytes=materialized_bytes,
            segment_count=segment_count,
        )
    return record_prepared_prompt_capture(
        artifacts_dir,
        authored_local_request=authored_local_request,
        materialized_prompt=state.current_prompt,
        segments=(),
    )


def _wire_segments_from_prepared(
    prepared_payload: Mapping[str, Any],
) -> list[ContinuationPromptSegmentWire]:
    raw_segments = prepared_payload.get("materialized_local_prompt_segments")
    if not isinstance(raw_segments, list):
        return []
    segments: list[ContinuationPromptSegmentWire] = []
    for raw in raw_segments[:_MAX_SEGMENTS]:
        if not isinstance(raw, Mapping):
            continue
        segment_id = raw.get("segment_id")
        provenance = raw.get("provenance")
        text_ref = raw.get("text_ref")
        text_sha = raw.get("text_sha256")
        utf8_bytes = _optional_int(raw.get("utf8_bytes"))
        if not (
            isinstance(segment_id, str)
            and isinstance(provenance, str)
            and isinstance(text_ref, str)
            and isinstance(text_sha, str)
            and utf8_bytes is not None
        ):
            continue
        segment: ContinuationPromptSegmentWire = {
            "segment_id": segment_id,
            "provenance": provenance,  # type: ignore[typeddict-item]
            "text_ref": text_ref,
            "text_sha256": text_sha,
            "utf8_bytes": utf8_bytes,
        }
        source_ref = raw.get("source_ref")
        if isinstance(source_ref, str) and source_ref:
            segment["source_ref"] = source_ref
        segments.append(segment)
    return segments


def _validate_agent_delta(
    delta: AgentDeltaWire,
    *,
    allow_missing_validation: bool,
) -> dict[str, str]:
    try:
        from sase.core.continuation_facade import validate_agent_delta

        validate_agent_delta(delta)
        return {"status": "ok"}
    except (AttributeError, ModuleNotFoundError) as exc:
        if allow_missing_validation:
            return {"status": "unavailable", "message": str(exc)}
        raise


def _validate_continuation_node(
    node: ContinuationNodeWire,
    *,
    allow_missing_validation: bool,
) -> dict[str, str]:
    try:
        from sase.core.continuation_facade import validate_continuation_node

        validate_continuation_node(node)
        return {"status": "ok"}
    except (AttributeError, ModuleNotFoundError) as exc:
        if allow_missing_validation:
            return {"status": "unavailable", "message": str(exc)}
        raise


def _validate_continuation_intent(
    intent: ContinuationIntentWire,
    *,
    allow_missing_validation: bool,
) -> dict[str, str]:
    try:
        from sase.core.continuation_facade import validate_continuation_intent

        validate_continuation_intent(intent)
        return {"status": "ok"}
    except (AttributeError, ModuleNotFoundError) as exc:
        if allow_missing_validation:
            return {"status": "unavailable", "message": str(exc)}
        raise


def _validate_monitor_result(
    result: MonitorResultWire,
    *,
    allow_missing_validation: bool,
) -> dict[str, str]:
    try:
        from sase.core.continuation_facade import validate_monitor_result

        validate_monitor_result(result)
        return {"status": "ok"}
    except (AttributeError, ModuleNotFoundError) as exc:
        if allow_missing_validation:
            return {"status": "unavailable", "message": str(exc)}
        raise


def _monitor_result_node_id(result: MonitorResultWire) -> str:
    suffix = str(result["result_id"]).removeprefix("result:")
    return f"monitor-result:{_safe_identifier(suffix, max_len=180)}"


def _parent_node_ids_from_meta(
    meta: Mapping[str, Any],
    *,
    exclude: str | None = None,
) -> list[str]:
    return [
        node_id
        for node_id in _unique_identifiers(
            [
                meta.get("continuation_node_id"),
                *_iter_string_list(meta.get("continuation_parent_node_ids")),
                meta.get("continuation_parent_node_id"),
                meta.get("continuation_parent"),
            ]
        )
        if node_id != exclude
    ]


def _owner_from_monitor_meta(
    meta: Mapping[str, Any],
    artifacts_dir: str | os.PathLike[str],
    *,
    project_name: str | None = None,
) -> dict[str, str]:
    owner = {
        "project": _safe_identifier(
            project_name
            or _optional_str(meta.get("project_name"))
            or _optional_str(meta.get("project"))
            or "unknown"
        ),
        "run_id": _safe_identifier(Path(artifacts_dir).name),
        "agent_name": _safe_identifier(
            _optional_str(meta.get("name"))
            or _optional_str(meta.get("monitor_id"))
            or "monitor"
        ),
    }
    workspace_id = meta.get("workspace_num")
    if workspace_id is not None:
        owner["workspace_id"] = _safe_identifier(str(workspace_id))
    try:
        owner["machine_name"] = _safe_identifier(socket.gethostname())
    except OSError:
        pass
    return owner


def _monitor_command(meta: Mapping[str, Any]) -> object:
    argv = meta.get("monitor_execution_argv")
    if isinstance(argv, list) and argv:
        return [str(part) for part in argv if str(part)]
    return meta.get("monitor_command")


def _owner(
    ctx: AgentExecContext,
    artifacts_dir: str | os.PathLike[str],
) -> dict[str, str]:
    owner = {
        "project": _safe_identifier(ctx.project_name or "unknown"),
        "run_id": _safe_identifier(_run_id(ctx, artifacts_dir)),
        "agent_name": _safe_identifier(_agent_name(ctx, artifacts_dir)),
        "workspace_id": _safe_identifier(str(ctx.workspace_num)),
    }
    try:
        owner["machine_name"] = _safe_identifier(socket.gethostname())
    except OSError:
        pass
    return owner


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
    run_id = _safe_identifier(_run_id(ctx, artifacts_dir), max_len=96)
    seed = _sha_json(
        {
            "run_id": run_id,
            "status": status,
            "authored_sha256": _sha_text(authored_local_request),
            "final_response_ref": final_response_ref,
            "handoff_checkpoint_ref": handoff_checkpoint_ref,
            "source_refs": list(source_refs),
        }
    )
    return f"agent-delta:{run_id}:{seed[:16]}"


def _parent_node_ids(
    launch_meta: Mapping[str, Any],
    artifacts_dir: str | os.PathLike[str],
    *,
    exclude: str | None = None,
) -> list[str]:
    meta = dict(launch_meta)
    meta.update(_read_json_object(Path(artifacts_dir) / "agent_meta.json"))
    return [
        node_id
        for node_id in _unique_identifiers(
            [
                meta.get("continuation_node_id"),
                *_iter_string_list(meta.get("continuation_parent_node_ids")),
                meta.get("continuation_parent_node_id"),
                meta.get("continuation_parent"),
            ]
        )
        if node_id != exclude
    ]


def _read_workspace_ref(artifacts_dir: str | os.PathLike[str]) -> str | None:
    meta = _read_json_object(Path(artifacts_dir) / "agent_meta.json")
    raw = meta.get("continuation_workspace_ref")
    if isinstance(raw, str) and raw:
        return raw
    if (_continuation_root(artifacts_dir) / WORKSPACE_FACTS_FILENAME).exists():
        return _local_ref(WORKSPACE_FACTS_FILENAME)
    return None


def _run_id(ctx: AgentExecContext, artifacts_dir: str | os.PathLike[str]) -> str:
    value = ctx.artifacts_timestamp or Path(artifacts_dir).name
    return str(value or "run")


def _agent_name(
    ctx: AgentExecContext,
    artifacts_dir: str | os.PathLike[str],
) -> str:
    if ctx.agent_name:
        return ctx.agent_name
    meta = _read_json_object(Path(artifacts_dir) / "agent_meta.json")
    name = meta.get("name")
    if isinstance(name, str) and name:
        return name
    return "agent"


def _write_text_blob(root: Path, text: str) -> tuple[str, Path, str, int]:
    data = text.encode("utf-8")
    digest = _sha_bytes(data)
    path = root / "text" / f"{digest}.txt"
    if not path.exists():
        _write_bytes_atomic(path, data)
    return _local_ref("text", f"{digest}.txt"), path, digest, len(data)


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> str:
    data = _json_bytes(payload)
    _write_bytes_atomic(path, data)
    return _sha_bytes(data)


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    tmp_path = Path(tmp_name)
    replaced = False
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
        os.replace(tmp_path, path)
        replaced = True
    finally:
        if not replaced:
            try:
                tmp_path.unlink()
            except FileNotFoundError:
                pass


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(_json_safe(payload), indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, str | int | float | bool) or value is None:
        return value
    if isinstance(value, Sequence) and not isinstance(value, bytes | bytearray | str):
        return [_json_safe(item) for item in value]
    return str(value)


def _continuation_root(artifacts_dir: str | os.PathLike[str]) -> Path:
    return Path(artifacts_dir) / CONTINUATION_DIRNAME


def _local_ref(*parts: str) -> str:
    return "local:" + "/".join((CONTINUATION_DIRNAME, *parts))


def _sha_text(text: str) -> str:
    return _sha_bytes(text.encode("utf-8"))


def _sha_json(payload: Mapping[str, Any]) -> str:
    return _sha_bytes(_json_bytes(payload))


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _source_ref(kind: str, label: str, seed: str) -> str:
    safe_kind = _safe_identifier(kind, max_len=40)
    safe_label = _safe_identifier(label or "unknown", max_len=56)
    return f"{safe_kind}:{safe_label}:{_sha_text(seed)[:16]}"


def _wire_reference_or_none(value: str | None) -> str | None:
    if not value:
        return None
    return _wire_reference(value, fallback_kind="source")


def _wire_reference(value: str, *, fallback_kind: str) -> str:
    if not value:
        return f"{fallback_kind}:empty"
    if len(value.encode("utf-8")) <= 1024 and not any(ch.isspace() for ch in value):
        return value
    return f"{fallback_kind}:{_sha_text(value)[:16]}"


def _safe_identifier(value: object, *, max_len: int = 80) -> str:
    text = str(value).strip() or "unknown"
    text = _ID_SAFE_RE.sub("_", text)
    text = text.strip("_.:-") or "unknown"
    if len(text.encode("utf-8")) <= max_len:
        return text
    digest = _sha_text(text)[:16]
    keep = max(1, max_len - len(digest) - 1)
    return f"{text[:keep]}:{digest}"


def _unique_refs(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        if not isinstance(raw, str) or not raw:
            continue
        ref = _wire_reference(raw, fallback_kind="ref")
        if ref in seen:
            continue
        seen.add(ref)
        result.append(ref)
    return result


def _unique_identifiers(values: Iterable[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        if not isinstance(raw, str) or not raw:
            continue
        identifier = _wire_reference(raw, fallback_kind="id")
        if len(identifier.encode("utf-8")) > 256:
            identifier = f"id:{_sha_text(identifier)[:16]}"
        if identifier in seen:
            continue
        seen.add(identifier)
        result.append(identifier)
    return result


def _iter_string_list(value: Any) -> Iterable[str]:
    if isinstance(value, list):
        return (item for item in value if isinstance(item, str) and item)
    return ()


def _required_text(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_float(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _read_json_object(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _update_agent_meta_fields(
    artifacts_dir: str | os.PathLike[str],
    fields: Mapping[str, Any],
) -> None:
    try:
        from sase.axe.run_agent_helpers import update_meta_fields

        update_meta_fields(str(artifacts_dir), dict(fields))
    except Exception:
        pass


__all__ = [
    "ContinuationPublishResult",
    "ContinuationSegmentCapture",
    "MonitorResultPublishResult",
    "PreparedPromptCaptureResult",
    "embedded_workflow_prompt_segment",
    "local_authored_prompt_segment",
    "local_materialized_prompt_segment",
    "persist_agent_delta",
    "persist_agent_delta_best_effort",
    "persist_monitor_start_intent",
    "persist_monitor_start_intent_best_effort",
    "persist_monitor_result",
    "persist_monitor_result_best_effort",
    "persist_workspace_facts",
    "persist_workspace_facts_best_effort",
    "publish_handoff_checkpoint",
    "publish_handoff_checkpoint_best_effort",
    "read_latest_manifest_projection",
    "read_prepared_prompt_capture_ref",
    "record_capture_error",
    "record_prepared_prompt_capture",
    "record_prepared_prompt_capture_best_effort",
    "xprompt_trace_segments",
]
