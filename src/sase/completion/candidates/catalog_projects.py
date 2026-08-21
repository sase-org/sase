"""Catalog fetchers backed by project lifecycle records.

Repos, workspace numbers, and Patches all start from the same project record
set; see :mod:`sase.completion.candidates.catalog` for the import contract.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from sase.completion.candidates.catalog_support import (
    dedupe,
    project_records_and_snapshot,
)
from sase.completion.candidates.protocol import Candidate


def _read_json_object(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _workspace_state_root() -> Path:
    override = os.environ.get("SASE_WORKSPACE_ROOT", "").strip()
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg) / "sase" / "workspaces"
    return Path.home() / ".local" / "state" / "sase" / "workspaces"


def _workspace_nums_from_registry(path: Path) -> list[tuple[int, str]]:
    payload = _read_json_object(path)
    if payload is None:
        return []
    raw = payload.get("workspaces")
    if not isinstance(raw, dict):
        return []
    found: list[tuple[int, str]] = []
    for key, value in raw.items():
        try:
            number = int(key)
        except (TypeError, ValueError):
            continue
        role = ""
        if isinstance(value, dict):
            role = str(value.get("role") or "")
        found.append((number, role))
    return found


def repo_source_path(_project: str | None) -> Path | None:
    """Return the cache-invalidation path for repo candidates."""
    from sase.core.paths import sase_projects_dir

    return sase_projects_dir()


def repo_candidates(project: str | None) -> list[Candidate]:
    """Return known repo display names from the read-only inventory."""
    from sase.repo_inventory import collect_repo_inventory, repo_display_name

    inventory = collect_repo_inventory(project=project)
    candidates = [
        Candidate(repo_display_name(record), f"{record.kind} · {record.project}")
        for record in inventory.records
    ]
    return dedupe(candidates)


def workspace_source_path(_project: str | None) -> Path | None:
    """Return the cache-invalidation path for workspace candidates."""
    from sase.core.paths import sase_projects_dir

    return sase_projects_dir()


def workspace_candidates(project: str | None) -> list[Candidate]:
    """Return each project's workspace numbers, primary first."""
    records, snapshot = project_records_and_snapshot(project)
    state_root = _workspace_state_root()
    candidates: list[Candidate] = []
    for record in records:
        if not record.is_project:
            continue
        label = snapshot.label_for(record.project_name)
        candidates.append(Candidate("0", f"{label} primary"))
        seen = {0}
        registry_paths = [
            state_root / record.project_name / "registry.json",
        ]
        workspace_dir = (record.workspace_dir or "").strip()
        if workspace_dir:
            parent = Path(workspace_dir).expanduser()
            registry_paths.append(parent.parent / "registry.json")
            registry_paths.append(parent / ".sase" / "registry.json")
        for registry_path in registry_paths:
            for number, role in _workspace_nums_from_registry(registry_path):
                if number in seen:
                    continue
                seen.add(number)
                candidates.append(
                    Candidate(str(number), f"{label} {role or 'workspace'}")
                )
    return dedupe(candidates)


def patch_source_path(_project: str | None) -> Path | None:
    """Return the cache-invalidation path for Patch candidates."""
    from sase.core.paths import sase_projects_dir

    return sase_projects_dir()


def patch_candidates(project: str | None) -> list[Candidate]:
    """Return Patch names parsed from each project's ``.sase`` files."""
    from sase.core.rust import require_rust_binding

    records, snapshot = project_records_and_snapshot(project)
    parse = require_rust_binding("parse_patch_project_bytes")
    candidates: list[Candidate] = []
    for record in records:
        project_label = snapshot.label_for(record.project_name)
        for raw_path in (record.project_file, record.archive_file):
            if not raw_path:
                continue
            path = Path(raw_path)
            try:
                payload = path.read_bytes()
            except OSError:
                continue
            try:
                parsed = parse(str(path), payload)
            except Exception:
                continue
            if not isinstance(parsed, list):
                continue
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                name = str(item.get("name") or "")
                if not name:
                    continue
                status = str(item.get("status") or "")
                display = str(item.get("project_display_name") or "") or project_label
                description = " · ".join(part for part in (status, display) if part)
                candidates.append(Candidate(name, description))
    return dedupe(candidates)


__all__ = [
    "patch_candidates",
    "patch_source_path",
    "repo_candidates",
    "repo_source_path",
    "workspace_candidates",
    "workspace_source_path",
]
