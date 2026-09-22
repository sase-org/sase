"""Implementation and resolution helpers for ``sase repo open``."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import os
from pathlib import Path
import shlex
import sys
from typing import TYPE_CHECKING, Protocol

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
    RepoMatchResolution,
    RepoOpenResolutionError,
    clone_for_workspace,
    is_relative_to,
)
from .workspace_handler_context import ConfigLoader, ProjectContext

if TYPE_CHECKING:
    from .repo_open_external import ExternalProjectReference


class _CheckoutResolver(Protocol):
    def __call__(
        self,
        ctx: ProjectContext,
        workspace_num: int,
        *,
        materialize: bool,
    ) -> str: ...


MatchRepo = Callable[..., RepoMatchResolution]
RecordRepoOpen = Callable[..., None]
ResolveWorkspaceNum = Callable[[ProjectContext, int | None], int]
TargetContext = Callable[[ProjectContext, RepoRecord], ProjectContext]

_LINKED_REDIRECT_REASONS = {
    "remote_identity",
    "external_project_path",
    "external_project_remote",
}


def handle_open_command(
    args: argparse.Namespace,
    *,
    collect_inventory: InventoryCollector,
    resolve_project_context: ProjectContextResolver,
    resolve_checkout: _CheckoutResolver,
    resolve_workspace_num: ResolveWorkspaceNum,
    match_repo: MatchRepo,
    target_context: TargetContext,
    record_repo_open: RecordRepoOpen,
) -> int:
    from .repo_open_external import (
        ExternalProjectReference,
        ExternalRepoOpenError,
        open_external_repo,
        resolve_external_project_reference,
    )
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
        requested_repo = getattr(args, "repo", "")
        resolution = match_repo(
            requested_repo,
            host_ctx=host_ctx,
            inventory=inventory,
            workspace_num=workspace_num,
        )
    except (RepoInventoryProjectNotFoundError, RepoOpenResolutionError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    project_reference: ExternalProjectReference | None = None
    repo = resolution.record
    if repo is None:
        try:
            project_reference = resolve_external_project_reference(
                requested_repo,
                host_ctx=host_ctx,
            )
        except ExternalRepoOpenError as exc:
            print(str(exc), file=sys.stderr)
            return 2

        if project_reference is not None:
            try:
                resolution = match_repo(
                    requested_repo,
                    host_ctx=host_ctx,
                    inventory=inventory,
                    workspace_num=workspace_num,
                    external_project=_external_project_payload(project_reference),
                )
            except RepoOpenResolutionError as exc:
                print(str(exc), file=sys.stderr)
                return 2
            repo = resolution.record

    if repo is None:
        try:
            external = open_external_repo(
                requested_repo,
                host_ctx=host_ctx,
                workspace_num=workspace_num,
                inventory=inventory,
                reason=reason,
                resolve_checkout=resolve_checkout,
                project_reference=project_reference,
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
        _maybe_print_agents_hint(external.path, host_ctx=host_ctx)
        print(external.path)
        return 0

    target_ctx = target_context(host_ctx, repo)
    if target_ctx.is_machine_scoped_repo:
        try:
            clone_for_workspace(repo, workspace_num)
        except RepoOpenResolutionError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    path = prepare_opened_checkout(
        target_ctx,
        workspace_num,
        reason=reason,
        resolve_checkout=resolve_checkout,
        preparation="none",
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
    _print_linked_redirect_notice(
        resolution,
        repo=repo,
        host_ctx=host_ctx,
        path=path,
    )
    _maybe_print_agents_hint(path, host_ctx=host_ctx)
    print(path)
    return 0


def _external_project_payload(
    reference: ExternalProjectReference,
) -> dict[str, object]:
    return {
        "canonical_name": reference.canonical_name,
        "primary_path": reference.source_dir,
        "remote_urls": list(reference.remote_urls),
    }


def _print_linked_redirect_notice(
    resolution: RepoMatchResolution,
    *,
    repo: RepoRecord,
    host_ctx: ProjectContext,
    path: str,
) -> None:
    if repo.kind != "linked" or resolution.match_reason not in _LINKED_REDIRECT_REASONS:
        return
    reason = _linked_redirect_reason_text(resolution.match_reason)
    suggestion = f'sase repo open {shlex.quote(repo.name)} -r "<reason>"'
    print(
        f"Info: {resolution.requested!r} matches linked repo {repo.name!r} "
        f"in project {host_ctx.project_name!r}. Opened its configured checkout "
        f"at {path} so edits and repo tracking use the project's linked repo; "
        f"{reason}. Next time, use `{suggestion}`.",
        file=sys.stderr,
    )
    if resolution.external_collision_paths:
        collision_paths = ", ".join(resolution.external_collision_paths)
        print(
            "Warning: An external checkout of this repo also exists at "
            f"{collision_paths}. It was left untouched. Continue in the linked "
            "checkout printed on stdout; any work in the external copy remains there.",
            file=sys.stderr,
        )


def _maybe_print_agents_hint(path: str, *, host_ctx: ProjectContext) -> None:
    """Name an opened repo's AGENTS.md when one exists.

    Stdout stays exactly the path; the hint goes to stderr so scripts that
    capture stdout keep working. The caller's own checkout root gets no hint.
    """
    try:
        if Path(path).resolve(strict=False) == Path(
            host_ctx.primary_workspace_dir
        ).resolve(strict=False):
            return
    except OSError:
        return
    if (Path(path) / "AGENTS.md").is_file():
        print(
            f"Read {path}/AGENTS.md before working in this repo; "
            "it is not loaded automatically from here.",
            file=sys.stderr,
        )


def _linked_redirect_reason_text(match_reason: str | None) -> str:
    if match_reason == "external_project_path":
        return "the registered project's primary checkout is that linked repo"
    if match_reason == "external_project_remote":
        return "the registered project's primary checkout has the same supported remote identity"
    return "the requested reference has the same supported remote identity"


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
    from sase._linked_repo_config import HIDDEN_SIDECAR_ROLES

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
        is_machine_scoped_repo=(
            repo.kind == "sidecar" and repo.name in HIDDEN_SIDECAR_ROLES
        ),
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
