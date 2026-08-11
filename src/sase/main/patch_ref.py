"""Implementation for ``sase patch ref``."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path

from sase.ace.patch import Patch
from sase.artifact_ref_lists import (
    ArtifactRefListEntry,
    artifact_ref_list_display_lines,
    normalize_artifact_ref_list,
    resolve_artifact_ref_list,
)
from sase.artifact_ref_models import ArtifactRefContext
from sase.main.patch_common import (
    command_prefix,
    file_location,
    patch_target,
    target_option,
)
from sase.main.patch_current import (
    CurrentContext,
)
from sase.vcs_provider import VCSProvider


def resolve_ref_patch(
    name: str | None,
    args: argparse.Namespace,
    *,
    find_all_patches_fn: Callable[[], list[Patch]],
    resolve_project_context_fn: Callable[[str | None], tuple[str | None, str | None]],
    get_current_provider_fn: Callable[[str], VCSProvider | None],
    get_current_branch_fn: Callable[[VCSProvider | None, str], str | None],
    get_current_change_url_fn: Callable[[VCSProvider | None, str], str | None],
    find_current_patch_fn: Callable[
        [list[Patch], CurrentContext, VCSProvider | None], list[Patch]
    ],
) -> Patch | None:
    """Resolve an explicit name or the current checkout to one Patch."""

    patches = find_all_patches_fn()
    if name:
        matches = [patch for patch in patches if patch.name == name]
        if not matches:
            print(
                f"[{command_prefix(args, 'ref')}] Patch not found: {name}",
                file=sys.stderr,
            )
            return None
        if len(matches) > 1:
            print(
                f"[{command_prefix(args, 'ref')}] multiple Patches are named {name}:",
                file=sys.stderr,
            )
            for patch in matches:
                print(f"  {file_location(patch)}", file=sys.stderr)
            return None
        return matches[0]

    project, project_file = resolve_project_context_fn(None)
    cwd = os.getcwd()
    provider = get_current_provider_fn(cwd)
    context = CurrentContext(
        project=project,
        project_file=project_file,
        branch=get_current_branch_fn(provider, cwd),
        change_url=get_current_change_url_fn(provider, cwd),
    )
    matches = find_current_patch_fn(patches, context, provider)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        print(
            f"[{command_prefix(args, 'ref')}] could not find a Patch for the "
            f"current checkout; pass {target_option(args)}.",
            file=sys.stderr,
        )
    else:
        print(
            f"[{command_prefix(args, 'ref')}] multiple Patches match the current "
            f"checkout; pass {target_option(args)}.",
            file=sys.stderr,
        )
    return None


def artifact_reference_context(project: str) -> ArtifactRefContext | None:
    """Build the current workspace's reference context without failing a read."""

    from sase.artifact_ref_context import artifact_ref_context
    from sase.sdd.plan_refs import workspace_context_for_plan_resolution

    try:
        workspace_dir, workspace_num = workspace_context_for_plan_resolution(Path.cwd())
        return artifact_ref_context(workspace_dir, workspace_num, project)
    except Exception:
        return None


def render_ref_list(
    patch: Patch,
    *,
    resolve: bool,
    as_json: bool,
    artifact_reference_context_fn: Callable[[str], ArtifactRefContext | None],
) -> int:
    refs = tuple(patch.refs or ())
    entries: tuple[ArtifactRefListEntry | str, ...]
    if resolve and refs:
        context = artifact_reference_context_fn(patch.project_basename)
        entries = (
            resolve_artifact_ref_list(refs, context=context)
            if context is not None
            else refs
        )
    else:
        entries = refs

    if as_json:
        rendered_entries: list[object]
        if resolve:
            rendered_entries = [
                (
                    entry.to_wire()
                    if isinstance(entry, ArtifactRefListEntry)
                    else {"rendered": entry, "resolution": None}
                )
                for entry in entries
            ]
        else:
            rendered_entries = list(entries)
        print(
            json.dumps(
                {
                    "count": len(entries),
                    "results": [
                        {
                            "patch": patch.name,
                            "refs": rendered_entries,
                        }
                    ],
                },
                indent=2,
            )
        )
        return 0

    lines = (
        artifact_ref_list_display_lines(entries)
        if resolve
        else tuple(str(entry) for entry in entries)
    )
    print("\n".join(lines) if lines else "No artifact references found.")
    return 0


def handle_ref(
    args: argparse.Namespace,
    *,
    resolve_ref_patch_fn: Callable[[str | None, argparse.Namespace], Patch | None],
    render_ref_list_fn: Callable[
        [Patch],
        int,
    ],
    update_patch_refs_field_fn: Callable[[str, str, tuple[str, ...]], bool],
) -> int:
    """Handle ``sase patch ref``."""
    patch = resolve_ref_patch_fn(patch_target(args), args)
    if patch is None:
        return 1

    if args.ref_action == "list":
        return render_ref_list_fn(patch)

    existing = tuple(patch.refs or ())
    try:
        requested = normalize_artifact_ref_list(args.refs)
        if args.ref_action == "add":
            updated = normalize_artifact_ref_list((*existing, *requested))
            verb = "Attached"
            changed = [reference for reference in updated if reference not in existing]
        else:
            removed = set(requested)
            updated = tuple(
                reference for reference in existing if reference not in removed
            )
            verb = "Detached"
            changed = [reference for reference in existing if reference in removed]
    except ValueError as exc:
        print(f"[{command_prefix(args, 'ref')}] {exc}", file=sys.stderr)
        return 1

    if not update_patch_refs_field_fn(
        patch.file_path,
        patch.name,
        updated,
    ):
        print(
            f"[{command_prefix(args, 'ref')}] failed to update {patch.name}",
            file=sys.stderr,
        )
        return 1

    print(
        f"{verb} {len(changed)} artifact reference"
        f"{'' if len(changed) == 1 else 's'} "
        f"{'to' if args.ref_action == 'add' else 'from'} {patch.name}."
    )
    return 0


__all__ = [
    "artifact_reference_context",
    "handle_ref",
    "render_ref_list",
    "resolve_ref_patch",
]
