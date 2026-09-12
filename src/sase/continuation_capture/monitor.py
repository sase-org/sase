"""Monitor continuation intent and result publication."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import socket
import time
from typing import Any, cast

from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    ContinuationExecutionIdentityWire,
    ContinuationIntentWire,
    ContinuationModelRouteWire,
    ContinuationNodeWire,
    MonitorResultWire,
)

from ._disposition import (
    CAPTURE_DISPOSITION_NEEDS_RECOVERY,
    CAPTURE_DISPOSITION_OK,
    record_capture_disposition,
)
from ._storage import (
    PublicationTransaction,
    continuation_root,
    iter_string_list,
    optional_float,
    optional_str,
    read_json_object,
    recover_publication_journal,
    required_text,
    safe_identifier,
    sha_text,
    source_ref,
    unique_identifiers,
    update_agent_meta_fields,
    wire_reference,
    wire_reference_or_none,
    record_capture_error,
)
from ._validation import (
    validate_continuation_intent_capture,
    validate_continuation_node_capture,
    validate_monitor_result_capture,
)
from .checkpoints import publish_handoff_checkpoint
from .models import MonitorResultPublishResult


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
    checkpoint_ref: str | None = None,
    checkpoint_document: Mapping[str, Any] | None = None,
    starter_artifacts_dir: str | None = None,
    meta: dict[str, Any] | None = None,
    intent_revision: str | None = None,
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
            checkpoint_ref=checkpoint_ref,
            checkpoint_document=checkpoint_document,
            starter_artifacts_dir=starter_artifacts_dir,
            intent_revision=intent_revision,
            allow_missing_validation=True,
        )
    except Exception as exc:
        record_capture_error(artifacts_dir, "monitor_intent", exc)
        record_capture_disposition(
            artifacts_dir,
            disposition=CAPTURE_DISPOSITION_NEEDS_RECOVERY,
            error=str(exc),
            meta=meta,
        )
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
    checkpoint_ref: str | None = None,
    checkpoint_document: Mapping[str, Any] | None = None,
    starter_artifacts_dir: str | None = None,
    intent_revision: str | None = None,
    allow_missing_validation: bool = False,
) -> str:
    """Persist and validate a continuation intent for a monitor's next action."""

    resolved_parent_ids = list(parent_node_ids) or _hydrate_parent_node_ids(
        {},
        starter_artifacts_dir=starter_artifacts_dir,
    )
    authored_ref = checkpoint_ref
    if checkpoint_document:
        from .checkpoints import (
            canonicalize_authored_checkpoint,
            persist_authored_checkpoint,
        )

        authored = canonicalize_authored_checkpoint(checkpoint_document)
        authored_ref = persist_authored_checkpoint(
            artifacts_dir,
            authored,
            host_facts={
                "monitor_id": monitor_id,
                "member_agent_name": member_agent_name,
                "project_name": project_name,
                "command": command,
                "cwd": cwd,
                "parent_node_ids": resolved_parent_ids,
                "starter_agent": starter_agent,
                "starter_artifacts_dir": starter_artifacts_dir,
            },
            parent_ids=resolved_parent_ids,
            owner={
                "project": safe_identifier(project_name or "unknown"),
                "run_id": safe_identifier(Path(artifacts_dir).name),
                "agent_name": safe_identifier(member_agent_name or "monitor"),
            },
        )
    host_checkpoint_ref = publish_handoff_checkpoint(
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
            "parent_node_ids": resolved_parent_ids,
            "starter_agent": starter_agent,
            "starter_artifacts_dir": starter_artifacts_dir,
        },
    )
    checkpoint_ref = authored_ref or host_checkpoint_ref
    seed = (
        f"{monitor_id}\0{next_action}\0{next_model or ''}\0{next_output}"
        f"\0{intent_revision or ''}"
    )
    intent_id = f"intent:{safe_identifier(monitor_id)}:{sha_text(seed)[:16]}"
    route: dict[str, Any] = {"inherit_effort": True}
    if next_model:
        route["model"] = wire_reference(next_model, fallback_kind="model")
    else:
        route["inherit_model"] = True
    outcome_policy_ref = _frozen_outcome_policy_ref(artifacts_dir)
    intent: ContinuationIntentWire = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "intent_id": intent_id,
        "next_action": next_action,
        "checkpoint_ref": checkpoint_ref,
        "route": cast(ContinuationModelRouteWire, route),
        "outcome_policy_ref": outcome_policy_ref
        or source_ref(
            "monitor-policy",
            next_output or "default",
            request_fingerprint,
        ),
    }
    validation = validate_continuation_intent_capture(
        intent,
        allow_missing_validation=allow_missing_validation,
    )
    root = continuation_root(artifacts_dir)
    recover_publication_journal(root)
    filename = f"{intent_id}.json"
    txn = PublicationTransaction(root)
    intent_ref, intent_sha = txn.write_record("intents", filename, payload=intent)
    manifest: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "monitor_start_intent",
        "intent_id": intent_id,
        "intent_ref": intent_ref,
        "intent_sha256": intent_sha,
        "checkpoint_ref": checkpoint_ref,
        "parent_node_ids": list(resolved_parent_ids),
        "validation": {"intent": validation},
        "recorded_at_epoch": time.time(),
    }
    manifest_ref, _ = txn.write_pointer(
        "monitor_intent_manifest.json",
        payload=manifest,
    )
    txn.commit()
    fields: dict[str, Any] = {
        "continuation_intent_id": intent_id,
        "continuation_intent_ref": intent_ref,
        "continuation_intent_manifest_ref": manifest_ref,
        "continuation_checkpoint_ref": checkpoint_ref,
        "continuation_capture_disposition": CAPTURE_DISPOSITION_OK,
    }
    if resolved_parent_ids:
        fields["continuation_parent_node_ids"] = list(resolved_parent_ids)
    if starter_artifacts_dir:
        fields["monitor_starter_artifacts_dir"] = starter_artifacts_dir
    update_agent_meta_fields(artifacts_dir, fields)
    return intent_ref


