"""Per-artifact v2 link truth, rebuildable aggregate, and ``artifact_links`` gate.

Beads, agents, and stitches are not written into sidecar ``links/`` JSON.
Until the beads phase owns event-stream truth, bead-bead rows live only in
the project aggregate as a cache. v1 Referenced By files remain readable and
are migrated in memory (and rewritten to v2 on the first flag-on write).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
import fcntl
import json
from pathlib import Path
from typing import Any

from sase.agents_sync.io import atomic_write_json
from sase.core.paths import sase_projects_dir
from sase.core.rust import require_rust_binding
from sase.memory.locks import locked_file
from sase.sdd.artifact_link_migrate import migrate_v1_index_to_v2
from sase.sdd.referenced_by_index import (
    REFERENCED_BY_INDEX_SCHEMA_VERSION,
    REFERENCED_BY_LINKS_DIR,
    referenced_by_index_relpath,
    referenced_by_index_schema_version,
)
from sase.sdd.store import SddStore, document_sidecar_roles

ARTIFACT_LINK_ROW_SCHEMA_VERSION = 2
ARTIFACT_LINK_AGGREGATE_FILENAME = "artifact-links.json"
NON_SIDECAR_KINDS = frozenset({"agent", "bead", "stitch"})
_PLANS_ROLE = "plans"
_PLAN_KIND = "plan"


class ArtifactLinksDisabledError(RuntimeError):
    """Raised when a v2 link write is refused because the beta flag is off."""


def artifact_links_enabled() -> bool:
    """Return whether ``artifact_links`` is on in the process snapshot."""

    from sase.feature_flags import FeatureFlag, current_flags

    return current_flags().enabled(FeatureFlag.artifact_links)


def _artifact_links_disabled_message() -> str:
    """Return the flag-off diagnostic used by writers."""

    return (
        "feature flag `artifact_links` is disabled; enable it to write typed "
        "artifact links. Existing v1 Referenced By projections in links/ keep "
        "updating."
    )


def _require_artifact_links_enabled() -> None:
    """Refuse v2 writes when the beta flag is off."""

    if not artifact_links_enabled():
        raise ArtifactLinksDisabledError(_artifact_links_disabled_message())


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


def _canonicalize_artifact_link_ref(value: str) -> str:
    """Strip ``@`` and rewrite historical kind aliases through sase-core."""

    return str(require_rust_binding("artifact_link_canonicalize")(value))


def _sidecar_kind_for_role(role: str) -> str:
    """Map an SDD sidecar role onto the artifact-ref kind it stores."""

    return _PLAN_KIND if role == _PLANS_ROLE else role


def _kind_of_ref(value: str) -> str:
    """Return the canonical kind of *value*."""

    canonical = _canonicalize_artifact_link_ref(value)
    kind, _sep, _rest = canonical.partition(":")
    return kind


def _writes_sidecar_json(value: str) -> bool:
    """Return whether *value* owns per-artifact JSON under a sidecar ``links/``."""

    return _kind_of_ref(value) not in NON_SIDECAR_KINDS


def _sidecar_index_path(repo_root: Path, artifact_ref: str) -> Path:
    """Return ``<repo>/links/<relpath>.json`` for a document-shaped ref."""

    canonical = _canonicalize_artifact_link_ref(artifact_ref)
    _kind, _sep, relpath = canonical.partition(":")
    return repo_root / referenced_by_index_relpath(relpath)


def _empty_artifact_link_index(artifact_ref: str) -> dict[str, Any]:
    """Return an empty v2 per-artifact index."""

    return {
        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
        "artifact_ref": _canonicalize_artifact_link_ref(artifact_ref),
        "rows": [],
    }


def _empty_artifact_link_aggregate() -> dict[str, Any]:
    """Return an empty v2 aggregate document."""

    return {"schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION, "rows": []}


def _read_artifact_link_index(path: Path, *, artifact_ref: str) -> dict[str, Any]:
    """Read v2 truth, or migrate a v1 Referenced By index in memory."""

    if not path.is_file():
        return _empty_artifact_link_index(artifact_ref)
    schema = referenced_by_index_schema_version(path)
    payload = _read_json_object(path)
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
        "artifact_ref": _canonicalize_artifact_link_ref(ref),
        "rows": [dict(row) for row in rows if isinstance(row, dict)],
    }


def _validate_artifact_link_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Canonicalize and validate one v2 row through sase-core."""

    return dict(require_rust_binding("artifact_link_validate_row")(dict(row)))


