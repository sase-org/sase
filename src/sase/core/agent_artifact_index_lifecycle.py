"""Best-effort lifecycle maintenance for the agent artifact index."""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.core.agent_artifact_index_lock import (
    agent_artifact_index_operation_lock,
)
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    delete_agent_artifact_index_row,
    delete_agent_artifact_index_row_bounded,
    read_agent_artifact_index_meta,
    rebuild_agent_artifact_index,
    replace_agent_artifact_index_dismissed_agents,
    terminalize_stale_active_agent_artifact_index_rows,
    upsert_agent_artifact_index_row,
    write_agent_artifact_index_meta,
)
from sase.core.agent_scan_wire import (
    AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
    AgentArtifactScanOptionsWire,
)
from sase.core.paths import sase_home as _sase_home

log = logging.getLogger(__name__)

AgentIdentityLike = tuple[Any, str, str | None]
DismissedAgentsSignature = tuple[int, int] | None
DismissedBundleIndexSignature = tuple[int, int, int, int] | None

_LIFECYCLE_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=True,
    include_raw_prompt_snippets=False,
)
_INDEX_ERRORS = (
    ImportError,
    AttributeError,
    OSError,
    RuntimeError,
    ValueError,
)
_DISMISSED_PROJECTION_META_KEY = "dismissed_projection"
_DISMISSED_PROJECTION_META_VERSION = 1
_INDEX_SCHEMA_META_KEY = "schema_version"
_STALE_ACTIVE_TERMINALIZE_AFTER_SECONDS = 24 * 60 * 60
_STALE_ACTIVE_TERMINALIZE_MAX_ROWS = 10_000

# SQLite error messages that indicate on-disk corruption (as opposed to
# transient lock/timeout failures, which must never trigger a quarantine).
_CORRUPTION_MARKERS = (
    "database disk image is malformed",
    "file is not a database",
    "not a database",
    "malformed database schema",
    "database corruption",
    "unsupported file format",
)


class _CorruptArtifactIndexError(Exception):
    """Internal signal that the artifact index reported on-disk corruption."""


def _is_corruption_error(error: BaseException) -> bool:
    """Return whether *error* signals on-disk corruption.

    Matches corruption messages surfaced through the Rust facade's
    ``RuntimeError``. Transient errors (locked/busy timeouts) never match.
    """
    message = " ".join(str(arg) for arg in getattr(error, "args", ())).lower()
    return any(marker in message for marker in _CORRUPTION_MARKERS)


@dataclass(frozen=True)
class _DismissedProjectionInputs:
    """Dismissed identities plus the source signatures used to build them."""

    identities: list[AgentCleanupIdentityWire]
    dismissed_agents_signature: DismissedAgentsSignature
    dismissed_bundle_index_signature: DismissedBundleIndexSignature
    skipped_bundle_rows: int = 0


@dataclass(frozen=True)
class DismissedProjectionSyncReport:
    """Outcome of one dismissed-projection sync pass.

    ``changed`` is True when the projection rows were actually rewritten
    (i.e. the signature fast path did not hit), so callers can decide
    whether dismissed-visibility state may have drifted. ``healed`` is
    True when a corrupt index was quarantined and rebuilt during the
    sync; ``quarantined_path`` then points at the preserved corrupt copy.
    """

    synced: bool
    changed: bool = False
    healed: bool = False
    quarantined_path: Path | None = None
    terminalized_active_rows: int = 0


@dataclass(frozen=True)
class _ArtifactIndexSchemaRefreshReport:
    """Outcome of startup schema refresh for the persistent artifact index."""

    checked: bool
    refreshed: bool = False
    stored_schema_version: int | None = None
    rows_indexed: int = 0


@dataclass(frozen=True)
class _ArtifactIndexSchemaStatus:
    """Cheap stored-schema check that never opens the Rust index."""

    checked: bool
    stale: bool = False
    stored_schema_version: int | None = None


def _default_projects_root(sase_home: Path | str | None = None) -> Path:
    """Return the default projects root used by the artifact index."""
    root = Path(sase_home).expanduser() if sase_home is not None else _sase_home()
    return root / "projects"


