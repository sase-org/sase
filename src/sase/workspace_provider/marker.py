"""Managed-checkout marker files (Phase 3 of sase-3p).

Each managed checkout carries a ``.sase/checkout.json`` describing the
workspace identity it belongs to.  ``sase`` commands run from inside the
checkout read this marker to recover project context without falling
back to sibling-basename parsing.

Markers are deliberately *not* written into the user's primary checkout.
The primary workspace is identified via ``ProjectSpec.WORKSPACE_DIR``
and treating it like a managed checkout would force a config decision
this phase explicitly defers.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sase.core.state_write_guard import pytest_path_is_sandboxed
from sase.workspace_provider.registry import registry_path
from sase.workspace_provider.store import (
    PRIMARY_WORKSPACE_NUM,
    WorkspacePath,
    WorkspaceStore,
)


MARKER_DIR = ".sase"
MARKER_FILENAME = "checkout.json"


@dataclass
class CheckoutMarker:
    """Project identity stored at ``<checkout>/.sase/checkout.json``."""

    project_name: str
    project_key: str
    workspace_num: int
    primary_workspace_dir: str
    registry_path: str
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CheckoutMarker:
        return cls(
            project_name=str(raw.get("project_name", "")),
            project_key=str(raw.get("project_key", "")),
            workspace_num=int(raw.get("workspace_num", 0)),
            primary_workspace_dir=str(raw.get("primary_workspace_dir", "")),
            registry_path=str(raw.get("registry_path", "")),
            schema_version=int(raw.get("schema_version", 1)),
        )


def _marker_path(checkout_dir: str) -> str:
    """Return the path to the marker file inside *checkout_dir*."""
    return str(Path(checkout_dir) / MARKER_DIR / MARKER_FILENAME)


def write_marker(store: WorkspaceStore, workspace_path: WorkspacePath) -> str | None:
    """Write the marker for *workspace_path* under *store*.

    Returns the marker path on success or ``None`` when the marker
    should not be written (primary checkout, missing checkout dir).
    """
    if workspace_path.workspace_num == PRIMARY_WORKSPACE_NUM:
        return None
    if workspace_path.materialization == "primary":
        return None

    checkout_dir = workspace_path.checkout_dir.rstrip("/")
    if not checkout_dir or not os.path.isdir(checkout_dir):
        return None

    marker = CheckoutMarker(
        project_name=os.path.basename(store.primary_workspace_dir.rstrip("/"))
        or workspace_path.project_key,
        project_key=workspace_path.project_key,
        workspace_num=workspace_path.workspace_num,
        primary_workspace_dir=store.primary_workspace_dir,
        registry_path=registry_path(store.root_dir),
    )

    path = _marker_path(checkout_dir)
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    payload = json.dumps(marker.to_dict(), indent=2, sort_keys=True)

    fd, temp_path = tempfile.mkstemp(dir=parent, prefix=".checkout.", suffix=".tmp")
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

    return path


def read_marker(checkout_dir: str) -> CheckoutMarker | None:
    """Read the marker from *checkout_dir*, or return ``None``.

    Malformed markers are treated as absent so callers can fall back to
    legacy detection without raising.
    """
    path = _marker_path(checkout_dir)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    try:
        return CheckoutMarker.from_dict(data)
    except (TypeError, ValueError):
        return None


def find_marker_from_cwd(start_dir: str) -> tuple[str, CheckoutMarker] | None:
    """Walk upward from *start_dir* looking for a checkout marker.

    Returns ``(checkout_dir, marker)`` for the nearest ancestor that
    contains a readable marker, or ``None`` when no marker is found
    before reaching the filesystem root.
    """
    current = os.path.abspath(start_dir)
    while True:
        if not pytest_path_is_sandboxed(current):
            return None
        marker = read_marker(current)
        if marker is not None:
            return current, marker
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


__all__ = [
    "MARKER_DIR",
    "MARKER_FILENAME",
    "CheckoutMarker",
    "find_marker_from_cwd",
    "read_marker",
    "write_marker",
]
