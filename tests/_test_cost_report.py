"""Human-readable reporting for suite-cost recordings."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from tests._test_cost_records import _cause_seconds, _summary_value


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
    ("median_worker_rss_kib", "median worker RSS KiB"),
    ("post_collection_worker_rss_kib", "post-collection worker RSS KiB"),
)


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
