"""Persist a terminal monitor result and its continuation graph node."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import socket
import time
from typing import Any, cast

from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    ContinuationExecutionIdentityWire,
    ContinuationNodeWire,
    MonitorResultWire,
)

from ._disposition import (
    CAPTURE_DISPOSITION_NEEDS_RECOVERY,
    CAPTURE_DISPOSITION_OK,
    record_capture_disposition,
)
from ._monitor_parents import (
    collect_parent_portable_refs,
    hydrate_parent_node_ids,
    missing_essential_starter_parent,
    wait_for_starter_settle,
)
from ._storage import (
    PublicationTransaction,
    RequiredPortableCaptureError,
    attach_portable_locator,
    continuation_root,
    optional_float,
    optional_str,
    recover_publication_journal,
    required_text,
    safe_identifier,
    wire_reference_or_none,
    record_capture_error,
    update_agent_meta_fields,
)
from ._validation import (
    validate_continuation_node_capture,
    validate_monitor_result_capture,
)
from .models import MonitorResultPublishResult
from .rollout import monitor_continuation_records_enabled_for_meta


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

    if not monitor_continuation_records_enabled_for_meta(meta):
        return None
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
        if isinstance(meta, dict):
            record_capture_disposition(
                artifacts_dir,
                disposition=CAPTURE_DISPOSITION_NEEDS_RECOVERY,
                error=str(exc),
                meta=meta,
            )
        else:
            record_capture_disposition(
                artifacts_dir,
                disposition=CAPTURE_DISPOSITION_NEEDS_RECOVERY,
                error=str(exc),
            )
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

    root = continuation_root(artifacts_dir)
    recover_publication_journal(root)
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
    result_validation = validate_monitor_result_capture(
        result,
        allow_missing_validation=allow_missing_validation,
    )

    txn = PublicationTransaction(root)
    result_filename = f"{result['result_id']}.json"
    result_ref, result_sha = txn.write_record(
        "records",
        "monitor_result",
        result_filename,
        payload=result,
    )
    result_path = root / "records" / "monitor_result" / result_filename

    node_id = _monitor_result_node_id(result)
    parent_ids = hydrate_parent_node_ids(meta, exclude=node_id)
    if not parent_ids and missing_essential_starter_parent(meta, parent_ids):
        starter_dir = optional_str(meta.get("monitor_starter_artifacts_dir"))
        if starter_dir and wait_for_starter_settle(starter_dir):
            parent_ids = hydrate_parent_node_ids(
                meta, exclude=node_id, starter_artifacts_dir=starter_dir
            )
    node: ContinuationNodeWire = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "node_id": node_id,
        "kind": "monitor_result",
        "parent_ids": parent_ids,
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
    node_validation = validate_continuation_node_capture(
        node,
        allow_missing_validation=allow_missing_validation,
    )

    node_ref, node_sha = txn.write_record(
        "nodes",
        f"{node_id}.json",
        payload=node,
    )
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
    manifest_ref, _ = txn.write_pointer(
        "monitor_result_manifest.json",
        payload=manifest,
    )
    txn.commit()
    manifest_path = root / "monitor_result_manifest.json"
    node_path = root / "nodes" / f"{node_id}.json"

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
    fields: dict[str, Any] = dict(published.marker_projection())
    missing_starter_parent = missing_essential_starter_parent(meta, parent_ids)
    if missing_starter_parent:
        fields["continuation_capture_disposition"] = CAPTURE_DISPOSITION_NEEDS_RECOVERY
        fields["continuation_capture_error"] = missing_starter_parent
    else:
        fields["continuation_capture_disposition"] = CAPTURE_DISPOSITION_OK
    if parent_ids:
        fields["continuation_parent_node_ids"] = list(parent_ids)
    try:
        result_portable = attach_portable_locator(
            artifacts_dir,
            result_ref,
            Path(result_path),
            label="monitor-result",
            required=True,
        )
        node_portable = attach_portable_locator(
            artifacts_dir,
            node_ref,
            node_path,
            label="monitor-result-node",
            required=True,
        )
        if result_portable:
            fields["continuation_monitor_result_portable_ref"] = result_portable
        if node_portable:
            fields["continuation_node_portable_ref"] = node_portable
        parent_portable = collect_parent_portable_refs(
            artifacts_dir,
            parent_ids,
            optional_str(meta.get("monitor_starter_artifacts_dir")),
        )
        if parent_portable:
            fields["continuation_parent_portable_refs"] = parent_portable
    except RequiredPortableCaptureError as exc:
        fields["continuation_capture_disposition"] = CAPTURE_DISPOSITION_NEEDS_RECOVERY
        fields["continuation_capture_error"] = str(exc)
        if isinstance(meta, dict):
            meta.update(fields)
        if update_meta:
            update_agent_meta_fields(artifacts_dir, fields)
        if not allow_missing_validation:
            raise
        return published
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
