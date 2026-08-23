"""Recording and serialization for the opt-in ``test-cost`` lane.

The diff-scoped selector's timing table answers one question: how many
per-test-file wall seconds a selection costs. This module keeps the heavier
diagnostic shape separate from that table while living beside it in the same
host-local store, so normal lanes keep their cheap schema and the cost lane can
attribute why the seconds were spent.
"""

from __future__ import annotations

import hashlib
import json
import os
import statistics
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tests._test_selection_timings import (
    RECORDING_SUFFIX,
    recording_filename,
    recording_host,
    recording_paths as timing_recording_paths,
    timings_directory,
)

TEST_COST_SCHEMA = 1
TEST_COST_SUBDIRECTORY = "cost"
TEST_COST_DIR_ENV = "SASE_TEST_COST_DIR"
KEEP_COST_RECORDINGS = 8


def cost_directory(store: Path, environ: Mapping[str, str] | None = None) -> Path:
    """Return the suite-cost directory beside the existing timing recordings."""

    environ = os.environ if environ is None else environ
    override = environ.get(TEST_COST_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return timings_directory(store, environ) / TEST_COST_SUBDIRECTORY


def cost_recording_paths(directory: Path) -> list[Path]:
    """Every recognised cost recording, oldest first."""

    return [
        path
        for path in timing_recording_paths(directory)
        if path.name.endswith(RECORDING_SUFFIX)
    ]


def prune_cost_recordings(
    directory: Path, keep: int = KEEP_COST_RECORDINGS
) -> list[Path]:
    """Keep only the newest cost recordings."""

    removed: list[Path] = []
    paths = cost_recording_paths(directory)
    for path in paths[: max(0, len(paths) - keep)]:
        try:
            path.unlink()
        except OSError:
            continue
        removed.append(path)
    return removed


def _round_seconds(value: float | int | None) -> float | None:
    return None if value is None else round(float(value), 6)


def _coerce_cause(raw: object) -> dict[str, float | int]:
    if not isinstance(raw, Mapping):
        return {"count": 0, "seconds": 0.0, "cpu_seconds": 0.0}
    try:
        count = int(raw.get("count", 0))
    except (TypeError, ValueError):
        count = 0
    try:
        seconds = float(raw.get("seconds", 0.0))
    except (TypeError, ValueError):
        seconds = 0.0
    try:
        cpu_seconds = float(raw.get("cpu_seconds", 0.0))
    except (TypeError, ValueError):
        cpu_seconds = 0.0
    return {
        "count": max(count, 0),
        "seconds": max(seconds, 0.0),
        "cpu_seconds": max(cpu_seconds, 0.0),
    }


def _merge_causes(
    target: dict[str, dict[str, float | int]],
    raw_causes: object,
) -> None:
    if not isinstance(raw_causes, Mapping):
        return
    for raw_name, raw_cause in raw_causes.items():
        name = str(raw_name)
        cause = _coerce_cause(raw_cause)
        bucket = target.setdefault(
            name, {"count": 0, "seconds": 0.0, "cpu_seconds": 0.0}
        )
        bucket["count"] = int(bucket["count"]) + int(cause["count"])
        bucket["seconds"] = float(bucket["seconds"]) + float(cause["seconds"])
        bucket["cpu_seconds"] = float(bucket["cpu_seconds"]) + float(
            cause["cpu_seconds"]
        )


def _merged_files(
    worker_payloads: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    files: dict[str, dict[str, Any]] = {}
    for worker in worker_payloads:
        raw_files = worker.get("files")
        if not isinstance(raw_files, Mapping):
            continue
        for raw_path, raw_metrics in raw_files.items():
            if not isinstance(raw_metrics, Mapping):
                continue
            path = str(raw_path)
            file_metrics = files.setdefault(
                path,
                {
                    "node_count": 0,
                    "wall_seconds": 0.0,
                    "cpu_seconds": 0.0,
                    "causes": {},
                },
            )
            file_metrics["node_count"] = int(file_metrics["node_count"]) + int(
                raw_metrics.get("node_count", 0) or 0
            )
            file_metrics["wall_seconds"] = float(file_metrics["wall_seconds"]) + float(
                raw_metrics.get("wall_seconds", 0.0) or 0.0
            )
            file_metrics["cpu_seconds"] = float(file_metrics["cpu_seconds"]) + float(
                raw_metrics.get("cpu_seconds", 0.0) or 0.0
            )
            _merge_causes(file_metrics["causes"], raw_metrics.get("causes"))

    rounded: dict[str, dict[str, Any]] = {}
    for path, metrics in sorted(files.items()):
        wall = float(metrics["wall_seconds"])
        cpu = float(metrics["cpu_seconds"])
        rounded[path] = {
            "node_count": int(metrics["node_count"]),
            "wall_seconds": _round_seconds(wall),
            "cpu_seconds": _round_seconds(cpu),
            "idle_seconds": _round_seconds(max(wall - cpu, 0.0)),
            "causes": {
                name: {
                    "count": int(cause["count"]),
                    "seconds": _round_seconds(float(cause["seconds"])),
                    "cpu_seconds": _round_seconds(float(cause["cpu_seconds"])),
                }
                for name, cause in sorted(metrics["causes"].items())
            },
        }
    return rounded


def _merged_worker_causes(
    worker_payloads: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    causes: dict[str, dict[str, float | int]] = {}
    for worker in worker_payloads:
        _merge_causes(causes, worker.get("causes"))
    return {
        name: {
            "count": int(cause["count"]),
            "seconds": _round_seconds(float(cause["seconds"])),
            "cpu_seconds": _round_seconds(float(cause["cpu_seconds"])),
        }
        for name, cause in sorted(causes.items())
    }


def _coerce_rss_curve(worker: Mapping[str, Any]) -> dict[str, int]:
    peak = int(worker.get("peak_rss_kib", 0) or 0)
    raw_curve = worker.get("rss_curve_kib")
    if not isinstance(raw_curve, Mapping):
        return {
            "start": peak,
            "post_collection": peak,
            "median": peak,
            "peak": peak,
            "sample_count": 1 if peak else 0,
        }
    curve: dict[str, int] = {}
    for key in ("start", "post_collection", "median", "peak", "sample_count"):
        try:
            curve[key] = max(int(raw_curve.get(key, 0) or 0), 0)
        except (TypeError, ValueError):
            curve[key] = 0
    if curve["peak"] <= 0:
        curve["peak"] = peak
    return curve


def _worker_rss_curve(
    worker_payloads: Sequence[Mapping[str, Any]], *, peak_rss_kib: int
) -> dict[str, int]:
    curves = [_coerce_rss_curve(worker) for worker in worker_payloads]
    samples: list[int] = []
    for curve in curves:
        samples.extend(
            value
            for value in (
                curve["start"],
                curve["post_collection"],
                curve["median"],
                curve["peak"],
            )
            if value > 0
        )
    if not samples and peak_rss_kib:
        samples.append(peak_rss_kib)
    return {
        "start": max((curve["start"] for curve in curves), default=peak_rss_kib),
        "post_collection": max(
            (curve["post_collection"] for curve in curves), default=peak_rss_kib
        ),
        "median": int(statistics.median(samples)) if samples else 0,
        "peak": peak_rss_kib,
        "sample_count": sum(curve["sample_count"] for curve in curves),
    }


def _record_identity(record: Mapping[str, Any]) -> str:
    payload = json.dumps(record, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def build_cost_record(
    worker_payloads: Sequence[Mapping[str, Any]],
    *,
    mode: str,
    worker_count: int | None,
    host: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a JSON-serializable suite-cost recording."""

    stamp = now or datetime.now(UTC)
    files = _merged_files(worker_payloads)
    causes = _merged_worker_causes(worker_payloads)
    worker_wall = sum(
        float(worker.get("wall_seconds", 0.0) or 0.0) for worker in worker_payloads
    )
    worker_cpu = sum(
        float(worker.get("cpu_seconds", 0.0) or 0.0) for worker in worker_payloads
    )
    collection = sum(
        float(worker.get("collection_seconds", 0.0) or 0.0)
        for worker in worker_payloads
    )
    collection_cpu = sum(
        float(worker.get("collection_cpu_seconds", 0.0) or 0.0)
        for worker in worker_payloads
    )
    peak_rss = max(
        (int(worker.get("peak_rss_kib", 0) or 0) for worker in worker_payloads),
        default=0,
    )
    rss_curve = _worker_rss_curve(worker_payloads, peak_rss_kib=peak_rss)
    total_wall = sum(
        float(metrics["wall_seconds"] or 0.0) for metrics in files.values()
    )
    total_cpu = sum(float(metrics["cpu_seconds"] or 0.0) for metrics in files.values())
    record: dict[str, Any] = {
        "schema": TEST_COST_SCHEMA,
        "recorded_at": stamp.astimezone(UTC).isoformat(),
        "host": recording_host() if host is None else host,
        "mode": mode,
        "worker_count": worker_count,
        "summary": {
            "file_count": len(files),
            "node_count": sum(int(metrics["node_count"]) for metrics in files.values()),
            "total_file_wall_seconds": _round_seconds(total_wall),
            "total_file_cpu_seconds": _round_seconds(total_cpu),
            "idle_seconds": _round_seconds(max(total_wall - total_cpu, 0.0)),
            "worker_wall_seconds": _round_seconds(worker_wall),
            "worker_cpu_seconds": _round_seconds(worker_cpu),
            "collection_seconds": _round_seconds(collection),
            "collection_cpu_seconds": _round_seconds(collection_cpu),
            "peak_worker_rss_kib": peak_rss,
            "median_worker_rss_kib": rss_curve["median"],
            "post_collection_worker_rss_kib": rss_curve["post_collection"],
            "worker_rss_curve_kib": rss_curve,
            "causes": causes,
        },
        "files": files,
        "workers": list(worker_payloads),
    }
    record["identity"] = _record_identity(record)
    return record


def write_cost_record(
    directory: Path,
    worker_payloads: Sequence[Mapping[str, Any]],
    *,
    mode: str,
    worker_count: int | None = None,
    host: str | None = None,
    pid: int | None = None,
    now: datetime | None = None,
    keep: int = KEEP_COST_RECORDINGS,
) -> Path | None:
    """Persist one suite-cost recording, returning ``None`` for empty runs."""

    if not worker_payloads:
        return None
    stamp = now or datetime.now(UTC)
    path = directory / recording_filename(
        now=stamp, pid=os.getpid() if pid is None else pid
    )
    directory.mkdir(parents=True, exist_ok=True)
    payload = build_cost_record(
        worker_payloads,
        mode=mode,
        worker_count=worker_count,
        host=host,
        now=stamp,
    )
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    prune_cost_recordings(directory, keep)
    return path


def load_cost_record(path: Path) -> dict[str, Any]:
    """Load and validate one cost record or committed baseline."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("schema") != TEST_COST_SCHEMA:
        raise ValueError(f"{path} is not a schema-{TEST_COST_SCHEMA} cost record")
    if not isinstance(payload.get("summary"), Mapping):
        raise ValueError(f"{path} has no summary object")
    return payload


def latest_cost_record(directory: Path) -> Path | None:
    """Return the newest recognised cost recording."""

    paths = cost_recording_paths(directory)
    return paths[-1] if paths else None


def _summary_value(record: Mapping[str, Any], key: str) -> float | None:
    summary = record.get("summary")
    if not isinstance(summary, Mapping):
        return None
    value = summary.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _cause_seconds(record: Mapping[str, Any], cause: str) -> float | None:
    summary = record.get("summary")
    if not isinstance(summary, Mapping):
        return None
    causes = summary.get("causes")
    if not isinstance(causes, Mapping):
        return None
    payload = causes.get(cause)
    if not isinstance(payload, Mapping) or payload.get("seconds") is None:
        return None
    try:
        return float(payload["seconds"])
    except (TypeError, ValueError):
        return None


def _cause_cpu_seconds(record: Mapping[str, Any], cause: str) -> float | None:
    summary = record.get("summary")
    if not isinstance(summary, Mapping):
        return None
    causes = summary.get("causes")
    if not isinstance(causes, Mapping):
        return None
    payload = causes.get(cause)
    if not isinstance(payload, Mapping) or payload.get("cpu_seconds") is None:
        return None
    try:
        return float(payload["cpu_seconds"])
    except (TypeError, ValueError):
        return None


def _cause_count(record: Mapping[str, Any], cause: str) -> int | None:
    summary = record.get("summary")
    if not isinstance(summary, Mapping):
        return None
    causes = summary.get("causes")
    if not isinstance(causes, Mapping):
        return None
    payload = causes.get(cause)
    if not isinstance(payload, Mapping) or payload.get("count") is None:
        return None
    try:
        return int(payload["count"])
    except (TypeError, ValueError):
        return None
