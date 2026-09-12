"""Monitor intent and result persistence for local continuation capture."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
import socket
import time
from typing import Any, cast

from sase.continuation_capture_support import (
    capture_validation,
    continuation_root,
    local_ref,
    optional_float,
    optional_str,
    parent_node_ids_from_mapping,
    publish_handoff_checkpoint,
    record_capture_error,
    required_text,
    safe_identifier,
    sha_text,
    source_ref,
    update_agent_meta_fields,
    wire_reference,
    wire_reference_or_none,
    write_json_atomic,
)
from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    ContinuationExecutionIdentityWire,
    ContinuationIntentWire,
    ContinuationModelRouteWire,
    ContinuationNodeWire,
    MonitorResultWire,
)


@dataclass(frozen=True)
class _MonitorResultPublishResult:
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
        return _persist_monitor_start_intent(
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


def _persist_monitor_start_intent(
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
    intent_id = f"intent:{safe_identifier(monitor_id)}:{sha_text(seed)[:16]}"
    route: dict[str, Any] = {"inherit_effort": True}
    if next_model:
        route["model"] = wire_reference(next_model, fallback_kind="model")
    else:
        route["inherit_model"] = True
    intent: ContinuationIntentWire = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "intent_id": intent_id,
        "next_action": next_action,
        "checkpoint_ref": checkpoint_ref,
        "route": cast(ContinuationModelRouteWire, route),
        "outcome_policy_ref": source_ref(
            "monitor-policy",
            next_output or "default",
            request_fingerprint,
        ),
    }
    validation = capture_validation(
        "validate_continuation_intent",
        intent,
        allow_missing_validation=allow_missing_validation,
    )
    root = continuation_root(artifacts_dir)
    filename = f"{intent_id}.json"
    intent_path = root / "intents" / filename
    intent_sha = write_json_atomic(intent_path, intent)
    intent_ref = local_ref("intents", filename)
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
    write_json_atomic(manifest_path, manifest)
    fields: dict[str, Any] = {
        "continuation_intent_id": intent_id,
        "continuation_intent_ref": intent_ref,
        "continuation_intent_manifest_ref": local_ref("monitor_intent_manifest.json"),
        "continuation_checkpoint_ref": checkpoint_ref,
    }
    if parent_node_ids:
        fields["continuation_parent_node_ids"] = list(parent_node_ids)
    update_agent_meta_fields(artifacts_dir, fields)
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
) -> _MonitorResultPublishResult | None:
    """Persist a terminal monitor result without interrupting settlement."""

    try:
        return _persist_monitor_result(
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


def _persist_monitor_result(
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
) -> _MonitorResultPublishResult:
    """Publish a frozen monitor-result record and graph node."""

    from sase.monitor.result_projection import build_monitor_result_wire

    root = continuation_root(artifacts_dir)
    root.mkdir(parents=True, exist_ok=True)
    monitor_id = required_text(meta.get("monitor_id"), "monitor")
    diagnostic_ref = (
        diagnostic_manifest.get("manifest_ref") if diagnostic_manifest else None
    ) or meta.get("monitor_diagnostic_manifest_ref")
    result = build_monitor_result_wire(
        monitor_id=monitor_id,
        monitor_state=monitor_state,
        exit_code=exit_code,
        command=_monitor_command(meta),
        cwd=required_text(meta.get("monitor_cwd"), required_text(meta.get("cwd"), "")),
        started_at=required_text(meta.get("run_started_at"), "unknown"),
        stopped_at=stopped_at,
        elapsed_seconds=elapsed_seconds,
        timeout_seconds=optional_float(meta.get("monitor_timeout_seconds")),
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
    result_validation = capture_validation(
        "validate_monitor_result",
        result,
        allow_missing_validation=allow_missing_validation,
    )

    result_filename = f"{result['result_id']}.json"
    result_path = root / "records" / "monitor_result" / result_filename
    result_sha = write_json_atomic(result_path, result)
    result_ref = local_ref("records", "monitor_result", result_filename)

    node_id = _monitor_result_node_id(result)
    node: ContinuationNodeWire = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "node_id": node_id,
        "kind": "monitor_result",
        "parent_ids": parent_node_ids_from_mapping(meta, exclude=node_id),
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
    workspace_ref = wire_reference_or_none(
        optional_str(meta.get("continuation_workspace_ref"))
        or optional_str(meta.get("workspace_dir"))
    )
    if workspace_ref:
        node["workspace_ref"] = workspace_ref
    checkpoint_ref = optional_str(meta.get("continuation_checkpoint_ref"))
    if checkpoint_ref:
        node["checkpoint_ref"] = checkpoint_ref
    intent_ref = optional_str(meta.get("continuation_intent_ref"))
    if intent_ref:
        node["intent_ref"] = intent_ref
    node_validation = capture_validation(
        "validate_continuation_node",
        node,
        allow_missing_validation=allow_missing_validation,
    )

    node_path = root / "nodes" / f"{node_id}.json"
    node_sha = write_json_atomic(node_path, node)
    node_ref = local_ref("nodes", f"{node_id}.json")
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
    write_json_atomic(manifest_path, manifest)
    manifest_ref = local_ref("monitor_result_manifest.json")

    published = _MonitorResultPublishResult(
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
        update_agent_meta_fields(artifacts_dir, fields)
    return published


def _monitor_result_node_id(result: MonitorResultWire) -> str:
    suffix = str(result["result_id"]).removeprefix("result:")
    return f"monitor-result:{safe_identifier(suffix, max_len=180)}"


def _owner_from_monitor_meta(
    meta: Mapping[str, Any],
    artifacts_dir: str | os.PathLike[str],
    *,
    project_name: str | None = None,
) -> dict[str, str]:
    owner = {
        "project": safe_identifier(
            project_name
            or optional_str(meta.get("project_name"))
            or optional_str(meta.get("project"))
            or "unknown"
        ),
        "run_id": safe_identifier(Path(artifacts_dir).name),
        "agent_name": safe_identifier(
            optional_str(meta.get("name"))
            or optional_str(meta.get("monitor_id"))
            or "monitor"
        ),
    }
    workspace_id = meta.get("workspace_num")
    if workspace_id is not None:
        owner["workspace_id"] = safe_identifier(str(workspace_id))
    try:
        owner["machine_name"] = safe_identifier(socket.gethostname())
    except OSError:
        pass
    return owner


def _monitor_command(meta: Mapping[str, Any]) -> object:
    argv = meta.get("monitor_execution_argv")
    if isinstance(argv, list) and argv:
        return [str(part) for part in argv if str(part)]
    return meta.get("monitor_command")
