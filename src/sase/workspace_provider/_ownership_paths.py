"""Writable path resolution for the workspace ownership contract.

Split out of :mod:`sase.workspace_provider.ownership`. These helpers are the
only sanctioned way to turn an :class:`OperationContext` into a path
SASE-initiated code may write to, so new importers are gated by
``tests/workspace_provider/test_primary_writable_store_import_boundary.py``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from sase.workspace_provider._ownership_types import (
    AccessKind,
    OperationContext,
    WorkspaceOwnershipError,
    normalize_path,
    path_is_within,
)


def writable_checkout_dir(context: OperationContext) -> Path:
    """Return the checkout a writable context may mutate."""

    _require_writable(context)
    if context.access_kind is AccessKind.PRIMARY_SIDECAR_SYNC:
        raise WorkspaceOwnershipError(
            "primary-sidecar sync may not mutate the primary checkout; "
            f"use writable_sidecar_root for role {context.sidecar_role!r}"
        )
    return context.checkout_dir


def writable_kind_root(context: OperationContext, kind: str) -> Path:
    """Resolve a writable SDD kind root inside *context*."""

    _require_writable(context)
    if (
        context.access_kind is AccessKind.PRIMARY_SIDECAR_SYNC
        and kind != context.sidecar_role
    ):
        raise WorkspaceOwnershipError(
            f"primary-sidecar sync context is limited to role "
            f"{context.sidecar_role!r}, not {kind!r}"
        )
    root = kind_root_for_context(context, kind)
    if context.access_kind is AccessKind.PRIMARY_SIDECAR_SYNC:
        require_separate_sidecar_clone(context, root, kind)
    return root


def writable_beads_dir(context: OperationContext) -> Path:
    """Resolve the writable beads store for *context*."""

    return writable_kind_root(context, "beads")


def writable_plans_dir(context: OperationContext) -> Path:
    """Resolve the writable plans store for *context*."""

    return writable_kind_root(context, "plans")


def writable_sidecar_root(context: OperationContext, role: str) -> Path:
    """Resolve a writable sidecar clone for *role* inside *context*."""

    return writable_kind_root(context, role)


def kind_root_for_context(context: OperationContext, kind: str) -> Path:
    """Resolve the *kind* root *context* points at, writable or not."""

    from sase.sdd.store import resolve_sdd_store

    if context.access_kind is AccessKind.PRIMARY_SIDECAR_SYNC:
        from sase._linked_repo_paths import sidecar_repo_clone_dir

        return normalize_path(
            sidecar_repo_clone_dir(context.primary_checkout_dir, kind)
        )
    checkout = (
        context.primary_checkout_dir
        if context.access_kind is AccessKind.READ_ONLY_CANONICAL
        else context.checkout_dir
    )
    store = resolve_sdd_store(checkout, context.workspace_num)
    root = normalize_path(store.kind_root(kind))
    if (
        context.access_kind in {AccessKind.LEASED_OPERATIONAL, AccessKind.USER_DIRECTED}
        and not context.is_primary
        and not path_is_within(root, context.checkout_dir)
    ):
        return _workspace_local_kind_root(context.checkout_dir, store, kind)
    return root


def _workspace_local_kind_root(
    checkout: Path,
    store: Any,
    kind: str,
) -> Path:
    """Keep writable roots inside a numbered checkout when policy points at primary."""

    if getattr(store, "is_sidecar_storage", False):
        from sase._linked_repo_paths import sidecar_repo_clone_dir

        return normalize_path(sidecar_repo_clone_dir(checkout, kind))
    if getattr(store, "is_in_tree", False):
        return checkout / "sdd" / kind
    return checkout / ".sase" / "sdd" / kind


def _require_writable(context: OperationContext) -> None:
    if not context.is_writable:
        raise WorkspaceOwnershipError(
            "writable store APIs require a writable operation context, "
            "not read-only canonical access"
        )


def require_separate_sidecar_clone(
    context: OperationContext,
    sidecar_root: Path,
    role: str,
) -> None:
    """Refuse a sidecar sync that would write inside the primary checkout."""

    primary = context.primary_checkout_dir
    if sidecar_root == primary:
        raise WorkspaceOwnershipError(
            f"primary-sidecar sync cannot target the primary checkout for {role}"
        )
    primary_git = _checkout_git_root(primary)
    sidecar_git = _checkout_git_root(sidecar_root)
    if (
        primary_git is not None
        and sidecar_git is not None
        and primary_git == sidecar_git
    ):
        raise WorkspaceOwnershipError(
            f"primary-sidecar sync cannot mutate in-tree {role} inside {primary}"
        )


def _checkout_git_root(path: Path) -> Path | None:
    if not path.exists():
        return None
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=path,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    root = result.stdout.strip()
    if result.returncode != 0 or not root:
        return None
    return Path(root).resolve()


__all__ = [
    "kind_root_for_context",
    "require_separate_sidecar_clone",
    "writable_beads_dir",
    "writable_checkout_dir",
    "writable_kind_root",
    "writable_plans_dir",
    "writable_sidecar_root",
]
