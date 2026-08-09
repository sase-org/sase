"""Managed workspaces registry (Phase 3 of sase-3p).

Tracks the set of materialized workspace checkouts under a managed
project root.  The registry lives at ``<root_dir>/registry.json`` and is
written atomically so concurrent ``sase`` processes never observe a
half-written file.

The registry is required for ``xdg-state`` and absolute-root policies
(where managed checkouts live under a project-keyed directory) and is
optional for ``adjacent`` policy, which can keep its existing
sibling-directory behavior without it.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sase.workspace_provider.store import (
    PRIMARY_WORKSPACE_NUM,
    WorkspacePath,
    WorkspaceStore,
)


REGISTRY_FILENAME = "registry.json"
SCHEMA_VERSION = 1


class WorkspaceRegistryError(RuntimeError):
    """Raised when an existing workspace registry cannot be read safely."""


@dataclass
class WorkspaceEntry:
    """One row of the managed-workspaces registry."""

    checkout_dir: str
    materialization: str
    role: str
    created_at: float
    last_used_at: float
    pinned: bool = False
    generation: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> WorkspaceEntry:
        return cls(
            checkout_dir=str(raw.get("checkout_dir", "")),
            materialization=str(raw.get("materialization", "")),
            role=str(raw.get("role", "")),
            created_at=float(raw.get("created_at", 0.0)),
            last_used_at=float(raw.get("last_used_at", 0.0)),
            pinned=bool(raw.get("pinned", False)),
            generation=int(raw.get("generation", 0)),
        )


@dataclass
class WorkspaceRegistry:
    """In-memory view of the managed workspaces registry."""

    project_key: str
    primary_workspace_dir: str
    workspaces: dict[str, WorkspaceEntry] = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "project_key": self.project_key,
            "primary_workspace_dir": self.primary_workspace_dir,
            "workspaces": {k: v.to_dict() for k, v in self.workspaces.items()},
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> WorkspaceRegistry:
        workspaces_raw = raw.get("workspaces", {})
        workspaces: dict[str, WorkspaceEntry] = {}
        if isinstance(workspaces_raw, dict):
            for key, value in workspaces_raw.items():
                if isinstance(value, dict):
                    workspaces[str(key)] = WorkspaceEntry.from_dict(value)
        return cls(
            project_key=str(raw.get("project_key", "")),
            primary_workspace_dir=str(raw.get("primary_workspace_dir", "")),
            workspaces=workspaces,
            schema_version=int(raw.get("schema_version", SCHEMA_VERSION)),
        )


def registry_path(root_dir: str) -> str:
    """Return the registry path under *root_dir*."""
    return str(Path(root_dir) / REGISTRY_FILENAME)


def _read_registry_file(
    path: str,
    *,
    strict: bool = False,
) -> WorkspaceRegistry | None:
    """Read a registry file from disk, returning ``None`` when absent."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError) as exc:
        if strict:
            raise WorkspaceRegistryError(
                f"Unable to read workspace registry {path}: {exc}"
            ) from exc
        return None
    if not isinstance(data, dict):
        if strict:
            raise WorkspaceRegistryError(
                f"Unable to read workspace registry {path}: expected a JSON object"
            )
        return None
    try:
        return WorkspaceRegistry.from_dict(data)
    except (TypeError, ValueError) as exc:
        if strict:
            raise WorkspaceRegistryError(
                f"Unable to read workspace registry {path}: {exc}"
            ) from exc
        return None


