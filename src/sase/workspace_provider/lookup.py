"""Directory-to-workspace-number lookup (Phase `lookup` of sase-lb.1).

Several call sites know a checkout directory but not the workspace number
that owns it.  The per-project workspace registry (``registry.json``, see
:mod:`sase.workspace_provider.registry`) is the durable, authoritative
mapping from workspace number to ``checkout_dir`` -- including ``0`` for the
primary checkout -- so this module resolves the reverse direction from it
instead of parsing directory basenames.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.workspace_provider.registry import load_or_init_registry
from sase.workspace_provider.store import (
    PRIMARY_WORKSPACE_NUM,
    WorkspaceStore,
)


def _normalize_checkout_path(path: str) -> str:
    """Return an absolute, symlink-resolved path for checkout comparison.

    Expands ``~``, resolves symlinks, and normalizes away trailing
    slashes, so the registry's ``checkout_dir`` values (written with a
    trailing slash for managed checkouts) compare equal to caller paths
    that lack one.
    """
    return str(Path(path).expanduser().resolve(strict=False))


def resolve_workspace_num_for_dir(
    primary_workspace_dir: str,
    directory: str,
    *,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> int | None:
    """Resolve *directory* to the workspace number that owns it.

    Consults the project's workspace registry first -- authoritative for
    every managed checkout, including the seeded primary ``#0`` entry --
    then falls back to ``WorkspaceStore.resolve(0)`` in case the registry
    could not be read. Returns ``None`` when *directory* is not a managed
    checkout of this project; the number is never guessed from the
    directory basename.
    """
    if not directory:
        return None

    target = _normalize_checkout_path(directory)
    store = WorkspaceStore(primary_workspace_dir, config=config, env=env)

    registry = load_or_init_registry(store)
    for raw_num, entry in registry.workspaces.items():
        try:
            workspace_num = int(raw_num)
        except (TypeError, ValueError):
            continue
        if _normalize_checkout_path(entry.checkout_dir) == target:
            return workspace_num

    primary_path = store.resolve(PRIMARY_WORKSPACE_NUM)
    if _normalize_checkout_path(primary_path.checkout_dir) == target:
        return PRIMARY_WORKSPACE_NUM

    return None


__all__ = [
    "resolve_workspace_num_for_dir",
]
