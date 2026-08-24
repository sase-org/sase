"""Launch-to-agent-record matching for chop action lifecycle finalization."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sase.artifacts import convert_timestamp_to_artifacts_format

from ._chop_lifecycle_completion import record_artifacts_dir
from ._chop_lifecycle_types import MatchedAgentRecord
from .state import ChopRunEntry


def duration_ms(entry: ChopRunEntry, finished_at: datetime) -> int:
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
    artifacts_dir = record_artifacts_dir(record)
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


def match_records_to_launches(
    records: list[object],
    launches: list[dict[str, object]],
) -> tuple[list[MatchedAgentRecord], list[object], list[str]]:
    """Match launch roots and their retry successors to registry records."""
    available = set(range(len(records)))
    matched: list[MatchedAgentRecord] = []
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
            matched.append(MatchedAgentRecord(record=record, launch=launch))

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


__all__ = ["duration_ms", "match_records_to_launches"]