def _frozen_outcome_policy_ref(artifacts_dir: str | os.PathLike[str]) -> str | None:
    meta = read_json_object(Path(artifacts_dir) / "agent_meta.json")
    if isinstance(meta, Mapping):
        stored = meta.get("continuation_outcome_policy_ref")
        if isinstance(stored, str) and stored.strip():
            return stored.strip()
    from .policy import load_frozen_outcome_policy

    frozen = load_frozen_outcome_policy(str(artifacts_dir))
    fingerprint = frozen.get("fingerprint") if frozen else None
    if isinstance(fingerprint, str) and fingerprint:
        return fingerprint
    return None


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
    parent_ids = _hydrate_parent_node_ids(meta, exclude=node_id)
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
    missing_starter_parent = _missing_essential_starter_parent(meta, parent_ids)
    if missing_starter_parent:
        fields["continuation_capture_disposition"] = CAPTURE_DISPOSITION_NEEDS_RECOVERY
        fields["continuation_capture_error"] = missing_starter_parent
    else:
        fields["continuation_capture_disposition"] = CAPTURE_DISPOSITION_OK
    if parent_ids:
        fields["continuation_parent_node_ids"] = list(parent_ids)
    if isinstance(meta, dict):
        meta.update(fields)
    if update_meta:
        update_agent_meta_fields(artifacts_dir, fields)
    return published


def _monitor_result_node_id(result: MonitorResultWire) -> str:
    suffix = str(result["result_id"]).removeprefix("result:")
    return f"monitor-result:{safe_identifier(suffix, max_len=180)}"


def _parent_node_ids_from_meta(
    meta: Mapping[str, Any],
    *,
    exclude: str | None = None,
) -> list[str]:
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


def _hydrate_parent_node_ids(
    meta: Mapping[str, Any],
    *,
    exclude: str | None = None,
    starter_artifacts_dir: str | None = None,
) -> list[str]:
    ids = _parent_node_ids_from_meta(meta, exclude=exclude)
    if ids:
        return ids
    starter_dir = starter_artifacts_dir or optional_str(
        meta.get("monitor_starter_artifacts_dir")
    )
    if not starter_dir:
        return []
    starter_meta = read_json_object(Path(starter_dir) / "agent_meta.json")
    return _parent_node_ids_from_meta(starter_meta, exclude=exclude)


def _missing_essential_starter_parent(
    meta: Mapping[str, Any],
    parent_ids: Sequence[str],
) -> str | None:
    if optional_str(meta.get("monitor_state")) in {"stopped", "lost"}:
        return None
    next_action = optional_str(meta.get("monitor_next_action"))
    if not next_action:
        return None
    has_starter = optional_str(meta.get("monitor_starter_agent")) or optional_str(
        meta.get("monitor_starter_artifacts_dir")
    )
    if not has_starter:
        return None
    if parent_ids:
        return None
    return (
        "monitor result is missing its exact starter parent node; "
        "automatic dispatch is blocked pending recovery"
    )


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


__all__ = [
    "persist_monitor_result",
    "persist_monitor_result_best_effort",
    "persist_monitor_start_intent",
    "persist_monitor_start_intent_best_effort",
]
