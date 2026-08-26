"""Shared row, reference, and JSON helpers for typed artifact-link storage."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from functools import cache
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.core.paths import sase_projects_dir
from sase.core.rust import require_rust_binding
from sase.sdd.referenced_by_index import (
    referenced_by_index_relpath,
    referenced_by_index_schema_version,
)

if TYPE_CHECKING:
    from collections.abc import Callable

ARTIFACT_LINK_ROW_SCHEMA_VERSION = 2
ARTIFACT_LINK_AGGREGATE_FILENAME = "artifact-links.json"
NON_SIDECAR_KINDS = frozenset({"agent", "bead", "stitch"})
PLANS_ROLE = "plans"
PLAN_KIND = "plan"
BEAD_KIND = "bead"

# Origins written from a `ReferencedByOutboxItem` drained at commit
# granularity: a repeated drain of the same commit's entry must converge its
# `uses` count rather than re-accumulate it.
_COMMIT_SCOPED_ORIGINS = frozenset({"prompt_ref", "prompt_prose"})

_PROJECTION_RELATIONS = (
    {
        "schema_version": 2,
        "slug": "produced-by",
        "inverse": "produced",
        "directed": True,
        "written_by": "projection",
        "direction_note": (
            "The stitch is the source; the agent that produced it is the target."
        ),
        "positive_example": (
            "stitch:sase@0123456789abcdef0123456789abcdef01234567 "
            "produced-by agent:sase-tj.land"
        ),
        "negative_example": (
            "agent:sase-tj.land produced-by "
            "stitch:sase@0123456789abcdef0123456789abcdef01234567"
        ),
        "recommended_source_kinds": ["stitch"],
        "recommended_target_kinds": ["agent"],
    },
    {
        "schema_version": 2,
        "slug": "launched",
        "inverse": "launched-by",
        "directed": True,
        "written_by": "projection",
        "direction_note": "The chop is the source; the agent it launched is the target.",
        "positive_example": "chop:refresh_docs/refresh_docs launched agent:sase-tj.land",
        "negative_example": "agent:sase-tj.land launched chop:refresh_docs/refresh_docs",
        "recommended_source_kinds": ["chop"],
        "recommended_target_kinds": ["agent"],
    },
)


def assembled_artifact_relations(
    *,
    plugins: Sequence[Mapping[str, Any]] = (),
    config: Sequence[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Assemble the relation registry: builtins, then plugins, then config.

    v1 ships builtins only. The concatenation order is the snapshot shape
    later phases must keep so plugins are not painted out.
    """

    rows = [
        dict(item) for item in require_rust_binding("artifact_relations_builtins")()
    ]
    existing_slugs = {str(item.get("slug") or "") for item in rows}
    rows.extend(
        dict(item)
        for item in _PROJECTION_RELATIONS
        if str(item.get("slug") or "") not in existing_slugs
    )
    rows.extend(dict(item) for item in plugins)
    rows.extend(dict(item) for item in config)
    return rows


def artifact_link_aggregate_path(project_key: str) -> Path:
    """Return ``~/.sase/projects/<key>/artifact-links.json``."""

    key = project_key.strip()
    if not key or "/" in key or key in {".", ".."}:
        raise ValueError(
            f"invalid project key for artifact-links index: {project_key!r}"
        )
    return sase_projects_dir() / key / ARTIFACT_LINK_AGGREGATE_FILENAME


def canonicalize_artifact_link_ref(value: str) -> str:
    """Strip ``@`` and rewrite historical kind aliases through sase-core."""

    return str(require_rust_binding("artifact_link_canonicalize")(value))


def sidecar_kind_for_role(role: str) -> str:
    """Map an SDD sidecar role onto the artifact-ref kind it stores."""

    return PLAN_KIND if role == PLANS_ROLE else role


def kind_of_ref(value: str) -> str:
    """Return the canonical kind of *value*."""

    canonical = canonicalize_artifact_link_ref(value)
    kind, _sep, _rest = canonical.partition(":")
    return kind


def writes_sidecar_json(value: str) -> bool:
    """Return whether *value* owns per-artifact JSON under a sidecar ``links/``."""

    return kind_of_ref(value) not in NON_SIDECAR_KINDS


