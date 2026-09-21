"""Python facade for the Rust-backed agent/bead touch index.

The reduction itself lives in ``sase-core`` (``bead/touch_index.rs``): it
reduces per-bead event streams into actor-keyed touch rows, keeps a
signature-cached index at ``~/.sase/projects/<key>/agent_bead_touches.json``,
and answers read-only queries from that file. This module owns nothing the
Rust side already owns: index-path resolution from :func:`sase_projects_dir`,
thin binding wrappers with wire-to-dataclass conversion, the agent-identity
matching from the epic plan (so the CLI, the panel, and any later caller
share one matcher), the durable-behind-views merge order for the
machine-local view log, and a best-effort refresh entry point for the three
off-hot-path refresh sites (post-mutation, post-sync, lumberjack tick).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir
from sase.core.rust import require_rust_binding

_logger = logging.getLogger(__name__)

TOUCH_INDEX_FILENAME = "agent_bead_touches.json"


@dataclass(frozen=True)
class BeadTouch:
    """One ``(actor, bead)`` pair with aggregated verbs."""

    actor: str
    bead_id: str
    title: str = ""
    issue_type: str = ""
    status: str = ""
    verbs: dict[str, int] = field(default_factory=dict)
    first_at: str = ""
    last_at: str = ""


@dataclass(frozen=True)
class BeadTouchQuery:
    """Read-only answer from the touch index file."""

    schema_version: int
    generation: str
    touches: tuple[BeadTouch, ...] = ()


@dataclass(frozen=True)
class BeadTouchRefresh:
    """Outcome of one incremental touch-index refresh."""

    schema_version: int
    generation: str
    full_rebuild: bool
    wrote: bool
    stream_count: int
    reduced_streams: tuple[str, ...] = ()
    reused_streams: int = 0
    removed_streams: tuple[str, ...] = ()
    touch_count: int = 0


@dataclass(frozen=True)
class BeadTouchIndexStatus:
    """Stat-only staleness report for the touch index."""

    schema_version: int
    state: str
    index_schema_version: int | None
    generation: str
    indexed_streams: int
    current_streams: int
    changed_streams: tuple[str, ...] = ()
    vanished_streams: tuple[str, ...] = ()


def resolve_touch_index_project(
    *,
    project: str | None = None,
    cwd: Path | None = None,
    beads_dir: Path | None = None,
) -> str | None:
    """Return the projects-dir key owning the touch index, if resolvable.

    An explicit *project* wins (after alias resolution), mirroring
    :func:`sase.artifact_read_log.artifact_read_log_path`. Otherwise the
    project is inferred from *cwd* via the checkout marker / git / workspace
    chain, or from *beads_dir* via the workspace scan; anything unresolvable
    is ``None`` so refresh sites can skip quietly instead of guessing.
    """
    if project:
        try:
            from sase.project_aliases import resolve_project_alias_ref

            return resolve_project_alias_ref(project)
        except Exception:
            return project
    if cwd is not None:
        try:
            from sase.main.init_memory.config import project_memory_name
            from sase.project_aliases import resolve_project_alias_ref

            return resolve_project_alias_ref(project_memory_name(cwd.expanduser()))
        except Exception:
            return None
    if beads_dir is not None:
        try:
            from sase.bead.project_name import infer_project_name_from_cwd

            return infer_project_name_from_cwd(str(beads_dir.expanduser()))
        except Exception:
            return None
    return None


def touch_index_path(project: str | None = None, *, cwd: Path | None = None) -> Path:
    """Return ``~/.sase/projects/<key>/agent_bead_touches.json``."""
    from sase.project_aliases import resolve_project_alias_ref

    if project is not None:
        project_name = resolve_project_alias_ref(project)
    else:
        from sase.main.init_memory.config import project_memory_name

        project_name = resolve_project_alias_ref(
            project_memory_name((cwd or Path.cwd()).expanduser())
        )
    return sase_projects_dir() / project_name / TOUCH_INDEX_FILENAME


def _refresh_touch_index(
    beads_dir: Path | str, index_path: Path | str
) -> BeadTouchRefresh:
    """Bring the index at *index_path* up to date with *beads_dir*.

    Incremental and idempotent: unchanged streams keep their cached rows and
    the file is left untouched when nothing changed. Raises on genuine
    failures; refresh sites that must never break use
    :func:`refresh_touch_index_best_effort` instead.
    """
    binding = require_rust_binding("bead_touch_index_refresh")
    payload: Mapping[str, Any] = binding(str(beads_dir), str(index_path))
    return BeadTouchRefresh(
        schema_version=int(payload.get("schema_version", 0)),
        generation=str(payload.get("generation", "")),
        full_rebuild=bool(payload.get("full_rebuild", False)),
        wrote=bool(payload.get("wrote", False)),
        stream_count=int(payload.get("stream_count", 0)),
        reduced_streams=tuple(
            str(name) for name in payload.get("reduced_streams") or ()
        ),
        reused_streams=int(payload.get("reused_streams", 0)),
        removed_streams=tuple(
            str(name) for name in payload.get("removed_streams") or ()
        ),
        touch_count=int(payload.get("touch_count", 0)),
    )


def refresh_touch_index_best_effort(
    beads_dir: Path | str,
    *,
    project: str | None = None,
    cwd: Path | None = None,
    index_path: Path | str | None = None,
) -> BeadTouchRefresh | None:
    """Refresh the touch index, logging and swallowing every failure.

    Resolves *index_path* from *project*/*cwd* when not given; an
    unresolvable project is a quiet skip, never an error. Callers that only
    hold a store path resolve the project first with
    :func:`resolve_touch_index_project`. Returns the refresh outcome, or
    ``None`` when there was nothing to do or the refresh failed. A failed
    refresh never breaks a bead mutation, a sync, or a job tick; the next
    refresh site converges the store instead.
    """
    try:
        if index_path is not None:
            resolved_index = Path(index_path)
        else:
            resolved_project = resolve_touch_index_project(project=project, cwd=cwd)
            if not resolved_project:
                _logger.debug(
                    "Skipping bead touch-index refresh: no project for %s",
                    beads_dir,
                )
                return None
            resolved_index = (
                sase_projects_dir() / resolved_project / TOUCH_INDEX_FILENAME
            )
        return _refresh_touch_index(beads_dir, resolved_index)
    except Exception as exc:
        _logger.warning("Skipping bead touch-index refresh for %s: %s", beads_dir, exc)
        return None


def query_touch_index(
    index_path: Path | str, actors: list[str] | tuple[str, ...] | None = None
) -> BeadTouchQuery:
    """Return the indexed touches, optionally restricted to *actors*.

    Read-only: loads the index file only, never scans or parses streams. A
    missing, truncated, unparseable, or wrong-schema index is a cache miss
    that returns no rows, never an error. ``actors=None`` returns every
    actor's touches so the facade can apply the legacy bare-local-name match
    itself.
    """
    binding = require_rust_binding("bead_touch_index_query")
    payload: Mapping[str, Any] = binding(
        str(index_path), None if actors is None else list(actors)
    )
    touches = payload.get("touches") or ()
    return BeadTouchQuery(
        schema_version=int(payload.get("schema_version", 0)),
        generation=str(payload.get("generation", "")),
        touches=tuple(
            _touch_from_dict(row) for row in touches if isinstance(row, dict)
        ),
    )


def _touch_from_dict(payload: Mapping[str, Any]) -> BeadTouch:
    verbs_raw = payload.get("verbs")
    verbs: dict[str, int] = {}
    if isinstance(verbs_raw, Mapping):
        for verb, count in verbs_raw.items():
            try:
                total = int(count)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if total > 0:
                verbs[str(verb)] = total
    return BeadTouch(
        actor=str(payload.get("actor", "")),
        bead_id=str(payload.get("bead_id", "")),
        title=str(payload.get("title", "")),
        issue_type=str(payload.get("issue_type", "")),
        status=str(payload.get("status", "")),
        verbs=verbs,
        first_at=str(payload.get("first_at", "")),
        last_at=str(payload.get("last_at", "")),
    )


def touch_index_status(
    beads_dir: Path | str, index_path: Path | str
) -> BeadTouchIndexStatus:
    """Classify the index against the live streams without reducing anything.

    Stat-only and lock-free: compares each stream file's ``(mtime_ns, size)``
    with the signature the index recorded. ``state`` is one of ``missing``,
    ``unreadable``, ``schema_mismatch``, ``stale``, or ``fresh``.
    """
    binding = require_rust_binding("bead_touch_index_status")
    payload: Mapping[str, Any] = binding(str(beads_dir), str(index_path))
    index_schema = payload.get("index_schema_version")
    return BeadTouchIndexStatus(
        schema_version=int(payload.get("schema_version", 0)),
        state=str(payload.get("state", "missing")),
        index_schema_version=(None if index_schema is None else int(index_schema)),
        generation=str(payload.get("generation", "")),
        indexed_streams=int(payload.get("indexed_streams", 0)),
        current_streams=int(payload.get("current_streams", 0)),
        changed_streams=tuple(
            str(name) for name in payload.get("changed_streams") or ()
        ),
        vanished_streams=tuple(
            str(name) for name in payload.get("vanished_streams") or ()
        ),
    )


def touch_matches_agent(
    actor: str,
    *,
    globalized_name: str,
    local_name: str | None = None,
    identity: Any | None = None,
) -> bool:
    """Return whether an index touch *actor* is one agent's work.

    The touch matches when its actor, after trimming, equals the agent's
    globalized name or local ``agent_name``, or when
    :func:`globalize_owned_agent_name` maps the recorded actor onto the
    agent's globalized name (which recovers the legacy bare-local-name rows).
    Matching is exact after those normalizations: no prefix or suffix
    matching, because bead ids and agent names both use dotted suffixes and a
    loose match would cross-attribute. Anything unrecognizable (an email
    address, a name validation rejects) never matches.
    """
    candidate = actor.strip()
    if not candidate:
        return False
    if candidate == globalized_name:
        return True
    if local_name is not None and candidate == local_name:
        return True
    try:
        from sase.core.agent_identity_facade import globalize_owned_agent_name

        if identity is None:
            from sase.core.agent_identity_facade import AgentIdentitySnapshot

            identity = AgentIdentitySnapshot.current()
        return globalize_owned_agent_name(candidate, identity) == globalized_name
    except Exception:
        return False


def touches_for_agent(
    touches: Any,
    *,
    globalized_name: str,
    local_name: str | None = None,
    identity: Any | None = None,
) -> list[BeadTouch]:
    """Filter touch rows down to one agent's work, preserving order."""
    return [
        touch
        for touch in touches
        if touch_matches_agent(
            touch.actor,
            globalized_name=globalized_name,
            local_name=local_name,
            identity=identity,
        )
    ]


def merge_view_touches(
    durable_touches: Any,
    view_touches: Any,
) -> tuple[BeadTouch, ...]:
    """Concatenate durable index rows with synthesized view rows.

    Durable rows stay first so a later per-bead merge keeps the durable
    title and verbs and only gains the weaker ``viewed`` count. View rows
    (from the machine-local ``bead_views.jsonl`` log) never override
    durable facts; a bead with only views still surfaces as a
    ``viewed``-only entry. Both inputs may be any sequence and are never
    mutated.
    """
    return tuple(durable_touches) + tuple(view_touches)


def query_touches_for_agent(
    index_path: Path | str,
    *,
    globalized_name: str,
    local_name: str | None = None,
    identity: Any | None = None,
) -> BeadTouchQuery:
    """Query the index and return one agent's touches, newest first.

    Loads every actor's touches (``actors=None``) so the legacy
    bare-local-name match applies, then filters to the agent. A cache miss
    returns an empty query, never an error.
    """
    query = query_touch_index(index_path)
    return BeadTouchQuery(
        schema_version=query.schema_version,
        generation=query.generation,
        touches=tuple(
            touches_for_agent(
                query.touches,
                globalized_name=globalized_name,
                local_name=local_name,
                identity=identity,
            )
        ),
    )


@dataclass(frozen=True)
class FoldedBeadTouch:
    """One bead folded from every contributing ``(actor, bead)`` row."""

    bead_id: str
    title: str = ""
    issue_type: str = ""
    status: str = ""
    verbs: dict[str, int] = field(default_factory=dict)
    first_at: str = ""
    last_at: str = ""
    actors: tuple[str, ...] = ()


def canonical_bead_touch_id(value: str | None) -> str:
    """Return the per-bead fold key for a touch id or ``bead:`` read ref."""
    text = (value or "").strip()
    if text.startswith("bead:"):
        text = text.removeprefix("bead:").strip()
    return text


def _parse_touch_moment(value: str | None) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


class _FoldBucket:
    """Mutable per-bead accumulator behind :func:`fold_touches_per_bead`."""

    def __init__(self, bead_id: str) -> None:
        self.bead_id = bead_id
        self.title = ""
        self.issue_type = ""
        self.status = ""
        self.verbs: dict[str, int] = {}
        self._moments: list[tuple[datetime, str]] = []
        self._actors: set[str] = set()

    def add(self, touch: BeadTouch) -> None:
        actor = str(getattr(touch, "actor", "") or "").strip()
        if actor:
            self._actors.add(actor)
        title = str(getattr(touch, "title", "") or "").strip()
        if not self.title and title:
            self.title = title
        issue_type = str(getattr(touch, "issue_type", "") or "").strip()
        if not self.issue_type and issue_type:
            self.issue_type = issue_type
        status = str(getattr(touch, "status", "") or "").strip()
        if not self.status and status:
            self.status = status
        verbs = getattr(touch, "verbs", {}) or {}
        for verb, count in verbs.items():
            try:
                total = int(count)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if total > 0:
                self.verbs[str(verb)] = self.verbs.get(str(verb), 0) + total
        for moment_value in (
            str(getattr(touch, "first_at", "") or ""),
            str(getattr(touch, "last_at", "") or ""),
        ):
            moment = _parse_touch_moment(moment_value)
            if moment is not None:
                self._moments.append((moment, moment_value.strip()))

    def build(self) -> FoldedBeadTouch:
        first_at = ""
        last_at = ""
        if self._moments:
            ordered = sorted(self._moments, key=lambda item: item[0])
            first_at = ordered[0][1]
            last_at = ordered[-1][1]
        return FoldedBeadTouch(
            bead_id=self.bead_id,
            title=self.title,
            issue_type=self.issue_type,
            status=self.status,
            verbs=dict(self.verbs),
            first_at=first_at,
            last_at=last_at,
            actors=tuple(sorted(self._actors)),
        )


def fold_touches_per_bead(
    touches: Sequence[BeadTouch],
) -> list[FoldedBeadTouch]:
    """Fold ``(actor, bead)`` rows into one row per bead.

    Pure function over its input so it is testable without a store: verb
    counts sum, ``first_at`` is the earliest moment and ``last_at`` the
    newest across all contributing rows, and the title (plus ``issue_type``
    and ``status``) is the first non-empty value in input order. Callers
    pass durable index rows first so durable facts win over synthesized
    ``viewed`` and ``read`` rows; ``viewed`` never promotes to ``read``.
    Bead ids are compared after :func:`canonical_bead_touch_id` so a
    ``bead:``-prefixed ref and a bare id never split into two rows.
    """
    buckets: dict[str, _FoldBucket] = {}
    order: list[str] = []
    for touch in touches:
        key = canonical_bead_touch_id(getattr(touch, "bead_id", ""))
        if not key:
            continue
        bucket = buckets.get(key)
        if bucket is None:
            display_id = str(getattr(touch, "bead_id", "") or "").strip()
            if display_id.startswith("bead:"):
                display_id = display_id.removeprefix("bead:").strip()
            bucket = buckets[key] = _FoldBucket(display_id or key)
            order.append(key)
        bucket.add(touch)
    return [buckets[key].build() for key in order]


__all__ = [
    "TOUCH_INDEX_FILENAME",
    "BeadTouch",
    "BeadTouchIndexStatus",
    "BeadTouchQuery",
    "BeadTouchRefresh",
    "FoldedBeadTouch",
    "canonical_bead_touch_id",
    "fold_touches_per_bead",
    "merge_view_touches",
    "query_touches_for_agent",
    "query_touch_index",
    "refresh_touch_index_best_effort",
    "resolve_touch_index_project",
    "touch_index_path",
    "touch_index_status",
    "touch_matches_agent",
    "touches_for_agent",
]
