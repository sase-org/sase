"""List, path, and open commands for ``sase workspace``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
import time
from typing import Protocol

from sase.workspace_provider.registry import (
    WorkspaceEntry,
    WorkspaceRegistry,
)
from sase.repo_inventory import RepoKind
from sase.workspace_provider.inventory import (
    WorkspaceInventory,
    WorkspaceInventoryProjectNotFoundError,
    collect_workspace_inventory,
)
from sase.workspace_provider.store import WorkspaceStore
from sase.workspace_provider.utils import ensure_workspace_checkout

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


def normalize_repo_open_reason(reason: str | None) -> str:
    """Normalize and validate a ``sase repo open`` reason."""

    normalized = (reason or "").strip()
    if not normalized:
        raise _WorkspaceOpenReasonError("sase repo open requires a non-empty --reason")
    return normalized


class _CheckoutResolver(Protocol):
    def __call__(
        self,
        ctx: ProjectContext,
        workspace_num: int,
        *,
        materialize: bool,
    ) -> str: ...


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


def _print_single_project_human(
    ctx: ProjectContext,
    inventory: WorkspaceInventory,
) -> None:
    print(f"Project: {ctx.project_name}  policy={ctx.store.root_policy}")
    print(f"Root: {ctx.store.root_dir}")
    print()
    print(
        f"{'#':>4}  {'CLAIMED BY':<24} {'ROLE':<7} {'EXISTS':<7} "
        f"{'PIN':<3} {'LAST USED':<10} {'STALE':<5} PATH"
    )
    for row in inventory.records:
        print(
            f"{row.workspace_num:>4}  "
            f"{(row.claim_agent or '-'):<24.24} "
            f"{row.role:<7.7} "
            f"{('yes' if row.exists else 'missing'):<7} "
            f"{('yes' if row.pinned else '-'):<3} "
            f"{_relative_age(row.last_used_at):<10} "
            f"{('yes' if row.stale else '-'):<5} "
            f"{row.checkout_dir}"
        )
    _print_inventory_issues(inventory)


def _print_all_projects_human(inventory: WorkspaceInventory) -> None:
    if not inventory.records:
        print("No registered workspaces found.")
    else:
        print(
            f"{'PROJECT':<20} {'#':>4}  {'CLAIMED BY':<24} {'ROLE':<7} "
            f"{'PIN':<3} {'LAST USED':<10} {'STALE':<5} {'EXISTS':<7} PATH"
        )
        for row in inventory.records:
            print(
                f"{row.project:<20.20} "
                f"{row.workspace_num:>4}  "
                f"{(row.claim_agent or '-'):<24.24} "
                f"{row.role:<7.7} "
                f"{('yes' if row.pinned else '-'):<3} "
                f"{_relative_age(row.last_used_at):<10} "
                f"{('yes' if row.stale else '-'):<5} "
                f"{('yes' if row.exists else 'missing'):<7} "
                f"{row.checkout_dir}"
            )
    _print_inventory_issues(inventory)


def _print_inventory_issues(inventory: WorkspaceInventory) -> None:
    for issue in inventory.issues:
        print(f"warning [{issue.project}]: {issue.message}", file=sys.stderr)


def _relative_age(timestamp: float) -> str:
    seconds = max(0, int(time.time() - timestamp))
    if seconds < 60:
        return "now"
    if seconds < 3600:
        return f"{seconds // 60}m ago"
    if seconds < 86400:
        return f"{seconds // 3600}h ago"
    return f"{seconds // 86400}d ago"


def handle_list(
    args: argparse.Namespace,
    *,
    resolve_project_context: ProjectResolver,
) -> int:
    all_projects = bool(getattr(args, "all_projects", False))
    requested_project = getattr(args, "project", None)
    if all_projects and requested_project:
        print("--all cannot be combined with --project", file=sys.stderr)
        return 2

    if all_projects:
        inventory = collect_workspace_inventory(include_disabled=True)
        if getattr(args, "json", False):
            print(json.dumps(inventory.to_json_dict(), indent=2, sort_keys=True))
        else:
            _print_all_projects_human(inventory)
        return 0

    ctx = resolve_project_context(requested_project)
    try:
        inventory = collect_workspace_inventory(project=ctx.project_name)
    except WorkspaceInventoryProjectNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if getattr(args, "json", False):
        payload = {
            "project": ctx.project_name,
            "project_key": ctx.store.project_key,
            "root_policy": ctx.store.root_policy,
            "root_dir": ctx.store.root_dir,
            "primary_workspace_dir": ctx.store.primary_workspace_dir,
            "workspaces": [row.to_json_dict() for row in inventory.records],
            "issues": [issue.to_json_dict() for issue in inventory.issues],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_single_project_human(ctx, inventory)
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
            sidecar_repo_clone_dir,
            linked_repo_clone_dir,
            materialize_linked_repo_workspace,
            sdd_sidecar_clone_dirname,
        )

        sidecar_dirname = sdd_sidecar_clone_dirname(host_primary, ctx.project_name)
        workspace_dir = (
            sidecar_repo_clone_dir(host_checkout, sidecar_dirname)
            if sidecar_dirname is not None
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

    path = prepare_opened_checkout(
        ctx,
        workspace_num,
        reason=reason,
        resolve_checkout=resolve_checkout,
    )
    if path is None:
        return 1

    _record_legacy_repo_open(
        ctx,
        workspace_num=workspace_num,
        path=path,
        reason=reason,
    )
    print(path)
    return 0


def prepare_opened_checkout(
    ctx: ProjectContext,
    workspace_num: int,
    *,
    reason: str,
    resolve_checkout: _CheckoutResolver,
) -> str | None:
    """Materialize, prepare, and marker-record a repository checkout."""

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
        return None

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
        return None

    if ctx.is_sibling or _is_configured_linked_repo(ctx.project_name):
        from sase.linked_repos import record_opened_linked_repo

        record_opened_linked_repo(
            ctx.project_name,
            path,
            reason=reason,
            opened_at=datetime.now(tz=UTC).isoformat(),
        )
    return path


def _record_legacy_repo_open(
    ctx: ProjectContext,
    *,
    workspace_num: int,
    path: str,
    reason: str,
) -> None:
    """Best-effort durable audit for the deprecated workspace spelling."""

    project, repo, repo_kind = _legacy_repo_open_identity(ctx)
    try:
        from sase.repo_open_log import (
            append_repo_open_event,
            build_repo_open_event,
        )

        event = build_repo_open_event(
            project=project,
            repo=repo,
            repo_kind=repo_kind,
            workspace_num=workspace_num,
            path=path,
            reason=reason,
        )
        append_repo_open_event(event)
    except Exception as exc:
        print(f"Warning: unable to record repo open: {exc}", file=sys.stderr)


def _legacy_repo_open_identity(
    ctx: ProjectContext,
) -> tuple[str, str, RepoKind]:
    is_linked = ctx.is_sibling or _is_configured_linked_repo(ctx.project_name)
    if not is_linked:
        repo = Path(ctx.primary_workspace_dir.rstrip("/")).name or ctx.project_name
        return ctx.project_name, repo, "primary"

    host_primary = ctx.linked_host_primary_workspace_dir
    project = _legacy_host_project(ctx, host_primary=host_primary)
    repo_kind: RepoKind = "linked"
    if host_primary:
        from sase.linked_repos import sdd_sidecar_clone_dirname

        if sdd_sidecar_clone_dirname(host_primary, ctx.project_name) is not None:
            repo_kind = "sidecar"
    return project, ctx.project_name, repo_kind


def _legacy_host_project(
    ctx: ProjectContext,
    *,
    host_primary: str | None,
) -> str:
    from sase.bead.project_name import infer_project_name_from_cwd

    if host_primary:
        inferred = infer_project_name_from_cwd(host_primary)
        if inferred:
            return inferred

    spec_project = Path(ctx.project_file).parent.name.strip()
    if spec_project and spec_project != ctx.project_name:
        return spec_project
    inferred = infer_project_name_from_cwd()
    if inferred and inferred != ctx.project_name:
        return inferred
    return spec_project or ctx.project_name


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
