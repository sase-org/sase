"""Artifact link graph relation source for Artifacts panes.

The aggregate JSON is loaded by pane workers into :class:`ArtifactLinksSnapshot`.
This module's edge projection is intentionally I/O-free so relation rendering stays
off the event loop.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from threading import RLock
from typing import Any

from sase.ace.tui._artifact_link_contract import ARTIFACT_LINK_SOURCE
from sase.ace.tui._artifact_tab_model import ArtifactsPaneContract, PaneRelationDecl
from sase.core.agent_identity_facade import current_owner_agent_name_lookup_candidates
from sase.core.artifact_relations import RelationEdge
from sase.core.artifact_entry_target import ArtifactEntryTarget
from sase.core.paths import sase_projects_dir
from sase.project_display_names import load_project_ref_display_snapshot
from sase.sdd.artifact_link_store import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    artifact_link_aggregate_path,
)


@dataclass(frozen=True, slots=True)
class ArtifactLinksSnapshot:
    """Already-loaded artifact link aggregate rows for one pane snapshot."""

    rows: tuple[Mapping[str, Any], ...] = ()
    source_key: tuple[object, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _KnownTargetIndex:
    """Index the target fields artifact-link ref resolution matches."""

    targets: frozenset[ArtifactEntryTarget]
    by_file_first_part: Mapping[str, ArtifactEntryTarget]
    by_pane_last_part: Mapping[tuple[str, str], ArtifactEntryTarget]
    by_stitch_repo_sha_prefix: Mapping[tuple[str, str], ArtifactEntryTarget]
    agent_targets: tuple[ArtifactEntryTarget, ...]

    @classmethod
    def build(cls, known_targets: Iterable[ArtifactEntryTarget]) -> _KnownTargetIndex:
        targets = frozenset(known_targets)
        by_file_first_part: dict[str, ArtifactEntryTarget] = {}
        by_pane_last_part: dict[tuple[str, str], ArtifactEntryTarget] = {}
        by_stitch_repo_sha_prefix: dict[tuple[str, str], ArtifactEntryTarget] = {}
        agent_targets: list[ArtifactEntryTarget] = []

        for target in targets:
            parts = target.parts
            if not parts:
                continue
            if target.pane_id == "files":
                by_file_first_part.setdefault(parts[0], target)
            elif target.pane_id == "stitches" and len(parts) >= 2:
                repo, sha = parts[0], parts[1]
                for end in range(0, len(sha) + 1):
                    by_stitch_repo_sha_prefix.setdefault((repo, sha[:end]), target)
            elif target.pane_id == "agents":
                agent_targets.append(target)
            by_pane_last_part.setdefault((target.pane_id, parts[-1]), target)

        return cls(
            targets=targets,
            by_file_first_part=by_file_first_part,
            by_pane_last_part=by_pane_last_part,
            by_stitch_repo_sha_prefix=by_stitch_repo_sha_prefix,
            agent_targets=tuple(agent_targets),
        )


_CACHE_LOCK = RLock()
_CACHE: dict[tuple[tuple[str, object, object], ...], ArtifactLinksSnapshot] = {}


def empty_artifact_links_snapshot() -> ArtifactLinksSnapshot:
    """Return an empty snapshot for tests and fallback data models."""

    return ArtifactLinksSnapshot()


def load_artifact_links_snapshot(project: str | None) -> ArtifactLinksSnapshot:
    """Load project aggregate rows on a worker thread.

    ``project=None`` means every known project aggregate. Missing aggregates are
    treated as empty; malformed aggregates are skipped and recorded in ``errors``.
    """

    projects = _project_keys(project)
    if not projects:
        return ArtifactLinksSnapshot()
    signature = tuple(_aggregate_signature(project_key) for project_key in projects)
    with _CACHE_LOCK:
        cached = _CACHE.get(signature)
        if cached is not None:
            return cached
    rows: list[Mapping[str, Any]] = []
    errors: list[str] = []
    for project_key in projects:
        path = artifact_link_aggregate_path(project_key)
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("schema_version") != ARTIFACT_LINK_ROW_SCHEMA_VERSION:
                raise RuntimeError("unsupported artifact link aggregate schema")
            raw_rows = payload.get("rows")
            if not isinstance(raw_rows, list):
                raise RuntimeError("artifact link aggregate rows must be a list")
        except Exception as exc:  # noqa: BLE001 - relation rail degrades to no rows
            errors.append(f"{project_key}: {exc}")
            continue
        for row in raw_rows:
            if isinstance(row, Mapping):
                copied = dict(row)
                copied.setdefault("_project", project_key)
                rows.append(copied)
    snapshot = ArtifactLinksSnapshot(
        rows=tuple(rows),
        source_key=signature,
        errors=tuple(errors),
    )
    with _CACHE_LOCK:
        _CACHE[signature] = snapshot
    return snapshot


def artifact_link_edges(
    snapshot: ArtifactLinksSnapshot | None,
    *,
    contract: ArtifactsPaneContract,
    known_targets: Iterable[ArtifactEntryTarget],
    project_hint: str | None = None,
) -> tuple[RelationEdge, ...]:
    """Return link-graph edges touching the current pane's known targets."""

    if snapshot is None:
        return ()
    declarations = {item.name: item for item in contract.relations}
    known_index = _KnownTargetIndex.build(known_targets)
    known = known_index.targets
    seen: set[tuple[str, ArtifactEntryTarget, ArtifactEntryTarget]] = set()
    edges: list[RelationEdge] = []
    for row in snapshot.rows:
        source_ref = str(row.get("source_ref") or "").strip()
        target_ref = str(row.get("target_ref") or "").strip()
        relation = str(row.get("relation") or "").strip()
        decl = declarations.get(relation)
        if not source_ref or not target_ref or decl is None:
            continue
        project = str(row.get("_project") or project_hint or "").strip() or None
        source = _target_for_ref(source_ref, known_index, project_hint=project)
        target = _target_for_ref(target_ref, known_index, project_hint=project)
        if source is None or target is None:
            continue
        if source not in known and target not in known:
            continue
        key = _edge_key(row, source, target)
        if key in seen:
            continue
        seen.add(key)
        edges.append(_emit_link_edge(decl, row, source, target))
    return tuple(edges)


