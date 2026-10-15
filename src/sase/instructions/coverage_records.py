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
    actor: str = ""
    is_helper: bool = False
    manifest: dict[str, Any] = field(compare=False, default_factory=dict)
    invocation_id: str | None = None
    session_ids: tuple[str, ...] = ()
    delivery_status: str | None = None
    fallback_reason: str | None = None
    bundle_sha256: str | None = None


def record_from_entry(entry: Any, artifact_dir: str | Path) -> ManifestRecord | None:
    """Return the match fields for one reader entry, or ``None``."""
    if entry.manifest is None:
        return None
    facts = entry.manifest.get("facts")
    provider = ""
    purpose = ""
    actor = ""
    if isinstance(facts, dict):
        raw_provider = facts.get("provider")
        if isinstance(raw_provider, str):
            provider = raw_provider.lower()
        raw_purpose = facts.get("purpose")
        if isinstance(raw_purpose, str):
            purpose = raw_purpose
        raw_actor = facts.get("actor")
        if isinstance(raw_actor, str):
            actor = raw_actor
    is_helper = bool(getattr(entry, "is_helper", False) or actor == "native_helper")
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
    invocation_id: str | None = None
    session_ids: tuple[str, ...] = ()
    delivery_status: str | None = None
    fallback_reason: str | None = None
    if isinstance(delivery, dict):
        raw_invocation = delivery.get("invocation_id")
        if isinstance(raw_invocation, str) and raw_invocation:
            invocation_id = raw_invocation
        raw_sessions = delivery.get("session_ids")
        if isinstance(raw_sessions, list):
            session_ids = tuple(
                item for item in raw_sessions if isinstance(item, str) and item
            )
        raw_status = delivery.get("status")
        if isinstance(raw_status, str) and raw_status:
            delivery_status = raw_status
        raw_fallback = delivery.get("fallback")
        if isinstance(raw_fallback, dict):
            raw_reason = raw_fallback.get("reason")
            if isinstance(raw_reason, str) and raw_reason:
                fallback_reason = raw_reason
    bundle = entry.manifest.get("bundle")
    bundle_sha256 = (
        bundle.get("sha256")
        if isinstance(bundle, dict) and isinstance(bundle.get("sha256"), str)
        else None
    )
    return ManifestRecord(
        artifact_dir=str(artifact_dir),
        seq=entry.seq,
        provider=provider,
        purpose=purpose,
        rendered_at=rendered,
        render_ms=render_ms,
        cache=cache,
        manifest_path=str(manifest_path) if manifest_path else "",
        actor=actor,
        is_helper=is_helper,
        manifest=entry.manifest,
        invocation_id=invocation_id,
        session_ids=session_ids,
        delivery_status=delivery_status,
        fallback_reason=fallback_reason,
        bundle_sha256=bundle_sha256,
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


def _root_records(records: list[ManifestRecord]) -> list[ManifestRecord]:
    return [
        record
        for record in records
        if not record.is_helper and record.actor != "native_helper"
    ]


def _session_recorded(session: RootSession, record: ManifestRecord) -> bool:
    """Return whether *record* listed *session*'s provider session id.

    Codex manifests store the rollout thread id, while discovery uses the
    rollout filename stem (``rollout-<local-time>-<thread-id>``). A Codex
    stem that ends with ``-<recorded id>`` counts as recorded.
    """
    if session.session_id in record.session_ids:
        return True
    if session.provider != "codex":
        return False
    return any(
        session.session_id.endswith(f"-{recorded}") for recorded in record.session_ids
    )


def session_is_foreign(session: RootSession, records: list[ManifestRecord]) -> bool:
    """Return whether *session* is another invocation's or was never recorded.

    True when the session has at least one marker and none of those
    invocation ids appear among *records*' root manifests.

    Also true for a marker-less session when the run has at least one
    same-provider non-helper root record, every such record recorded
    ``session_ids``, and none of them records this session. A nested
    ``claude -p`` started by a tool inside the workspace is the typical
    case. Records that recorded no ids (legacy, shadow, or pre-writeback)
    keep time-matching.
    """
    roots = _root_records(records)
    marker_invocations = {invocation for _sha, invocation in session.bundle_markers}
    if marker_invocations:
        root_invocations = {
            record.invocation_id for record in roots if record.invocation_id
        }
        return marker_invocations.isdisjoint(root_invocations)
    provider_roots = [record for record in roots if record.provider == session.provider]
    if not provider_roots:
        return False
    if not all(record.session_ids for record in provider_roots):
        return False
    return not any(_session_recorded(session, record) for record in provider_roots)


def matching_manifests(
    session: RootSession, records: list[ManifestRecord]
) -> list[ManifestRecord]:
    """Return same-provider manifests covering *session*, latest first.

    A session that carries any bundle marker matches only records whose
    ``invocation_id`` is among those markers and never falls through to
    session id or time. Marker-less sessions match recorded ``session_ids``
    (Codex rollout stems also match a recorded thread-id suffix), then
    time-match only records that recorded none.
    """
    provider_candidates = [
        record
        for record in records
        if record.provider == session.provider
        and not record.is_helper
        and record.actor != "native_helper"
    ]
    marker_invocations = {invocation for _sha, invocation in session.bundle_markers}
    if marker_invocations:
        matches = [
            record
            for record in provider_candidates
            if record.invocation_id and record.invocation_id in marker_invocations
        ]
    else:
        session_id_matches = [
            record
            for record in provider_candidates
            if _session_recorded(session, record)
        ]
        if session_id_matches:
            matches = session_id_matches
        else:
            matches = [
                record
                for record in provider_candidates
                if not record.session_ids
                and _rendered_covers(record.rendered_at, session.session_start)
            ]
    matches.sort(
        key=lambda record: (
            record.rendered_at or datetime.min.replace(tzinfo=UTC),
            record.seq,
        ),
        reverse=True,
    )
    return matches


def manifest_layer_included(record: ManifestRecord, layer: str) -> bool:
    """Return whether any manifest section from *layer* is included."""
    sections = record.manifest.get("sections")
    if not isinstance(sections, list):
        return False
    return any(
        isinstance(section, dict)
        and section.get("layer") == layer
        and section.get("status") == "included"
        for section in sections
    )


def delivery_label(record: ManifestRecord) -> str:
    """Return the scoreboard label for this manifest's delivery state."""
    if record.delivery_status == "explicit":
        return "explicit"
    if record.delivery_status == "shadow":
        return "shadow"
    reason = record.fallback_reason or "provider_legacy"
    return f"legacy:{reason}"


__all__ = [
    "COVERAGE_SKEW",
    "ManifestRecord",
    "delivery_label",
    "manifest_layer_included",
    "matching_manifests",
    "record_from_entry",
    "run_manifest_records",
    "session_is_foreign",
]