def sidecar_index_path(repo_root: Path, artifact_ref: str) -> Path:
    """Return ``<repo>/links/<relpath>.json`` for a document-shaped ref."""

    canonical = canonicalize_artifact_link_ref(artifact_ref)
    _kind, _sep, relpath = canonical.partition(":")
    return repo_root / referenced_by_index_relpath(relpath)


def _empty_artifact_link_index(artifact_ref: str) -> dict[str, Any]:
    """Return an empty v2 per-artifact index."""

    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "artifact_ref": canonicalize_artifact_link_ref(artifact_ref),
        "rows": [],
    }


def _empty_artifact_link_aggregate() -> dict[str, Any]:
    """Return an empty v2 aggregate document."""

    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "generation": 0,
        "rows": [],
    }


def read_aggregate_document(path: Path) -> dict[str, Any]:
    """Read one aggregate document from disk without acquiring a lock.

    Every caller either already holds the aggregate's flock or explicitly
    wants an unlocked snapshot; the flock in :class:`locked_file` is a
    per-open-file-description ``flock``, so a nested call through
    ``ArtifactLinkStore.load_aggregate`` from inside an already-held lock
    would deadlock rather than reenter.
    """

    if not path.is_file():
        return _empty_artifact_link_aggregate()
    payload = read_json_object(path)
    if payload.get("schema_version") != ARTIFACT_LINK_ROW_SCHEMA_VERSION:
        raise RuntimeError(f"unsupported artifact link aggregate schema: {path}")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("artifact link aggregate rows must be a list")
    try:
        generation = int(payload.get("generation") or 0)
    except (TypeError, ValueError):
        generation = 0
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "generation": generation,
        "rows": [dict(row) for row in rows if isinstance(row, dict)],
    }


def project_aggregate_rows(
    *,
    collected: Iterable[Mapping[str, Any]],
    prior_rows: Iterable[Mapping[str, Any]],
    authoritative_source_was_consulted: Callable[[Mapping[str, Any]], bool],
    projected_rows: Iterable[Mapping[str, Any]] = (),
) -> list[dict[str, Any]]:
    """Decide which rows survive an aggregate projection.

    The single point every aggregate-rebuilding path -- this workspace's own
    scan, the cross-workspace reconciliation scan, and any future scan --
    must route through, so those paths can differ only in *which stores
    they scan*, never in *which of the scanned-plus-prior rows they keep*.
    A prior row is carried forward exactly when this pass could not have
    proven it deleted. Publication status has no bearing on that question:
    it is a publication-holdback concern, not a local read-model concern,
    and must never be checked here (see ``durable_sidecar_rows`` for the
    filter that does apply it).

    Every prior row whose ``origin`` is ``projected`` is dropped rather than
    carried forward -- a projected row is recomputed on every pass, not
    persisted, so a rule that stops matching must let its row disappear
    here. *projected_rows* is appended last so :func:`unique_rows`'s
    first-wins dedup lets a store-backed row with the same identity beat a
    projected one.
    """

    rows = list(collected)
    for row in prior_rows:
        if is_projected_row(row):
            continue
        if not authoritative_source_was_consulted(row):
            rows.append(row)
    rows.extend(projected_rows)
    return unique_rows(rows)


def is_projected_row(row: Mapping[str, Any]) -> bool:
    """Return whether *row* was recomputed by the projection layer.

    A projected row enters the machine-local read model and nothing else:
    every path that treats an aggregate row as durable truth must exclude
    it.
    """

    return str(row.get("origin") or "") == "projected"


def store_backed_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return *rows* with every projected row excluded."""

    return [dict(row) for row in rows if not is_projected_row(row)]


def read_artifact_link_index(path: Path, *, artifact_ref: str) -> dict[str, Any]:
    """Read one v2 artifact-link index."""

    if not path.is_file():
        return _empty_artifact_link_index(artifact_ref)
    schema = referenced_by_index_schema_version(path)
    payload = read_json_object(path)
    if schema == 1:
        raise RuntimeError(
            f"unsupported schema-v1 Referenced By index after artifact-link "
            f"graduation: {path}; migrate this sidecar before reading links"
        )
    if schema != ARTIFACT_LINK_ROW_SCHEMA_VERSION:
        raise RuntimeError(f"unsupported artifact link index schema: {path}")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("artifact link index rows must be a list")
    ref = str(payload.get("artifact_ref") or artifact_ref)
    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "artifact_ref": canonicalize_artifact_link_ref(ref),
        "rows": [dict(row) for row in rows if isinstance(row, dict)],
    }


def validate_artifact_link_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize and validate one v2 row through sase-core."""

    return dict(require_rust_binding("artifact_link_validate_row")(dict(row)))


