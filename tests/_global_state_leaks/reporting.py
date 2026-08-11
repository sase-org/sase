"""Aggregate worker payloads and read report summaries."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import UTC, datetime
import json
from pathlib import Path


def _combine_payloads(payloads: list[Mapping[str, object]]) -> dict[str, object]:
    records: list[dict[str, object]] = []
    warming_counts: Counter[str] = Counter()
    cooling_counts: Counter[str] = Counter()
    invalidation_counts: Counter[str] = Counter()
    errors: list[str] = []
    observed_tests = 0
    for payload in payloads:
        observed_tests += int(payload.get("observed_tests") or 0)
        raw_warming = payload.get("warming_counts")
        if isinstance(raw_warming, Mapping):
            warming_counts.update(
                {str(key): int(value) for key, value in raw_warming.items()}
            )
        raw_cooling = payload.get("cooling_counts")
        if isinstance(raw_cooling, Mapping):
            cooling_counts.update(
                {str(key): int(value) for key, value in raw_cooling.items()}
            )
        raw_invalidations = payload.get("invalidation_counts")
        if isinstance(raw_invalidations, Mapping):
            invalidation_counts.update(
                {str(key): int(value) for key, value in raw_invalidations.items()}
            )
        raw_errors = payload.get("errors")
        if isinstance(raw_errors, list):
            errors.extend(str(error) for error in raw_errors)
        raw_records = payload.get("records")
        if isinstance(raw_records, list):
            records.extend(record for record in raw_records if isinstance(record, dict))

    records.sort(
        key=lambda record: (
            str(record.get("worker_id") or ""),
            int(record.get("worker_order") or 0),
            str(record.get("nodeid") or ""),
        )
    )
    poisoning_changes = sum(
        len(record.get("changes") or [])
        for record in records
        if isinstance(record.get("changes"), list)
    )
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "summary": {
            "observed_tests": observed_tests,
            "tests_with_poisoning": len(records),
            "poisoning_changes": poisoning_changes,
            "warming_changes_filtered": sum(warming_counts.values()),
            "warming_by_kind": dict(sorted(warming_counts.items())),
            "cooling_changes_filtered": sum(cooling_counts.values()),
            "cooling_by_kind": dict(sorted(cooling_counts.items())),
            "invalidation_changes_filtered": sum(invalidation_counts.values()),
            "invalidation_by_kind": dict(sorted(invalidation_counts.items())),
        },
        "poisoning": records,
        "errors": errors,
    }


def _report_with_errors(
    report: Mapping[str, object], errors: list[str]
) -> dict[str, object]:
    merged_errors: list[str] = []
    raw_errors = report.get("errors")
    if isinstance(raw_errors, list):
        merged_errors.extend(str(error) for error in raw_errors)
    merged_errors.extend(str(error) for error in errors)
    return {**dict(report), "errors": list(dict.fromkeys(merged_errors))}


def _report_summary(payload: Mapping[str, object] | None) -> Mapping[str, object]:
    if not isinstance(payload, Mapping):
        return {}
    summary = payload.get("summary")
    return summary if isinstance(summary, Mapping) else {}


def _read_report_summary(path: Path) -> Mapping[str, object]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, Mapping):
        return {}
    summary = raw.get("summary")
    return summary if isinstance(summary, Mapping) else {}
