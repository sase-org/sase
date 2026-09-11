"""Orphaned link-index and missing head-index checks."""

from __future__ import annotations

from pathlib import Path

from sase.sdd._artifact_link_store_support import read_artifact_link_index
from sase.sdd.artifact_link_store import ArtifactLinkStore
from sase.sdd.referenced_by_doctor import missing_referenced_by_indexes
from sase.sdd.referenced_by_index import REFERENCED_BY_LINKS_DIR


def orphaned_link_indexes(store: ArtifactLinkStore) -> list[str]:
    orphaned: list[str] = []
    seen: set[str] = set()
    for kind, root in store.sidecar_roots.items():
        links_root = root / REFERENCED_BY_LINKS_DIR
        if not links_root.is_dir():
            continue
        for path in sorted(links_root.rglob("*.json")):
            relative = path.relative_to(links_root).as_posix()
            if not relative.endswith(".json"):
                continue
            fallback_ref = f"{kind}:{relative[: -len('.json')]}"
            try:
                index = read_artifact_link_index(path, artifact_ref=fallback_ref)
            except Exception:  # noqa: BLE001 - malformed indexes are separate health.
                continue
            ref = str(index.get("artifact_ref") or fallback_ref)
            if ref in seen:
                continue
            seen.add(ref)
            artifact_path = _artifact_path_for(root, ref)
            if artifact_path is not None and not artifact_path.is_file():
                orphaned.append(ref)
    return sorted(orphaned)


def _artifact_path_for(root: Path, artifact_ref: str) -> Path | None:
    try:
        _kind, separator, relpath = artifact_ref.partition(":")
        if not separator or not relpath:
            return None
        relative = Path(relpath)
        if relative.is_absolute() or any(
            part in {"", ".", ".."} for part in relative.parts
        ):
            return None
    except (TypeError, ValueError):
        return None
    return root / relative


def missing_head_indexes(store: ArtifactLinkStore) -> list[str]:
    missing: list[str] = []
    for kind, root in store.sidecar_roots.items():
        if not root.is_dir():
            continue
        for relpath in missing_referenced_by_indexes(root):
            missing.append(f"{kind}:{relpath}")
    return sorted(missing)


__all__ = [
    "missing_head_indexes",
    "orphaned_link_indexes",
]
