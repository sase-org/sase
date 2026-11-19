"""Grouped axe error-digest rendering and digest-file pruning."""

from __future__ import annotations

from collections.abc import Mapping
import logging
import os
from pathlib import Path
from typing import Any

from sase.core.axe_error_facade import (
    axe_error_wire_schema_version,
    group_errors,
    normalize_error_signature,
)
from sase.core.time import parse_local

_logger = logging.getLogger(__name__)

_NO_PYTHON_TRACEBACK = "<no python traceback: subprocess error>"
_EN_DASH = "\u2013"
_CAUSE_SAMPLE_CHARS = 80
_UNCLASSIFIED_SIGNATURE = "<unclassified>"

ERROR_DIGEST_MAX_AGE_DAYS = 30.0
ERROR_DIGEST_KEEP_COUNT = 50
ERROR_DIGEST_PRUNE_INTERVAL_SECONDS = 86400.0
ERROR_DIGEST_RETENTION_MARKER = ".error_digest_retention"
ERROR_DIGEST_DEDUP_PREFIX = "axe-error-digest:"


def error_digest_dir() -> Path:
    """Return the directory that holds ViewErrorReport digest files."""
    from sase.axe.state import axe_state_dir

    return axe_state_dir() / "error_digests"


def digest_dedup_key(interval_id: str) -> str:
    """Return the notification dedup key for one digest interval."""
    return f"{ERROR_DIGEST_DEDUP_PREFIX}{interval_id}"


