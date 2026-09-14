"""Receiver-ownership proofs and manual-revision branch allocation for resume."""

from __future__ import annotations

from collections.abc import Mapping
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

from sase.continuation_capture import AuthoredCheckpoint, persist_monitor_start_intent
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.finalizers.declaration_store import write_json_atomic

from .continuation_delivery import maybe_crash
from .delivery import (
    MANUAL_SUPERSEDE_REASON_PREFIX,
    decide_resume_adoption,
    delivery_store_lock,
    load_delivery_record,
    load_delivery_records,
    transition_delivery,
    write_delivery_record_locked,
)
from .identity import supervisor_is_alive
from .models import MonitorRecord
from .resume_delivery_state import delivery_identity
from .resume_support import read_json_object, read_meta, utc_now_iso

_MANUAL_BRANCH_RE = re.compile(r"^manual-recovery-(\d+)$")


def apply_resume_adoption(
    record: MonitorRecord,
    meta: dict[str, Any],
    *,
    monitor_id: str,
    result_id: str,
    kind: str,
    requested_branch: str,
    checkpoint: AuthoredCheckpoint | None,
    selected_model: str | None,
    next_action: str,
    proofs: list[dict[str, Any]],
) -> tuple[dict[str, Any], bool, str | None]:
    """Reload current deliveries, decide, fence, and allocate under one lock.

    Spawn, provider invocation, and process waits stay outside this
    transaction. Receiver proofs are collected before the lock is taken.
    Intent revision persistence for a newly admitted manual branch stays
    inside the lock so concurrent identical revisions cannot publish
    conflicting checkpoint files.
    """

    artifacts_dir = record.artifacts_dir
    with delivery_store_lock(artifacts_dir):
        current = [
            item
            for item in load_delivery_records(
                artifacts_dir,
                monitor_id=monitor_id,
                result_id=result_id,
            )
            if item.get("selected_action") == "continue"
        ]
        maybe_crash("before_resume_decision")
        reused = False
        existing_manual: str | None = None
        next_manual: str | None = None
        fingerprint: str | None = None
        if kind == "manual_revision":
            existing_manual, next_manual, reused, fingerprint = (
                _plan_manual_branch_unlocked(
                    artifacts_dir,
                    monitor_id=monitor_id,
                    result_id=result_id,
                    checkpoint=checkpoint,
                    selected_model=selected_model,
                    next_action=next_action,
                )
            )
        decision = decide_resume_adoption(
            {
                "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
                "records": current,
                "request": {
                    "kind": kind,
                    "monitor_id": monitor_id,
                    "result_id": result_id,
                    "requested_branch": requested_branch,
                    "revision_fingerprint": fingerprint,
                    "existing_manual_branch": existing_manual,
                    "next_manual_branch": next_manual,
                },
                "receiver_proofs": proofs,
                "recorded_at": utc_now_iso(),
            }
        )
        branch = str(decision.get("selected_branch") or requested_branch)
        reason = f"{MANUAL_SUPERSEDE_REASON_PREFIX} branch {branch}"
        for key in decision.get("fence_keys") or []:
            if not isinstance(key, Mapping):
                continue
            current_record = load_delivery_record(artifacts_dir, key)
            if current_record is None:
                continue
            updated = transition_delivery(
                current_record,
                "needs_attention",
                reason=reason,
            )
            write_delivery_record_locked(artifacts_dir, updated)
        maybe_crash("after_resume_fence")
        if (
            kind == "manual_revision"
            and decision.get("admit")
            and next_manual
            and not reused
            and branch == next_manual
            and fingerprint is not None
        ):
            _write_manual_branch_unlocked(
                artifacts_dir,
                monitor_id=monitor_id,
                result_id=result_id,
                branch=next_manual,
                fingerprint=fingerprint,
                checkpoint=checkpoint,
                selected_model=selected_model,
            )
        checkpoint_ref: str | None = None
        if kind == "manual_revision" and decision.get("admit"):
            if not reused:
                checkpoint_ref = _persist_manual_intent_revision(
                    record,
                    meta,
                    branch=branch,
                    checkpoint=checkpoint,
                    selected_model=selected_model,
                )
            else:
                refreshed = read_meta(artifacts_dir)
                checkpoint_ref = (
                    str(
                        refreshed.get("continuation_checkpoint_ref")
                        or meta.get("continuation_checkpoint_ref")
                        or (checkpoint.content_ref if checkpoint is not None else "")
                        or ""
                    )
                    or None
                )
        return decision, reused, checkpoint_ref


def _persist_manual_intent_revision(
    record: MonitorRecord,
    meta: dict[str, Any],
    *,
    branch: str,
    checkpoint: AuthoredCheckpoint | None,
    selected_model: str | None,
) -> str | None:
    checkpoint_ref = checkpoint.content_ref if checkpoint is not None else None
    checkpoint_document = checkpoint.payload if checkpoint is not None else None
    persist_monitor_start_intent(
        artifacts_dir=record.artifacts_dir,
        monitor_id=record.monitor_id,
        member_agent_name=record.member_agent_name,
        project_name=record.project_name,
        command=record.command,
        cwd=record.cwd,
        next_action=str(meta.get("monitor_next_action") or ""),
        next_model=selected_model,
        next_output=str(meta.get("monitor_next_output") or record.next_output),
        request_fingerprint=str(meta.get("monitor_request_fingerprint") or ""),
        parent_node_ids=tuple(
            item
            for item in meta.get("continuation_parent_node_ids", [])
            if isinstance(item, str)
        ),
        starter_agent=(
            str(meta.get("monitor_starter_agent"))
            if meta.get("monitor_starter_agent")
            else None
        ),
        checkpoint_ref=checkpoint_ref,
        checkpoint_document=checkpoint_document,
        starter_artifacts_dir=(
            str(meta.get("monitor_starter_artifacts_dir"))
            if meta.get("monitor_starter_artifacts_dir")
            else None
        ),
        intent_revision=branch,
        allow_missing_validation=True,
    )
    refreshed = read_meta(record.artifacts_dir)
    meta.clear()
    meta.update(refreshed)
    return str(meta.get("continuation_checkpoint_ref") or checkpoint_ref or "")