def upsert_artifact_link_rows(
    rows: Sequence[Mapping[str, Any]], incoming: Mapping[str, Any]
) -> dict[str, Any]:
    """Insert or rewrite *incoming* in *rows* through sase-core."""

    original_rows = [dict(row) for row in rows]
    incoming_row = dict(incoming)
    outcome = require_rust_binding("artifact_link_upsert_row")(
        original_rows,
        incoming_row,
    )
    outcome_row = dict(outcome["row"])
    outcome_rows = [dict(row) for row in outcome["rows"]]
    if str(incoming_row.get("origin") or "") in _COMMIT_SCOPED_ORIGINS:
        outcome_rows = _converge_prompt_ref_uses(
            original_rows,
            incoming_row,
            outcome_rows,
        )
        identity = _row_identity(incoming_row)
        for row in outcome_rows:
            if (
                str(row.get("origin") or "") in _COMMIT_SCOPED_ORIGINS
                and _row_identity(row) == identity
            ):
                outcome_row = dict(row)
                break
    return {
        "kind": "unchanged" if outcome_rows == original_rows else str(outcome["kind"]),
        "row": outcome_row,
        "rows": outcome_rows,
    }


def _converge_prompt_ref_uses(
    original_rows: Sequence[Mapping[str, Any]],
    incoming: Mapping[str, Any],
    outcome_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Make commit-scoped outbox retries converge, not accumulate like reads."""

    origin = str(incoming.get("origin") or "")
    identity = _row_identity(incoming)
    existing_uses = max(
        (
            _row_uses(row)
            for row in original_rows
            if str(row.get("origin") or "") == origin and _row_identity(row) == identity
        ),
        default=0,
    )
    uses = max(existing_uses, _row_uses(incoming))
    rows: list[dict[str, Any]] = []
    for raw in outcome_rows:
        row = dict(raw)
        if str(row.get("origin") or "") == origin and _row_identity(row) == identity:
            row["uses"] = uses
        rows.append(row)
    return rows


def _row_uses(row: Mapping[str, Any]) -> int:
    try:
        return int(row.get("uses") or 0)
    except (TypeError, ValueError):
        return 0


def pair_matches(
    row: Mapping[str, Any],
    *,
    source: str,
    target: str,
    relation: str | None,
) -> bool:
    """Return whether a row matches an endpoint pair and optional relation."""

    endpoints = {
        str(row.get("source_ref") or ""),
        str(row.get("target_ref") or ""),
    }
    if endpoints != {source, target}:
        return False
    if relation is None:
        return True
    return str(row.get("relation") or "") == relation


def row_touches(row: Mapping[str, Any], artifact_ref: str) -> bool:
    """Return whether a row touches an artifact reference."""

    return artifact_ref in {
        str(row.get("source_ref") or ""),
        str(row.get("target_ref") or ""),
    }


@cache
def _relation_is_directed(relation: str) -> bool:
    """Return whether *relation* is directed, per the compiled-in registry."""

    try:
        looked_up = require_rust_binding("artifact_relation_lookup")(relation)
        return bool(looked_up.get("directed", True))
    except (ValueError, TypeError, AttributeError):
        return relation != "related"


def _row_identity(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the directed or undirected identity of a row."""

    relation = str(row.get("relation") or "")
    source = str(row.get("source_ref") or "")
    target = str(row.get("target_ref") or "")
    if _relation_is_directed(relation):
        return ("directed", source, relation, target)
    left, right = sorted((source, target))
    return ("undirected", relation, left, right)


def unique_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate rows by relation-aware identity while preserving order."""

    seen: dict[tuple[str, ...], dict[str, Any]] = {}
    order: list[tuple[str, ...]] = []
    for row in rows:
        identity = _row_identity(row)
        if identity in seen:
            continue
        seen[identity] = dict(row)
        order.append(identity)
    return [seen[key] for key in order]


def read_json_object(path: Path) -> dict[str, Any]:
    """Read a JSON object from *path*."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"artifact link index must be a JSON object: {path}")
    return payload