def _upsert_artifact_link_rows(
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


@dataclass(frozen=True)
class ArtifactLinkStore:
    """Kind-native adapter over sidecar ``links/`` JSON plus the aggregate."""

    project_key: str
    sidecar_roots: Mapping[str, Path]

    @classmethod
    def from_sdd_store(cls, store: SddStore, project_key: str) -> ArtifactLinkStore:
        """Build an adapter from one resolved SDD store."""

        roots: dict[str, Path] = {}
        roles = document_sidecar_roles(store.split_sidecar_roles(), include_plans=True)
        for role in roles:
            try:
                roots[_sidecar_kind_for_role(role)] = (
                    store.repo_root_for_kind(role).expanduser().resolve(strict=False)
                )
            except Exception:  # noqa: BLE001 - skip unresolved sidecars
                continue
        return cls(project_key=project_key, sidecar_roots=roots)

    def sidecar_root_for(self, artifact_ref: str) -> Path | None:
        """Return the sidecar root that should store *artifact_ref*, if any."""

        if not _writes_sidecar_json(artifact_ref):
            return None
        return self.sidecar_roots.get(_kind_of_ref(artifact_ref))

    def upsert_row(self, row: Mapping[str, Any]) -> dict[str, Any]:
        """Write one validated row to sidecar JSON (when owned) and the aggregate."""

        _require_artifact_links_enabled()
        validated = _validate_artifact_link_row(row)
        outcome: dict[str, Any] | None = None
        for ref in (validated["source_ref"], validated["target_ref"]):
            written = self._upsert_sidecar(ref, validated)
            if written is not None:
                outcome = written
        rebuilt = self.rebuild_aggregate()
        if _is_bead_bead(validated):
            outcome = self._upsert_aggregate_row(validated)
        return outcome or {
            "kind": "unchanged",
            "row": validated,
            "rows": list(rebuilt.get("rows", [])),
        }

    def load_artifact_rows(self, artifact_ref: str) -> tuple[dict[str, Any], ...]:
        """Return every stored row touching *artifact_ref*."""

        canonical = _canonicalize_artifact_link_ref(artifact_ref)
        root = self.sidecar_root_for(canonical)
        if root is not None:
            index = _read_artifact_link_index(
                _sidecar_index_path(root, canonical),
                artifact_ref=canonical,
            )
            return tuple(dict(row) for row in index.get("rows", []))
        return tuple(
            dict(row)
            for row in self.load_aggregate().get("rows", [])
            if _row_touches(row, canonical)
        )

    def load_aggregate(self) -> dict[str, Any]:
        """Read the project aggregate, or return an empty v2 document."""

        path = artifact_link_aggregate_path(self.project_key)
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_SH):
            if not path.is_file():
                return _empty_artifact_link_aggregate()
            payload = _read_json_object(path)
        if payload.get("schema_version") != ARTIFACT_LINK_ROW_SCHEMA_VERSION:
            raise RuntimeError(f"unsupported artifact link aggregate schema: {path}")
        rows = payload.get("rows")
        if not isinstance(rows, list):
            raise RuntimeError("artifact link aggregate rows must be a list")
        return {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "rows": [dict(row) for row in rows if isinstance(row, dict)],
        }

    def preview_aggregate(self) -> dict[str, Any]:
        """Return the aggregate that a rebuild would write, without writing it."""

        collected = list(self._iter_sidecar_rows())
        for row in self.load_aggregate().get("rows", []):
            if _is_bead_bead(row):
                collected.append(row)
        return {
            "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
            "rows": _unique_rows(collected),
        }

    def rebuild_aggregate(self) -> dict[str, Any]:
        """Rebuild ``artifact-links.json`` from sidecar JSON plus bead-bead cache."""

        document = self.preview_aggregate()
        self._write_aggregate(document)
        return document

    def _upsert_sidecar(
        self, artifact_ref: str, incoming: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        root = self.sidecar_root_for(artifact_ref)
        if root is None:
            return None
        canonical = _canonicalize_artifact_link_ref(artifact_ref)
        path = _sidecar_index_path(root, canonical)
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
            index = _read_artifact_link_index(path, artifact_ref=canonical)
            outcome = _upsert_artifact_link_rows(index["rows"], incoming)
            atomic_write_json(
                path,
                {
                    "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                    "artifact_ref": canonical,
                    "rows": outcome["rows"],
                },
            )
        return outcome

    def _upsert_aggregate_row(self, incoming: Mapping[str, Any]) -> dict[str, Any]:
        path = artifact_link_aggregate_path(self.project_key)
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
            current = _empty_artifact_link_aggregate()
            if path.is_file():
                payload = _read_json_object(path)
                rows = payload.get("rows")
                if isinstance(rows, list):
                    current["rows"] = [
                        dict(row) for row in rows if isinstance(row, dict)
                    ]
            outcome = _upsert_artifact_link_rows(current["rows"], incoming)
            document = {
                "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                "rows": outcome["rows"],
            }
            atomic_write_json(path, document)
        return outcome

    def _write_aggregate(self, document: Mapping[str, Any]) -> None:
        path = artifact_link_aggregate_path(self.project_key)
        with locked_file(path.with_suffix(".lock"), fcntl.LOCK_EX):
            atomic_write_json(path, dict(document))

    def _iter_sidecar_rows(self) -> Iterable[dict[str, Any]]:
        seen_roots: set[Path] = set()
        for kind, root in self.sidecar_roots.items():
            resolved = root.expanduser().resolve(strict=False)
            if resolved in seen_roots or not resolved.is_dir():
                continue
            seen_roots.add(resolved)
            links_root = resolved / REFERENCED_BY_LINKS_DIR
            if not links_root.is_dir():
                continue
            for path in sorted(links_root.rglob("*.json")):
                schema = referenced_by_index_schema_version(path)
                if schema not in {
                    REFERENCED_BY_INDEX_SCHEMA_VERSION,
                    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                }:
                    continue
                relative = path.relative_to(links_root).as_posix()
                if not relative.endswith(".json"):
                    continue
                artifact_ref = f"{kind}:{relative[: -len('.json')]}"
                index = _read_artifact_link_index(path, artifact_ref=artifact_ref)
                for row in index.get("rows", []):
                    if isinstance(row, dict):
                        yield dict(row)


def _is_bead_bead(row: Mapping[str, Any]) -> bool:
    source = str(row.get("source_ref") or "")
    target = str(row.get("target_ref") or "")
    return _kind_of_ref(source) == "bead" and _kind_of_ref(target) == "bead"


def _row_touches(row: Mapping[str, Any], artifact_ref: str) -> bool:
    return artifact_ref in {
        str(row.get("source_ref") or ""),
        str(row.get("target_ref") or ""),
    }


def _row_identity(row: Mapping[str, Any]) -> tuple[str, ...]:
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


def _unique_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, ...], dict[str, Any]] = {}
    order: list[tuple[str, ...]] = []
    for row in rows:
        identity = _row_identity(row)
        if identity in seen:
            continue
        seen[identity] = dict(row)
        order.append(identity)
    return [seen[key] for key in order]


def _read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"artifact link index must be a JSON object: {path}")
    return payload


__all__ = [
    "ARTIFACT_LINK_AGGREGATE_FILENAME",
    "ARTIFACT_LINK_ROW_SCHEMA_VERSION",
    "NON_SIDECAR_KINDS",
    "ArtifactLinkStore",
    "ArtifactLinksDisabledError",
    "artifact_link_aggregate_path",
    "artifact_links_enabled",
    "assembled_artifact_relations",
]
