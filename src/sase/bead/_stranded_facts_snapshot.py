"""Snapshot reuse and batched session-index reads for stranded-work facts."""

from __future__ import annotations

from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

from sase.bead.model import Issue
from sase.core.agent_artifact_index_lock import DEFAULT_READ_LOCK_TIMEOUT_SECONDS
from sase.core.agent_scan_facade import (
    default_agent_artifact_index_path,
)
from sase.core.agent_scan_index_queries import AgentArtifactIndexReader
from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactRecordWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)
from sase.core.bead_read_facade import store_fingerprint, stranded_snapshot
from sase.core.paths import sase_projects_dir


@lru_cache(maxsize=8)
def _session_index_reader(
    _project: str, _keys: tuple[str, ...]
) -> AgentArtifactIndexReader:
    # Own a bounded set of batches: projects and >100-session chunks interleave.
    # Rust still validates the complete query, paths, options and markers on every
    # read. Session/name pushdowns never certify a payload generation, so these
    # readers isolate consumers instead of skipping hydration. Eviction only
    # drops that isolation; reports always build independent fact dicts.
    return AgentArtifactIndexReader()


class _StrandedSnapshotReader:
    """Retain one decoded candidate/context projection per store identity.

    Rust ``bead_store_fingerprint`` certifies whether the bead store still
    matches the identity that produced the retained rows. Platform liveness,
    marker, handoff, and finalizer observations are never cached here.
    A missing or failed fingerprint cannot certify reuse.
    """

    def __init__(self) -> None:
        self._identity: tuple[str, str, tuple[str, ...] | None] | None = None
        self._candidates: list[Issue] = []
        self._context: list[Issue] = []

    def read(
        self,
        beads_dir: Path,
        bead_ids: Iterable[str] | None,
    ) -> tuple[list[Issue], list[Issue], bool]:
        identity = _stable_snapshot_identity(beads_dir, bead_ids)
        if (
            identity is not None
            and identity == self._identity
            and self._identity is not None
        ):
            return self._candidates, self._context, False
        candidates, context = stranded_snapshot(beads_dir, bead_ids=bead_ids)
        if identity is None:
            self._identity = None
            self._candidates = []
            self._context = []
            return candidates, context, True
        self._identity = identity
        self._candidates = candidates
        self._context = context
        return candidates, context, True


@lru_cache(maxsize=8)
def _snapshot_reader(
    _project: str, _scope: tuple[str, ...] | None
) -> _StrandedSnapshotReader:
    return _StrandedSnapshotReader()


def _scope_key(bead_ids: Iterable[str] | None) -> tuple[str, ...] | None:
    if bead_ids is None:
        return None
    return tuple(sorted({str(item) for item in bead_ids if item}))


def _stable_snapshot_identity(
    beads_dir: Path, bead_ids: Iterable[str] | None
) -> tuple[str, str, tuple[str, ...] | None] | None:
    """Return the Rust-certified store identity, or ``None`` when uncertified."""
    fingerprint = store_fingerprint(beads_dir)
    if fingerprint is None:
        return None
    try:
        path = str(Path(beads_dir).expanduser().resolve())
    except OSError:
        path = str(beads_dir)
    return (path, fingerprint.token, _scope_key(bead_ids))


def read_stranded_snapshot(
    project: str,
    beads_dir: Path,
    bead_ids: Iterable[str] | None,
) -> tuple[list[Issue], list[Issue], bool]:
    """Read candidate and context rows, reusing a certified store identity."""
    return _snapshot_reader(project, _scope_key(bead_ids)).read(beads_dir, bead_ids)


def _query_session_index(
    project: str,
    keys: tuple[str, ...],
    query: AgentArtifactIndexQueryWire,
    options: AgentArtifactScanOptionsWire,
) -> AgentArtifactScanWire | None:
    return _session_index_reader(project, keys).query(
        default_agent_artifact_index_path(),
        sase_projects_dir(),
        query,
        options,
        lock_timeout_seconds=DEFAULT_READ_LOCK_TIMEOUT_SECONDS,
    )


_BATCH_CHUNK_SIZE = 100

_QueryCache = dict[str, tuple[list[AgentArtifactRecordWire], bool]]


def session_record_cache(project: str, assignees: set[str]) -> _QueryCache:
    """Load artifact-index records for *assignees*, batched by session key."""
    keys = sorted(assignees)
    if not keys:
        return {}
    if not default_agent_artifact_index_path().is_file():
        return {key: ([], False) for key in keys}
    cache: _QueryCache = {}
    for start in range(0, len(keys), _BATCH_CHUNK_SIZE):
        chunk = keys[start : start + _BATCH_CHUNK_SIZE]
        try:
            records = _query_session_records_chunk(project, chunk)
        except (OSError, RuntimeError, ValueError, ImportError, AttributeError):
            for key in chunk:
                cache[key] = ([], False)
            continue
        grouped = _group_records_by_assignee(records, chunk)
        for key in chunk:
            cache[key] = (grouped[key], True)
    return cache


def _query_session_records_chunk(
    project: str, keys: list[str]
) -> list[AgentArtifactRecordWire]:
    """Run one batched session query for *keys*; return the raw records."""
    query = AgentArtifactIndexQueryWire(
        include_active=True,
        include_recent_completed=True,
        include_full_history=True,
        active_limit=None,
        recent_completed_limit=None,
        include_hidden=True,
        # A session's root member keeps agent_session null until it gets a
        # successor, so also match its agent_name; the grouping recheck
        # below keeps the match exact.
        candidate_filter={
            "kind": "any",
            "filters": [
                {
                    "kind": "equals",
                    "field": field,
                    "value": key,
                }
                for key in keys
                for field in ("agent_session", "agent_name")
            ],
        },
    )
    options = AgentArtifactScanOptionsWire(
        only_workflow_dirs=("ace-run",),
        include_prompt_step_markers=False,
        include_raw_prompt_snippets=False,
        only_projects=(project,),
    )
    scan = _query_session_index(project, tuple(keys), query, options)
    if scan is None:
        raise RuntimeError("artifact index operation lock is busy")
    return list(scan.records)


def _group_records_by_assignee(
    records: list[AgentArtifactRecordWire], keys: list[str]
) -> dict[str, list[AgentArtifactRecordWire]]:
    """Group index records per requested key with the exact recheck.

    A record can match more than one key (its session is one key and its
    name another), so it is given to every key it matches. Per-key
    ``artifact_dir`` dedupe and index-returned order are preserved.
    """
    grouped: dict[str, list[AgentArtifactRecordWire]] = {key: [] for key in keys}
    seen_dirs: dict[str, set[str]] = {key: set() for key in keys}
    for record in records:
        for key in keys:
            if record.artifact_dir in seen_dirs[key]:
                continue
            if _record_matches_assignee(record, key):
                seen_dirs[key].add(record.artifact_dir)
                grouped[key].append(record)
    return grouped


def _record_matches_assignee(record: AgentArtifactRecordWire, assignee: str) -> bool:
    meta = record.agent_meta
    if meta is None:
        return False
    session = (meta.agent_session or "").strip()
    name = (meta.name or "").strip()
    return session == assignee or name == assignee