def _plan_manual_branch_unlocked(
    artifacts_dir: str,
    *,
    monitor_id: str,
    result_id: str,
    checkpoint: AuthoredCheckpoint | None,
    selected_model: str | None,
    next_action: str,
) -> tuple[str | None, str | None, bool, str]:
    fingerprint = _manual_revision_fingerprint(
        monitor_id=monitor_id,
        result_id=result_id,
        checkpoint_ref=checkpoint.content_ref if checkpoint is not None else None,
        selected_model=selected_model,
        next_action=next_action,
    )
    root = Path(artifacts_dir) / "continuation" / "manual_resume"
    root.mkdir(parents=True, exist_ok=True)
    for path in sorted(root.glob("manual-recovery-*.json")):
        payload = read_json_object(path)
        if payload.get("fingerprint") == fingerprint:
            branch = str(payload.get("branch") or "")
            if branch:
                return branch, None, True, fingerprint
    used = _used_manual_branch_numbers(root, artifacts_dir)
    number = 1
    while number in used:
        number += 1
    return None, f"manual-recovery-{number}", False, fingerprint


def _write_manual_branch_unlocked(
    artifacts_dir: str,
    *,
    monitor_id: str,
    result_id: str,
    branch: str,
    fingerprint: str,
    checkpoint: AuthoredCheckpoint | None,
    selected_model: str | None,
) -> None:
    root = Path(artifacts_dir) / "continuation" / "manual_resume"
    root.mkdir(parents=True, exist_ok=True)
    write_json_atomic(
        root / f"{branch}.json",
        {
            "schema_version": 1,
            "kind": "manual_monitor_resume",
            "branch": branch,
            "fingerprint": fingerprint,
            "monitor_id": monitor_id,
            "result_id": result_id,
            "checkpoint_ref": checkpoint.content_ref
            if checkpoint is not None
            else None,
            "next_model": selected_model,
            "recorded_at": utc_now_iso(),
        },
    )


def _used_manual_branch_numbers(root: Path, artifacts_dir: str) -> set[int]:
    used: set[int] = set()
    for path in root.glob("manual-recovery-*.json"):
        payload = read_json_object(path)
        number = _manual_branch_number(str(payload.get("branch") or path.stem))
        if number is not None:
            used.add(number)
    for record in load_delivery_records(artifacts_dir):
        raw_key = record.get("key")
        key = raw_key if isinstance(raw_key, Mapping) else {}
        number = _manual_branch_number(str(key.get("branch") or ""))
        if number is not None:
            used.add(number)
    return used


def _manual_branch_number(branch: str) -> int | None:
    match = _MANUAL_BRANCH_RE.match(branch)
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _manual_revision_fingerprint(
    *,
    monitor_id: str,
    result_id: str,
    checkpoint_ref: str | None,
    selected_model: str | None,
    next_action: str,
) -> str:
    payload = {
        "monitor_id": monitor_id,
        "result_id": result_id,
        "checkpoint_ref": checkpoint_ref,
        "selected_model": selected_model,
        "next_action": next_action,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def collect_receiver_proofs(
    record: MonitorRecord,
    deliveries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Collect launch-receipt and process-identity proofs outside the lock."""

    meta = read_meta(record.artifacts_dir)
    followup_agent = meta.get("monitor_followup_agent")
    followup_outcome = meta.get("monitor_followup_outcome")
    proofs: list[dict[str, Any]] = []
    for delivery in deliveries:
        raw_key = delivery.get("key")
        key = raw_key if isinstance(raw_key, Mapping) else {}
        branch = str(key.get("branch") or "")
        if not branch:
            continue
        identity = delivery_identity(delivery)
        discoverable = False
        process_alive = False
        spawn_recorded = bool(delivery.get("workspace_identity"))
        if identity:
            ctx = _try_resolve_agent(record.project_name, identity)
            if ctx is not None:
                spawn_recorded = True
                process_alive = _receiver_process_alive(ctx)
                discoverable = process_alive
            if followup_agent == identity and followup_outcome == "launched":
                spawn_recorded = True
        proofs.append(
            {
                "branch": branch,
                "identity": identity,
                "discoverable": discoverable,
                "process_alive": process_alive,
                "spawn_recorded": spawn_recorded,
            }
        )
    return proofs


def _try_resolve_agent(project_name: str, identity: str) -> Any | None:
    try:
        from .store_lane import resolve_exact_agent

        return resolve_exact_agent(project_name, identity)
    except Exception:
        return None


def _receiver_process_alive(ctx: Any) -> bool:
    running = getattr(ctx.record, "running", None)
    if running is not None and getattr(running, "pid", None) is not None:
        return supervisor_is_alive(running.pid, running.process_identity)
    meta = getattr(ctx.record, "agent_meta", None)
    if meta is None or getattr(meta, "pid", None) is None:
        return False
    identity = None
    family_shell = getattr(meta, "family_shell", None)
    if family_shell is not None:
        identity = getattr(family_shell, "supervisor_identity", None)
    return supervisor_is_alive(meta.pid, identity)


__all__ = [
    "apply_resume_adoption",
    "collect_receiver_proofs",
]
