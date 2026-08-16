"""State files for external mirror chops.

``ChopScriptContext.state_dir`` is the lumberjack directory shared by every
chop in a lane, not a per-instance directory. Files here are therefore keyed
as ``<kind>__<project_key>.json`` under a caller-supplied state directory.

Both mirrors persist their per-project cursor at a stable, lane-independent
path (``sase_subdir("external_mirror")``, see ``pr_mirror_state_dir`` and
``_mirror_state_dir`` below), because their manual CLI entry points must read
and write the same cursor as their AXE chop without knowing which lane the
chop is configured in.

The PR filter-outcome document (``read_pr_unmirrored_counts`` /
``write_pr_unmirrored_count``) is lane-independent from birth for the same
reason, and is a single shared, read-modify-write document keyed by project
rather than one file per project. No lock guards the read-modify-write: a
lost update between two concurrent per-project chop instances costs one
stale cosmetic counter until the next pass, which is cheaper than a lock.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from sase.axe.state import lumberjack_state_dir
from sase.core.paths import sase_subdir
from sase.core.state_write_guard import best_effort_test_state_write_allowed


@dataclass(frozen=True)
class MirrorCursor:
    last_updated_at: datetime | None = None
    last_provider_id: str = ""
    backfill_complete: bool = False
    last_full_scan_at: datetime | None = None
    #: Digest of the last ``PullRequestFilters`` a clean pass observed. A
    #: mismatch against the current filters' fingerprint means the filter
    #: config changed since, so the next pass must go full to re-examine
    #: records the old filters dropped.
    filters_fingerprint: str = ""


@dataclass(frozen=True)
class BackoffEntry:
    failures: int
    next_attempt_at: datetime
    last_error: str = ""


def mirror_state_path(state_dir: Path, kind: str, project_key: str) -> Path:
    """Return the cursor path for one mirror kind/project pair."""
    return state_dir / f"{kind}__{project_key}.json"


def _backoff_state_path(state_dir: Path, kind: str) -> Path:
    """Return the shared backoff-state path for one mirror kind."""
    return state_dir / f"{kind}__backoff.json"


#: Lane the PR mirror's cursor and backoff files used to live under, back
#: when they were threaded through ``ChopScriptContext.state_dir``.
_LEGACY_PR_MIRROR_LANE = "checks"


def pr_mirror_state_dir() -> Path:
    """Return the PR mirror's stable, lane-independent state directory.

    Migrates any ``external_pr__*.json`` cursor and backoff files left
    behind under the old ``checks`` lumberjack directory the first time this
    is called, so relocating the chop to its own lane does not silently
    reset a project's backfill.
    """
    new_dir = sase_subdir("external_mirror")
    _migrate_legacy_pr_mirror_state(new_dir)
    return new_dir


def _migrate_legacy_pr_mirror_state(new_dir: Path) -> None:
    legacy_dir = lumberjack_state_dir(_LEGACY_PR_MIRROR_LANE)
    if not legacy_dir.is_dir():
        return
    for legacy_path in legacy_dir.glob("external_pr__*.json"):
        destination = new_dir / legacy_path.name
        if destination.exists():
            continue
        try:
            new_dir.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(legacy_path.read_bytes())
        except OSError:
            continue


def read_mirror_cursor(state_dir: Path, kind: str, project_key: str) -> MirrorCursor:
    """Read a cursor, degrading malformed or absent state to an empty cursor."""
    path = mirror_state_path(state_dir, kind, project_key)
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError):
        return MirrorCursor()
    if not isinstance(payload, dict):
        return MirrorCursor()
    return MirrorCursor(
        last_updated_at=_parse_datetime(payload.get("last_updated_at")),
        last_provider_id=str(payload.get("last_provider_id") or ""),
        backfill_complete=bool(payload.get("backfill_complete", False)),
        last_full_scan_at=_parse_datetime(payload.get("last_full_scan_at")),
        filters_fingerprint=str(payload.get("filters_fingerprint") or ""),
    )


def write_mirror_cursor(
    state_dir: Path,
    kind: str,
    project_key: str,
    cursor: MirrorCursor,
) -> None:
    """Atomically write one mirror cursor."""
    path = mirror_state_path(state_dir, kind, project_key)
    _atomic_json_write(
        path,
        {
            "last_updated_at": _format_datetime(cursor.last_updated_at),
            "last_provider_id": cursor.last_provider_id,
            "backfill_complete": cursor.backfill_complete,
            "last_full_scan_at": _format_datetime(cursor.last_full_scan_at),
            "filters_fingerprint": cursor.filters_fingerprint,
        },
    )


def read_backoff_state(state_dir: Path, kind: str) -> dict[str, BackoffEntry]:
    """Read shared mirror backoff state keyed by project."""
    path = _backoff_state_path(state_dir, kind)
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    state: dict[str, BackoffEntry] = {}
    for project_key, raw_entry in payload.items():
        if not isinstance(project_key, str) or not isinstance(raw_entry, dict):
            continue
        failures = raw_entry.get("failures")
        next_attempt_at = _parse_datetime(raw_entry.get("next_attempt_at"))
        if (
            not isinstance(failures, int)
            or isinstance(failures, bool)
            or failures < 1
            or next_attempt_at is None
        ):
            continue
        state[project_key] = BackoffEntry(
            failures=failures,
            next_attempt_at=next_attempt_at,
            last_error=str(raw_entry.get("last_error") or ""),
        )
    return state


def write_backoff_state(
    state_dir: Path,
    kind: str,
    state: dict[str, BackoffEntry],
) -> None:
    """Atomically write shared mirror backoff state."""
    path = _backoff_state_path(state_dir, kind)
    payload = {
        project_key: {
            "failures": entry.failures,
            "next_attempt_at": entry.next_attempt_at.isoformat(),
            "last_error": entry.last_error,
        }
        for project_key, entry in sorted(state.items())
    }
    _atomic_json_write(path, payload)


def next_backoff_entry(
    previous: BackoffEntry | None,
    *,
    now: datetime,
    run_every_seconds: int = 600,
    max_backoff_seconds: int = 3600,
    last_error: str = "",
) -> BackoffEntry:
    """Return the next exponential backoff entry."""
    failures = (previous.failures if previous is not None else 0) + 1
    exponent = min(failures, 5)
    delay_seconds = min(run_every_seconds * (2**exponent), max_backoff_seconds)
    return BackoffEntry(
        failures=failures,
        next_attempt_at=now + timedelta(seconds=delay_seconds),
        last_error=last_error,
    )


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _atomic_json_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_path = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2)
            stream.write("\n")
        os.replace(temporary_path, path)
    except BaseException:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


ISSUE_SCHEMA_VERSION = 1

#: Capped exponential backoff ceiling, the same pattern the ``sidecar_auto_sync``
#: chop uses for its own per-role schedule state.
ISSUE_MAX_BACKOFF_SECONDS = 60 * 60


def _mirror_state_dir(kind: str) -> Path:
    """Return the stable, lane-independent state directory for one mirror kind."""
    return sase_subdir("external_mirror") / kind


def mirror_state_document_path(kind: str, project_key: str) -> Path:
    """Return the per-project state document path for one mirror kind."""
    return _mirror_state_dir(kind) / f"{project_key}.json"


def pr_unmirrored_state_path() -> Path:
    return _mirror_state_dir("external_pr") / "unmirrored.json"


def read_pr_unmirrored_counts() -> dict[str, int]:
    """Return ``{project_key: unmirrored}`` from the last recorded PR pass.

    Tolerant of a missing or malformed document, including per-entry
    malformation; degrades to omitting the offending project rather than
    discarding the whole read. Safe to call from a render path: pure and
    synchronous, so callers that must avoid event-loop I/O should still wrap
    it (e.g. ``asyncio.to_thread``).
    """
    path = pr_unmirrored_state_path()
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    counts: dict[str, int] = {}
    for project_key, raw_entry in payload.items():
        if not isinstance(project_key, str) or not isinstance(raw_entry, dict):
            continue
        unmirrored = raw_entry.get("unmirrored")
        if (
            not isinstance(unmirrored, int)
            or isinstance(unmirrored, bool)
            or unmirrored < 0
        ):
            continue
        counts[project_key] = unmirrored
    return counts


def write_pr_unmirrored_count(
    project_key: str,
    *,
    fetched: int,
    unmirrored: int,
    now: datetime,
) -> None:
    """Read-modify-write this project's entry in the shared PR filter document.

    See the module docstring for why this shared document takes no lock.
    """
    path = pr_unmirrored_state_path()
    if not best_effort_test_state_write_allowed(path, category="external-mirror-state"):
        return
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload[project_key] = {
        "fetched": fetched,
        "unmirrored": unmirrored,
        "observed_at": iso_utc(now),
    }
    _atomic_json_write(path, payload)


@dataclass
class _MirrorState:
    """One project's durable mirror cursor, drift, and backoff record."""

    project: str = ""
    #: Newest ``updated_at`` observed across every issue in the last full listing.
    watermark_updated_at: str = ""
    #: Every provider id observed in that same listing, used to detect additions,
    #: removals, and transfers even when they do not move ``watermark_updated_at``.
    watermark_provider_ids: tuple[str, ...] = ()
    backfill_complete: bool = False
    last_full_scan_at: str = ""
    last_success_at: str = ""
    #: ``external_ref -> last observed remote state`` for every ref covered by a
    #: local bead. Pruned to refs still covered so it stays bounded by the
    #: mirrored-bead count.
    upstream_states: dict[str, str] = field(default_factory=dict)
    failures: int = 0
    next_attempt_at: str = ""
    #: Digest of the last ``IssueFilters`` a clean (``deferred == 0``) pass
    #: observed. A mismatch against the current filters' fingerprint means the
    #: filter config changed since, so the unchanged-upstream early return is
    #: skipped for one pass to re-examine records the old filters dropped.
    filters_fingerprint: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ISSUE_SCHEMA_VERSION,
            "project": self.project,
            "watermark_updated_at": self.watermark_updated_at,
            "watermark_provider_ids": list(self.watermark_provider_ids),
            "backfill_complete": self.backfill_complete,
            "last_full_scan_at": self.last_full_scan_at,
            "last_success_at": self.last_success_at,
            "upstream_states": dict(self.upstream_states),
            "failures": self.failures,
            "next_attempt_at": self.next_attempt_at,
            "filters_fingerprint": self.filters_fingerprint,
        }