def _emit_link_edge(
    decl: PaneRelationDecl,
    row: Mapping[str, Any],
    source: ArtifactEntryTarget,
    target: ArtifactEntryTarget,
) -> RelationEdge:
    return RelationEdge(
        kind=decl.kind,
        relation=decl.name,
        label=decl.label,
        source=source,
        target=target,
        description=str(row.get("description") or "").strip(),
        origin=str(row.get("origin") or "").strip(),
        uses=_uses_count(row.get("uses")),
    )


def _uses_count(value: Any) -> int:
    try:
        uses = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, uses)


def _edge_key(
    row: Mapping[str, Any],
    source: ArtifactEntryTarget,
    target: ArtifactEntryTarget,
) -> tuple[str, ArtifactEntryTarget, ArtifactEntryTarget]:
    relation = str(row.get("relation") or "")
    if relation == "related":
        left, right = sorted((source, target), key=lambda item: item.to_token())
        return (relation, left, right)
    return (relation, source, target)


def parse_link_ref(value: str) -> tuple[str, str] | None:
    """Split a link-graph ref string into its kind and payload.

    Shared by every direction of ref/target conversion so they agree on the
    same ``@``/``#``-stripping and ``commit`` -> ``stitch`` aliasing.
    """

    ref = value.removeprefix("@").split("#", 1)[0].strip()
    kind, sep, payload = ref.partition(":")
    if not sep or not payload:
        return None
    kind = "stitch" if kind == "commit" else kind
    return kind, payload


