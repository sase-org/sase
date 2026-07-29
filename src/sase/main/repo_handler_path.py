"""Implementation and resolution helpers for ``sase repo path``."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
import sys

from sase.repo_inventory import (
    RepoInventory,
    RepoInventoryProjectNotFoundError,
    RepoRecord,
)

from .repo_handler_common import (
    InventoryCollector,
    ProjectContextResolver,
    RepoOpenResolutionError,
    ambiguous_repo_error,
    clone_for_workspace,
    match_repo_record,
)
from .workspace_handler_context import ProjectContext


ResolveWorkspaceNum = Callable[[ProjectContext, int | None], int]
SidecarRoleDisabled = Callable[..., bool]
WorkspaceValidator = Callable[..., None]


def handle_path_command(
    args: argparse.Namespace,
    *,
    collect_inventory: InventoryCollector,
    resolve_project_context: ProjectContextResolver,
    resolve_workspace_num: ResolveWorkspaceNum,
    validate_workspace: WorkspaceValidator,
    sidecar_role_disabled: SidecarRoleDisabled,
) -> int:
    host_ctx = resolve_project_context(getattr(args, "project", None))
    requested = str(getattr(args, "repo", "")).strip()
    if not requested:
        print("repository name must not be empty", file=sys.stderr)
        return 2

    try:
        workspace_num = resolve_workspace_num(
            host_ctx,
            getattr(args, "workspace", None),
        )
        inventory = collect_inventory(project=host_ctx.project_name)
        validate_workspace(
            inventory.records,
            project=host_ctx.project_name,
            workspace_num=workspace_num,
        )
        repo = match_repo_path_record(
            requested,
            host_ctx=host_ctx,
            inventory=inventory,
        )
    except (RepoInventoryProjectNotFoundError, RepoOpenResolutionError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if repo is not None and repo.kind in {"linked", "external"}:
        print(
            f"Repository '{requested}' is {repo.kind}; use "
            f'`sase repo open {requested} --reason "<reason>"` instead.',
            file=sys.stderr,
        )
        return 2

    path: str | Path
    try:
        if repo is not None:
            clone = clone_for_workspace(repo, workspace_num)
            path = clone.path
            if repo.kind == "sidecar" and getattr(args, "ensure", False):
                from sase.linked_repos import materialize_linked_repo_workspace

                path = materialize_linked_repo_workspace(
                    primary_dir=repo.path,
                    workspace_dir=path,
                    workspace_num=workspace_num,
                    expected_remote_url=repo.remote_url,
                )
        elif _sdd_role_available(
            requested,
            primary_workspace_dir=host_ctx.primary_workspace_dir,
        ) and not sidecar_role_disabled(
            requested, primary_workspace_dir=host_ctx.primary_workspace_dir
        ):
            path = resolve_legacy_sdd_repo_path(
                requested,
                inventory=inventory,
                workspace_num=workspace_num,
                ensure=bool(getattr(args, "ensure", False)),
            )
        else:
            raise RepoOpenResolutionError(
                f"Repository '{requested}' is not a primary or sidecar repository "
                f"for project '{host_ctx.project_name}'"
            )
    except RepoOpenResolutionError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except (OSError, RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(Path(path).expanduser().resolve(strict=False))
    return 0


def match_repo_path_record(
    name: str,
    *,
    host_ctx: ProjectContext,
    inventory: RepoInventory,
) -> RepoRecord | None:
    repo = match_repo_record(name, host_ctx=host_ctx, inventory=inventory)
    if repo is not None:
        return repo

    matches = [
        record
        for record in inventory.records
        if record.kind == "external" and name in {record.name, record.slug}
    ]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ambiguous_repo_error(name, matches)
    return None


def resolve_legacy_sdd_repo_path(
    kind: str,
    *,
    inventory: RepoInventory,
    workspace_num: int,
    ensure: bool,
) -> Path:
    from sase.sdd.store import ensure_sdd_kind_clone, resolve_sdd_kind_dir

    primary_records = [
        record for record in inventory.records if record.kind == "primary"
    ]
    if len(primary_records) != 1:
        raise RepoOpenResolutionError(
            "Unable to identify the project's primary repository"
        )
    workspace_dir = clone_for_workspace(primary_records[0], workspace_num).path
    if ensure:
        ensure_sdd_kind_clone(workspace_dir, workspace_num, kind, strict=True)
    return resolve_sdd_kind_dir(workspace_dir, workspace_num, kind)


def sidecar_role_disabled(
    role: str,
    *,
    primary_workspace_dir: str,
) -> bool:
    from sase._linked_repo_config import (
        merged_sidecar_entries_from_config,
        resolution_config,
    )

    try:
        config = resolution_config(primary_workspace_dir, None)
        entries = merged_sidecar_entries_from_config(
            config,
            primary_workspace_dir=primary_workspace_dir,
        )
    except (OSError, RuntimeError, ValueError):
        return False
    return any(
        entry.get("name") == role and entry.get("disabled") is True for entry in entries
    )


def _sdd_role_available(
    role: str,
    *,
    primary_workspace_dir: str,
) -> bool:
    from sase._linked_repo_config import (
        configured_sidecar_roles,
        resolution_config,
    )
    from sase.sdd.store import (
        AGENTS_SIDECAR_ROLE,
        BEADS_SIDECAR_ROLE,
        PLANS_SIDECAR_ROLE,
        read_sdd_store_record,
    )

    if role in {PLANS_SIDECAR_ROLE, BEADS_SIDECAR_ROLE}:
        return True
    if role == AGENTS_SIDECAR_ROLE:
        return False
    try:
        record = read_sdd_store_record(primary_workspace_dir)
    except (OSError, RuntimeError, ValueError):
        record = None
    if record is not None and record.sidecar_for_kind(role) is not None:
        return True
    try:
        config = resolution_config(primary_workspace_dir, None)
        return role in configured_sidecar_roles(
            config,
            primary_workspace_dir=primary_workspace_dir,
        )
    except (OSError, RuntimeError, ValueError):
        return False
