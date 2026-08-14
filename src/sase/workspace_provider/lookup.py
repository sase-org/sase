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


def resolve_consistent_workspace_pair(
    primary_workspace_dir: str,
    workspace_dir: str,
    workspace_num: int | None,
    *,
    config: Mapping[str, Any] | None = None,
    env: Mapping[str, str] | None = None,
) -> tuple[str, int] | None:
    """Repair a ``(workspace_dir, workspace_num)`` pair against the corollary
    that ``workspace_num == 0`` may only ever be paired with the primary
    checkout directory (see Phase `followup` of plan
    ``202608/workspace_claim_invariant.md``). Pairing ``0`` with a numbered
    checkout is a bug, never a degradation.

    A truthy *workspace_num* is returned unchanged alongside *workspace_dir*
    -- a caller that already has an authoritative number needs no repair.
    A falsy *workspace_num* (``0`` or ``None``) is self-consistent only when
    *workspace_dir* is the primary checkout; otherwise *workspace_dir* is
    looked up in the project's workspace registry to recover its real
    number. Returns ``None`` when the pair cannot be made self-consistent
    -- *workspace_dir* is empty, or names a checkout the registry does not
    recognize -- leaving the decision of how to handle an unresolvable pair
    to the caller.
    """
    if workspace_num:
        return workspace_dir, workspace_num
    if not workspace_dir:
        return None
    if _normalize_checkout_path(workspace_dir) == _normalize_checkout_path(
        primary_workspace_dir
    ):
        return workspace_dir, PRIMARY_WORKSPACE_NUM

    resolved = resolve_workspace_num_for_dir(
        primary_workspace_dir, workspace_dir, config=config, env=env
    )
    if resolved:
        return workspace_dir, resolved
    return None


__all__ = [
    "resolve_consistent_workspace_pair",
    "resolve_workspace_num_for_dir",
]
