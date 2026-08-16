"""Coverage and probe metadata for the Statistics Perf view."""

from __future__ import annotations

import os
from collections.abc import Mapping

from sase.stats._view_models import (
    PerfCoverage,
    PerfLogCoverage,
    PerfProbeStatus,
    PerfTelemetryCoverage,
)
from sase.stats._view_payload import (
    Payload,
    boolean,
    integer,
    mapping,
    optional_number,
    rows,
    text,
)
from sase.stats.ranges import StatsRange

_PERF_PROBES: tuple[tuple[str, str], ...] = (
    ("SASE_TUI_PERF", "Set SASE_TUI_PERF=1 to record per-keystroke j/k timings."),
    ("SASE_TUI_TRACE", "Set SASE_TUI_TRACE=1 to record hot-path span traces."),
)


def build_coverage(
    perf_payload: Payload,
    telemetry_payload: Payload,
    *,
    selected_range: StatsRange,
    now: float | None,
) -> PerfCoverage:
    """Build source coverage, telemetry store, and probe metadata."""
    logs = tuple(
        PerfLogCoverage(
            source=text(row.get("source"), "unknown"),
            path=text(row.get("path")),
            present=boolean(row.get("present")),
            records_scanned=integer(row.get("records_scanned")),
            records_in_window=integer(row.get("records_in_window")),
            earliest_ts=optional_number(row.get("earliest_ts")),
            latest_ts=optional_number(row.get("latest_ts")),
            truncated=boolean(row.get("truncated")),
            malformed_skipped=integer(row.get("malformed_skipped")),
        )
        for row in rows(perf_payload, "coverage")
    )
    store = mapping(telemetry_payload.get("store"))
    last_write_ts = _optional_int(store.get("last_write_ts"))
    last_write_age = None
    if now is not None and last_write_ts is not None:
        last_write_age = max(0.0, float(now) - float(last_write_ts))
    enabled = boolean(telemetry_payload.get("enabled"))
    telemetry = PerfTelemetryCoverage(
        enabled=enabled,
        available=enabled and _telemetry_has_samples(store, telemetry_payload),
        store_path=text(store.get("store_path")),
        store_size_bytes=integer(store.get("db_size_bytes")),
        raw_sample_count=integer(store.get("raw_sample_count")),
        rollup_5m_count=integer(store.get("rollup_5m_count")),
        rollup_1h_count=integer(store.get("rollup_1h_count")),
        resolution=text(telemetry_payload.get("resolution")) or None,
        last_write_ts=last_write_ts,
        last_write_age_seconds=last_write_age,
        last_write_by_subsystem=_subsystem_writes(store.get("last_write_by_subsystem")),
        earliest_sample_ts=_optional_int(store.get("earliest_sample_ts")),
        latest_sample_ts=_optional_int(store.get("latest_sample_ts")),
        error=text(telemetry_payload.get("error")) or None,
    )
    probes = tuple(
        PerfProbeStatus(name=name, enabled=name in os.environ, hint=hint)
        for name, hint in _PERF_PROBES
    )
    notes = _coverage_notes(logs, telemetry, selected_range)
    return PerfCoverage(
        telemetry=telemetry,
        logs=logs,
        probes=probes,
        notes=notes,
    )


def _telemetry_has_samples(store: Payload, telemetry: Payload) -> bool:
    has_store_rows = any(
        integer(store.get(key))
        for key in ("raw_sample_count", "rollup_5m_count", "rollup_1h_count")
    )
    if has_store_rows:
        return True
    histograms = mapping(telemetry.get("histograms"))
    counters = mapping(telemetry.get("counters"))
    return bool(histograms) or bool(counters)


def _subsystem_writes(value: object) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, Mapping):
        return ()
    writes: list[tuple[str, int]] = []
    for key, raw in value.items():
        if not isinstance(key, str):
            continue
        stamp = _optional_int(raw)
        if stamp is None:
            continue
        writes.append((key, stamp))
    writes.sort(key=lambda item: item[0])
    return tuple(writes)


def _coverage_notes(
    logs: tuple[PerfLogCoverage, ...],
    telemetry: PerfTelemetryCoverage,
    selected_range: StatsRange,
) -> tuple[str, ...]:
    notes: list[str] = []
    malformed = sum(entry.malformed_skipped for entry in logs)
    if malformed:
        notes.append(f"{malformed} unreadable records skipped")
    truncated = [entry.source for entry in logs if entry.truncated]
    if truncated:
        notes.append(
            "Bounded log read truncated older records for: " + ", ".join(truncated)
        )
    if not telemetry.enabled:
        notes.append("Telemetry is disabled (telemetry.enabled).")
    elif telemetry.error:
        notes.append(f"Telemetry store error: {telemetry.error}")
    if selected_range.start_ts == 0:
        notes.append(
            "All time means as far back as retained telemetry and bounded logs go."
        )
    return tuple(notes)


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)
