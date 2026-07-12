"""List, path, and open commands for ``sase workspace``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Protocol

from sase.workspace_provider.registry import (
    WorkspaceEntry,
    WorkspaceRegistry,
    load_or_init_registry,
)
from sase.workspace_provider.store import WorkspaceStore
from sase.workspace_provider.utils import ensure_workspace_checkout
from sase.project_display_names import project_display_name_for

from .workspace_handler_context import ConfigLoader, ProjectContext

ProjectResolver = Callable[[str | None], ProjectContext]


class _WorkspaceOpenReasonError(ValueError):
    """Raised when a ``sase workspace open`` reason is missing or empty."""


def _normalize_workspace_open_reason(reason: str | None) -> str:
    """Normalize and validate a ``sase workspace open`` reason.

    Trims surrounding whitespace and rejects empty values, mirroring the
    ``sase memory read`` reason contract.
    """
    normalized = (reason or "").strip()
    if not normalized:
        raise _WorkspaceOpenReasonError(
            "sase workspace open requires a non-empty --reason"
        )
    return normalized


class _CheckoutResolver(Protocol):
    def __call__(
        self,
        ctx: ProjectContext,
        workspace_num: int,
        *,
        materialize: bool,
    ) -> str: ...


def _entry_row(num: int, entry: WorkspaceEntry) -> dict[str, Any]:
    return {
        "workspace_num": num,
        "checkout_dir": entry.checkout_dir.rstrip("/") or entry.checkout_dir,
        "materialization": entry.materialization,
        "role": entry.role,
        "pinned": entry.pinned,
        "created_at": entry.created_at,
        "last_used_at": entry.last_used_at,
        "generation": entry.generation,
        "exists": os.path.isdir(entry.checkout_dir.rstrip("/") or entry.checkout_dir),
    }


def sorted_entries(registry: WorkspaceRegistry) -> list[tuple[int, WorkspaceEntry]]:
    items: list[tuple[int, WorkspaceEntry]] = []
    for key, entry in registry.workspaces.items():
        try:
            num = int(key)
        except (TypeError, ValueError):
            continue
        items.append((num, entry))
    items.sort(key=lambda pair: pair[0])
    return items


def _print_list_human(
    ctx: ProjectContext,
    rows: list[dict[str, Any]],
) -> None:
    header = (
        f"Project: {project_display_name_for(ctx.store.project_key)}  "
        f"policy={ctx.store.root_policy}"
    )
    print(header)
    print(f"Root: {ctx.store.root_dir}")
    print()
    print(f"{'#':>4}  {'ROLE':<7} {'EXISTS':<6} {'PINNED':<6} {'PATH'}")
    for row in rows:
        print(
            f"{row['workspace_num']:>4}  "
            f"{row['role']:<7} "
            f"{('yes' if row['exists'] else 'no'):<6} "
            f"{('yes' if row['pinned'] else 'no'):<6} "
            f"{row['checkout_dir']}"
        )


def handle_list(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectResolver,
) -> int:
    ctx = resolve_project_context(args.project)
    registry = load_or_init_registry(ctx.store)
    rows = [_entry_row(num, entry) for num, entry in sorted_entries(registry)]

    if args.json:
        payload = {
            "project": ctx.project_name,
            "project_key": ctx.store.project_key,
            "root_policy": ctx.store.root_policy,
            "root_dir": ctx.store.root_dir,
            "primary_workspace_dir": ctx.store.primary_workspace_dir,
            "workspaces": rows,
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_list_human(ctx, rows)
    return 0


def resolve_checkout_path(
    ctx: ProjectContext,
    workspace_num: int,
    *,
    materialize: bool,
    load_config: ConfigLoader,
) -> str:
    """Return the checkout path for *workspace_num*.

    Materializes (cloning when missing) only when *materialize* is true.
    """
    if workspace_num <= 1:
        return ctx.primary_workspace_dir.rstrip("/") or ctx.primary_workspace_dir
    if ctx.is_configured_linked_repo and workspace_num > 1:
        host_primary = ctx.linked_host_primary_workspace_dir
        if not host_primary:
            raise RuntimeError(
                f"Linked repo '{ctx.project_name}' workspaces are host-scoped; "
                "run this command from the host project workspace that configures it"
            )
        config = load_config()
        host_store = WorkspaceStore(host_primary, config=config)
        if materialize:
            host_checkout = ensure_workspace_checkout(
                host_primary, workspace_num, config=config
            )
        else:
            host_checkout = host_store.resolve(workspace_num).checkout_dir.rstrip("/")
        from sase.linked_repos import (
            companion_repo_clone_dir,
            linked_repo_clone_dir,
            materialize_linked_repo_workspace,
            sdd_companion_clone_dirname,
        )

        companion_dirname = sdd_companion_clone_dirname(host_primary, ctx.project_name)
        workspace_dir = (
            companion_repo_clone_dir(host_checkout, companion_dirname)
            if companion_dirname is not None
            else linked_repo_clone_dir(host_checkout, ctx.project_name)
        )
        if not materialize:
            return workspace_dir

        return materialize_linked_repo_workspace(
            primary_dir=ctx.primary_workspace_dir,
            workspace_dir=workspace_dir,
            workspace_num=workspace_num,
        )
    if materialize:
        path = ensure_workspace_checkout(
            ctx.primary_workspace_dir,
            workspace_num,
            config=load_config(),
        )
        return path.rstrip("/") or path
    return ctx.store.resolve(workspace_num).checkout_dir.rstrip("/")


def handle_path(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectResolver,
    resolve_checkout: _CheckoutResolver,
) -> int:
    ctx = resolve_project_context(args.project)
    workspace_num = int(args.workspace_num)
    if workspace_num < 0:
        print(
            f"workspace number must be >= 0, got {workspace_num}",
            file=sys.stderr,
        )
        return 2

    try:
        path = resolve_checkout(ctx, workspace_num, materialize=False)
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(path)
    return 0


def handle_open_clean(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectResolver,
    resolve_checkout: _CheckoutResolver,
) -> int:
    try:
        reason = _normalize_workspace_open_reason(getattr(args, "reason", None))
    except _WorkspaceOpenReasonError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    ctx = resolve_project_context(args.project)
    workspace_num = int(args.workspace_num)
    if workspace_num < 0:
        print(
            f"workspace number must be >= 0, got {workspace_num}",
            file=sys.stderr,
        )
        return 2

    try:
        from sase.sdd.files import ensure_bare_git_sdd_initialized

        ensure_bare_git_sdd_initialized(
            ctx.primary_workspace_dir,
            commit=True,
            push=True,
            raise_on_error=True,
        )
        path = resolve_checkout(ctx, workspace_num, materialize=True)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    from sase.axe.runner_utils import prepare_workspace
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    clean_label = f"{ctx.project_name}-workspace-{workspace_num}"
    if not prepare_workspace(
        path,
        clean_label,
        VCS_DEFAULT_REVISION,
        backup_suffix="workspace-open",
        project_basename=ctx.project_name,
    ):
        return 1

    if ctx.is_sibling or _is_configured_linked_repo(ctx.project_name):
        from sase.linked_repos import record_opened_linked_repo

        record_opened_linked_repo(
            ctx.project_name,
            path,
            reason=reason,
            opened_at=datetime.now(tz=UTC).isoformat(),
        )

    print(path)
    return 0


def _is_configured_linked_repo(project_name: str) -> bool:
    from sase.linked_repos import linked_repo_metadata_from_env

    normalized = project_name.strip()
    if not normalized:
        return False
    for item in linked_repo_metadata_from_env(os.environ):
        name = item.get("name")
        if isinstance(name, str) and name.strip() == normalized:
            return True
    return False
