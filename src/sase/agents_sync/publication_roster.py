"""Small validated machine-roster views for agent publication."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import threading
from types import MappingProxyType
from typing import TypeGuard

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2OwnerManifest,
)
from sase.core.paths import sase_home

_ROSTER_CACHE_SCHEMA_VERSION = 1
_ROSTER_CACHE_MAX_BYTES = 8 * 1024 * 1024
_DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
_VALID_STATES = {
    "active",
    "waiting",
    "completed",
    "failed",
    "stopped",
    "dismissed",
}
RosterSummaryKey = tuple[str, str, str, str, str, str]


@dataclass(frozen=True, slots=True)
class HoodRosterSummary:
    """The machine-index fields rendered for one published hood."""

    local_hood: str
    run_count: int
    session_count: int
    state_counts: Mapping[str, int]

    @classmethod
    def from_snapshot(cls, snapshot: V2HoodSnapshot) -> HoodRosterSummary:
        """Build the stable roster projection from a validated snapshot."""

        from sase.agents_sync.v2_models import is_session_container

        counts = Counter(run.state for run in snapshot.runs)
        return cls(
            snapshot.local_hood,
            len(snapshot.runs),
            sum(is_session_container(item.kind) for item in snapshot.containers),
            MappingProxyType(dict(sorted(counts.items()))),
        )


def roster_summary_key(
    manifest: V2OwnerManifest,
    hood: str,
    digest: str,
) -> RosterSummaryKey:
    """Return the cache identity pinned to one manifest entry."""

    return (
        manifest.owner.username,
        manifest.owner.machine_name,
        manifest.project.key,
        manifest.project.name,
        hood,
        digest,
    )


@dataclass(slots=True)
class _RosterSummaryCache:
    """Validated cache contents plus the bytes read for write elision."""

    path: Path | None
    project_key: str
    sidecar_path: str
    summaries: dict[RosterSummaryKey, HoodRosterSummary]
    original_bytes: bytes | None


def read_roster_summary_cache(
    repo_root: Path,
    project_key: str,
    *,
    path_override: Path | None = None,
) -> _RosterSummaryCache:
    """Read an opportunistic cache; malformed or inaccessible data is empty."""

    try:
        sidecar_path = str(repo_root.resolve(strict=False))
        path = path_override or _roster_cache_path(project_key, sidecar_path)
    except PublicationDrainTimedOut:
        raise
    except Exception:  # noqa: BLE001 - cache path problems never fail planning.
        return _RosterSummaryCache(None, project_key, "", {}, None)
    empty = _RosterSummaryCache(path, project_key, sidecar_path, {}, None)
    try:
        if path.stat().st_size > _ROSTER_CACHE_MAX_BYTES:
            return empty
        raw = path.read_bytes()
    except PublicationDrainTimedOut:
        raise
    except FileNotFoundError:
        return empty
    except OSError:
        return empty
    if len(raw) > _ROSTER_CACHE_MAX_BYTES:
        return empty
    empty.original_bytes = raw
    try:
        payload = json.loads(raw)
        if (
            not isinstance(payload, dict)
            or payload.get("schema_version") != _ROSTER_CACHE_SCHEMA_VERSION
            or payload.get("project_key") != project_key
            or payload.get("sidecar_path") != sidecar_path
            or not isinstance(payload.get("summaries"), list)
        ):
            return empty
        summaries: dict[RosterSummaryKey, HoodRosterSummary] = {}
        for row in payload["summaries"]:
            decoded = _decode_summary_row(row)
            if decoded is None:
                return empty
            key, summary = decoded
            if key in summaries:
                return empty
            summaries[key] = summary
    except PublicationDrainTimedOut:
        raise
    except Exception:  # noqa: BLE001 - malformed cache data is empty.
        return empty
    empty.summaries = summaries
    return empty


def write_roster_summary_cache(
    cache: _RosterSummaryCache,
    *,
    current_keys: set[RosterSummaryKey],
    additions: Mapping[RosterSummaryKey, HoodRosterSummary],
) -> None:
    """Prune stale entries and atomically persist changed bounded contents."""

    if cache.path is None:
        return
    try:
        summaries = {
            key: value for key, value in cache.summaries.items() if key in current_keys
        }
        summaries.update(
            {key: value for key, value in additions.items() if key in current_keys}
        )
        rows = [
            _encode_summary_row(key, summary)
            for key, summary in sorted(summaries.items())
        ]
        payload = {
            "schema_version": _ROSTER_CACHE_SCHEMA_VERSION,
            "project_key": cache.project_key,
            "sidecar_path": cache.sidecar_path,
            "summaries": rows,
        }
        encoded = (
            json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
        ).encode("utf-8")
        if len(encoded) > _ROSTER_CACHE_MAX_BYTES or encoded == cache.original_bytes:
            return
        cache.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = cache.path.with_name(
            f".{cache.path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
        )
        try:
            with temporary.open("wb") as output:
                output.write(encoded)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, cache.path)
        finally:
            temporary.unlink(missing_ok=True)
        cache.original_bytes = encoded
        cache.summaries = summaries
    except PublicationDrainTimedOut:
        raise
    except Exception:  # noqa: BLE001 - cache write problems never fail planning.
        return


def _roster_cache_path(project_key: str, sidecar_path: str) -> Path:
    identity = f"{project_key}\0{sidecar_path}"
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return sase_home() / "cache" / "agent-publication-hood-summaries" / f"{digest}.json"


def _decode_summary_row(
    row: object,
) -> tuple[RosterSummaryKey, HoodRosterSummary] | None:
    if not isinstance(row, dict):
        return None
    raw_key = row.get("key")
    if (
        not isinstance(raw_key, list)
        or len(raw_key) != 6
        or any(not isinstance(part, str) for part in raw_key)
    ):
        return None
    key: RosterSummaryKey = tuple(raw_key)  # type: ignore[assignment]
    if not _DIGEST_RE.fullmatch(key[-1]):
        return None
    local_hood = row.get("local_hood")
    run_count = row.get("run_count")
    session_count = row.get("session_count")
    state_counts = row.get("state_counts")
    summary_digest = row.get("summary_digest")
    if (
        not isinstance(local_hood, str)
        or local_hood != key[4]
        or not _nonnegative_int(run_count)
        or not _nonnegative_int(session_count)
        or not isinstance(state_counts, dict)
        or not isinstance(summary_digest, str)
    ):
        return None
    counts: dict[str, int] = {}
    for state, count in state_counts.items():
        if (
            not isinstance(state, str)
            or state not in _VALID_STATES
            or not _positive_int(count)
        ):
            return None
        counts[state] = count
    if sum(counts.values()) != run_count:
        return None
    summary = HoodRosterSummary(
        local_hood,
        run_count,
        session_count,
        MappingProxyType(dict(sorted(counts.items()))),
    )
    if summary_digest != _summary_digest(summary):
        return None
    return key, summary


def _encode_summary_row(
    key: RosterSummaryKey,
    summary: HoodRosterSummary,
) -> dict[str, object]:
    return {
        "key": list(key),
        "local_hood": summary.local_hood,
        "run_count": summary.run_count,
        "session_count": summary.session_count,
        "state_counts": dict(summary.state_counts),
        "summary_digest": _summary_digest(summary),
    }


def _summary_digest(summary: HoodRosterSummary) -> str:
    canonical = {
        "local_hood": summary.local_hood,
        "run_count": summary.run_count,
        "session_count": summary.session_count,
        "state_counts": dict(sorted(summary.state_counts.items())),
    }
    encoded = json.dumps(canonical, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _nonnegative_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _positive_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


__all__ = [
    "HoodRosterSummary",
    "RosterSummaryKey",
    "read_roster_summary_cache",
    "roster_summary_key",
    "write_roster_summary_cache",
]