def read_mirror_state(path: Path, *, project: str) -> _MirrorState:
    """Tolerantly read one project's mirror state.

    A missing, truncated, corrupt, or wrong-schema-version file returns a
    fresh empty state rather than raising, following ``_read_schedule_state``
    in ``sase.scripts.sase_chop_sidecar_auto_sync``.
    """
    try:
        with path.open(encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError):
        return _MirrorState(project=project)
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != ISSUE_SCHEMA_VERSION
    ):
        return _MirrorState(project=project)

    upstream_states_raw = payload.get("upstream_states")
    upstream_states = (
        {str(key): str(value) for key, value in upstream_states_raw.items()}
        if isinstance(upstream_states_raw, dict)
        else {}
    )
    provider_ids_raw = payload.get("watermark_provider_ids")
    provider_ids = (
        tuple(str(item) for item in provider_ids_raw)
        if isinstance(provider_ids_raw, list)
        else ()
    )
    failures = payload.get("failures")
    if not isinstance(failures, int) or isinstance(failures, bool) or failures < 0:
        failures = 0

    return _MirrorState(
        project=str(payload.get("project") or project),
        watermark_updated_at=str(payload.get("watermark_updated_at") or ""),
        watermark_provider_ids=provider_ids,
        backfill_complete=bool(payload.get("backfill_complete")),
        last_full_scan_at=str(payload.get("last_full_scan_at") or ""),
        last_success_at=str(payload.get("last_success_at") or ""),
        upstream_states=upstream_states,
        failures=failures,
        next_attempt_at=str(payload.get("next_attempt_at") or ""),
        filters_fingerprint=str(payload.get("filters_fingerprint") or ""),
    )