def _projects_root_for_artifact_dir(artifact_dir: Path | str) -> Path:
    """Resolve the projects root that contains *artifact_dir* when possible."""
    path = Path(artifact_dir).expanduser()
    for candidate in (path, *path.parents):
        if candidate.name == "projects":
            return candidate
    return _default_projects_root()


def sync_dismissed_agent_artifact_index(
    dismissed: Iterable[AgentIdentityLike] | None = None,
    *,
    added: Iterable[AgentIdentityLike] | None = None,
    index_path: Path | str | None = None,
    force: bool = False,
    run_active_tier_maintenance: bool = True,
) -> bool:
    """Best-effort sync of dismissed identities into the SQLite artifact index.

    Bool-returning wrapper around
    :func:`sync_dismissed_agent_artifact_index_report` for callers that
    only care about success.
    """
    return sync_dismissed_agent_artifact_index_report(
        dismissed,
        added=added,
        index_path=index_path,
        force=force,
        run_active_tier_maintenance=run_active_tier_maintenance,
    ).synced


def sync_dismissed_agent_artifact_index_report(
    dismissed: Iterable[AgentIdentityLike] | None = None,
    *,
    added: Iterable[AgentIdentityLike] | None = None,
    index_path: Path | str | None = None,
    force: bool = False,
    run_active_tier_maintenance: bool = True,
) -> DismissedProjectionSyncReport:
    """Sync dismissed identities into the artifact index, reporting outcome.

    When ``added`` is provided, the caller asserts that ``dismissed`` is the
    full authoritative set of dismissed identities for this session. The
    expensive bundle-summary scan and bundle-index verify pass are skipped:
    the projection is built directly from ``dismissed`` only. The
    SQLite-side replace is still issued in one transaction so the on-disk
    rows match the in-memory set; ``added`` is a perf hint, not a
    correctness shortcut. On signature drift the full path remains.

    A corrupt index (e.g. ``database disk image is malformed``) is
    quarantined to ``<index>.corrupt-<UTC timestamp>``, rebuilt from
    source artifacts, and re-synced; transient lock errors never trigger
    that heal.
    """
    with agent_artifact_index_operation_lock():
        index = (
            Path(index_path).expanduser()
            if index_path is not None
            else default_agent_artifact_index_path()
        )
        if not index.is_file():
            return DismissedProjectionSyncReport(synced=False)

        try:
            report = _sync_projection(index, dismissed, added=added, force=force)
            if not run_active_tier_maintenance:
                return report
            return _run_active_tier_maintenance(index, report)
        except _CorruptArtifactIndexError:
            return _heal_corrupt_index_and_resync(index, dismissed)


def read_agent_artifact_index_schema_status(
    *,
    index_path: Path | str | None = None,
) -> _ArtifactIndexSchemaStatus:
    """Read stored schema metadata without migrating or rebuilding the index."""

    with agent_artifact_index_operation_lock():
        index = (
            Path(index_path).expanduser()
            if index_path is not None
            else default_agent_artifact_index_path()
        )
        return _read_agent_artifact_index_schema_status(index)


def refresh_agent_artifact_index_if_schema_stale(
    *,
    index_path: Path | str | None = None,
    projects_root: Path | str | None = None,
) -> _ArtifactIndexSchemaRefreshReport:
    """Rebuild the index once when stored schema metadata is older.

    The Rust index open path mutates ``meta.schema_version`` as part of normal
    DDL migration, so this reads the value directly with sqlite3 before any
    Rust query/status call can mask an old ``record_json`` projection.
    """
    with agent_artifact_index_operation_lock():
        index = (
            Path(index_path).expanduser()
            if index_path is not None
            else default_agent_artifact_index_path()
        )
        status = _read_agent_artifact_index_schema_status(index)
        if not status.checked:
            return _ArtifactIndexSchemaRefreshReport(checked=False)
        stored_version = status.stored_schema_version
        if not status.stale:
            return _ArtifactIndexSchemaRefreshReport(
                checked=True,
                stored_schema_version=stored_version,
            )

        root = (
            Path(projects_root).expanduser()
            if projects_root is not None
            else _default_projects_root()
        )
        try:
            update = rebuild_agent_artifact_index(index, root, _LIFECYCLE_SCAN_OPTIONS)
        except _INDEX_ERRORS:
            log.debug("agent artifact index stale-schema rebuild failed", exc_info=True)
            return _ArtifactIndexSchemaRefreshReport(
                checked=True,
                stored_schema_version=stored_version,
            )
        return _ArtifactIndexSchemaRefreshReport(
            checked=True,
            refreshed=True,
            stored_schema_version=stored_version,
            rows_indexed=update.rows_indexed,
        )


