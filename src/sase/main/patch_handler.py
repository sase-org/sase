"""Handler facade for the ``sase patch`` subcommands.

``sase changespec`` remains a compatibility alias.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from sase.ace.deltas import refresh_deltas_for_patch as refresh_deltas_for_patch
from sase.ace.patch import Patch as Patch
from sase.ace.patch import find_all_patches as find_all_patches
from sase.ace.patch.refs_persistence import (
    update_patch_refs_field as update_patch_refs_field,
)
from sase.artifact_ref_models import ArtifactRefContext
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.main.patch_common import (
    command_name,
    resolve_project_context,
    resolve_project_file,
)
from sase.main.patch_current import (
    CurrentContext,
    find_current_patch as find_current_patch_impl,
    get_current_branch as get_current_branch_impl,
    get_current_change_url as get_current_change_url_impl,
    get_current_provider as get_current_provider_impl,
    handle_current as handle_current_impl,
)
from sase.main.patch_maintenance import (
    handle_migrate_extension as handle_migrate_extension_impl,
    handle_set_origin as handle_set_origin_impl,
    resolve_set_origin_patch as resolve_set_origin_patch_impl,
)
from sase.main.patch_ref import (
    artifact_reference_context as artifact_reference_context_impl,
    handle_ref as handle_ref_impl,
    render_ref_list as render_ref_list_impl,
    resolve_ref_patch as resolve_ref_patch_impl,
)
from sase.main.patch_sync import (
    handle_sync_deltas as handle_sync_deltas_impl,
    handle_sync_external as handle_sync_external_impl,
    select_sync_external_project as select_sync_external_project_impl,
)
from sase.output import console as console
from sase.vcs_provider import VCSProvider
from sase.vcs_provider import get_vcs_provider as get_vcs_provider
from sase.workflows.utils import get_project_file_path as get_project_file_path
from sase.workflows.utils import (
    get_project_from_workspace as get_project_from_workspace,
)


def list_project_records(*args: Any, **kwargs: Any) -> Any:
    """Facade injection seam for ``patch sync-external`` project discovery."""
    from sase.core.project_lifecycle_facade import list_project_records as impl

    return impl(*args, **kwargs)


def ensure_lumberjack_dirs(name: str) -> Path:
    """Facade injection seam for ``patch sync-external`` state directories."""
    from sase.axe.state import ensure_lumberjack_dirs as impl

    return impl(name)


def sase_projects_dir() -> Path:
    """Facade injection seam for project lifecycle storage lookup."""
    from sase.core.paths import sase_projects_dir as impl

    return impl()


def resolve_project_alias_ref(value: str) -> str:
    """Facade injection seam for project alias resolution."""
    from sase.project_aliases import resolve_project_alias_ref as impl

    return impl(value)


def sync_external_pull_requests(**kwargs: Any) -> Any:
    """Facade injection seam for external PR mirroring."""
    from sase.external_mirror.pr_sync import sync_external_pull_requests as impl

    return impl(**kwargs)


def _resolve_project_file(explicit: str | None) -> str | None:
    return resolve_project_file(
        explicit,
        get_project_from_workspace_fn=get_project_from_workspace,
        get_project_file_path_fn=get_project_file_path,
    )


def _command_name(args: argparse.Namespace) -> str:
    return command_name(args)


def _resolve_project_context(
    explicit: str | None,
) -> tuple[str | None, str | None]:
    return resolve_project_context(
        explicit,
        get_project_from_workspace_fn=get_project_from_workspace,
        get_project_file_path_fn=get_project_file_path,
    )


def _get_current_provider(cwd: str) -> VCSProvider | None:
    return get_current_provider_impl(
        cwd,
        get_vcs_provider_fn=get_vcs_provider,
    )


def _get_current_branch(provider: VCSProvider | None, cwd: str) -> str | None:
    return get_current_branch_impl(provider, cwd)


def _get_current_change_url(provider: VCSProvider | None, cwd: str) -> str | None:
    return get_current_change_url_impl(provider, cwd)


def _find_current_patch(
    patches: list[Patch],
    context: CurrentContext,
    provider: VCSProvider | None,
) -> list[Patch]:
    return find_current_patch_impl(patches, context, provider)


def _handle_current(args: argparse.Namespace) -> int:
    return handle_current_impl(
        args,
        find_all_patches_fn=find_all_patches,
        resolve_project_context_fn=_resolve_project_context,
        get_current_provider_fn=_get_current_provider,
        get_current_branch_fn=_get_current_branch,
        get_current_change_url_fn=_get_current_change_url,
        find_current_patch_fn=_find_current_patch,
    )


def _resolve_ref_patch(name: str | None, args: argparse.Namespace) -> Patch | None:
    return resolve_ref_patch_impl(
        name,
        args,
        find_all_patches_fn=find_all_patches,
        resolve_project_context_fn=_resolve_project_context,
        get_current_provider_fn=_get_current_provider,
        get_current_branch_fn=_get_current_branch,
        get_current_change_url_fn=_get_current_change_url,
        find_current_patch_fn=_find_current_patch,
    )


def _artifact_reference_context(project: str) -> ArtifactRefContext | None:
    return artifact_reference_context_impl(project)


def _render_ref_list(patch: Patch, *, resolve: bool, as_json: bool) -> int:
    return render_ref_list_impl(
        patch,
        resolve=resolve,
        as_json=as_json,
        artifact_reference_context_fn=_artifact_reference_context,
    )


def _handle_ref(args: argparse.Namespace) -> int:
    return handle_ref_impl(
        args,
        resolve_ref_patch_fn=_resolve_ref_patch,
        render_ref_list_fn=lambda patch: _render_ref_list(
            patch,
            resolve=bool(args.resolve),
            as_json=bool(args.json),
        ),
        update_patch_refs_field_fn=update_patch_refs_field,
    )


def _handle_sync_deltas(args: argparse.Namespace) -> int:
    return handle_sync_deltas_impl(
        args,
        resolve_project_file_fn=_resolve_project_file,
        refresh_deltas_for_patch_fn=refresh_deltas_for_patch,
    )


def _select_sync_external_project(
    records: list[ProjectRecordWire],
    project_ref: str,
) -> ProjectRecordWire | None:
    return select_sync_external_project_impl(records, project_ref)


def _handle_sync_external(args: argparse.Namespace) -> int:
    return handle_sync_external_impl(
        args,
        ensure_lumberjack_dirs_fn=ensure_lumberjack_dirs,
        get_vcs_provider_fn=get_vcs_provider,
        list_project_records_fn=list_project_records,
        projects_dir_fn=sase_projects_dir,
        resolve_project_alias_ref_fn=resolve_project_alias_ref,
        select_sync_external_project_fn=_select_sync_external_project,
        sync_external_pull_requests_fn=sync_external_pull_requests,
        console_obj=console,
    )


def _resolve_set_origin_patch(
    name: str,
    project_file: str | None,
    args: argparse.Namespace,
) -> Patch | None:
    return resolve_set_origin_patch_impl(
        name,
        project_file,
        args,
        find_all_patches_fn=find_all_patches,
    )


def _handle_set_origin(args: argparse.Namespace) -> int:
    return handle_set_origin_impl(
        args,
        resolve_set_origin_patch_fn=_resolve_set_origin_patch,
    )


def _handle_migrate_extension(args: argparse.Namespace) -> int:
    return handle_migrate_extension_impl(args)


def handle_patch_command(args: argparse.Namespace) -> None:
    """Dispatch ``sase patch`` subcommands."""
    sub = getattr(args, "patch_subcommand", None) or getattr(
        args, "changespec_subcommand", None
    )
    if sub == "current":
        sys.exit(_handle_current(args))
    if sub == "search":
        from .search_handler import handle_search_command

        handle_search_command(args)
        return
    if sub == "ref":
        sys.exit(_handle_ref(args))
    if sub == "sync-deltas":
        sys.exit(_handle_sync_deltas(args))
    if sub == "sync-external":
        sys.exit(_handle_sync_external(args))
    if sub == "set-origin":
        sys.exit(_handle_set_origin(args))
    if sub == "migrate-extension":
        sys.exit(_handle_migrate_extension(args))
    print(
        f"Usage: sase {_command_name(args)} "
        "{current,migrate-extension,ref,search,set-origin,sync-deltas,sync-external} [-h]",
        file=sys.stderr,
    )
    sys.exit(1)


handle_patch_command = handle_patch_command


__all__ = [
    "_artifact_reference_context",
    "_handle_current",
    "_handle_migrate_extension",
    "_handle_ref",
    "_handle_set_origin",
    "_handle_sync_deltas",
    "_handle_sync_external",
    "handle_patch_command",
]
