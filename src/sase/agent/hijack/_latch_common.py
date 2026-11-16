"""Shared helpers for the private hijack latch implementation modules."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from sase.agent.hijack import core, ledger
from sase.agent.hijack._stop_models import HijackTarget, StopDeps, read_json_dict


def same_owner(
    record: dict[str, Any],
    target: HijackTarget,
    identity: str | None,
    *,
    target_key: str,
) -> bool:
    return (
        same_owner_anchor(record, target, target_key=target_key)
        and bool(identity)
        and str(record.get("owner_identity") or "") == identity
    )


def same_owner_anchor(
    record: dict[str, Any],
    target: HijackTarget,
    *,
    target_key: str,
) -> bool:
    return (
        str(record.get("agent_name") or "") == target.name
        and str(record.get("artifacts_dir") or "") == target.artifacts_dir
        and record.get("owner_pid") == target.pid
        and str(record.get("target_key") or "") == target_key
    )


def owner_identity_for(target: HijackTarget) -> str | None:
    if target.pid is None or target.pid <= 0:
        return None
    metadata = read_json_dict(Path(target.artifacts_dir) / "agent_meta.json") or {}
    recorded = metadata.get("process_identity")
    recorded_identity = recorded.strip() if isinstance(recorded, str) else ""
    try:
        from sase.core.process_identity import process_identity_token

        current = process_identity_token(int(target.pid))
    except (OSError, RuntimeError, ValueError):
        current = ""
    if not current or (recorded_identity and current != recorded_identity):
        return None
    return current


def observe_record(
    record: dict[str, Any],
    *,
    target_key: str,
    boundary: str,
    target: HijackTarget,
    owner_identity: str | None = None,
) -> dict[str, Any]:
    identity = owner_identity or owner_identity_for(target)
    return core.agent_hijack_latch_observe(
        record,
        {
            "schema_version": core.agent_hijack_latch_wire_schema_version(),
            "target_key": target_key,
            "boundary": boundary,
            "member": target.name,
            "artifacts_dir": target.artifacts_dir,
            "owner_pid": target.pid,
            "owner_identity": identity,
        },
    )


def state_result(record: dict[str, Any], target_key: str) -> dict[str, Any]:
    state = str(record.get("state") or "")
    verdict = {
        "latched": "pending",
        "stopping": "applied" if record.get("latched_at") is not None else "no_latch",
        "held": "applied" if record.get("latched_at") is not None else "no_latch",
        "cancelled": "cancelled",
        "finished_first": "moot"
        if record.get("latched_at") is not None
        else "no_latch",
    }.get(state, "no_latch")
    return result(
        verdict,
        code=state or "no_latch",
        message=f"hijack latch is {state or 'absent'}",
        record=record,
        target_key=target_key,
    )


def application_pending(
    record: dict[str, Any], code: str, message: str
) -> dict[str, Any]:
    hijack_id = str(record.get("hijack_id") or "")
    if hijack_id:
        try:
            ledger.merge_record_fields(hijack_id, {"error": message})
            record = ledger.load_record(hijack_id) or record
        except Exception:
            pass
    return result(
        "applied",
        code=code,
        message=message,
        record=record,
        target_key=str(record.get("target_key") or ""),
        ready=False,
    )


def normalize_suppressed_followup(
    followup: dict[str, Any] | None,
) -> dict[str, str] | None:
    if not isinstance(followup, dict):
        return None
    kind = followup.get("kind")
    reference = followup.get("ref", followup.get("reference"))
    if not isinstance(kind, str) or not kind.strip():
        return None
    if not isinstance(reference, str) or not reference.strip():
        return None
    return {"kind": kind.strip(), "ref": reference.strip()}


def result(
    verdict: str,
    *,
    code: str,
    message: str,
    record: dict[str, Any] | None = None,
    target_key: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "code": code,
        "message": message,
        "hijack_id": None if record is None else record.get("hijack_id"),
        "target_key": target_key
        or (None if record is None else record.get("target_key")),
        "record": record,
        **fields,
    }


def current_time(deps: StopDeps) -> float:
    return float(deps.now() if deps.now is not None else time.time())


def apply_lock_path(hijack_id: str) -> Path:
    return ledger.hijack_record_path(hijack_id).with_suffix(".apply.lock")
