"""Persist continuation intent for a monitor's next action."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import time
from typing import Any, cast

from sase.core.continuation_wire import (
    CONTINUATION_WIRE_SCHEMA_VERSION,
    ContinuationIntentWire,
    ContinuationModelRouteWire,
)

from ._disposition import (
    CAPTURE_DISPOSITION_NEEDS_RECOVERY,
    CAPTURE_DISPOSITION_OK,
    record_capture_disposition,
)
from ._monitor_parents import hydrate_parent_node_ids
from ._storage import (
    PublicationTransaction,
    RequiredPortableCaptureError,
    attach_portable_locator,
    continuation_root,
    read_json_object,
    recover_publication_journal,
    safe_identifier,
    sha_text,
    source_ref,
    update_agent_meta_fields,
    wire_reference,
    record_capture_error,
)
from ._validation import validate_continuation_intent_capture
from .checkpoints import publish_handoff_checkpoint
from .rollout import monitor_continuation_records_enabled_for_meta


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

    if not next_action or not _records_enabled_for_artifacts(artifacts_dir, meta=meta):
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

    resolved_parent_ids = list(parent_node_ids) or hydrate_parent_node_ids(
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
    try:
        intent_portable = attach_portable_locator(
            artifacts_dir,
            intent_ref,
            root / "intents" / filename,
            label="monitor-intent",
            required=True,
        )
        if intent_portable:
            fields["continuation_intent_portable_ref"] = intent_portable
    except RequiredPortableCaptureError as exc:
        fields["continuation_capture_disposition"] = CAPTURE_DISPOSITION_NEEDS_RECOVERY
        fields["continuation_capture_error"] = str(exc)
        if not allow_missing_validation:
            update_agent_meta_fields(artifacts_dir, fields)
            raise
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


def _records_enabled_for_artifacts(
    artifacts_dir: str | os.PathLike[str],
    *,
    meta: Mapping[str, Any] | None = None,
) -> bool:
    if meta is not None:
        return monitor_continuation_records_enabled_for_meta(meta)
    loaded = read_json_object(Path(artifacts_dir) / "agent_meta.json")
    return (
        monitor_continuation_records_enabled_for_meta(loaded)
        if isinstance(loaded, Mapping)
        else False
    )
