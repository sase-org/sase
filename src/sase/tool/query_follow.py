"""``sase tool show --follow`` output streaming."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Any

from sase.core.tool_run import tool_run_show
from sase.tool._query_shared import (
    detail_retention,
    output_truncation,
    print_show,
    show_triage,
    write_bytes,
)
from sase.tool.control import (
    UnknownRunError,
    output_paths_for_run,
    wait_for_settlement,
)
from sase.tool.owner import owner_retention
from sase.tool.stage_protocol import attach_timeline

if TYPE_CHECKING:
    from sase.tool.query_show import ToolShowCliRequest


def handle_follow(request: ToolShowCliRequest, run_id: str) -> int:
    """Stream the output of record until the run settles, then summarize.

    Ctrl-C detaches the viewer and exits 130; the run continues.
    ``-F -j`` waits, then prints the final JSON envelope instead of the
    human summary.
    """

    try:
        first = tool_run_show(run_id)
    except Exception as exc:  # noqa: BLE001 - query failures are nonzero.
        print(str(exc), file=sys.stderr)
        return 1
    if not isinstance(first.get("run"), dict):
        diagnostic = "; ".join(str(item) for item in first.get("diagnostics") or ())
        print(diagnostic or f"tool run {run_id} was not found", file=sys.stderr)
        return 2
    offsets: dict[str, int] = {}
    notified: list[bool] = []
    ingestor = _follow_ingestor(first.get("run"))
    _stream_output_paths(first.get("run"), offsets)
    _notice_unretained_output(first["run"], notified)
    if ingestor is not None:
        for line in ingestor.tick():
            print(line, file=sys.stderr)

    def _on_poll(envelope: dict[str, Any]) -> None:
        run = envelope.get("run")
        if not isinstance(run, dict):
            return
        _stream_output_paths(run, offsets)
        nonlocal ingestor
        fresh = _follow_ingestor(run)
        if fresh is not None and (ingestor is None or fresh.path != ingestor.path):
            ingestor = fresh
        if ingestor is not None:
            for line in ingestor.tick():
                print(line, file=sys.stderr)

    try:
        final = wait_for_settlement(run_id, on_poll=_on_poll)
    except UnknownRunError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print(
            "sase tool show: detached; the run continues",
            file=sys.stderr,
        )
        return 130
    if final is None:  # No deadline is ever passed here; the loop ends settled.
        return 1
    run = final.get("run")
    if not isinstance(run, dict):
        print(f"tool run {run_id} was not found", file=sys.stderr)
        return 2
    _stream_output_paths(run, offsets)
    if ingestor is not None:
        for line in ingestor.tick():
            print(line, file=sys.stderr)
    _notice_unretained_output(run, notified)
    attach_timeline(final)
    final["triage"] = show_triage(run_id)
    final["output_truncation"] = output_truncation(run)
    final["detail_retention"] = detail_retention(run)
    final["owner_retention"] = owner_retention(run)
    if request.json:
        print(json.dumps(final, indent=2, sort_keys=True))
        return 0
    print_show(final)
    for diagnostic in final.get("diagnostics") or ():
        print(str(diagnostic), file=sys.stderr)
    return 0


def _follow_ingestor(run: object):  # type: ignore[no-untyped-def]
    if not isinstance(run, dict):
        return None
    logs = run.get("logs")
    raw = logs.get("events_path") if isinstance(logs, dict) else None
    if not raw:
        return None
    path = Path(str(raw))
    if not path.is_file():
        return None
    from sase.tool.stage_protocol import StageIngestor

    return StageIngestor(path=path, run_id=str(run.get("run_id") or ""))


def _stream_output_paths(run: object, offsets: dict[str, int]) -> None:
    """Print bytes appended to the output of record since the last poll."""

    if not isinstance(run, dict):
        return
    for path in output_paths_for_run(run):
        key = str(path)
        start = offsets.get(key, 0)
        try:
            if not path.is_file():
                continue
            size = path.stat().st_size
        except OSError:
            continue
        if size < start:
            start = 0
        if size == start:
            continue
        try:
            with open(path, "rb") as handle:
                handle.seek(start)
                chunk = handle.read()
        except OSError:
            continue
        offsets[key] = size
        if chunk:
            write_bytes(sys.stdout, chunk)


def _notice_unretained_output(run: dict[str, Any], notified: list[bool]) -> None:
    """Say once that an owner-bound run has no output of record to stream.

    A run still starting can lack its log for a moment, so the notice waits
    for a settled run or a pruned owner; the final call covers the rest.
    """

    if notified:
        return
    retention = owner_retention(run)
    if retention["owner"] == "none" or retention["log"] == "retained":
        return
    settled = str(run.get("state") or "") not in {"created", "running"}
    if not (settled or retention["owner"] == "pruned"):
        return
    notified.append(True)
    print(_unretained_message(run, retention), file=sys.stderr)


def _unretained_message(run: dict[str, Any], retention: dict[str, Any]) -> str:
    kind = str(run.get("owner_kind") or "owner")
    owner_id = str(run.get("owner_id") or "")
    path = retention.get("log_path")
    if retention["owner"] == "pruned":
        detail = (
            f"; its log {path} is missing" if path else "; its log was not recorded"
        )
        return f"sase: {kind} owner {owner_id} is no longer retained (pruned){detail}"
    if path:
        return f"sase: {kind} owner {owner_id} log {path} is missing or expired"
    return f"sase: {kind} owner {owner_id} did not record an output log"


__all__ = [
    "handle_follow",
]
