"""Evidence readers and record helpers for hijack latch reconciliation."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.hijack import ledger
from sase.agent.hijack._stop_models import HijackTarget
from sase.running_field import WorkspaceClaim, get_claimed_workspaces


def _string(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def owner_observation(record: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    raw_pid = record.get("owner_pid")
    if raw_pid is None:
        return {"lookup_succeeded": False}, "unknown"
    try:
        pid = int(raw_pid)
    except (TypeError, ValueError):
        return {"lookup_succeeded": False}, "unknown"
    if pid <= 1 or not _string(record.get("owner_identity")):
        return {"lookup_succeeded": False}, "unknown"
    try:
        from sase.ace.hooks.processes import is_process_running

        live = is_process_running(pid)
    except Exception:
        return {"lookup_succeeded": False, "pid": pid}, "unknown"
    if not live:
        return {"lookup_succeeded": True, "pid": None}, "dead"
    try:
        from sase.core.process_identity import process_identity_token

        token = process_identity_token(pid) or None
    except Exception:
        token = None
    observation = {
        "lookup_succeeded": True,
        "pid": pid,
        "process_identity": token,
    }
    if token is None:
        return observation, "unknown"
    if token != str(record.get("owner_identity") or ""):
        return observation, "dead"
    return observation, "live"


def matching_claim(
    record: Mapping[str, Any], project_file: str, artifacts_dir: str
) -> WorkspaceClaim | None:
    raw_workspace = record.get("workspace_num")
    raw_expected_owner = (
        record.get("expected_claim_owner_pid")
        if record.get("expected_claim_owner_pid") is not None
        else record.get("owner_pid")
    )
    if raw_workspace is None or raw_expected_owner is None:
        return None
    try:
        workspace = int(raw_workspace)
        expected_owner = int(raw_expected_owner)
    except (TypeError, ValueError):
        return None
    try:
        claims = get_claimed_workspaces(project_file)
    except Exception:
        return None
    candidates = [
        claim
        for claim in claims
        if claim.workspace_num == workspace
        and claim.artifacts_timestamp == Path(artifacts_dir).name
        and int(claim.pid) == expected_owner
    ]
    return candidates[0] if len(candidates) == 1 else None


def target_from_record(
    record: Mapping[str, Any],
    claim: WorkspaceClaim | None,
    done_outcome: str | None,
) -> HijackTarget:
    artifacts_dir = str(record.get("artifacts_dir") or "")
    raw_pid = record.get("owner_pid")
    try:
        pid = None if raw_pid is None else int(raw_pid)
    except (TypeError, ValueError):
        pid = None
    project_file = str(record.get("project_file") or "")
    session = record.get("session")
    is_monitor = str(record.get("scope") or "") == "monitor"
    monitor_id = None
    supervisor_identity = None
    if is_monitor and artifacts_dir:
        from sase.agent.hijack._stop_models import read_json_dict

        meta = read_json_dict(Path(artifacts_dir) / "agent_meta.json") or {}
        raw_id = meta.get("monitor_id")
        monitor_id = raw_id if isinstance(raw_id, str) and raw_id else None
        raw_identity = meta.get("monitor_supervisor_identity")
        supervisor_identity = (
            raw_identity if isinstance(raw_identity, str) and raw_identity else None
        )
    return HijackTarget(
        name=str(record.get("agent_name") or ""),
        artifacts_dir=artifacts_dir,
        project_name=str(record.get("project_name") or Path(project_file).parent.name),
        project_file=project_file,
        artifacts_timestamp=Path(artifacts_dir).name,
        is_home=False,
        pid=pid,
        claim_pid=(
            int(claim.pid)
            if claim is not None
            else int(
                record.get("expected_claim_owner_pid") or record.get("owner_pid") or 0
            )
        ),
        claim_pinned=bool(claim.pinned) if claim is not None else False,
        cl_name=claim.cl_name
        if claim is not None
        else _optional_string(record.get("cl_name")),
        workflow=claim.workflow
        if claim is not None
        else _optional_string(record.get("workflow")),
        workspace_num=(
            int(claim.workspace_num)
            if claim is not None
            else int(record.get("workspace_num") or 0)
        ),
        workspace_dir=(
            str(record.get("workspace_dir"))
            if record.get("workspace_dir") is not None
            else None
        ),
        status="DONE",
        lifecycle_phase=None,
        is_monitor_turn=is_monitor,
        is_gate_turn=False,
        gate_state=None,
        agent_session=str(session) if isinstance(session, str) else None,
        capabilities=[],
        model_alias=_optional_string(record.get("model_alias")),
        model_alias_trail=[],
        model_origin=_optional_string(record.get("model_origin")),
        provider=_optional_string(record.get("provider")),
        model=_optional_string(record.get("model")),
        effort=_optional_string(record.get("effort")),
        run_started_at=None,
        done_outcome=done_outcome,
        done_recovery=None,
        monitor_id=monitor_id,
        monitor_supervisor_identity=supervisor_identity,
    )


def successor_observation(
    record: Mapping[str, Any], artifacts_dir: str
) -> tuple[dict[str, Any], str | None]:
    absent = {"kind": "absent"}
    try:
        from sase.agent.staged_handoff import (
            read_adoption_receipt,
            read_staged_handoff,
            read_staged_successor,
            receipt_authorizes,
        )

        staged = read_staged_handoff(artifacts_dir)
        receipt = read_adoption_receipt(artifacts_dir)
        successor = read_staged_successor(artifacts_dir)
    except Exception as exc:  # malformed evidence is uncertainty, never absence.
        return {"kind": "uncertain"}, f"staged handoff evidence is malformed: {exc}"

    staged_id = _optional_string((staged or {}).get("staged_id"))
    receipt_id = _optional_string((receipt or {}).get("staged_id"))
    successor_id = _optional_string((successor or {}).get("staged_id"))
    if len({item for item in (staged_id, receipt_id, successor_id) if item}) > 1:
        return {
            "kind": "uncertain"
        }, "staged handoff, receipt, and successor identities disagree"
    stage_id = staged_id or receipt_id or successor_id
    if stage_id is None:
        return absent, None

    receipt_adopted = False
    receipt_refs: Mapping[str, Any] = {}
    if receipt is not None:
        if str(receipt.get("outcome") or "") == "adopted":
            try:
                receipt_adopted = bool(receipt_authorizes(receipt, stage_id))
            except Exception as exc:
                return {
                    "kind": "uncertain"
                }, f"adoption receipt could not be verified: {exc}"
            raw_refs = receipt.get("refs")
            if isinstance(raw_refs, Mapping):
                receipt_refs = raw_refs
            if not receipt_adopted:
                return {
                    "kind": "uncertain"
                }, "adoption receipt does not authorize the staged handoff"
    if successor is None:
        if receipt_adopted:
            return {"kind": "uncertain"}, "adopted receipt has no successor manifest"
        return absent, None
    state = str(successor.get("delivery_state") or "")
    if state == "prepared" and not receipt_adopted:
        return absent, None
    if not receipt_adopted:
        return {
            "kind": "uncertain"
        }, "successor delivery exists without an authorizing adoption receipt"
    identity = successor.get("successor")
    if not isinstance(identity, Mapping):
        return {"kind": "uncertain"}, "successor manifest has no identity"
    successor_dir = _optional_string(identity.get("artifacts_dir"))
    launch_identity = _optional_string(identity.get("launch_identity"))
    if not successor_dir or not launch_identity:
        return {"kind": "uncertain"}, "successor manifest lacks durable launch identity"
    if receipt_refs.get("successor_artifacts_dir") not in (None, successor_dir):
        return {
            "kind": "uncertain"
        }, "adopted receipt names a different successor artifacts directory"
    if receipt_refs.get("successor_launch_identity") not in (None, launch_identity):
        return {
            "kind": "uncertain"
        }, "adopted receipt names a different successor launch identity"
    meta = _read_json(Path(successor_dir) / "agent_meta.json")
    if meta is None:
        return {
            "kind": "uncertain"
        }, "adopted successor has no readable process metadata"
    if (
        meta.get("name") != identity.get("agent_name")
        or meta.get("staged_handoff_id") != stage_id
        or meta.get("staged_successor_launch_id") != launch_identity
    ):
        return {
            "kind": "uncertain"
        }, "successor process metadata does not match its manifest"
    raw_pid = meta.get("pid")
    try:
        pid = 0 if raw_pid is None else int(raw_pid)
    except (TypeError, ValueError):
        pid = 0
    process_identity = _optional_string(meta.get("process_identity"))
    if pid <= 1 or process_identity is None:
        return {
            "kind": "uncertain"
        }, "adopted successor has no verified process identity"
    owner_identity = _optional_string(record.get("owner_identity"))
    if owner_identity is None:
        return {"kind": "uncertain"}, "latch owner process identity is missing"
    return {
        "kind": "launched",
        "source_member": str(record.get("agent_name") or ""),
        "source_artifacts_dir": artifacts_dir,
        "source_identity": owner_identity,
        "launch_identity": launch_identity,
        "admission_request_id": _optional_string(meta.get("admission_request_id")),
        "name": str(identity.get("agent_name") or ""),
        "pid": pid,
        "process_identity": process_identity,
        "artifacts_dir": successor_dir,
    }, None


def suppressed_stage(artifacts_dir: str) -> tuple[dict[str, str] | None, str | None]:
    from sase.agent.staged_handoff import STAGED_HANDOFF_FILENAME, read_staged_handoff

    path = Path(artifacts_dir) / STAGED_HANDOFF_FILENAME
    if not path.is_file():
        return None, None
    try:
        staged = read_staged_handoff(artifacts_dir)
    except Exception as exc:
        return {
            "kind": "staged",
            "ref": str(path),
        }, f"staged payload identity is malformed: {exc}"
    if staged is None:
        return None, None
    return {
        "kind": str(staged.get("kind") or "staged"),
        "ref": str(path),
    }, None


def read_real_outcome(artifacts_dir: str) -> str | None:
    done = _read_json(Path(artifacts_dir) / "done.json")
    outcome = done.get("outcome") if done else None
    if not isinstance(outcome, str) or not outcome or outcome == "hijacked":
        return None
    return outcome


def _read_json(path: Path) -> dict[str, Any] | None:
    import json

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def save_error(hijack_id: str, error: str) -> None:
    try:
        ledger.merge_record_fields(hijack_id, {"error": error})
    except Exception:
        pass


def clear_error(hijack_id: str) -> None:
    try:
        ledger.merge_record_fields(hijack_id, {"error": None})
    except Exception:
        pass


def _optional_string(value: object) -> str | None:
    result = _string(value)
    return result or None
