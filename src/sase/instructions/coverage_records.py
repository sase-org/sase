"""Shadow manifest records and session matching."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sase.instructions.coverage_sessions import RootSession, parse_time

#: Allowance for writer clock ordering between the shadow render and the
#: provider session start (plan: scoreboard coverage column).
COVERAGE_SKEW = timedelta(seconds=5)


@dataclass(frozen=True)
class ManifestRecord:
    """One readable shadow manifest with its match fields."""

    artifact_dir: str
    seq: int
    provider: str
    purpose: str
    rendered_at: datetime | None
    render_ms: float | None
    cache: str | None
    manifest_path: str
    manifest: dict[str, Any] = field(compare=False)


def record_from_entry(entry: Any, artifact_dir: str | Path) -> ManifestRecord | None:
    """Return the match fields for one reader entry, or ``None``."""
    if entry.manifest is None:
        return None
    facts = entry.manifest.get("facts")
    provider = ""
    purpose = ""
    if isinstance(facts, dict):
        raw_provider = facts.get("provider")
        if isinstance(raw_provider, str):
            provider = raw_provider.lower()
        raw_purpose = facts.get("purpose")
        if isinstance(raw_purpose, str):
            purpose = raw_purpose
    delivery = entry.manifest.get("delivery")
    rendered: datetime | None = None
    render_ms: float | None = None
    cache: str | None = None
    if isinstance(delivery, dict):
        rendered = parse_time(delivery.get("rendered_at"))
        raw_ms = delivery.get("render_ms")
        if isinstance(raw_ms, (int, float)):
            render_ms = float(raw_ms)
        raw_cache = delivery.get("cache")
        if isinstance(raw_cache, str):
            cache = raw_cache
    manifest_path = getattr(entry, "manifest_path", None)
    return ManifestRecord(
        artifact_dir=str(artifact_dir),
        seq=entry.seq,
        provider=provider,
        purpose=purpose,
        rendered_at=rendered,
        render_ms=render_ms,
        cache=cache,
        manifest_path=str(manifest_path) if manifest_path else "",
        manifest=entry.manifest,
    )


def run_manifest_records(artifact_dir: str | Path) -> list[ManifestRecord]:
    """Return readable shadow manifests under *artifact_dir*."""
    from sase.instructions.manifests import read_run_manifests

    records: list[ManifestRecord] = []
    for entry in read_run_manifests(artifact_dir):
        record = record_from_entry(entry, artifact_dir)
        if record is not None:
            records.append(record)
    return records


def _rendered_covers(rendered: datetime | None, start: datetime | None) -> bool:
    """Return whether *rendered* precedes *start* within skew allowance."""
    if rendered is None or start is None:
        return False
    return rendered <= start + COVERAGE_SKEW


def matching_manifests(
    session: RootSession, records: list[ManifestRecord]
) -> list[ManifestRecord]:
    """Return same-provider manifests covering *session*, latest first."""
    matches = [
        record
        for record in records
        if record.provider == session.provider
        and _rendered_covers(record.rendered_at, session.session_start)
    ]
    matches.sort(
        key=lambda record: record.rendered_at or datetime.min.replace(tzinfo=UTC),
        reverse=True,
    )
    return matches


__all__ = [
    "COVERAGE_SKEW",
    "ManifestRecord",
    "matching_manifests",
    "record_from_entry",
    "run_manifest_records",
]