def write_mirror_state(path: Path, state: _MirrorState) -> None:
    """Atomically write one project's mirror state document."""
    if not best_effort_test_state_write_allowed(path, category="external-mirror-state"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path_str = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temp_path = Path(temp_path_str)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(state.to_dict(), stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temp_path, path)
    except BaseException:
        try:
            temp_path.unlink()
        except OSError:
            pass
        raise


def next_backoff(previous_failures: int, *, now: datetime) -> tuple[int, str]:
    """Return the next failure count and ISO ``next_attempt_at``, capped at 1h."""
    failures = max(previous_failures, 0) + 1
    exponent = min(failures, 6)
    delay_seconds = min(30 * (2**exponent), ISSUE_MAX_BACKOFF_SECONDS)
    next_attempt_at = now + timedelta(seconds=delay_seconds)
    return failures, iso_utc(next_attempt_at)


def is_backed_off(state: _MirrorState, *, now: datetime) -> bool:
    """Return whether *state* is still inside its backoff window."""
    if not state.next_attempt_at:
        return False
    parsed = _parse_iso(state.next_attempt_at)
    if parsed is None:
        return False
    return now < parsed


def iso_utc(value: datetime) -> str:
    """Render *value* as a ``Z``-suffixed UTC ISO-8601 string."""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


__all__ = [
    "ISSUE_MAX_BACKOFF_SECONDS",
    "ISSUE_SCHEMA_VERSION",
    "BackoffEntry",
    "MirrorCursor",
    "is_backed_off",
    "iso_utc",
    "mirror_state_document_path",
    "mirror_state_path",
    "next_backoff",
    "next_backoff_entry",
    "pr_mirror_state_dir",
    "pr_unmirrored_state_path",
    "read_backoff_state",
    "read_mirror_cursor",
    "read_mirror_state",
    "read_pr_unmirrored_counts",
    "write_backoff_state",
    "write_mirror_cursor",
    "write_mirror_state",
    "write_pr_unmirrored_count",
]
