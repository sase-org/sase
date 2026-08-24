"""Typed admission reconciliation for chop action lifecycle finalization."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from sase.ace.hooks.processes import is_process_running

from ._chop_lifecycle_completion import record_artifacts_dir
from ._chop_lifecycle_types import TypedAdmissionReconciliation
from .chop_typed_admission import (
    UNIT_DISPATCH_METADATA_KEY,
    launch_descriptor_from_metadata,
)
from .state import ChopRunEntry


def typed_admission_reconciliation(
    *,
    entry: ChopRunEntry,
    records: list[object],
) -> TypedAdmissionReconciliation:
    typed = entry.typed_admission
    if not isinstance(typed, dict):
        return TypedAdmissionReconciliation()
    bundle_raw = str(typed.get("bundle_dir") or "")
    if not bundle_raw:
        return TypedAdmissionReconciliation(
            applies=True,
            failures=["typed admission linkage incomplete: missing bundle path"],
        )
    bundle_dir = Path(bundle_raw).expanduser()
    payload = _read_typed_admission_payload(bundle_dir)
    if payload is None:
        return TypedAdmissionReconciliation(
            applies=True,
            failures=[
                "typed admission linkage incomplete: launch bundle is missing or invalid"
            ],
        )

    receipt = _read_admission_receipt(bundle_dir)
    if not _receipt_complete(receipt):
        if _coordinator_live(bundle_dir):
            return TypedAdmissionReconciliation(applies=True, waiting=True)
        try:
            from sase.agent.launch_admission import dispatch_typed_launch_request

            progress = dispatch_typed_launch_request(
                bundle_dir,
                payload,
                spawn_coordinator=True,
            )
        except Exception as exc:
            return TypedAdmissionReconciliation(
                applies=True,
                failures=[f"typed admission coordinator restart failed: {exc}"],
            )
        if not progress.admission_complete:
            return TypedAdmissionReconciliation(applies=True, waiting=True)
        receipt = _read_admission_receipt(bundle_dir)

    if not isinstance(receipt, dict):
        return TypedAdmissionReconciliation(
            applies=True,
            failures=["typed admission linkage incomplete: missing receipt"],
        )

    raw_units = receipt.get("units")
    unit_results = (
        [unit for unit in raw_units if isinstance(unit, dict)]
        if isinstance(raw_units, list)
        else []
    )
    metadata = _dispatch_metadata(payload)
    keys_by_logical_id = _typed_admission_keys(typed)
    failures: list[str] = []
    release_keys: list[str] = []
    launched_logical_ids: list[str] = []
    for unit in unit_results:
        logical_id = str(unit.get("logical_id") or "")
        outcome = str(unit.get("outcome") or "")
        message = str(unit.get("message") or outcome)
        if outcome == "launched":
            launched_logical_ids.append(logical_id)
            continue
        key = keys_by_logical_id.get(logical_id, "")
        if key:
            release_keys.append(key)
        if outcome in {"condition_error", "launch_error", "cancelled"}:
            failures.append(
                f"typed admission {logical_id or 'unknown'} {outcome}: {message}"
            )

    launches: list[dict[str, object]] = []
    records_by_logical_id = {
        str(getattr(record, "admission_logical_id", "") or ""): record
        for record in records
        if str(getattr(record, "admission_logical_id", "") or "")
    }
    for logical_id in launched_logical_ids:
        record = records_by_logical_id.get(logical_id)
        if record is None:
            failures.append(
                "typed admission linkage incomplete: no agent record matched "
                f"logical unit {logical_id}"
            )
            continue
        unit_meta = metadata.get(logical_id, {})
        launches.append(
            launch_descriptor_from_metadata(
                unit_meta,
                SimpleNamespace(
                    pid=int(getattr(record, "pid", 0) or 0),
                    agent_name=None,
                    workspace_num=int(getattr(record, "workspace_num", 0) or 0),
                    workspace_dir="",
                    project_name=str(getattr(record, "project_name", "") or ""),
                    workflow_name=str(getattr(record, "workflow_name", "") or ""),
                    cl_name=str(getattr(record, "cl_name", "") or ""),
                    timestamp="",
                    artifacts_timestamp=str(
                        getattr(record, "artifacts_timestamp", "") or ""
                    ),
                    artifacts_dir=str(record_artifacts_dir(record) or ""),
                ),
                logical_id=logical_id,
                fingerprint=str(getattr(record, "admission_fingerprint", "") or ""),
            )
        )

    raw_summary = receipt.get("summary")
    summary = raw_summary if isinstance(raw_summary, dict) else {}
    success_detail = (
        "typed admission completed: "
        f"{_json_int(summary.get('launched'))} launched, "
        f"{_json_int(summary.get('skipped'))} skipped"
    )
    return TypedAdmissionReconciliation(
        applies=True,
        launches=launches,
        failures=failures,
        release_keys=release_keys,
        success_detail=success_detail,
    )


def _read_typed_admission_payload(bundle_dir: Path) -> dict[str, object] | None:
    try:
        from sase.agent.launch_request_response import read_launch_request

        return read_launch_request(bundle_dir)
    except Exception:
        return None


def _read_admission_receipt(bundle_dir: Path) -> dict[str, object] | None:
    from sase.agent.launch_admission_store import (
        RECEIPT_FILENAME,
        admission_dir,
        read_json,
    )

    return read_json(admission_dir(bundle_dir) / RECEIPT_FILENAME)


def _receipt_complete(receipt: dict[str, object] | None) -> bool:
    return isinstance(receipt, dict) and bool(receipt.get("complete"))


def _coordinator_live(bundle_dir: Path) -> bool:
    from sase.agent.launch_admission_store import (
        SIDECAR_FILENAME,
        admission_dir,
        read_json,
    )

    sidecar = read_json(admission_dir(bundle_dir) / SIDECAR_FILENAME)
    pid = sidecar.get("pid") if isinstance(sidecar, dict) else None
    return isinstance(pid, int) and pid > 0 and is_process_running(pid)


def _dispatch_metadata(
    payload: dict[str, object],
) -> dict[str, dict[str, object]]:
    raw = payload.get(UNIT_DISPATCH_METADATA_KEY)
    if not isinstance(raw, dict):
        return {}
    result: dict[str, dict[str, object]] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, dict):
            result[key] = value
    return result


def _typed_admission_keys(typed: dict[str, object]) -> dict[str, str]:
    units = typed.get("units")
    if not isinstance(units, list):
        return {}
    result: dict[str, str] = {}
    for unit in units:
        if not isinstance(unit, dict):
            continue
        logical_id = str(unit.get("logical_id") or "")
        key = str(unit.get("dedupe_key") or "")
        if logical_id and key:
            result[logical_id] = key
    return result


def _json_int(value: object) -> int:
    if not isinstance(value, int | float | str):
        return 0
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = ["typed_admission_reconciliation"]