def target_for_ref_kind(
    kind: str,
    payload: str,
    *,
    project_hint: str | None,
) -> ArtifactEntryTarget | None:
    """Synthesize a target for a ref's kind/payload with no known-target lookup.

    This is the half of :func:`_target_for_ref` that never needs a pane's
    rendered rows: a pure kind-dispatch, safe to call from an app-level index
    build with no ``known_targets`` scope at all.
    """

    if kind == "stitch":
        repo, at, sha = payload.partition("@")
        if not at or not repo or not sha:
            return None
        return ArtifactEntryTarget("stitches", (repo, sha))
    if kind == "patch":
        return ArtifactEntryTarget("patches", (project_hint or "", payload))
    if kind == "bead":
        return ArtifactEntryTarget("beads", (project_hint or "", "task", payload))
    if kind == "file":
        return ArtifactEntryTarget("files", (payload,))
    if kind == "agent":
        return ArtifactEntryTarget("agents", (payload,))
    if kind in {"bug", "chat", "chop"}:
        # ``chop`` is a virtual link-graph subject kind (bead:sase-ug.5): it
        # has no owning Artifacts pane and never joins the ref-kind catalog.
        return None
    return ArtifactEntryTarget(f"ref:{kind}", (project_hint or "", "archive", payload))


def _target_for_ref(
    value: str,
    known_targets: _KnownTargetIndex,
    *,
    project_hint: str | None,
) -> ArtifactEntryTarget | None:
    parsed = parse_link_ref(value)
    if parsed is None:
        return None
    kind, payload = parsed
    exact = _known_target_for_ref(kind, payload, known_targets)
    if exact is not None:
        return exact
    return target_for_ref_kind(kind, payload, project_hint=project_hint)


def _known_target_for_ref(
    kind: str,
    payload: str,
    known_targets: frozenset[ArtifactEntryTarget] | _KnownTargetIndex,
) -> ArtifactEntryTarget | None:
    index = (
        known_targets
        if isinstance(known_targets, _KnownTargetIndex)
        else _KnownTargetIndex.build(known_targets)
    )
    if kind == "file":
        exact_file = ArtifactEntryTarget("files", (payload,))
        if exact_file in index.targets:
            return exact_file
        return index.by_file_first_part.get(payload)
    if kind == "agent":
        exact_agent = ArtifactEntryTarget("agents", (payload,))
        if exact_agent in index.targets:
            return exact_agent
        candidates = set(current_owner_agent_name_lookup_candidates(payload))
        for target in index.agent_targets:
            if target.parts and target.parts[-1] in candidates:
                return target
        return None
    if kind == "stitch":
        repo, at, sha = payload.partition("@")
        if at:
            return index.by_stitch_repo_sha_prefix.get((repo, sha))
        return None
    if kind == "patch":
        return index.by_pane_last_part.get(("patches", payload))
    if kind == "bead":
        return index.by_pane_last_part.get(("beads", payload))
    return index.by_pane_last_part.get((f"ref:{kind}", payload))
    return None


def _project_keys(project: str | None) -> tuple[str, ...]:
    display = load_project_ref_display_snapshot()
    if project is not None:
        return (display.project_key_for_ref(project) or project,)
    keys = tuple(display.display_snapshot.labels_by_key)
    if keys:
        return keys
    root = sase_projects_dir()
    try:
        return tuple(sorted(path.name for path in root.iterdir() if path.is_dir()))
    except OSError:
        return ()


def _aggregate_signature(project_key: str) -> tuple[str, object, object]:
    path = artifact_link_aggregate_path(project_key)
    try:
        stat = path.stat()
    except OSError:
        return (project_key, None, None)
    return (project_key, stat.st_mtime_ns, stat.st_size)


__all__ = [
    "ARTIFACT_LINK_SOURCE",
    "ArtifactLinksSnapshot",
    "artifact_link_edges",
    "empty_artifact_links_snapshot",
    "load_artifact_links_snapshot",
    "parse_link_ref",
    "target_for_ref_kind",
]
