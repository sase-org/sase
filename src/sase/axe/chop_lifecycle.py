"""Finalize runner-owned chop actions from linked agent artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
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

    if not launches:
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
            launches = list(entry.launches)
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

            failures = [f"proposal launch failed: {entry.error}"] if entry.error else []
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
                else (f"all {len(launches)} launched agent(s) completed successfully")
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
