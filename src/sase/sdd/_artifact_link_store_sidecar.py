"""Sidecar ``links/`` JSON read/write helpers for :class:`ArtifactLinkStore`."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import fcntl
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.agents_sync.io import atomic_write_json
from sase.memory.locks import locked_file
from sase.sdd._artifact_link_files import artifact_link_lock_path
from sase.sdd._artifact_link_store_support import (
    ARTIFACT_LINK_ROW_SCHEMA_VERSION,
    canonicalize_artifact_link_ref,
    pair_matches,
    read_artifact_link_index,
    sidecar_index_path,
    upsert_artifact_link_rows,
)
from sase.sdd.referenced_by_index import REFERENCED_BY_LINKS_DIR

if TYPE_CHECKING:
    from collections.abc import Callable


class ArtifactLinkStoreSidecarMixin:
    """Reads and writes for per-artifact sidecar ``links/`` JSON."""

    sidecar_roots: Mapping[str, Path]
    sidecar_root_for: Callable[[str], Path | None]

    def _upsert_sidecar(
        self, artifact_ref: str, incoming: Mapping[str, Any]
    ) -> dict[str, Any] | None:
        root = self.sidecar_root_for(artifact_ref)
        if root is None:
            return None
        canonical = canonicalize_artifact_link_ref(artifact_ref)
        path = sidecar_index_path(root, canonical)
        with locked_file(artifact_link_lock_path(path), fcntl.LOCK_EX):
            index = read_artifact_link_index(path, artifact_ref=canonical)
            outcome = upsert_artifact_link_rows(index["rows"], incoming)
            if str(outcome.get("kind") or "") == "unchanged" and path.is_file():
                return {**outcome, "changed_indexes": ()}
            atomic_write_json(
                path,
                {
                    "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                    "artifact_ref": canonical,
                    "rows": outcome["rows"],
                },
            )
        return {**outcome, "changed_indexes": (path,)}

    def _remove_sidecar_rows(
        self,
        artifact_ref: str,
        *,
        source: str,
        target: str,
        relation: str | None,
    ) -> tuple[list[dict[str, Any]], Path | None]:
        root = self.sidecar_root_for(artifact_ref)
        if root is None:
            return [], None
        canonical = canonicalize_artifact_link_ref(artifact_ref)
        path = sidecar_index_path(root, canonical)
        with locked_file(artifact_link_lock_path(path), fcntl.LOCK_EX):
            if not path.is_file():
                return [], None
            index = read_artifact_link_index(path, artifact_ref=canonical)
            kept: list[dict[str, Any]] = []
            dropped: list[dict[str, Any]] = []
            for row in index.get("rows", []):
                if pair_matches(row, source=source, target=target, relation=relation):
                    dropped.append(dict(row))
                else:
                    kept.append(dict(row))
            if dropped:
                atomic_write_json(
                    path,
                    {
                        "schema_version": ARTIFACT_LINK_ROW_SCHEMA_VERSION,
                        "artifact_ref": canonical,
                        "rows": kept,
                    },
                )
                return dropped, path
        return dropped, None

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
                relative = path.relative_to(links_root).as_posix()
                if not relative.endswith(".json"):
                    continue
                artifact_ref = f"{kind}:{relative[: -len('.json')]}"
                index = read_artifact_link_index(path, artifact_ref=artifact_ref)
                for row in index.get("rows", []):
                    if isinstance(row, dict):
                        yield dict(row)
