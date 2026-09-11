"""Durable monitor diagnostics and retained-log metadata."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.continuation_facade import validate_diagnostic_manifest
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.logs.pipe import BoundedLogRetention, RetainedByteRange

from .transaction import write_json_marker_atomic

DIAGNOSTICS_DIRNAME = "diagnostics"
STAGES_DIRNAME = "stages"
RETAINED_LOGS_DIRNAME = "retained_logs"
DIAGNOSTIC_MANIFEST_FILENAME = "diagnostic_manifest.json"
RETAINED_LOG_METADATA_FILENAME = "retained_log_metadata.json"
DEFAULT_DIAGNOSTICS_MAX_BYTES = 64 * 1024
MAX_DIAGNOSTICS_MAX_BYTES = 1024 * 1024
DEFAULT_RANGE_MAX_BYTES = 64 * 1024
MAX_RANGE_MAX_BYTES = 1024 * 1024


@dataclass(frozen=True)
class MonitorTextRead:
    """Bounded text plus metadata for a monitor evidence read."""

    text: str
    metadata: dict[str, Any]


def diagnostics_dir(artifacts_dir: str | Path) -> Path:
    """Return the monitor-owned diagnostics directory."""
    return Path(artifacts_dir) / DIAGNOSTICS_DIRNAME


def stages_dir(artifacts_dir: str | Path) -> Path:
    """Return the directory of isolated first-party stage reports."""
    return diagnostics_dir(artifacts_dir) / STAGES_DIRNAME


def diagnostic_manifest_path(artifacts_dir: str | Path) -> Path:
    """Return the assembled diagnostic manifest path."""
    return diagnostics_dir(artifacts_dir) / DIAGNOSTIC_MANIFEST_FILENAME


def retained_log_metadata_path(artifacts_dir: str | Path) -> Path:
    """Return the frozen retained-log metadata path."""
    return diagnostics_dir(artifacts_dir) / RETAINED_LOG_METADATA_FILENAME


def retained_logs_dir(artifacts_dir: str | Path) -> Path:
    """Return the directory containing immutable retained-log snapshots."""
    return diagnostics_dir(artifacts_dir) / RETAINED_LOGS_DIRNAME


def assemble_diagnostic_manifest(
    artifacts_dir: str | Path,
    *,
    monitor_id: str,
    complete: bool,
) -> dict[str, Any]:
    """Assemble and persist one continuation diagnostic manifest."""
    manifest_path = diagnostic_manifest_path(artifacts_dir)
    stages = _load_stage_reports(stages_dir(artifacts_dir))
    manifest: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "producer": _identifier(f"monitor-{monitor_id}"),
        "complete": bool(complete) and all(not s.get("capture_errors") for s in stages),
        "manifest_ref": _manifest_ref(monitor_id),
        "stages": stages,
    }
    _validate_manifest_or_add_error(manifest)
    write_json_marker_atomic(manifest_path, manifest)
    return manifest


def freeze_retained_log_metadata(
    artifacts_dir: str | Path,
    *,
    output_path: Path,
    monitor_id: str,
    retention: BoundedLogRetention | None,
) -> dict[str, Any]:
    """Snapshot retained log files and persist continuation metadata."""
    target_dir = retained_logs_dir(artifacts_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    segments: list[dict[str, Any]] = []
    ranges = list(retention.retained_ranges if retention is not None else ())
    for source_path, source_name in (
        (output_path.with_name(f"{output_path.name}.1"), "rotated"),
        (output_path, "active"),
    ):
        if not source_path.exists():
            continue
        target_path = target_dir / source_path.name
        shutil.copyfile(source_path, target_path)
        size = target_path.stat().st_size
        segment_range = _pop_segment_range(ranges, size)
        segments.append(
            {
                "kind": source_name,
                "locator": _relative_locator(artifacts_dir, target_path),
                "bytes": size,
                "range": _range_to_dict(segment_range) if segment_range else None,
            }
        )

    retained_ranges = (
        [_range_to_dict(item) for item in retention.retained_ranges]
        if retention is not None
        else _fallback_retained_ranges(segments)
    )
    total_observed = (
        retention.total_observed_bytes
        if retention is not None
        else sum(int(segment["bytes"]) for segment in segments)
    )
    metadata = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "producer": "sase.monitor.supervise",
        "log_ref": _log_ref(monitor_id),
        "local_locator": _relative_locator(artifacts_dir, target_dir),
        "total_observed_bytes": total_observed,
        "retained_ranges": retained_ranges,
        "complete": bool(retention.complete) if retention is not None else True,
        "drain_confirmed": (
            bool(retention.drain_confirmed) if retention is not None else True
        ),
        "segments": segments,
    }
    write_json_marker_atomic(retained_log_metadata_path(artifacts_dir), metadata)
    return metadata


def read_diagnostics_text(
    artifacts_dir: str | Path,
    *,
    max_bytes: int = DEFAULT_DIAGNOSTICS_MAX_BYTES,
) -> MonitorTextRead:
    """Return bounded failed-stage diagnostics text for ``monitor show``."""
    budget = _clamped_max_bytes(max_bytes, default=DEFAULT_DIAGNOSTICS_MAX_BYTES)
    manifest = _read_json(diagnostic_manifest_path(artifacts_dir))
    if not manifest:
        return MonitorTextRead(
            "(no diagnostic manifest captured)\n",
            {"mode": "diagnostics", "available": False},
        )
    chunks: list[str] = []
    remaining = budget
    selected: list[dict[str, Any]] = []
    for stage in manifest.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        if stage.get("status") not in {"failed", "error"}:
            continue
        header = f"== {stage.get('name') or stage.get('stage_id')} ==\n"
        if remaining <= 0:
            break
        chunks.append(_take_text(header.encode(), remaining))
        remaining -= len(chunks[-1].encode("utf-8"))
        locators = [item for item in stage.get("diagnostic_locators") or [] if item]
        if not locators and stage.get("capture_errors"):
            detail = "\n".join(str(item) for item in stage["capture_errors"]) + "\n"
            chunks.append(_take_text(detail.encode(), remaining))
            remaining -= len(chunks[-1].encode("utf-8"))
        for locator in locators:
            if remaining <= 0:
                break
            try:
                path = _locator_path(artifacts_dir, str(locator))
                data = path.read_bytes()
            except OSError as exc:
                data = f"[could not read diagnostic: {exc}]\n".encode()
            part = _take_text(data, remaining)
            chunks.append(part if part.endswith("\n") else f"{part}\n")
            remaining -= len(chunks[-1].encode("utf-8"))
        selected.append(
            {
                "stage_id": stage.get("stage_id"),
                "status": stage.get("status"),
                "diagnostic_locators": locators,
            }
        )
    if not chunks:
        chunks.append("(no failed-stage diagnostics captured)\n")
    return MonitorTextRead(
        "".join(chunks),
        {
            "mode": "diagnostics",
            "available": True,
            "complete": bool(manifest.get("complete")),
            "selected_stages": selected,
            "max_bytes": budget,
        },
    )


def read_retained_log_range(
    artifacts_dir: str | Path,
    *,
    start: int,
    end: int,
    max_bytes: int = DEFAULT_RANGE_MAX_BYTES,
) -> MonitorTextRead:
    """Return a bounded raw-log byte range with explicit gap notices."""
    if start < 0 or end < start:
        raise ValueError("range must satisfy 0 <= START <= END")
    budget = _clamped_max_bytes(max_bytes, default=DEFAULT_RANGE_MAX_BYTES)
    metadata = _read_json(retained_log_metadata_path(artifacts_dir))
    if not metadata:
        return MonitorTextRead(
            "(no retained-log metadata captured)\n",
            {"mode": "range", "available": False},
        )
    cursor = start
    remaining = min(budget, end - start)
    chunks: list[str] = []
    available: list[dict[str, int]] = []
    missing: list[dict[str, int]] = []
    for segment in metadata.get("segments") or []:
        if remaining <= 0:
            break
        if not isinstance(segment, dict) or not isinstance(segment.get("range"), dict):
            continue
        seg_start = int(segment["range"].get("start", 0))
        seg_end = int(segment["range"].get("end", 0))
        overlap_start = max(cursor, seg_start)
        overlap_end = min(end, seg_end)
        if overlap_end <= overlap_start:
            continue
        if cursor < overlap_start:
            missing.append({"start": cursor, "end": overlap_start})
            chunks.append(_gap_notice(cursor, overlap_start))
            cursor = overlap_start
            remaining = max(0, min(budget, end - start) - _text_bytes(chunks))
            if remaining <= 0:
                break
        locator = str(segment.get("locator") or "")
        try:
            path = _locator_path(artifacts_dir, locator)
            with path.open("rb") as stream:
                stream.seek(overlap_start - seg_start)
                data = stream.read(min(remaining, overlap_end - overlap_start))
        except OSError as exc:
            data = f"[could not read retained range: {exc}]\n".encode()
        chunks.append(_take_text(data, remaining))
        read_bytes = len(data)
        available.append({"start": overlap_start, "end": overlap_start + read_bytes})
        cursor = overlap_start + read_bytes
        remaining = max(0, min(budget, end - start) - _text_bytes(chunks))
    if cursor < end and remaining > 0:
        missing.append({"start": cursor, "end": end})
        chunks.append(_gap_notice(cursor, end))
    return MonitorTextRead(
        "".join(chunks),
        {
            "mode": "range",
            "available": True,
            "complete": bool(metadata.get("complete")),
            "drain_confirmed": bool(metadata.get("drain_confirmed")),
            "requested_range": {"start": start, "end": end},
            "available_ranges": available,
            "missing_ranges": missing,
            "continuation_offset": cursor,
            "max_bytes": budget,
        },
    )


def retained_log_metadata(artifacts_dir: str | Path) -> dict[str, Any]:
    """Return persisted retained-log metadata, if present."""
    return _read_json(retained_log_metadata_path(artifacts_dir))


def diagnostic_manifest(artifacts_dir: str | Path) -> dict[str, Any]:
    """Return persisted diagnostic manifest, if present."""
    return _read_json(diagnostic_manifest_path(artifacts_dir))


def _load_stage_reports(root: Path) -> list[dict[str, Any]]:
    reports: list[dict[str, Any]] = []
    if not root.exists():
        return reports
    for path in sorted(root.glob("*.json")):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            reports.append(_invalid_stage(path, exc))
            continue
        if not isinstance(report, dict):
            reports.append(
                _invalid_stage(path, ValueError("stage report is not JSON object"))
            )
            continue
        reports.append(report)
    return reports


def _invalid_stage(path: Path, exc: BaseException) -> dict[str, Any]:
    stem = _identifier(f"invalid-{path.stem}")[:80]
    return {
        "stage_id": stem,
        "name": f"invalid diagnostic stage report {path.name}",
        "status": "error",
        "capture_errors": [str(exc) or exc.__class__.__name__],
    }


def _validate_manifest_or_add_error(manifest: dict[str, Any]) -> None:
    try:
        validate_diagnostic_manifest(manifest)
    except Exception as exc:  # noqa: BLE001 - persist actionable diagnostic.
        manifest["complete"] = False
        manifest.setdefault("stages", []).append(
            {
                "stage_id": "manifest-validation-error",
                "name": "diagnostic manifest validation",
                "status": "error",
                "capture_errors": [str(exc) or exc.__class__.__name__],
            }
        )


def _pop_segment_range(
    ranges: list[RetainedByteRange],
    size: int,
) -> RetainedByteRange | None:
    if size <= 0 or not ranges:
        return None
    target = ranges.pop(0)
    return target


def _fallback_retained_ranges(segments: list[dict[str, Any]]) -> list[dict[str, int]]:
    cursor = 0
    ranges: list[dict[str, int]] = []
    for segment in segments:
        size = int(segment.get("bytes") or 0)
        if size <= 0:
            continue
        ranges.append({"start": cursor, "end": cursor + size})
        cursor += size
    return ranges


def _range_to_dict(value: RetainedByteRange) -> dict[str, int]:
    return {"start": int(value.start), "end": int(value.end)}


def _identifier(value: str) -> str:
    translated = "".join(ch if ch.isalnum() or ch in "._:-" else "-" for ch in value)
    return translated.strip("-") or "monitor"


def _manifest_ref(monitor_id: str) -> str:
    return f"file:monitor-diagnostic-manifest:{_identifier(monitor_id)}"


def _log_ref(monitor_id: str) -> str:
    return f"file:monitor-retained-log:{_identifier(monitor_id)}"


def _relative_locator(artifacts_dir: str | Path, path: Path) -> str:
    try:
        return path.relative_to(Path(artifacts_dir)).as_posix()
    except ValueError:
        return path.as_posix()


def _locator_path(artifacts_dir: str | Path, locator: str) -> Path:
    root = Path(artifacts_dir).resolve()
    path = (Path(artifacts_dir) / locator).resolve()
    if root != path and root not in path.parents:
        raise OSError(f"diagnostic locator escapes monitor artifacts: {locator}")
    return path


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _clamped_max_bytes(value: int, *, default: int) -> int:
    if value <= 0:
        return default
    return min(value, MAX_DIAGNOSTICS_MAX_BYTES)


def _take_text(data: bytes, budget: int) -> str:
    if budget <= 0:
        return ""
    return data[:budget].decode("utf-8", errors="replace")


def _gap_notice(start: int, end: int) -> str:
    return f"\n[retained output gap: bytes {start}:{end} are unavailable]\n"


def _text_bytes(chunks: list[str]) -> int:
    return sum(len(chunk.encode("utf-8")) for chunk in chunks)


__all__ = [
    "DEFAULT_DIAGNOSTICS_MAX_BYTES",
    "DEFAULT_RANGE_MAX_BYTES",
    "MAX_DIAGNOSTICS_MAX_BYTES",
    "MAX_RANGE_MAX_BYTES",
    "MonitorTextRead",
    "assemble_diagnostic_manifest",
    "diagnostic_manifest",
    "diagnostic_manifest_path",
    "diagnostics_dir",
    "freeze_retained_log_metadata",
    "read_diagnostics_text",
    "read_retained_log_range",
    "retained_log_metadata",
    "retained_log_metadata_path",
    "stages_dir",
]
