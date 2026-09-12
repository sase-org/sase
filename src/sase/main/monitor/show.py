"""Show handler for ``sase monitor``."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from rich.console import Console

from sase.monitor import MonitorRecord, MonitorRefError, read_monitor_marker

from ..monitor_render import monitor_detail, monitor_show_json
from .common import resolve_ref

_ALL_OUTPUT_LINES = 1_000_000
_KILLED_EXIT_CODE = 130
_FOLLOW_POLL_SECONDS = 0.5


def handle_monitor_show(args: argparse.Namespace) -> int:
    """Show one monitor's detail panel and captured output."""
    validation_error = _validate_show_args(args)
    if validation_error is not None:
        print(f"sase monitor show: {validation_error}", file=sys.stderr)
        return 2
    try:
        record = resolve_ref(getattr(args, "monitor_id", ""))
    except MonitorRefError as exc:
        print(f"sase monitor show: {exc}", file=sys.stderr)
        return 2

    output_only = bool(getattr(args, "output_only", False))
    follow = bool(getattr(args, "follow", False))

    if getattr(args, "format", "markdown") == "json":
        # JSON is a snapshot, so following means "wait, then report the result".
        if follow and not record.is_terminal:
            try:
                record = _wait_for_monitor(record)
            except KeyboardInterrupt:
                return _KILLED_EXIT_CODE
        output, evidence = _output_text_and_evidence(record, args)
        payload = monitor_show_json(record, output=output, evidence=evidence)
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if not output_only:
        Console().print(monitor_detail(record))

    if follow:
        try:
            return _follow_output(record, args)
        except KeyboardInterrupt:
            return _KILLED_EXIT_CODE

    output, _evidence = _output_text_and_evidence(record, args)
    if output:
        sys.stdout.write(output if output.endswith("\n") else f"{output}\n")
    elif not output_only:
        print("(no output captured yet)")
    return 0


def _follow_output(record: MonitorRecord, args: argparse.Namespace) -> int:
    """Print the retained output, then stream new lines until terminal."""
    path = _output_path(record)
    retained = _output_text(record, args)
    if retained:
        sys.stdout.write(retained if retained.endswith("\n") else f"{retained}\n")

    try:
        offset = path.stat().st_size
    except OSError:
        offset = 0

    while True:
        current = read_monitor_marker(record.project_name, record.artifacts_dir)
        if current is None:
            print("sase monitor show: monitor record disappeared", file=sys.stderr)
            return 1
        new_text, offset = _read_new_text(path, offset)
        if new_text:
            sys.stdout.write(new_text)
            sys.stdout.flush()
        if current.is_terminal:
            return 0
        time.sleep(_FOLLOW_POLL_SECONDS)


def _wait_for_monitor(record: MonitorRecord) -> MonitorRecord:
    """Poll silently until *record*'s monitor reaches a terminal state."""
    while True:
        current = read_monitor_marker(record.project_name, record.artifacts_dir)
        if current is None:
            return record
        if current.is_terminal:
            return current
        time.sleep(_FOLLOW_POLL_SECONDS)


def _output_path(record: MonitorRecord) -> Path:
    if record.output_path:
        return Path(record.output_path)

    from sase.monitor.logs import monitor_log_path

    return monitor_log_path(record.artifacts_dir)


def _output_text(record: MonitorRecord, args: argparse.Namespace) -> str:
    from sase.monitor.logs import read_monitor_log_tail

    return read_monitor_log_tail(_output_path(record), _log_lines(args))


def _output_text_and_evidence(
    record: MonitorRecord,
    args: argparse.Namespace,
) -> tuple[str, dict[str, object] | None]:
    if bool(getattr(args, "diagnostics", False)):
        from sase.monitor.diagnostics import read_diagnostics_text

        result = read_diagnostics_text(
            record.artifacts_dir,
            max_bytes=_show_max_bytes(args),
        )
        return result.text, result.metadata
    raw_range = getattr(args, "raw_range", None)
    if raw_range:
        from sase.monitor.diagnostics import read_retained_log_range

        start, end = _parse_raw_range(raw_range)
        result = read_retained_log_range(
            record.artifacts_dir,
            start=start,
            end=end,
            max_bytes=_show_max_bytes(args),
        )
        return result.text, result.metadata
    evidence = _retained_log_evidence(record)
    return _output_text(record, args), evidence


def _retained_log_evidence(record: MonitorRecord) -> dict[str, object] | None:
    from sase.monitor.diagnostics import retained_log_metadata

    metadata = retained_log_metadata(record.artifacts_dir)
    if not metadata:
        return None
    return {"mode": "tail", "retained_log": metadata}


def _validate_show_args(args: argparse.Namespace) -> str | None:
    diagnostics = bool(getattr(args, "diagnostics", False))
    raw_range = getattr(args, "raw_range", None)
    follow = bool(getattr(args, "follow", False))
    all_lines = bool(getattr(args, "all_lines", False))
    if diagnostics and raw_range:
        return "--diagnostics and --range are mutually exclusive"
    if diagnostics and follow:
        return "--diagnostics cannot be combined with --follow"
    if raw_range and follow:
        return "--range cannot be combined with --follow"
    if raw_range and all_lines:
        return "--range cannot be combined with --all-lines"
    if raw_range:
        try:
            _parse_raw_range(raw_range)
        except ValueError as exc:
            return str(exc)
    if _show_max_bytes(args) <= 0:
        return "--max-bytes must be positive"
    return None


def _parse_raw_range(value: str) -> tuple[int, int]:
    if ":" not in value:
        raise ValueError("--range must use START:END")
    raw_start, raw_end = value.split(":", 1)
    try:
        start = int(raw_start)
        end = int(raw_end)
    except ValueError as exc:
        raise ValueError("--range START and END must be integers") from exc
    if start < 0 or end < start:
        raise ValueError("--range must satisfy 0 <= START <= END")
    return start, end


def _show_max_bytes(args: argparse.Namespace) -> int:
    return int(getattr(args, "max_bytes", 64 * 1024) or 0)


def _read_new_text(path: Path, offset: int) -> tuple[str, int]:
    try:
        current_size = path.stat().st_size
    except OSError:
        return "", offset
    if current_size < offset:
        offset = 0
    try:
        with open(path, "rb") as f:
            f.seek(offset)
            chunk = f.read()
    except OSError:
        return "", offset
    if not chunk:
        return "", offset
    return chunk.decode("utf-8", errors="replace"), offset + len(chunk)


def _log_lines(args: argparse.Namespace) -> int:
    if bool(getattr(args, "all_lines", False)):
        return _ALL_OUTPUT_LINES
    return max(0, getattr(args, "log_lines", 200))


__all__ = [
    "_read_new_text",
    "handle_monitor_show",
]
