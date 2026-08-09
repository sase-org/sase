"""Suite cost-attribution records for the opt-in ``test-cost`` lane.

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

CAUSE_LABELS: Mapping[str, str] = {
    "ace_page_enter": "AcePage.__aenter__",
    "ace_page_exit": "AcePage.__aexit__",
    "ace_pause_until_cpu_idle": "ACE pause_until_cpu_idle",
    "ace_settle_pilot": "ACE settle_pilot",
    "config_load_merged": "sase.config.core.load_merged_config",
    "gettext_find": "gettext.find",
    "parser_create": "sase.main.parser.create_parser",
    "pilot_pause_delay": "Pilot.pause(delay)",
    "pilot_pause_none": "Pilot.pause(None)",
    "subprocess_popen": "subprocess.Popen",
    "subprocess_run": "subprocess.run",
    "textual_app_run_test_enter": "Textual App.run_test enter",
    "textual_app_run_test_exit": "Textual App.run_test exit",
    "textual_wait_for_idle": "textual wait_for_idle",
    "yaml_load": "YAML load",
}

_SUMMARY_FIELDS: tuple[tuple[str, str], ...] = (
    ("total_file_wall_seconds", "per-test wall"),
    ("total_file_cpu_seconds", "per-test CPU"),
    ("idle_seconds", "per-test idle"),
    ("collection_seconds", "collection"),
    ("worker_wall_seconds", "worker wall"),
    ("worker_cpu_seconds", "worker CPU"),
    ("peak_worker_rss_kib", "peak worker RSS KiB"),
)


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
        return {"count": 0, "seconds": 0.0}
    try:
        count = int(raw.get("count", 0))
    except (TypeError, ValueError):
        count = 0
    try:
        seconds = float(raw.get("seconds", 0.0))
    except (TypeError, ValueError):
        seconds = 0.0
    return {"count": max(count, 0), "seconds": max(seconds, 0.0)}


def _merge_causes(
    target: dict[str, dict[str, float | int]],
    raw_causes: object,
) -> None:
    if not isinstance(raw_causes, Mapping):
        return
    for raw_name, raw_cause in raw_causes.items():
        name = str(raw_name)
        cause = _coerce_cause(raw_cause)
        bucket = target.setdefault(name, {"count": 0, "seconds": 0.0})
        bucket["count"] = int(bucket["count"]) + int(cause["count"])
        bucket["seconds"] = float(bucket["seconds"]) + float(cause["seconds"])


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
            "peak_worker_rss_kib": peak_rss,
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


def _format_seconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.3f}s"


def _format_delta(current: float | None, baseline: float | None) -> str:
    if current is None or baseline is None:
        return "n/a"
    delta = current - baseline
    if baseline == 0:
        return f"{delta:+.3f}"
    return f"{delta:+.3f} ({delta / baseline:+.1%})"


def _format_summary_value(key: str, value: float | None) -> str:
    if key.endswith("_rss_kib"):
        return "n/a" if value is None else f"{value:,.0f} KiB"
    return _format_seconds(value)


def _format_rss_curve(record: Mapping[str, Any]) -> str | None:
    summary = record.get("summary")
    curve = (
        summary.get("worker_rss_curve_kib") if isinstance(summary, Mapping) else None
    )
    if not isinstance(curve, Mapping):
        return None
    fields = []
    for key in ("start", "post_collection", "median", "peak"):
        try:
            value = int(curve.get(key, 0) or 0)
        except (TypeError, ValueError):
            value = 0
        fields.append(f"{key}={value:,} KiB")
    fields.append(f"samples={curve.get('sample_count', 'n/a')}")
    return ", ".join(fields)


def _sorted_causes(record: Mapping[str, Any]) -> list[tuple[str, Mapping[str, Any]]]:
    summary = record.get("summary")
    causes = summary.get("causes") if isinstance(summary, Mapping) else {}
    if not isinstance(causes, Mapping):
        return []
    rows = [
        (str(name), payload)
        for name, payload in causes.items()
        if isinstance(payload, Mapping)
    ]
    rows.sort(key=lambda item: float(item[1].get("seconds", 0.0) or 0.0), reverse=True)
    return rows


def _top_files(
    record: Mapping[str, Any],
    key: str,
    *,
    limit: int,
) -> list[tuple[str, Mapping[str, Any], float]]:
    files = record.get("files")
    if not isinstance(files, Mapping):
        return []
    rows: list[tuple[str, Mapping[str, Any], float]] = []
    for path, metrics in files.items():
        if not isinstance(metrics, Mapping):
            continue
        if key in {"wall_seconds", "cpu_seconds", "idle_seconds"}:
            value = metrics.get(key)
        else:
            causes = metrics.get("causes")
            cause = causes.get(key) if isinstance(causes, Mapping) else None
            value = cause.get("seconds") if isinstance(cause, Mapping) else None
        try:
            seconds = float(value or 0.0)
        except (TypeError, ValueError):
            seconds = 0.0
        if seconds > 0:
            rows.append((str(path), metrics, seconds))
    rows.sort(key=lambda item: item[2], reverse=True)
    return rows[:limit]


def _append_summary(lines: list[str], record: Mapping[str, Any]) -> None:
    lines.append("Summary")
    for key, label in _SUMMARY_FIELDS:
        value = _summary_value(record, key)
        lines.append(f"  {label}: {_format_summary_value(key, value)}")
    summary = record.get("summary")
    if isinstance(summary, Mapping):
        rss_curve = _format_rss_curve(record)
        if rss_curve is not None:
            lines.append(f"  worker RSS curve: {rss_curve}")
        lines.append(f"  files: {summary.get('file_count', 'n/a')}")
        lines.append(f"  nodes: {summary.get('node_count', 'n/a')}")


def _append_causes(
    lines: list[str],
    record: Mapping[str, Any],
    *,
    baseline: Mapping[str, Any] | None,
) -> None:
    lines.append("")
    lines.append("Causes")
    rows = _sorted_causes(record)
    if not rows:
        lines.append("  no attributed causes recorded")
        return
    for name, payload in rows:
        seconds = float(payload.get("seconds", 0.0) or 0.0)
        count = int(payload.get("count", 0) or 0)
        label = CAUSE_LABELS.get(name, name)
        suffix = ""
        if baseline is not None:
            suffix = f"  delta {_format_delta(seconds, _cause_seconds(baseline, name))}"
        lines.append(f"  {label}: {_format_seconds(seconds)} ({count}x){suffix}")


def _append_top_files(lines: list[str], record: Mapping[str, Any], *, top: int) -> None:
    lines.append("")
    lines.append(f"Top {top} Files")
    for label, key in (
        ("wall", "wall_seconds"),
        ("CPU", "cpu_seconds"),
        ("idle", "idle_seconds"),
    ):
        rows = _top_files(record, key, limit=top)
        if not rows:
            continue
        lines.append(f"  by {label}:")
        for path, _metrics, seconds in rows:
            lines.append(f"    {seconds:8.3f}s  {path}")

    for cause, _payload in _sorted_causes(record):
        rows = _top_files(record, cause, limit=top)
        if not rows:
            continue
        lines.append(f"  by {CAUSE_LABELS.get(cause, cause)}:")
        for path, metrics, seconds in rows:
            causes = metrics.get("causes")
            cause_payload = causes.get(cause) if isinstance(causes, Mapping) else {}
            count = (
                int(cause_payload.get("count", 0) or 0)
                if isinstance(cause_payload, Mapping)
                else 0
            )
            lines.append(f"    {seconds:8.3f}s  {count:4d}x  {path}")


def _append_diff(
    lines: list[str],
    *,
    record: Mapping[str, Any],
    baseline: Mapping[str, Any] | None,
) -> None:
    if baseline is None:
        return
    lines.append("")
    lines.append("Diff")
    for key, label in _SUMMARY_FIELDS:
        current = _summary_value(record, key)
        previous = _summary_value(baseline, key)
        lines.append(
            f"  {label}: current {_format_summary_value(key, current)}; "
            f"baseline {_format_summary_value(key, previous)}; "
            f"delta {_format_delta(current, previous)}"
        )


def format_cost_report(
    record: Mapping[str, Any],
    *,
    baseline: Mapping[str, Any] | None = None,
    top: int = 10,
) -> str:
    """Return a stable human-readable attribution report."""

    worker_count = record.get("worker_count")
    lines = [
        "Test Cost Report",
        f"  record: {record.get('identity', 'n/a')}",
        f"  recorded_at: {record.get('recorded_at', 'n/a')}",
        f"  host: {record.get('host', 'n/a')}",
        f"  mode: {record.get('mode', 'n/a')}",
        f"  worker_count: {'n/a' if worker_count is None else worker_count}",
        "",
    ]
    _append_summary(lines, record)
    _append_diff(lines, record=record, baseline=baseline)
    _append_causes(lines, record, baseline=baseline)
    _append_top_files(lines, record, top=top)
    return "\n".join(lines) + "\n"
