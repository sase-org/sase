"""Collect artifact ids protected by durable SASE references."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re

from sase._repo_inventory_models import RepoRecord
from sase.core.paths import sase_projects_dir
from sase.repo_inventory import collect_repo_inventory


_ARTIFACT_ID_RE = re.compile(r"(?:file:)?(?P<id>(?:default|explicit):[0-9a-f]{24})")
_TEXT_SUFFIXES = frozenset({".json", ".md", ".sase", ".txt", ".yml"})
_REQUIRED_SIDECAR_ROLES = ("beads", "plans")
_OPPORTUNISTIC_SIDECAR_ROLES = ("research",)


@dataclass(frozen=True)
class ProtectedArtifactIds:
    """Reference-protected ids plus scan coverage evidence."""

    ids: frozenset[str]
    sources_scanned: tuple[str, ...]
    sources_unavailable: tuple[str, ...]


def collect_protected_artifact_ids() -> ProtectedArtifactIds:
    """Scan ProjectSpecs and live SDD sidecars for artifact references."""

    ids: set[str] = set()
    scanned: set[str] = set()
    unavailable: set[str] = set()

    projects_root = sase_projects_dir()
    _scan_root(
        projects_root,
        ids=ids,
        scanned=scanned,
        unavailable=unavailable,
        required=True,
        suffixes=frozenset({".sase"}),
    )

    try:
        inventory = collect_repo_inventory()
    except Exception as exc:
        unavailable.add(f"repository inventory: {exc}")
    else:
        project_names = sorted(
            {record.project for record in inventory.records if record.kind == "primary"}
        )
        for project in project_names:
            records = tuple(
                record
                for record in inventory.records
                if record.project == project and record.kind == "sidecar"
            )
            for role in _REQUIRED_SIDECAR_ROLES:
                root = _live_sidecar_root(records, role)
                if root is None:
                    unavailable.add(f"{project}:{role}")
                    continue
                _scan_root(
                    root,
                    ids=ids,
                    scanned=scanned,
                    unavailable=unavailable,
                    required=True,
                    suffixes=_TEXT_SUFFIXES,
                )
            for role in _OPPORTUNISTIC_SIDECAR_ROLES:
                root = _live_sidecar_root(records, role)
                if root is None:
                    continue
                _scan_root(
                    root,
                    ids=ids,
                    scanned=scanned,
                    unavailable=unavailable,
                    required=False,
                    suffixes=_TEXT_SUFFIXES,
                )

    return ProtectedArtifactIds(
        ids=frozenset(ids),
        sources_scanned=tuple(sorted(scanned)),
        sources_unavailable=tuple(sorted(unavailable)),
    )


def _live_sidecar_root(
    records: tuple[RepoRecord, ...],
    role: str,
) -> Path | None:
    candidates = tuple(record for record in records if _record_has_role(record, role))
    for record in candidates:
        paths = ((record.path, record.exists),) + tuple(
            (clone.path, clone.exists) for clone in record.clones
        )
        for raw_path, exists in paths:
            if exists and raw_path:
                path = Path(raw_path).expanduser()
                if path.is_dir():
                    return path
    return None


def _record_has_role(record: RepoRecord, role: str) -> bool:
    tokens = (record.name, record.slug or "")
    return any(token == role or token.endswith(f"--{role}") for token in tokens)


def _scan_root(
    root: Path,
    *,
    ids: set[str],
    scanned: set[str],
    unavailable: set[str],
    required: bool,
    suffixes: frozenset[str],
) -> None:
    resolved = root.expanduser().resolve(strict=False)
    if not resolved.is_dir():
        if required:
            unavailable.add(str(resolved))
        return

    walk_errors: list[OSError] = []
    try:
        for directory, child_dirs, filenames in os.walk(
            resolved,
            followlinks=False,
            onerror=walk_errors.append,
        ):
            child_dirs[:] = [
                name
                for name in child_dirs
                if name != ".git" and not (Path(directory) / name).is_symlink()
            ]
            for filename in filenames:
                path = Path(directory) / filename
                if path.suffix.lower() not in suffixes or path.is_symlink():
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    if required:
                        unavailable.add(str(path))
                    continue
                ids.update(
                    match.group("id") for match in _ARTIFACT_ID_RE.finditer(text)
                )
    except OSError:
        if required:
            unavailable.add(str(resolved))
        return

    scanned.add(str(resolved))
    if required:
        unavailable.update(f"{resolved}: {error}" for error in walk_errors)


__all__ = [
    "ProtectedArtifactIds",
    "collect_protected_artifact_ids",
]