def _read_agent_artifact_index_schema_status(
    index: Path,
) -> _ArtifactIndexSchemaStatus:
    """Return schema status for *index* without invoking Rust migrations."""

    if not index.is_file():
        return _ArtifactIndexSchemaStatus(checked=False)
    stored_version = _read_stored_index_schema_version(index)
    if stored_version is None:
        return _ArtifactIndexSchemaStatus(checked=False)
    return _ArtifactIndexSchemaStatus(
        checked=True,
        stale=stored_version < AGENT_ARTIFACT_INDEX_SCHEMA_VERSION,
        stored_schema_version=stored_version,
    )


def _read_stored_index_schema_version(index: Path) -> int | None:
    """Read stored schema metadata without invoking Rust index migration."""
    try:
        with sqlite3.connect(f"{index.resolve().as_uri()}?mode=ro", uri=True) as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?",
                (_INDEX_SCHEMA_META_KEY,),
            ).fetchone()
    except sqlite3.OperationalError as error:
        message = str(error).lower()
        if "no such table" in message:
            return 0
        log.debug("agent artifact index schema-version read failed", exc_info=True)
        return None
    except sqlite3.Error:
        log.debug("agent artifact index schema-version read failed", exc_info=True)
        return None
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def _sync_projection(
    index: Path,
    dismissed: Iterable[AgentIdentityLike] | None,
    *,
    added: Iterable[AgentIdentityLike] | None,
    force: bool,
) -> DismissedProjectionSyncReport:
    """Run one projection sync pass, raising on index corruption."""
    authoritative = added is not None and dismissed is not None
    dismissed_agents_signature, dismissed_bundle_index_signature = (
        _current_projection_source_metadata()
    )
    if (
        not authoritative
        and not force
        and _projection_metadata_matches(
            index,
            dismissed_agents_signature,
            dismissed_bundle_index_signature,
        )
    ):
        return DismissedProjectionSyncReport(synced=True, changed=False)

    if authoritative:
        assert dismissed is not None
        projection = _projection_inputs_from_dismissed_only(
            dismissed,
            dismissed_agents_signature,
            dismissed_bundle_index_signature,
        )
    else:
        projection = build_dismissed_agent_projection_inputs(dismissed)
    try:
        replace_agent_artifact_index_dismissed_agents(index, projection.identities)
        _write_projection_metadata(index, projection)
    except _INDEX_ERRORS as error:
        if _is_corruption_error(error):
            raise _CorruptArtifactIndexError from error
        log.debug("agent artifact index dismissed sync failed", exc_info=True)
        return DismissedProjectionSyncReport(synced=False)
    return DismissedProjectionSyncReport(synced=True, changed=True)


def _heal_corrupt_index_and_resync(
    index: Path,
    dismissed: Iterable[AgentIdentityLike] | None,
) -> DismissedProjectionSyncReport:
    """Quarantine a corrupt artifact index, rebuild it, and force a resync."""
    quarantined = _quarantine_corrupt_index(index)
    if quarantined is None:
        # Another process won the quarantine race (or the rename failed);
        # a missing index is skipped harmlessly, exactly like today.
        return DismissedProjectionSyncReport(synced=False)
    log.warning(
        "agent artifact index corrupt; quarantined to %s and rebuilding",
        quarantined,
    )
    try:
        rebuild_agent_artifact_index(index, _default_projects_root())
        report = _sync_projection(index, dismissed, added=None, force=True)
        report = _run_active_tier_maintenance(index, report)
    except (_CorruptArtifactIndexError, *_INDEX_ERRORS):
        log.exception("agent artifact index rebuild after quarantine failed")
        return DismissedProjectionSyncReport(
            synced=False, healed=True, quarantined_path=quarantined
        )
    return DismissedProjectionSyncReport(
        synced=report.synced,
        changed=report.changed,
        healed=True,
        quarantined_path=quarantined,
        terminalized_active_rows=report.terminalized_active_rows,
    )


