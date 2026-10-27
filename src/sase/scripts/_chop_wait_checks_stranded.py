"""Targeted stranded-bead collection for wait_checks.

The scheduled chop runs in a short-lived subprocess, so its 60-second report
cache is stored atomically under the SASE state home. Cache failures only cost
another collection; they never affect waiter state.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sase.bead.stranded_facts import collect_issue_titles, collect_stranded_work_input
from sase.bead.store_locator import canonical_beads_dir_for_project
from sase.core import bead_read_facade
from sase.core.paths import sase_home
from sase.core.stranded_work_facade import (
    STRANDED_WORK_WIRE_SCHEMA_VERSION,
    StrandedWorkReport,
    StrandedWorkVerdict,
    reduce_stranded_work,
)
from sase.bead.stranded import StrandedReport

STRANDED_REPORT_CACHE_TTL_SECONDS = 60.0
_CACHE_SCHEMA_VERSION = 1
_CACHE_FILENAME = "wait_checks_stranded_reports.json"
_CACHE_MAX_ENTRIES = 64


def collect_targeted_stranded_report(
    project: str,
    bead_ids: set[str] | frozenset[str] | tuple[str, ...],
    *,
    now: float,
) -> StrandedReport:
    """Collect and reduce named beads, reusing a fresh per-project snapshot."""
    requested = tuple(
        sorted({bead_id.strip() for bead_id in bead_ids if bead_id.strip()})
    )
    if not requested:
        return _empty_report(now)
    beads_dir = canonical_beads_dir_for_project(project)
    if beads_dir is None:
        raise RuntimeError(f"bead store is unavailable for project {project}")
    fingerprint = _bead_store_fingerprint(beads_dir)
    cached = _read_cached(project, requested, fingerprint, now)
    if cached is not None:
        return cached

    facts = collect_stranded_work_input(project, now=now, bead_ids=requested)
    titles = collect_issue_titles(project, bead_ids=requested)
    report = reduce_stranded_work(facts)
    snapshot = StrandedReport(report=report, titles=titles, generated_at=now)
    _write_cached(project, requested, fingerprint, snapshot, now)
    return snapshot


def _empty_report(now: float) -> StrandedReport:
    return StrandedReport(
        report=StrandedWorkReport(schema_version=STRANDED_WORK_WIRE_SCHEMA_VERSION),
        titles={},
        generated_at=now,
    )


def _bead_store_fingerprint(beads_dir: Path) -> str | None:
    try:
        fingerprint = bead_read_facade.store_fingerprint(beads_dir)
    except Exception:  # noqa: BLE001 - cache invalidation is best-effort.
        fingerprint = None
    if fingerprint is not None:
        return fingerprint.token
    try:
        stat = (beads_dir / "issues.jsonl").stat()
    except OSError:
        return None
    return f"mtime:{stat.st_mtime_ns}:{stat.st_size}"


def _cache_path() -> Path:
    return sase_home() / "cache" / _CACHE_FILENAME


def _cache_key(project: str, bead_ids: tuple[str, ...], fingerprint: str | None) -> str:
    encoded = json.dumps(
        [project, list(bead_ids), fingerprint], separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _read_cached(
    project: str,
    bead_ids: tuple[str, ...],
    fingerprint: str | None,
    now: float,
) -> StrandedReport | None:
    try:
        raw = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("schema_version") != _CACHE_SCHEMA_VERSION:
        return None
    entries = raw.get("entries")
    if not isinstance(entries, dict):
        return None
    entry = entries.get(_cache_key(project, bead_ids, fingerprint))
    if not isinstance(entry, dict):
        return None
    expires_at = entry.get("expires_at")
    snapshot = entry.get("snapshot")
    if (
        isinstance(expires_at, bool)
        or not isinstance(expires_at, (int, float))
        or float(expires_at) <= now
        or not isinstance(snapshot, dict)
    ):
        return None
    try:
        return _snapshot_from_json(snapshot)
    except (TypeError, ValueError, KeyError):
        return None


def _snapshot_to_json(snapshot: StrandedReport) -> dict[str, Any]:
    report = snapshot.report
    return {
        "generated_at": snapshot.generated_at,
        "titles": dict(snapshot.titles),
        "report": {
            "schema_version": report.schema_version,
            "stranded_ids": list(report.stranded_ids),
            "blocked_ids": list(report.blocked_ids),
            "verdicts": [asdict(verdict) for verdict in report.verdicts],
        },
    }


def _snapshot_from_json(raw: dict[str, Any]) -> StrandedReport:
    report_raw = raw["report"]
    if not isinstance(report_raw, dict):
        raise TypeError("cached report is not an object")
    verdicts_raw = report_raw.get("verdicts", [])
    if not isinstance(verdicts_raw, list):
        raise TypeError("cached verdicts are not a list")
    verdicts = tuple(_verdict_from_json(value) for value in verdicts_raw)
    titles_raw = raw.get("titles", {})
    if not isinstance(titles_raw, dict):
        raise TypeError("cached titles are not an object")
    return StrandedReport(
        report=StrandedWorkReport(
            schema_version=int(report_raw.get("schema_version", 1)),
            verdicts=verdicts,
            stranded_ids=_string_tuple(report_raw.get("stranded_ids")),
            blocked_ids=_string_tuple(report_raw.get("blocked_ids")),
        ),
        titles={str(key): str(value) for key, value in titles_raw.items()},
        generated_at=float(raw["generated_at"]),
    )


def _verdict_from_json(raw: object) -> StrandedWorkVerdict:
    if not isinstance(raw, dict):
        raise TypeError("cached verdict is not an object")
    return StrandedWorkVerdict(
        bead_id=str(raw["bead_id"]),
        kind=str(raw["kind"]),
        state=str(raw["state"]),
        reason=_optional_string(raw.get("reason")),
        owner=_optional_string(raw.get("owner")),
        delegates=_string_tuple(raw.get("delegates")),
        session=_optional_string(raw.get("session")),
        last_turn=_optional_string(raw.get("last_turn")),
        last_turn_artifact_dir=_optional_string(raw.get("last_turn_artifact_dir")),
        declared_bead_action=_optional_string(raw.get("declared_bead_action")),
        since=_optional_float(raw.get("since")),
        parent_id=_optional_string(raw.get("parent_id")),
        blocked_by=_string_tuple(raw.get("blocked_by")),
        blocks=_string_tuple(raw.get("blocks")),
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _optional_float(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    return tuple(item for item in value if isinstance(item, str))


def _write_cached(
    project: str,
    bead_ids: tuple[str, ...],
    fingerprint: str | None,
    snapshot: StrandedReport,
    now: float,
) -> None:
    path = _cache_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {"schema_version": _CACHE_SCHEMA_VERSION, "entries": {}}
    if (
        not isinstance(raw, dict)
        or raw.get("schema_version") != _CACHE_SCHEMA_VERSION
        or not isinstance(raw.get("entries"), dict)
    ):
        raw = {"schema_version": _CACHE_SCHEMA_VERSION, "entries": {}}
    entries: dict[str, Any] = raw["entries"]
    entries[_cache_key(project, bead_ids, fingerprint)] = {
        "expires_at": now + STRANDED_REPORT_CACHE_TTL_SECONDS,
        "snapshot": _snapshot_to_json(snapshot),
    }
    entries = {
        key: value
        for key, value in entries.items()
        if isinstance(value, dict)
        and isinstance(value.get("expires_at"), (int, float))
        and float(value["expires_at"]) > now
    }
    if len(entries) > _CACHE_MAX_ENTRIES:
        entries = dict(
            sorted(
                entries.items(),
                key=lambda item: float(item[1]["expires_at"]),
                reverse=True,
            )[:_CACHE_MAX_ENTRIES]
        )
    tmp: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.parent / f".{path.name}.{os.getpid()}.{id(snapshot):x}.tmp"
        tmp.write_text(
            json.dumps(
                {"schema_version": _CACHE_SCHEMA_VERSION, "entries": entries},
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except OSError:
        if tmp is not None:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass


__all__ = ["STRANDED_REPORT_CACHE_TTL_SECONDS", "collect_targeted_stranded_report"]
