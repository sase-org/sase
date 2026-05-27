"""Best-effort lifecycle maintenance for the agent artifact index."""

from __future__ import annotations

import logging
import json
import sqlite3
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
    delete_agent_artifact_index_row,
    replace_agent_artifact_index_dismissed_agents,
    upsert_agent_artifact_index_row,
)
from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire
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
    sqlite3.Error,
)
_DISMISSED_PROJECTION_META_KEY = "dismissed_projection"
_DISMISSED_PROJECTION_META_VERSION = 1


@dataclass(frozen=True)
class _DismissedProjectionInputs:
    """Dismissed identities plus the source signatures used to build them."""

    identities: list[AgentCleanupIdentityWire]
    dismissed_agents_signature: DismissedAgentsSignature
    dismissed_bundle_index_signature: DismissedBundleIndexSignature
    skipped_bundle_rows: int = 0


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
) -> bool:
    """Best-effort sync of dismissed identities into the SQLite artifact index.

    When ``added`` is provided, the caller asserts that ``dismissed`` is the
    full authoritative set of dismissed identities for this session. The
    expensive bundle-summary scan and bundle-index verify pass are skipped:
    the projection is built directly from ``dismissed`` only. The
    SQLite-side replace is still issued in one transaction so the on-disk
    rows match the in-memory set; ``added`` is a perf hint, not a
    correctness shortcut. On signature drift the full path remains.
    """
    index = (
        Path(index_path).expanduser()
        if index_path is not None
        else default_agent_artifact_index_path()
    )
    if not index.is_file():
        return False

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
        return True

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
    except _INDEX_ERRORS:
        log.debug("agent artifact index dismissed sync failed", exc_info=True)
        return False
    return True


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
        load_dismissed_bundle_summaries,
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
    for summary in load_dismissed_bundle_summaries(limit=None):
        identities.add(_dismissed_summary_identity(summary))

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


def upsert_agent_artifact_index_artifacts(
    artifact_dirs: Iterable[Path | str | None],
    *,
    index_path: Path | str | None = None,
) -> int:
    """Best-effort upsert of restored or changed artifact rows."""
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


def _dismissed_summary_identity(summary: Any) -> AgentCleanupIdentityWire:
    """Convert one dismissed bundle summary into an artifact-index identity."""

    return AgentCleanupIdentityWire(
        agent_type=str(summary.agent_type),
        cl_name=str(summary.cl_name or "unknown"),
        raw_suffix=str(summary.raw_suffix) if summary.raw_suffix else None,
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
        with sqlite3.connect(index_path, timeout=5) as conn:
            row = conn.execute(
                "SELECT value FROM meta WHERE key = ?",
                (_DISMISSED_PROJECTION_META_KEY,),
            ).fetchone()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    try:
        value = json.loads(str(row[0]))
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
    with sqlite3.connect(index_path, timeout=5) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS meta ("
            "key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)",
            (_DISMISSED_PROJECTION_META_KEY, json.dumps(payload, sort_keys=True)),
        )


def _json_signature(signature: tuple[int, ...] | None) -> list[int] | None:
    return list(signature) if signature is not None else None


__all__ = [
    "build_dismissed_agent_projection_inputs",
    "delete_agent_artifact_index_artifacts",
    "sync_dismissed_agent_artifact_index",
    "update_agent_artifact_index_for_marker_mutation",
    "upsert_agent_artifact_index_artifacts",
]
