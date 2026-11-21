"""Recent failed-row enumeration for the healer's pending sweep.

Sources, in order of preference:

1. the persistent agent artifact index, read as a recency window over its
   completed tier (rows that finished within the lookback), so a sweep
   decodes a week of completed rows instead of walking every artifact
   directory;
2. the bounded artifact scan facade, when the index file is missing or the
   index query fails;
3. the read-only history walk, when the scan also fails.

All three apply the same window: a failed row is enumerated only when its
artifact timestamp is inside :data:`HISTORY_LOOKBACK_SECONDS`.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agent.auto_restart._healer_common import read_json

if TYPE_CHECKING:
    from sase.core.agent_scan_wire_records import (
        AgentArtifactRecordWire,
        AgentArtifactScanOptionsWire,
    )

#: Failed rows older than this are never enumerated from history. In-flight
#: and skew-suspect rows stay eligible across the window; legacy rows get
#: the tighter ``max_defer_seconds`` bound inside ``is_healer_candidate``.
HISTORY_LOOKBACK_SECONDS = 7 * 86400


@dataclass(frozen=True)
class _RecentRow:
    """One recent failed row from any enumeration source."""

    artifacts_dir: Path
    project: str
    agent_name: str
    died_at: float | None
    done: dict[str, Any]


def recent_failure_rows(*, now: float | None = None) -> list[_RecentRow]:
    """Return recent failed rows, preferring the artifact index."""
    at = time.time() if now is None else now
    try:
        rows = _rows_via_index(now=at)
    except Exception:
        rows = None
    if rows is not None:
        return rows
    try:
        return _rows_via_scan(now=at)
    except Exception:
        pass
    return _rows_via_history(now=at)


def row_died_at(done: Mapping[str, Any], artifacts_dir: Path) -> float | None:
    """Return when a failed row died: ``finished_at``, else its artifact stamp."""
    finished = done.get("finished_at")
    if isinstance(finished, (int, float)) and not isinstance(finished, bool):
        return float(finished)
    try:
        from sase.agent.auto_restart.history import parse_artifact_stamp

        return parse_artifact_stamp(artifacts_dir.name)
    except Exception:
        return None


def _lookback_stamp(now: float) -> str:
    import datetime

    from sase.core.time import get_timezone

    return datetime.datetime.fromtimestamp(
        now - HISTORY_LOOKBACK_SECONDS, tz=get_timezone()
    ).strftime("%Y%m%d%H%M%S")


def _scan_options(
    *, not_before_timestamp: str | None = None
) -> AgentArtifactScanOptionsWire:
    from sase.core.agent_scan_wire_records import AgentArtifactScanOptionsWire

    return AgentArtifactScanOptionsWire(
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
        include_workflow_state=False,
        include_waiting=False,
        not_before_timestamp=not_before_timestamp,
        newest_first=True,
    )


def _rows_via_index(*, now: float) -> list[_RecentRow] | None:
    """Enumerate recent failed rows from the artifact index's completed tier.

    Every failed row carries a done marker, so it sits in the index's
    completed tier, which is paged newest ``finished_at`` first and stops
    one page past the lookback; only failed rows are rehydrated. Hidden and
    dismissed rows are included, matching the filesystem scan. Returns
    ``None`` when the index file is missing; query errors propagate so the
    caller falls back to the scan.
    """
    from sase.core.agent_artifact_index_recent import (
        query_recently_completed_payload_records,
    )
    from sase.core.agent_scan_facade import default_agent_artifact_index_path
    from sase.core.agent_scan_wire import agent_artifact_records_from_dicts
    from sase.core.paths import sase_projects_dir

    index_path = default_agent_artifact_index_path()
    if not index_path.is_file():
        return None
    stamp = _lookback_stamp(now)
    failed = query_recently_completed_payload_records(
        index_path,
        sase_projects_dir(),
        finished_after=now - HISTORY_LOOKBACK_SECONDS,
        keep=_is_failed_payload,
        options=_scan_options(),
        include_hidden=True,
    )
    records = agent_artifact_records_from_dicts(failed)
    rows: list[_RecentRow] = []
    for record in sorted(records, key=lambda item: item.timestamp, reverse=True):
        if record.timestamp < stamp:
            continue
        row = _row_from_record(record)
        if row is not None:
            rows.append(row)
    return rows


def _is_failed_payload(record: Mapping[str, Any]) -> bool:
    """Mirror :func:`_row_from_record`'s outcome test on a raw record dict."""
    done = record.get("done")
    return isinstance(done, Mapping) and done.get("outcome") == "failed"


def _rows_via_scan(*, now: float) -> list[_RecentRow]:
    """Enumerate recent failed rows through the artifact scan facade.

    The ``not_before_timestamp`` bound keeps completed rows inside the
    lookback, but the walk still visits every artifact directory. Raises on
    any problem so the caller falls back to the history walk.
    """
    from sase.core.agent_scan_facade import scan_agent_artifacts
    from sase.core.paths import sase_projects_dir

    options = _scan_options(not_before_timestamp=_lookback_stamp(now))
    scan = scan_agent_artifacts(sase_projects_dir(), options)
    rows: list[_RecentRow] = []
    for record in scan.records:
        row = _row_from_record(record)
        if row is not None:
            rows.append(row)
    return rows


def _row_from_record(record: AgentArtifactRecordWire) -> _RecentRow | None:
    """Project one scan or index record into a failed row, or ``None``."""
    done_wire = record.done
    if done_wire is None or done_wire.outcome != "failed":
        return None
    artifacts_dir = Path(str(record.artifact_dir))
    done = read_json(artifacts_dir / "done.json") or {}
    if not done:
        done = {
            "outcome": done_wire.outcome,
            "error": done_wire.error,
            "traceback": done_wire.traceback,
            "finished_at": done_wire.finished_at,
        }
    name = (record.agent_meta.name if record.agent_meta else None) or (
        done_wire.name or artifacts_dir.name
    )
    finished = done.get("finished_at")
    died_at = (
        float(finished)
        if isinstance(finished, (int, float)) and not isinstance(finished, bool)
        else row_died_at(done, artifacts_dir)
    )
    return _RecentRow(
        artifacts_dir=artifacts_dir,
        project=record.project_name,
        agent_name=str(name),
        died_at=died_at,
        done=dict(done),
    )


def _rows_via_history(*, now: float) -> list[_RecentRow]:
    """Enumerate recent failed rows through the read-only history walk."""
    from sase.agent.auto_restart.history import collect_failed_candidates

    rows: list[_RecentRow] = []
    candidates = collect_failed_candidates(
        since_seconds=HISTORY_LOOKBACK_SECONDS, now=now
    )
    for candidate in candidates:
        # Dismissed bundles are never healer candidates.
        if candidate.source != "done" or candidate.artifacts_dir is None:
            continue
        done = candidate.done
        rows.append(
            _RecentRow(
                artifacts_dir=candidate.artifacts_dir,
                project=candidate.project,
                agent_name=candidate.name,
                died_at=candidate.died_at,
                done=dict(done) if isinstance(done, Mapping) else {},
            )
        )
    return rows


__all__ = [
    "HISTORY_LOOKBACK_SECONDS",
    "recent_failure_rows",
    "row_died_at",
]
