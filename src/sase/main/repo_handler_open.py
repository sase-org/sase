"""Implementation and resolution helpers for ``sase repo open``."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import os
from pathlib import Path
import sys
from typing import Protocol

from sase.repo_inventory import (
    RepoInventory,
    RepoInventoryProjectNotFoundError,
    RepoKind,
    RepoRecord,
)
from sase.repo_open_log import append_repo_open_event, build_repo_open_event
from sase.workspace_provider.store import WorkspaceStore

from .repo_handler_common import (
    InventoryCollector,
    MarkerFinder,
    ProjectContextResolver,
    RepoOpenResolutionError,
    is_relative_to,
)
from .workspace_handler_context import ConfigLoader, ProjectContext


class CheckoutResolver(Protocol):
    def __call__(
        self,
        ctx: ProjectContext,
        workspace_num: int,
        *,
        materialize: bool,
    ) -> str: ...


MatchRepo = Callable[..., RepoRecord | None]
RecordRepoOpen = Callable[..., None]
ResolveWorkspaceNum = Callable[[ProjectContext, int | None], int]
TargetContext = Callable[[ProjectContext, RepoRecord], ProjectContext]


def handle_open_command(
    args: argparse.Namespace,
    *,
    collect_inventory: InventoryCollector,
    resolve_project_context: ProjectContextResolver,
    resolve_checkout: CheckoutResolver,
    resolve_workspace_num: ResolveWorkspaceNum,
    match_repo: MatchRepo,
    target_context: TargetContext,
    record_repo_open: RecordRepoOpen,
) -> int:
    from .repo_open_external import ExternalRepoOpenError, open_external_repo
    from .workspace_handler_list import (
        normalize_repo_open_reason,
        prepare_opened_checkout,
    )

    try:
        reason = normalize_repo_open_reason(getattr(args, "reason", None))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    host_ctx = resolve_project_context(getattr(args, "project", None))
    try:
        workspace_num = resolve_workspace_num(
            host_ctx,
            getattr(args, "workspace", None),
        )
        inventory = collect_inventory(project=host_ctx.project_name)
        repo = match_repo(
            getattr(args, "repo", ""),
            host_ctx=host_ctx,
            inventory=inventory,
        )
    except (RepoInventoryProjectNotFoundError, RepoOpenResolutionError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if repo is None:
        try:
            external = open_external_repo(
                getattr(args, "repo", ""),
                host_ctx=host_ctx,
                workspace_num=workspace_num,
                inventory=inventory,
                reason=reason,
                resolve_checkout=resolve_checkout,
            )
        except ExternalRepoOpenError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        record_repo_open(
            host_ctx=host_ctx,
            repo_name=external.canonical_name,
            repo_kind="external",
            workspace_num=workspace_num,
            path=external.path,
            reason=reason,
        )
        print(external.path)
        return 0

    target_ctx = target_context(host_ctx, repo)
    path = prepare_opened_checkout(
        target_ctx,
        workspace_num,
        reason=reason,
        resolve_checkout=resolve_checkout,
    )
    if path is None:
        return 1

    record_repo_open(
        host_ctx=host_ctx,
        repo_name=repo.name,
        repo_kind=repo.kind,
        workspace_num=workspace_num,
        path=path,
        reason=reason,
    )
    print(path)
    return 0


def resolve_open_workspace_num(
    host_ctx: ProjectContext,
    requested_workspace: int | None,
    *,
    find_marker: MarkerFinder,
    cwd: Path | None = None,
) -> int:
    if requested_workspace is not None:
        workspace_num = int(requested_workspace)
        if workspace_num < 0:
            raise RepoOpenResolutionError(
                f"workspace number must be >= 0, got {workspace_num}"
            )
        return workspace_num

    cwd_path = (cwd or Path.cwd()).resolve(strict=False)
    found = find_marker(str(cwd_path))
    if found is not None:
        _, marker = found
        marker_primary = Path(marker.primary_workspace_dir).resolve(strict=False)
        host_primary = Path(host_ctx.primary_workspace_dir).resolve(strict=False)
        if marker_primary != host_primary:
            raise RepoOpenResolutionError(
                "Current directory belongs to a different project's workspace; "
                "pass -w/--workspace."
            )
        if marker.workspace_num < 0:
            raise RepoOpenResolutionError(
                f"workspace marker has invalid number {marker.workspace_num}"
            )
        return marker.workspace_num

    host_primary = Path(host_ctx.primary_workspace_dir).resolve(strict=False)
    if is_relative_to(cwd_path, host_primary):
        return 0
    raise RepoOpenResolutionError(
        "Unable to infer workspace from current directory; pass -w/--workspace."
    )


def repo_target_context(
    host_ctx: ProjectContext,
    repo: RepoRecord,
    *,
    load_config: ConfigLoader,
) -> ProjectContext:
    if repo.kind == "primary":
        return host_ctx
    primary_clone = repo.clone_for_workspace(0)
    primary_dir = primary_clone.path if primary_clone is not None else repo.path
    return ProjectContext(
        project_name=repo.name,
        project_file=host_ctx.project_file,
        primary_workspace_dir=primary_dir,
        store=WorkspaceStore(primary_dir, config=load_config()),
        is_sibling=True,
        is_configured_linked_repo=True,
        linked_host_primary_workspace_dir=host_ctx.primary_workspace_dir,
        linked_repo_remote_url=repo.remote_url,
    )


def record_repo_open(
    *,
    host_ctx: ProjectContext,
    repo_name: str,
    repo_kind: RepoKind,
    workspace_num: int,
    path: str,
    reason: str,
) -> None:
    try:
        event = build_repo_open_event(
            project=host_ctx.project_name,
            repo=repo_name,
            repo_kind=repo_kind,
            workspace_num=workspace_num,
            path=path,
            reason=reason,
            cwd=Path(os.getcwd()),
        )
        append_repo_open_event(event)
    except Exception as exc:
        print(f"Warning: unable to record repo open: {exc}", file=sys.stderr)