def _run_active_tier_maintenance(
    index: Path,
    report: DismissedProjectionSyncReport,
) -> DismissedProjectionSyncReport:
    """Drain stale no-marker rows from the active tier after startup sync."""
    try:
        update = terminalize_stale_active_agent_artifact_index_rows(
            index,
            _default_projects_root(),
            stale_after_seconds=_STALE_ACTIVE_TERMINALIZE_AFTER_SECONDS,
            max_rows=_STALE_ACTIVE_TERMINALIZE_MAX_ROWS,
            options=_LIFECYCLE_SCAN_OPTIONS,
        )
    except _INDEX_ERRORS as error:
        if _is_corruption_error(error):
            raise _CorruptArtifactIndexError from error
        log.debug("agent artifact index active-tier maintenance failed", exc_info=True)
        return report
    terminalized = update.rows_indexed
    if terminalized <= 0:
        return report
    return DismissedProjectionSyncReport(
        synced=report.synced,
        changed=True,
        healed=report.healed,
        quarantined_path=report.quarantined_path,
        terminalized_active_rows=terminalized,
    )


def _quarantine_corrupt_index(index: Path) -> Path | None:
    """Atomically move a corrupt index aside; first renamer wins.

    The atomic rename doubles as the cross-process heal lock: a
    concurrent healer that loses the race sees a missing index and skips.
    At most one quarantine copy is kept. WAL sidecars are renamed next to
    the quarantined database instead of unlinked so live mappings are not
    invalidated inside the current process.
    """
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    quarantined = index.with_name(f"{index.name}.corrupt-{timestamp}")
    try:
        index.rename(quarantined)
    except OSError:
        log.debug("agent artifact index quarantine rename failed", exc_info=True)
        return None
    for sidecar_suffix in ("-wal", "-shm"):
        sidecar = Path(f"{index}{sidecar_suffix}")
        quarantined_sidecar = Path(f"{quarantined}{sidecar_suffix}")
        try:
            sidecar.rename(quarantined_sidecar)
        except FileNotFoundError:
            continue
        except OSError:
            log.debug("agent artifact index sidecar quarantine failed", exc_info=True)
    for stale in index.parent.glob(f"{index.name}.corrupt-*"):
        if stale == quarantined or stale.name.startswith(f"{quarantined.name}-"):
            continue
        try:
            stale.unlink()
        except OSError:
            log.debug("stale quarantine copy cleanup failed", exc_info=True)
    return quarantined


def _projection_inputs_from_dismissed_only(
    dismissed: Iterable[AgentIdentityLike],
    dismissed_agents_signature: DismissedAgentsSignature,
    dismissed_bundle_index_signature: DismissedBundleIndexSignature,
) -> _DismissedProjectionInputs:
    """Build projection inputs from an authoritative caller-supplied set.

    Skips the on-disk bundle scan that ``build_dismissed_agent_projection_inputs``
    performs, paying only the cost of converting the caller's identities.
    """
    identities = {_identity_to_wire(identity) for identity in dismissed}
    return _DismissedProjectionInputs(
        identities=sorted(identities),
        dismissed_agents_signature=dismissed_agents_signature,
        dismissed_bundle_index_signature=dismissed_bundle_index_signature,
        skipped_bundle_rows=0,
    )


