"""Finalize runner-owned chop actions from linked agent artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

from sase.ace.dismissed_agents import load_dismissed_bundle_summaries
from sase.ace.hooks.processes import is_process_running
from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.core.agent_artifact_paths import resolve_agent_artifact_timestamp_path
from sase.core.time import get_timezone

from .chop_agents import (
    garbage_collect_chop_agent_records,
    get_chop_agent_records,
    remove_chop_agent_records,
)
from .chop_typed_admission import (
    UNIT_DISPATCH_METADATA_KEY,
    launch_descriptor_from_metadata,
)
from .chop_policy import (
    finalize_pending_chop_checkpoints,
    release_chop_once_per_keys,
)
from .state import (
    ChopRunEntry,
    ChopRunStatus,
    append_chop_run_output,
    finish_chop_run,
    read_chop_run,
    read_chop_run_index,
)

_SUCCESS_DONE_OUTCOMES = {
    "completed",
    "epic_approved",
    "noop",
    "plan_committed",
    "plan_rejected",
}


@dataclass(frozen=True)
class _AgentCompletion:
    terminal: bool
    succeeded: bool
    detail: str


@dataclass(frozen=True)
class _MatchedAgentRecord:
    record: object
    launch: dict[str, object]


@dataclass(frozen=True)
class _TypedAdmissionReconciliation:
    applies: bool = False
    waiting: bool = False
    launches: list[dict[str, object]] | None = None
    failures: list[str] | None = None
    release_keys: list[str] | None = None
    success_detail: str = ""


def _record_artifacts_dir(record: object) -> Path | None:
    project_name = str(getattr(record, "project_name", ""))
    timestamp = str(getattr(record, "artifacts_timestamp", ""))
    if not project_name or not timestamp:
        return None
    return resolve_agent_artifact_timestamp_path(
        project_name,
        "ace-run",
        timestamp,
    )


def _dismissed_bundle_completion(
    record: object,
    *,
    pid: int,
) -> _AgentCompletion | None:
    raw_suffix = str(getattr(record, "artifacts_timestamp", "") or "").strip()
    if not raw_suffix:
        return None

    summaries = load_dismissed_bundle_summaries(
        suffixes={raw_suffix},
        top_level_only=True,
        limit=None,
    )
    summary = next(
        (
            candidate
            for candidate in summaries
            if getattr(candidate, "raw_suffix", None) == raw_suffix
            and not bool(getattr(candidate, "is_workflow_child", False))
        ),
        None,
    )
    if summary is None:
        return None

    status = str(getattr(summary, "status", "") or "unknown").strip().upper()
    bundle_path = str(getattr(summary, "bundle_path", "") or "archive")
    return _AgentCompletion(
        terminal=True,
        succeeded=status == "DONE",
        detail=(
            f"agent pid {pid} dismissed bundle {bundle_path} reports status {status}"
        ),
    )


def _agent_completion(record: object) -> _AgentCompletion:
    pid = int(getattr(record, "pid", 0) or 0)
    artifacts_dir = _record_artifacts_dir(record)
    done_path = artifacts_dir / "done.json" if artifacts_dir is not None else None
    if done_path is not None and done_path.is_file():
        try:
            raw = json.loads(done_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return _AgentCompletion(
                terminal=True,
                succeeded=False,
                detail=f"agent pid {pid} has unreadable done.json: {exc}",
            )
        if not isinstance(raw, dict):
            return _AgentCompletion(
                terminal=True,
                succeeded=False,
                detail=f"agent pid {pid} done.json is not an object",
            )
        outcome = str(raw.get("outcome") or "")
        if outcome in _SUCCESS_DONE_OUTCOMES or (
            outcome == "failed" and raw.get("retried_as_timestamp")
        ):
            return _AgentCompletion(
                terminal=True,
                succeeded=True,
                detail=f"agent pid {pid} finished with outcome {outcome}",
            )
        return _AgentCompletion(
            terminal=True,
            succeeded=False,
            detail=f"agent pid {pid} finished with outcome {outcome or 'unknown'}",
        )

    if pid > 0 and is_process_running(pid):
        return _AgentCompletion(
            terminal=False,
            succeeded=False,
            detail=f"agent pid {pid} is still running",
        )
    dismissed_completion = _dismissed_bundle_completion(record, pid=pid)
    if dismissed_completion is not None:
        return dismissed_completion
    location = str(done_path) if done_path is not None else "an unknown artifact path"
    return _AgentCompletion(
        terminal=True,
        succeeded=False,
        detail=f"agent pid {pid} exited without completion artifact {location}",
    )


def _duration_ms(entry: ChopRunEntry, finished_at: datetime) -> int:
    try:
        started_at = datetime.fromisoformat(entry.started_at)
    except ValueError:
        return entry.duration_ms
    if started_at.tzinfo is None:
        finished = finished_at.replace(tzinfo=None)
    else:
        finished = finished_at.astimezone(started_at.tzinfo)
    return max(0, int((finished - started_at).total_seconds() * 1000))


def _launch_artifacts_timestamp(launch: dict[str, object]) -> str:
    explicit = str(launch.get("artifacts_timestamp") or "").strip()
    if explicit:
        return explicit
    artifacts_dir = str(launch.get("artifacts_dir") or "").strip()
    if artifacts_dir:
        return Path(artifacts_dir).name
    timestamp = str(launch.get("timestamp") or "").strip()
    if timestamp:
        return convert_timestamp_to_artifacts_format(timestamp)
    return ""


def _launch_for_record(
    record: object,
    launches: list[dict[str, object]],
) -> dict[str, object] | None:
    artifacts_timestamp = str(getattr(record, "artifacts_timestamp", "") or "").strip()
    if artifacts_timestamp:
        launch = next(
            (
                candidate
                for candidate in launches
                if _launch_artifacts_timestamp(candidate) == artifacts_timestamp
            ),
            None,
        )
        if launch is not None:
            return launch

    pid = int(getattr(record, "pid", 0) or 0)
    return next(
        (
            candidate
            for candidate in launches
            if not _launch_artifacts_timestamp(candidate)
            and int(str(candidate.get("pid") or "0")) == pid
        ),
        None,
    )


def _retry_successor_timestamp(record: object) -> str:
    artifacts_dir = _record_artifacts_dir(record)
    done_path = artifacts_dir / "done.json" if artifacts_dir is not None else None
    if done_path is None or not done_path.is_file():
        return ""
    try:
        raw = json.loads(done_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(raw, dict):
        return ""
    return str(raw.get("retried_as_timestamp") or "").strip()


def _match_records_to_launches(
    records: list[object],
    launches: list[dict[str, object]],
) -> tuple[list[_MatchedAgentRecord], list[object], list[str]]:
    """Match launch roots and their retry successors to registry records."""
    available = set(range(len(records)))
    matched: list[_MatchedAgentRecord] = []
    linkage_failures: list[str] = []

    if not launches and records:
        linkage_failures.append(
            "launch registry linkage incomplete: expected 0 agent record(s), "
            f"found {len(records)}"
        )

    for launch_index, launch in enumerate(launches):
        record_index = next(
            (
                candidate_index
                for candidate_index in sorted(available)
                if _launch_for_record(records[candidate_index], [launch]) is not None
            ),
            None,
        )
        if record_index is None:
            timestamp = _launch_artifacts_timestamp(launch) or "unknown"
            pid = str(launch.get("pid") or "unknown")
            linkage_failures.append(
                "launch registry linkage incomplete: no agent record matched "
                f"launch {launch_index + 1} (artifacts timestamp {timestamp}, pid {pid})"
            )
            continue

        while record_index is not None:
            available.remove(record_index)
            record = records[record_index]
            matched.append(_MatchedAgentRecord(record=record, launch=launch))

            successor_timestamp = _retry_successor_timestamp(record)
            if not successor_timestamp:
                break
            record_index = next(
                (
                    candidate_index
                    for candidate_index in sorted(available)
                    if str(
                        getattr(
                            records[candidate_index],
                            "artifacts_timestamp",
                            "",
                        )
                        or ""
                    ).strip()
                    == successor_timestamp
                ),
                None,
            )
            if record_index is None:
                linkage_failures.append(
                    "launch registry linkage incomplete: retry successor "
                    f"{successor_timestamp} for launch {launch_index + 1} "
                    "has no agent record"
                )

    unmatched = [records[index] for index in sorted(available)]
    return matched, unmatched, linkage_failures


def _log_unmatched_records(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    records: list[object],
) -> None:
    if not records:
        return
    details = ", ".join(
        (
            f"pid {int(getattr(record, 'pid', 0) or 0)} "
            f"(artifacts timestamp "
            f"{str(getattr(record, 'artifacts_timestamp', '') or 'unknown')})"
        )
        for record in records
    )
    append_chop_run_output(
        lumberjack_name,
        chop_name,
        run_id,
        f"Ignored {len(records)} unmatched agent registry record(s): {details}\n",
    )


def _release_failed_launch_keys(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    matched_records: list[_MatchedAgentRecord],
    completions: list[_AgentCompletion],
) -> None:
    keys: list[str] = []
    for matched, completion in zip(matched_records, completions, strict=True):
        if completion.succeeded:
            continue
        key = str(matched.launch.get("dedupe_key") or "").strip()
        if key and key not in keys:
            keys.append(key)
    if not keys:
        return

    try:
        released = release_chop_once_per_keys(lumberjack_name, chop_name, keys)
    except Exception as exc:
        append_chop_run_output(
            lumberjack_name,
            chop_name,
            run_id,
            f"Failed to release once-per keys for failed launches: {exc}\n",
        )
        return
    append_chop_run_output(
        lumberjack_name,
        chop_name,
        run_id,
        f"Released {released} once-per key(s) for failed launches\n",
    )


def _release_typed_nonlaunched_keys(
    *,
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    keys: list[str],
) -> None:
    keys = list(dict.fromkeys(key for key in keys if key))
    if not keys:
        return
    try:
        released = release_chop_once_per_keys(lumberjack_name, chop_name, keys)
    except Exception as exc:
        append_chop_run_output(
            lumberjack_name,
            chop_name,
            run_id,
            f"Failed to release once-per keys after typed admission: {exc}\n",
        )
        return
    append_chop_run_output(
        lumberjack_name,
        chop_name,
        run_id,
        f"Released {released} once-per key(s) after typed admission\n",
    )


def _typed_admission_reconciliation(
    *,
    entry: ChopRunEntry,
    records: list[object],
) -> _TypedAdmissionReconciliation:
    typed = entry.typed_admission
    if not isinstance(typed, dict):
        return _TypedAdmissionReconciliation()
    bundle_raw = str(typed.get("bundle_dir") or "")
    if not bundle_raw:
        return _TypedAdmissionReconciliation(
            applies=True,
            failures=["typed admission linkage incomplete: missing bundle path"],
        )
    bundle_dir = Path(bundle_raw).expanduser()
    payload = _read_typed_admission_payload(bundle_dir)
    if payload is None:
        return _TypedAdmissionReconciliation(
            applies=True,
            failures=[
                "typed admission linkage incomplete: launch bundle is missing or invalid"
            ],
        )

    receipt = _read_admission_receipt(bundle_dir)
    if not _receipt_complete(receipt):
        if _coordinator_live(bundle_dir):
            return _TypedAdmissionReconciliation(applies=True, waiting=True)
        try:
            from sase.agent.launch_admission import dispatch_typed_launch_request

            progress = dispatch_typed_launch_request(
                bundle_dir,
                payload,
                spawn_coordinator=True,
            )
        except Exception as exc:
            return _TypedAdmissionReconciliation(
                applies=True,
                failures=[f"typed admission coordinator restart failed: {exc}"],
            )
        if not progress.admission_complete:
            return _TypedAdmissionReconciliation(applies=True, waiting=True)
        receipt = _read_admission_receipt(bundle_dir)

    if not isinstance(receipt, dict):
        return _TypedAdmissionReconciliation(
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
                    artifacts_dir=str(_record_artifacts_dir(record) or ""),
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
    return _TypedAdmissionReconciliation(
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


def finalize_launched_chop_runs(
    lumberjack_name: str,
    chop_names: list[str] | tuple[str, ...],
) -> int:
    """Finalize launched runs whose linked agents are all terminal.

    Returns the number of run-history entries transitioned during this pass.
    Missing linkage and dead agents without completion artifacts fail closed so
    a run cannot remain in ``launched`` forever.
    """
    garbage_collect_chop_agent_records(lumberjack_name)
    finalized = 0
    for chop_name in chop_names:
        for run_id in read_chop_run_index(lumberjack_name, chop_name):
            entry = read_chop_run(lumberjack_name, chop_name, run_id)
            if entry is None or entry.status != "launched":
                continue

            records = get_chop_agent_records(
                lumberjack_name,
                chop_name=chop_name,
                run_id=run_id,
            )
            typed_reconciliation = _typed_admission_reconciliation(
                entry=entry,
                records=list(records),
            )
            if typed_reconciliation.waiting:
                continue
            if typed_reconciliation.applies:
                _release_typed_nonlaunched_keys(
                    lumberjack_name=lumberjack_name,
                    chop_name=chop_name,
                    run_id=run_id,
                    keys=list(typed_reconciliation.release_keys or []),
                )
            launches = (
                list(typed_reconciliation.launches or [])
                if typed_reconciliation.applies
                else list(entry.launches)
            )
            matched_records, unmatched_records, linkage_failures = (
                _match_records_to_launches(list(records), launches)
            )
            if linkage_failures:
                completions = [
                    _AgentCompletion(True, False, detail) for detail in linkage_failures
                ]
            else:
                completions = [
                    _agent_completion(matched.record) for matched in matched_records
                ]

            if any(not completion.terminal for completion in completions):
                continue

            _log_unmatched_records(
                lumberjack_name=lumberjack_name,
                chop_name=chop_name,
                run_id=run_id,
                records=unmatched_records,
            )

            if matched_records and not linkage_failures:
                _release_failed_launch_keys(
                    lumberjack_name=lumberjack_name,
                    chop_name=chop_name,
                    run_id=run_id,
                    matched_records=matched_records,
                    completions=completions,
                )

            failures = list(typed_reconciliation.failures or [])
            if entry.error and not typed_reconciliation.applies:
                failures.append(f"proposal launch failed: {entry.error}")
            failures.extend(
                completion.detail
                for completion in completions
                if not completion.succeeded
            )
            checkpoint_event: Literal["action_succeeded", "action_failed"] = (
                "action_failed" if failures else "action_succeeded"
            )
            try:
                finalize_pending_chop_checkpoints(
                    lumberjack_name,
                    chop_name,
                    checkpoint_event,
                )
            except Exception as exc:
                failures.append(f"checkpoint finalization failed: {exc}")
            status: ChopRunStatus = "action_failed" if failures else "action_succeeded"
            detail = (
                "; ".join(failures)
                if failures
                else (
                    typed_reconciliation.success_detail
                    if typed_reconciliation.applies
                    else f"all {len(launches)} launched agent(s) completed successfully"
                )
            )
            append_chop_run_output(
                lumberjack_name,
                chop_name,
                run_id,
                f"\nChop action lifecycle: {status}: {detail}\n",
            )
            finished_at = datetime.now(get_timezone())
            finish_chop_run(
                lumberjack_name,
                chop_name,
                run_id,
                status=status,
                finished_at=finished_at.isoformat(),
                duration_ms=_duration_ms(entry, finished_at),
                exit_code=entry.exit_code,
                agent_pid=entry.agent_pid,
                error=detail if failures else None,
                traceback=entry.traceback,
            )
            remove_chop_agent_records(
                lumberjack_name,
                chop_name=chop_name,
                run_id=run_id,
            )
            finalized += 1
    return finalized


__all__ = ["finalize_launched_chop_runs"]
