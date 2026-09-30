"""Worker-grant demand writer for ``tools/run_pytest`` (stdlib only).

A grant decision appends one JSON line per grant to the ``SASE_TOOL_RUN_DEMAND``
channel the executing ToolRun wrapper pointed at it. The wrapper reads the file
once, after the reap, and merges the grants into the run's demand record. The
writer is a no-op unless both ``SASE_TOOL_RUN_DEMAND`` and ``SASE_TOOL_RUN_ID``
are set, and it never raises: demand evidence must not change the suite result.
"""

from __future__ import annotations

import json
import os
import secrets
import time

#: Grant channel the ToolRun wrapper sets beside ``SASE_TOOL_RUN_EVENTS``.
DEMAND_ENV = "SASE_TOOL_RUN_DEMAND"

#: Run the grant belongs to; the wrapper keeps only matching records.
RUN_ID_ENV = "SASE_TOOL_RUN_ID"

#: One ``O_APPEND`` write carries at most this many bytes.
_MAX_LINE_BYTES = 4096


def record_worker_grant(
    *,
    path: str,
    requested_floor: int,
    requested_ceiling: int,
    granted: int,
    lane: str | None = None,
    budget: int | None = None,
    wait_ms: int = 0,
    selected_files: int | None = None,
    escalated_from: str | None = None,
    grant_id: str | None = None,
    observed_ts_ms: int | None = None,
    source: str = "pytest",
) -> str | None:
    """Append one worker-grant record; return its id, or ``None``.

    Returns ``None`` without writing when the demand channel or run id is
    unset, when the line would exceed 4 KiB, or on any write failure. Never
    raises.
    """

    demand_path = os.environ.get(DEMAND_ENV)
    run_id = os.environ.get(RUN_ID_ENV)
    if not demand_path or not run_id:
        return None
    resolved_grant_id = grant_id or secrets.token_hex(8)
    resolved_ts = (
        observed_ts_ms if observed_ts_ms is not None else int(time.time() * 1000)
    )
    line = {
        "schema_version": 1,
        "kind": "worker_grant",
        "run_id": run_id,
        "grant": {
            "grant_id": resolved_grant_id,
            "source": source,
            "observed_ts_ms": resolved_ts,
            "lane": lane,
            "path": path,
            "requested_floor": requested_floor,
            "requested_ceiling": requested_ceiling,
            "granted": granted,
            "budget": budget,
            "wait_ms": wait_ms,
            "selected_files": selected_files,
            "escalated_from": escalated_from,
        },
    }
    try:
        encoded = (json.dumps(line) + "\n").encode("utf-8")
    except (TypeError, ValueError):
        return None
    if len(encoded) > _MAX_LINE_BYTES:
        return None
    try:
        fd = os.open(demand_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    except OSError:
        return None
    try:
        os.write(fd, encoded)
    except OSError:
        return None
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
    return resolved_grant_id