def build_dismissed_agent_projection_inputs(
    dismissed: Iterable[AgentIdentityLike] | None = None,
) -> _DismissedProjectionInputs:
    """Build artifact-index dismissed projection rows from state and bundles."""

    from sase.ace.dismissed_agents import (
        dismissed_agents_file_signature,
        dismissed_bundle_index_signature,
        load_dismissed_agents,
        load_dismissed_bundle_identities,
        rebuild_dismissed_bundle_index,
        verify_dismissed_bundle_index,
    )

    dismissed_identities = (
        set(dismissed) if dismissed is not None else load_dismissed_agents()
    )

    skipped_bundle_rows = 0
    try:
        bundle_report = verify_dismissed_bundle_index()
        if not bool(bundle_report.get("ok", False)):
            _, skipped_bundle_rows = rebuild_dismissed_bundle_index()
    except (OSError, RuntimeError, ValueError):
        log.debug("dismissed bundle index verification failed", exc_info=True)

    identities = {_identity_to_wire(identity) for identity in dismissed_identities}
    for agent_type, cl_name, raw_suffix in load_dismissed_bundle_identities():
        identities.add(
            AgentCleanupIdentityWire(
                agent_type=agent_type,
                cl_name=cl_name,
                raw_suffix=raw_suffix,
            )
        )

    return _DismissedProjectionInputs(
        identities=sorted(identities),
        dismissed_agents_signature=dismissed_agents_file_signature(),
        dismissed_bundle_index_signature=dismissed_bundle_index_signature(),
        skipped_bundle_rows=skipped_bundle_rows,
    )


def delete_agent_artifact_index_artifacts(
    artifact_dirs: Iterable[Path | str | None],
    *,
    index_path: Path | str | None = None,
) -> int:
    """Best-effort delete of artifact rows from the SQLite index."""
    with agent_artifact_index_operation_lock():
        index = (
            Path(index_path).expanduser()
            if index_path is not None
            else default_agent_artifact_index_path()
        )
        if not index.is_file():
            return 0

        deleted = 0
        for artifact_dir in artifact_dirs:
            if artifact_dir is None:
                continue
            try:
                update = delete_agent_artifact_index_row(
                    index, Path(artifact_dir).expanduser()
                )
            except _INDEX_ERRORS:
                log.debug(
                    "agent artifact index row delete failed: %s",
                    artifact_dir,
                    exc_info=True,
                )
                continue
            deleted += update.rows_deleted
        return deleted


def delete_agent_artifact_index_artifacts_bounded(
    artifact_dirs: Iterable[Path | str | None],
    *,
    index_path: Path | str | None = None,
    timeout_seconds: float,
) -> bool:
    """Best-effort delete that reports contention instead of waiting.

    Returns ``True`` only when every requested row was handled (including an
    already-absent index). A process-lock miss, SQLite busy timeout, or stale
    binding returns ``False`` so self-healing callers retry on their next pass.
    """
    index = (
        Path(index_path).expanduser()
        if index_path is not None
        else default_agent_artifact_index_path()
    )
    if not index.is_file():
        return True

    for artifact_dir in artifact_dirs:
        if artifact_dir is None:
            continue
        try:
            update = delete_agent_artifact_index_row_bounded(
                index,
                Path(artifact_dir).expanduser(),
                lock_timeout_seconds=timeout_seconds,
                busy_timeout_seconds=timeout_seconds,
            )
        except _INDEX_ERRORS:
            log.debug(
                "bounded agent artifact index row delete deferred: %s",
                artifact_dir,
                exc_info=True,
            )
            return False
        if update is None:
            return False
    return True


def upsert_agent_artifact_index_artifacts(
    artifact_dirs: Iterable[Path | str | None],
    *,
    index_path: Path | str | None = None,
) -> int:
    """Best-effort upsert of restored or changed artifact rows."""
    with agent_artifact_index_operation_lock():
        index = (
            Path(index_path).expanduser()
            if index_path is not None
            else default_agent_artifact_index_path()
        )
        indexed = 0
        seen: set[Path] = set()
        for artifact_dir in artifact_dirs:
            if artifact_dir is None:
                continue
            artifact_path = Path(artifact_dir).expanduser()
            if artifact_path in seen or not artifact_path.is_dir():
                continue
            seen.add(artifact_path)
            try:
                update = upsert_agent_artifact_index_row(
                    index,
                    _projects_root_for_artifact_dir(artifact_path),
                    artifact_path,
                    _LIFECYCLE_SCAN_OPTIONS,
                )
            except _INDEX_ERRORS:
                log.debug(
                    "agent artifact index row upsert failed: %s",
                    artifact_path,
                    exc_info=True,
                )
                continue
            indexed += update.rows_indexed
        return indexed


