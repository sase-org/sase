"""Shared row, reference, and JSON helpers for typed artifact-link storage."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import json
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir
from sase.core.rust import require_rust_binding
from sase.sdd.artifact_link_migrate import migrate_v1_index_to_v2
from sase.sdd.referenced_by_index import (
    REFERENCED_BY_INDEX_SCHEMA_VERSION,
    referenced_by_index_relpath,
    referenced_by_index_schema_version,
)

ARTIFACT_LINK_ROW_SCHEMA_VERSION = 2
ARTIFACT_LINK_AGGREGATE_FILENAME = "artifact-links.json"
NON_SIDECAR_KINDS = frozenset({"agent", "bead", "stitch"})
PLANS_ROLE = "plans"
PLAN_KIND = "plan"
BEAD_KIND = "bead"


class ArtifactLinksDisabledError(RuntimeError):
    """Raised when a v2 link write is refused because the beta flag is off."""


def artifact_links_enabled() -> bool:
    """Return whether ``artifact_links`` is on in the process snapshot."""

    from sase.feature_flags import FeatureFlag, current_flags

    return current_flags().enabled(FeatureFlag.artifact_links)


def artifact_links_disabled_message() -> str:
    """Return the flag-off diagnostic used by writers."""

    return (
        "feature flag `artifact_links` is disabled; enable it with "
        "`sase -f artifact_links ...` to write typed artifact links. Existing "
        "v1 Referenced By projections in links/ keep updating."
    )


def require_artifact_links_enabled() -> None:
    """Refuse v2 writes when the beta flag is off."""

    if not artifact_links_enabled():
        raise ArtifactLinksDisabledError(artifact_links_disabled_message())


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


def empty_artifact_link_aggregate() -> dict[str, Any]:
    """Return an empty v2 aggregate document."""

    return {"schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION, "rows": []}


def read_artifact_link_index(path: Path, *, artifact_ref: str) -> dict[str, Any]:
    """Read v2 truth, or migrate a v1 Referenced By index in memory."""

    if not path.is_file():
        return _empty_artifact_link_index(artifact_ref)
    schema = referenced_by_index_schema_version(path)
    payload = read_json_object(path)
    if schema == REFERENCED_BY_INDEX_SCHEMA_VERSION:
        return migrate_v1_index_to_v2(payload)
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

    outcome = require_rust_binding("artifact_link_upsert_row")(
        [dict(row) for row in rows],
        dict(incoming),
    )
    return {
        "kind": str(outcome["kind"]),
        "row": dict(outcome["row"]),
        "rows": [dict(row) for row in outcome["rows"]],
    }


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


def row_has_bead_endpoint(row: Mapping[str, Any]) -> bool:
    """Return whether either endpoint in a row is a bead."""

    source = str(row.get("source_ref") or "")
    target = str(row.get("target_ref") or "")
    prefix = f"{BEAD_KIND}:"
    return source.startswith(prefix) or target.startswith(prefix)


def row_touches(row: Mapping[str, Any], artifact_ref: str) -> bool:
    """Return whether a row touches an artifact reference."""

    return artifact_ref in {
        str(row.get("source_ref") or ""),
        str(row.get("target_ref") or ""),
    }


def _row_identity(row: Mapping[str, Any]) -> tuple[str, ...]:
    """Return the directed or undirected identity of a row."""

    relation = str(row.get("relation") or "")
    source = str(row.get("source_ref") or "")
    target = str(row.get("target_ref") or "")
    directed = True
    try:
        looked_up = require_rust_binding("artifact_relation_lookup")(relation)
        directed = bool(looked_up.get("directed", True))
    except (ValueError, TypeError, AttributeError):
        directed = relation != "related"
    if directed:
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