def _write_registry_file(path: str, registry: WorkspaceRegistry) -> None:
    """Write *registry* to *path* atomically via tempfile + os.replace."""
    parent = os.path.dirname(path) or "."
    os.makedirs(parent, exist_ok=True)
    payload = json.dumps(registry.to_dict(), indent=2, sort_keys=True)

    fd, temp_path = tempfile.mkstemp(dir=parent, prefix=".registry.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def load_registry(
    store: WorkspaceStore,
    *,
    strict: bool = False,
) -> WorkspaceRegistry:
    """Load the registry for *store*, initializing it with primary ``#0``.

    The primary checkout is always represented in the registry so that
    ``sase workspace list`` can show ``#0`` without special-casing it at
    the CLI layer.  Differences between the on-disk record and the
    store's current configuration (project_key, primary path) are
    reconciled in favor of the store and written back on save.

    When *strict* is true, an existing unreadable registry raises
    :class:`WorkspaceRegistryError`. Inventory callers use this mode so one
    corrupt project can be reported without being mistaken for an empty
    registry; mutating compatibility paths retain the historical recovery
    behavior through :func:`load_or_init_registry`.
    """
    path = registry_path(store.root_dir)
    registry = _read_registry_file(path, strict=strict)
    now = time.time()
    if registry is None:
        registry = WorkspaceRegistry(
            project_key=store.project_key,
            primary_workspace_dir=store.primary_workspace_dir,
        )
    else:
        registry.project_key = store.project_key
        registry.primary_workspace_dir = store.primary_workspace_dir
        registry.schema_version = SCHEMA_VERSION

    primary_key = str(PRIMARY_WORKSPACE_NUM)
    if primary_key not in registry.workspaces:
        registry.workspaces[primary_key] = WorkspaceEntry(
            checkout_dir=store.primary_workspace_dir,
            materialization="primary",
            role="primary",
            created_at=now,
            last_used_at=now,
            pinned=True,
        )
    else:
        existing = registry.workspaces[primary_key]
        existing.checkout_dir = store.primary_workspace_dir
        existing.materialization = "primary"
        existing.role = "primary"
        existing.pinned = True

    return registry


def load_or_init_registry(store: WorkspaceStore) -> WorkspaceRegistry:
    """Load a registry, tolerating corrupt input for legacy repair paths."""

    return load_registry(store)


def save_registry(store: WorkspaceStore, registry: WorkspaceRegistry) -> None:
    """Persist *registry* under ``store.root_dir`` atomically."""
    _write_registry_file(registry_path(store.root_dir), registry)


def record_workspace(
    store: WorkspaceStore,
    workspace_path: WorkspacePath,
    *,
    role: str = "claim",
    pinned: bool = False,
) -> WorkspaceRegistry:
    """Insert or refresh *workspace_path* in the registry and persist.

    ``last_used_at`` is bumped on every call; ``created_at`` is only
    set when the entry is new.  The returned registry reflects the
    on-disk state after the write.
    """
    registry = load_or_init_registry(store)
    key = str(workspace_path.workspace_num)
    now = time.time()
    existing = registry.workspaces.get(key)
    if existing is None:
        registry.workspaces[key] = WorkspaceEntry(
            checkout_dir=workspace_path.checkout_dir,
            materialization=workspace_path.materialization,
            role=role,
            created_at=now,
            last_used_at=now,
            pinned=pinned,
            generation=workspace_path.generation,
        )
    else:
        existing.checkout_dir = workspace_path.checkout_dir
        existing.materialization = workspace_path.materialization
        existing.role = role
        existing.last_used_at = now
        existing.generation = workspace_path.generation
        if pinned:
            existing.pinned = True

    save_registry(store, registry)
    return registry


def remove_workspace(store: WorkspaceStore, workspace_num: int) -> WorkspaceRegistry:
    """Drop the entry for *workspace_num* and persist.

    The primary workspace ``#0`` is never removed; callers asking to
    delete it get the registry back unchanged.
    """
    registry = load_or_init_registry(store)
    if workspace_num == PRIMARY_WORKSPACE_NUM:
        return registry
    registry.workspaces.pop(str(workspace_num), None)
    save_registry(store, registry)
    return registry


__all__ = [
    "REGISTRY_FILENAME",
    "SCHEMA_VERSION",
    "WorkspaceEntry",
    "WorkspaceRegistry",
    "WorkspaceRegistryError",
    "load_registry",
    "load_or_init_registry",
    "record_workspace",
    "registry_path",
    "remove_workspace",
    "save_registry",
]