def update_agent_artifact_index_for_marker_mutation(
    artifact_dir: Path | str | None,
    *,
    index_path: Path | str | None = None,
) -> bool:
    """Best-effort index refresh after an agent marker file changes."""
    return (
        upsert_agent_artifact_index_artifacts([artifact_dir], index_path=index_path) > 0
    )


def _identity_to_wire(identity: AgentIdentityLike) -> AgentCleanupIdentityWire:
    agent_type, cl_name, raw_suffix = identity
    return AgentCleanupIdentityWire(
        agent_type=str(getattr(agent_type, "value", agent_type)),
        cl_name=str(cl_name),
        raw_suffix=None if raw_suffix is None else str(raw_suffix),
    )


def _current_projection_source_metadata() -> tuple[
    DismissedAgentsSignature,
    DismissedBundleIndexSignature,
]:
    """Return cheap source signatures for deciding whether projection changed."""

    from sase.ace.dismissed_agents import (
        dismissed_agents_file_signature,
        dismissed_bundle_index_signature,
        rebuild_dismissed_bundle_index,
    )

    bundle_signature = dismissed_bundle_index_signature()
    if bundle_signature is None:
        try:
            rebuild_dismissed_bundle_index()
        except (OSError, RuntimeError, ValueError):
            log.debug("dismissed bundle index rebuild failed", exc_info=True)
        bundle_signature = dismissed_bundle_index_signature()

    return dismissed_agents_file_signature(), bundle_signature


def _projection_metadata_matches(
    index_path: Path,
    dismissed_agents_signature: DismissedAgentsSignature,
    dismissed_bundle_index_signature: DismissedBundleIndexSignature,
) -> bool:
    metadata = _read_projection_metadata(index_path)
    if metadata is None:
        return False
    return (
        metadata.get("version") == _DISMISSED_PROJECTION_META_VERSION
        and metadata.get("dismissed_agents_signature")
        == _json_signature(dismissed_agents_signature)
        and metadata.get("dismissed_bundle_index_signature")
        == _json_signature(dismissed_bundle_index_signature)
    )


def _read_projection_metadata(index_path: Path) -> dict[str, object] | None:
    try:
        raw = read_agent_artifact_index_meta(index_path, _DISMISSED_PROJECTION_META_KEY)
    except _INDEX_ERRORS as error:
        # Don't conflate corruption with "no metadata": a missing-table or
        # transient lock error just misses the fast path, but a malformed
        # database must surface so the sync entry point can heal it.
        if _is_corruption_error(error):
            raise _CorruptArtifactIndexError from error
        return None
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _write_projection_metadata(
    index_path: Path,
    projection: _DismissedProjectionInputs,
) -> None:
    payload = {
        "version": _DISMISSED_PROJECTION_META_VERSION,
        "dismissed_agents_signature": _json_signature(
            projection.dismissed_agents_signature
        ),
        "dismissed_bundle_index_signature": _json_signature(
            projection.dismissed_bundle_index_signature
        ),
        "projected_identity_count": len(projection.identities),
        "synced_at": datetime.now(UTC).isoformat(),
    }
    write_agent_artifact_index_meta(
        index_path,
        _DISMISSED_PROJECTION_META_KEY,
        json.dumps(payload, sort_keys=True),
    )


def _json_signature(signature: tuple[int, ...] | None) -> list[int] | None:
    return list(signature) if signature is not None else None


__all__ = [
    "DismissedProjectionSyncReport",
    "build_dismissed_agent_projection_inputs",
    "delete_agent_artifact_index_artifacts",
    "delete_agent_artifact_index_artifacts_bounded",
    "read_agent_artifact_index_schema_status",
    "refresh_agent_artifact_index_if_schema_stale",
    "sync_dismissed_agent_artifact_index",
    "sync_dismissed_agent_artifact_index_report",
    "update_agent_artifact_index_for_marker_mutation",
    "upsert_agent_artifact_index_artifacts",
]