def digest_record_from_errors(errors: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a digest record from raw ring entries.

    Uses the Rust grouping facade so one loud signature still becomes a
    single cause. Totals are the grouped counts, which matches a ring-only
    caller that has no durable interval counter.
    """
    entries: list[dict[str, Any]] = []
    for error in errors:
        routine = _as_str(error.get("lumberjack"), "unknown")
        job = _as_str(error.get("job"), "unknown")
        timestamp = _as_str(error.get("timestamp"), "")
        sample = _as_str(error.get("error"), "")
        entries.append(
            {
                "routine": routine,
                "job": job,
                "signature": _signature_of(error),
                "timestamp": timestamp,
                "sample": sample,
            }
        )
    grouped = _group_entries(entries)
    timestamps = [item["timestamp"] for item in entries if item["timestamp"]]
    interval_start = min(timestamps) if timestamps else ""
    interval_end = max(timestamps) if timestamps else ""
    return {
        "schema_version": _wire_schema_version(),
        "interval_id": "",
        "interval_start": interval_start,
        "interval_end": interval_end,
        "total": sum(int(group.get("count") or 0) for group in grouped),
        "write_failures": 0,
        "corrupt_files": 0,
        "samples_kept": len(errors),
        "groups": grouped,
        "ring_samples": [dict(error) for error in errors],
    }


def render_error_digest(record: Mapping[str, Any]) -> str:
    """Render a grouped digest body with a true-total header and per-cause detail."""
    causes = _causes_with_samples(record)
    total = int(record.get("total") or 0)
    samples_kept = int(record.get("samples_kept") or 0)
    uncertain = _is_uncertain(record)
    prefix = "\u2265" if uncertain else ""
    header = (
        f"{prefix}{_count_phrase(total, 'error')} from "
        f"{_count_phrase(len(causes), 'cause')} "
        f"({_count_phrase(samples_kept, 'sample')} kept), "
        f"{_clock_range(str(record.get('interval_start') or ''), str(record.get('interval_end') or ''))}"
        f"{_uncertainty_suffix(record)}"
    )
    lines: list[str] = [header, ""]
    for cause in causes:
        routine = _as_str(cause.get("routine"), "unknown")
        job = _as_str(cause.get("job"), "unknown")
        sample = _one_line_sample(_as_str(cause.get("sample"), ""))
        lines.append(
            "  "
            f"{int(cause.get('count') or 0):>5}  {routine}/{job}  "
            f"{_clock_range(_as_str(cause.get('first_ts'), ''), _as_str(cause.get('last_ts'), ''))}  "
            f"{sample}"
        )
    if causes:
        lines.append("")
    for index, cause in enumerate(causes, 1):
        sample_entry = cause.get("sample_entry")
        entry = sample_entry if isinstance(sample_entry, dict) else {}
        lines.append("=" * 60)
        lines.append(
            f"Cause {index}/{len(causes)} · "
            f"{_count_phrase(int(cause.get('count') or 0), 'error')} · "
            f"{_as_str(cause.get('routine'), 'unknown')}/"
            f"{_as_str(cause.get('job'), 'unknown')}"
        )
        lines.append(f"  First:      {_as_str(cause.get('first_ts'), 'unknown')}")
        lines.append(f"  Last:       {_as_str(cause.get('last_ts'), 'unknown')}")
        _append_sample_block(lines, entry)
        lines.append("")
    return "\n".join(lines)


def digest_notification_note(record: Mapping[str, Any]) -> str:
    """Return the one-line notification note for a digest record."""
    total = int(record.get("total") or 0)
    causes = record.get("groups")
    cause_count = len(causes) if isinstance(causes, list) else 0
    prefix = "\u2265" if _is_uncertain(record) else ""
    since = _clock(_as_str(record.get("interval_start"), ""))
    return (
        f"{prefix}{_count_phrase(total, 'error')} from "
        f"{_count_phrase(cause_count, 'cause')} since {since}"
    )


def prune_old_error_digests(
    *,
    now: float | None = None,
    max_age_days: float | None = None,
    keep_count: int | None = None,
    min_interval_seconds: float | None = None,
    digest_dir: Path | None = None,
) -> int:
    """Delete digest files older than 30 days, always keeping the newest 50.

    Runs at most once per day via a marker file. Best-effort: every
    filesystem failure is swallowed and logged.
    """
    import time

    if max_age_days is None:
        max_age_days = ERROR_DIGEST_MAX_AGE_DAYS
    if keep_count is None:
        keep_count = ERROR_DIGEST_KEEP_COUNT
    if min_interval_seconds is None:
        min_interval_seconds = ERROR_DIGEST_PRUNE_INTERVAL_SECONDS
    moment = now if now is not None else time.time()

    try:
        directory = digest_dir if digest_dir is not None else error_digest_dir()
    except Exception:
        return 0

    marker = directory / ERROR_DIGEST_RETENTION_MARKER
    try:
        last_run = marker.stat().st_mtime
    except OSError:
        last_run = 0.0
    if moment - last_run < max(0.0, min_interval_seconds):
        return 0
    try:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.touch(exist_ok=True)
        os.utime(marker, (moment, moment))
    except OSError as exc:
        _logger.warning("Could not update error-digest retention marker: %s", exc)

    try:
        files = [
            path
            for path in directory.glob("digest_*.txt")
            if path.is_file() and path.name != ERROR_DIGEST_RETENTION_MARKER
        ]
    except Exception as exc:  # noqa: BLE001 - pruning is best-effort
        _logger.warning("Could not list error digest files: %s", exc)
        return 0

    def mtime(path: Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:
            return float("inf")

    ordered = sorted(files, key=lambda path: (mtime(path), path.name), reverse=True)
    cutoff = moment - max(0.0, max_age_days) * 86400.0 if max_age_days > 0 else None

    deleted = 0
    for index, path in enumerate(ordered):
        if keep_count > 0 and index < keep_count:
            continue
        if cutoff is not None and mtime(path) >= cutoff:
            continue
        try:
            path.unlink()
        except OSError as exc:
            _logger.warning("Could not prune error digest %s: %s", path.name, exc)
            continue
        deleted += 1
    if deleted:
        _logger.info("Pruned %s old error digest file(s)", deleted)
    return deleted


def _wire_schema_version() -> int:
    try:
        return int(axe_error_wire_schema_version())
    except Exception:  # noqa: BLE001 - rendering must survive a missing binding
        return 1


def _signature_of(entry: Mapping[str, Any]) -> str:
    explicit = entry.get("failure_signature")
    if isinstance(explicit, str) and explicit:
        return explicit
    error = entry.get("error", "")
    text = error if isinstance(error, str) else str(error)
    try:
        return normalize_error_signature(text)
    except Exception:  # noqa: BLE001 - grouping degrades to unclassified
        return text.casefold()[:200] or _UNCLASSIFIED_SIGNATURE


def _group_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not entries:
        return []
    try:
        response = group_errors(entries)
        groups = response.get("groups")
        if isinstance(groups, list):
            return [group for group in groups if isinstance(group, dict)]
    except Exception:  # noqa: BLE001 - Python fallback keeps the digest truthful
        _logger.warning("Error grouping facade unavailable; grouping in Python")
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    order: list[tuple[str, str, str]] = []
    for entry in entries:
        key = (
            str(entry.get("routine") or ""),
            str(entry.get("job") or ""),
            str(entry.get("signature") or ""),
        )
        group = grouped.get(key)
        timestamp = str(entry.get("timestamp") or "")
        sample = str(entry.get("sample") or "")
        if group is None:
            grouped[key] = {
                "routine": key[0],
                "job": key[1],
                "signature": key[2],
                "count": 1,
                "first_ts": timestamp,
                "last_ts": timestamp,
                "sample": sample,
            }
            order.append(key)
            continue
        group["count"] += 1
        if timestamp and (not group["first_ts"] or timestamp < group["first_ts"]):
            group["first_ts"] = timestamp
        if timestamp and timestamp > group["last_ts"]:
            group["last_ts"] = timestamp
    return [grouped[key] for key in order]


def _causes_with_samples(record: Mapping[str, Any]) -> list[dict[str, Any]]:
    groups = [group for group in record.get("groups") or [] if isinstance(group, dict)]
    ring = [
        entry for entry in record.get("ring_samples") or [] if isinstance(entry, dict)
    ]
    full_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
    entries: list[dict[str, Any]] = []
    for entry in ring:
        routine = _as_str(entry.get("lumberjack"), "unknown")
        job = _as_str(entry.get("job"), "unknown")
        signature = _signature_of(entry)
        key = (routine, job, signature)
        if key not in full_by_key:
            full_by_key[key] = entry
        entries.append(
            {
                "routine": routine,
                "job": job,
                "signature": signature,
                "timestamp": _as_str(entry.get("timestamp"), ""),
                "sample": _as_str(entry.get("error"), ""),
            }
        )
    grouped_ring = _group_entries(entries) if entries else []
    if not groups:
        groups = grouped_ring
    causes: list[dict[str, Any]] = []
    for group in groups:
        routine = _as_str(group.get("routine"), "unknown")
        job = _as_str(group.get("job"), "unknown")
        signature = _as_str(group.get("signature"), "")
        sample_entry = full_by_key.get((routine, job, signature))
        if sample_entry is None:
            sample_entry = {
                "timestamp": _as_str(
                    group.get("last_ts") or group.get("first_ts"), "unknown"
                ),
                "lumberjack": routine,
                "job": job,
                "error": _as_str(group.get("sample"), "unknown"),
                "traceback": "",
            }
        causes.append({**group, "sample_entry": sample_entry})
    return causes


def _append_sample_block(lines: list[str], err: Mapping[str, Any]) -> None:
    lines.append(f"  Time:       {err.get('timestamp', 'unknown')}")
    lines.append(f"  Routine:    {err.get('lumberjack', 'unknown')}")
    lines.append(f"  Job:        {err.get('job', 'unknown')}")
    lines.append(f"  Error:      {err.get('error', 'unknown')}")
    subprocess_diagnostic = _subprocess_diagnostic(err)
    if subprocess_diagnostic is not None:
        _append_subprocess_diagnostic(lines, subprocess_diagnostic)
    traceback_text = err.get("traceback", "")
    if traceback_text and not (
        subprocess_diagnostic is not None and traceback_text == _NO_PYTHON_TRACEBACK
    ):
        lines.append("  Traceback:")
        for traceback_line in str(traceback_text).splitlines():
            lines.append(f"    {traceback_line}")


def _subprocess_diagnostic(error: Mapping[str, Any]) -> dict[str, Any] | None:
    value = error.get("subprocess_diagnostic")
    return value if isinstance(value, dict) else None


def _append_subprocess_diagnostic(
    lines: list[str], diagnostic: Mapping[str, Any]
) -> None:
    run_id = _string_value(diagnostic.get("run_id"))
    exit_code = diagnostic.get("exit_code")
    source_log_path = _string_value(diagnostic.get("source_log_path"))
    output_status = _string_value(diagnostic.get("output_status")) or "unknown"
    output_excerpt = _string_value(diagnostic.get("output_excerpt")) or ""

    lines.append("  Run:")
    if run_id:
        lines.append(f"    ID:         {run_id}")
    if isinstance(exit_code, int):
        lines.append(f"    Exit Code:  {exit_code}")
    if source_log_path:
        lines.append(f"    Source Log: {source_log_path}")

    markers = _subprocess_output_markers(diagnostic, output_status, output_excerpt)
    lines.append("  Subprocess Output:")
    for marker in markers:
        lines.append(f"    [{marker}]")
    if output_excerpt:
        for output_line in output_excerpt.splitlines():
            lines.append(f"    {output_line}")


def _subprocess_output_markers(
    diagnostic: Mapping[str, Any], output_status: str, output_excerpt: str
) -> list[str]:
    markers: list[str] = []
    if output_status == "absent":
        markers.append("output absent")
    elif output_status == "unavailable":
        reason = _string_value(diagnostic.get("unavailable_reason")) or "unknown"
        markers.append(f"output unavailable: {reason}")
    elif output_status != "captured":
        markers.append(f"output status: {output_status}")
    elif not output_excerpt:
        markers.append("captured output empty after normalization")

    if diagnostic.get("truncated") is True:
        details: list[str] = []
        omitted_lines = _nonnegative_int(diagnostic.get("omitted_lines"))
        omitted_bytes = _nonnegative_int(diagnostic.get("omitted_bytes"))
        if omitted_lines:
            details.append(f"{omitted_lines} line(s)")
        if omitted_bytes:
            details.append(f"{omitted_bytes} byte(s)")
        suffix = f": omitted {' and '.join(details)}" if details else ""
        markers.append(f"truncated{suffix}")
    if diagnostic.get("had_decode_errors") is True:
        markers.append("invalid UTF-8 replaced")
    return markers


def _is_uncertain(record: Mapping[str, Any]) -> bool:
    return (
        int(record.get("write_failures") or 0) > 0
        or int(record.get("corrupt_files") or 0) > 0
    )


def _uncertainty_suffix(record: Mapping[str, Any]) -> str:
    failures = int(record.get("write_failures") or 0)
    corrupt = int(record.get("corrupt_files") or 0)
    if failures <= 0 and corrupt <= 0:
        return ""
    parts: list[str] = []
    if failures > 0:
        parts.append(_count_phrase(failures, "write failure"))
    if corrupt > 0:
        parts.append(_count_phrase(corrupt, "corrupt file"))
    return " (" + ", ".join(parts) + ")"


def _count_phrase(count: int, singular: str) -> str:
    word = singular if count == 1 else f"{singular}s"
    return f"{count} {word}"


def _clock(timestamp: str) -> str:
    parsed = parse_local(timestamp)
    if parsed is None:
        return timestamp or "unknown"
    return parsed.strftime("%H:%M")


def _clock_range(start: str, end: str) -> str:
    start_dt = parse_local(start)
    end_dt = parse_local(end)
    if start_dt is None or end_dt is None:
        return f"{_clock(start)}{_EN_DASH}{_clock(end)}"
    if start_dt.date() == end_dt.date():
        return f"{start_dt.strftime('%H:%M')}{_EN_DASH}{end_dt.strftime('%H:%M')}"
    fmt = "%b %d %H:%M"
    return f"{start_dt.strftime(fmt)}{_EN_DASH}{end_dt.strftime(fmt)}"


def _one_line_sample(sample: str) -> str:
    collapsed = " ".join(sample.split())
    if len(collapsed) <= _CAUSE_SAMPLE_CHARS:
        return collapsed
    return collapsed[: _CAUSE_SAMPLE_CHARS - 1] + "…"


def _as_str(value: object, default: str) -> str:
    return value if isinstance(value, str) and value else default


def _string_value(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


__all__ = [
    "ERROR_DIGEST_DEDUP_PREFIX",
    "ERROR_DIGEST_KEEP_COUNT",
    "ERROR_DIGEST_MAX_AGE_DAYS",
    "ERROR_DIGEST_PRUNE_INTERVAL_SECONDS",
    "ERROR_DIGEST_RETENTION_MARKER",
    "digest_dedup_key",
    "digest_notification_note",
    "digest_record_from_errors",
    "error_digest_dir",
    "prune_old_error_digests",
    "render_error_digest",
]
