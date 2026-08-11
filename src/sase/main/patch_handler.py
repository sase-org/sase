"""Handler for the ``sase patch`` subcommands.

``sase changespec`` remains a compatibility alias.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sase.ace.patch import Patch, find_all_patches
from sase.ace.patch.refs_persistence import update_patch_refs_field
from sase.ace.deltas import refresh_deltas_for_patch
from sase.artifact_ref_lists import (
    ArtifactRefListEntry,
    artifact_ref_list_display_lines,
    normalize_artifact_ref_list,
    resolve_artifact_ref_list,
)
from sase.artifact_ref_models import ArtifactRefContext
from sase.core.patch import (
    patch_name_to_branch,
    patch_name_to_branch_with_suffix,
    strip_reverted_suffix,
)
from sase.core.project_lifecycle_wire import ProjectRecordWire
from sase.project_display_names import humanize_cl_name, project_display_name_for
from sase.vcs_provider import VCSProvider, get_vcs_provider
from sase.workflows.utils import get_project_file_path, get_project_from_workspace

find_all_patches = find_all_patches


@dataclass(frozen=True)
class _CurrentContext:
    project: str | None
    project_file: str | None
    branch: str | None
    change_url: str | None


def _resolve_project_file(explicit: str | None) -> str | None:
    """Resolve the project file path from --project-file or workspace inference."""
    if explicit:
        return os.path.expanduser(explicit)
    project = get_project_from_workspace()
    if not project:
        return None
    return get_project_file_path(project)


def _project_from_project_file(project_file: str | None) -> str | None:
    """Return the project basename for a main or archive project file path."""
    if not project_file:
        return None
    stem = Path(project_file).expanduser().stem
    if stem.endswith("-archive"):
        return stem[: -len("-archive")]
    return stem


Patch = Patch


def _command_name(args: argparse.Namespace) -> str:
    command = getattr(args, "command", "patch")
    return "patch" if command == "patch" else "patch"


def _command_prefix(args: argparse.Namespace, subcommand: str) -> str:
    return f"sase {_command_name(args)} {subcommand}"


def _target_option(args: argparse.Namespace) -> str:
    return "-c/--changespec" if _command_name(args) == "changespec" else "-p/--patch"


def _patch_target(args: argparse.Namespace) -> str | None:
    return getattr(args, "patch", None) or getattr(args, "patch", None)


def _resolve_project_context(explicit: str | None) -> tuple[str | None, str | None]:
    """Resolve project and project-file context for ``patch current``."""
    if explicit:
        explicit_project_file = os.path.expanduser(explicit)
        return _project_from_project_file(explicit_project_file), explicit_project_file
    project = get_project_from_workspace()
    project_file: str | None = get_project_file_path(project) if project else None
    return project, project_file


def _get_current_provider(cwd: str) -> VCSProvider | None:
    """Best-effort VCS provider lookup."""
    try:
        return get_vcs_provider(cwd)
    except Exception:
        return None


def _get_current_branch(provider: VCSProvider | None, cwd: str) -> str | None:
    """Best-effort current branch/bookmark lookup."""
    if provider is None:
        return None
    try:
        ok, branch = provider.get_branch_name(cwd)
    except Exception:
        return None
    return branch if ok and branch else None


def _get_current_change_url(provider: VCSProvider | None, cwd: str) -> str | None:
    """Best-effort current PR URL lookup."""
    if provider is None:
        return None
    try:
        ok, url = provider.get_change_url(cwd)
    except Exception:
        return None
    return url if ok and url else None


def _normalize_branch_name(branch: str) -> str:
    """Normalize common ref prefixes for branch candidate comparison."""
    normalized = branch
    for prefix in ("refs/heads/", "refs/remotes/", "origin/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized


def _add_if_present(values: set[str], value: str | None) -> None:
    """Add a non-empty candidate string."""
    if value:
        values.add(value)


def _branch_candidates_for_patch(cs: Patch, provider: VCSProvider | None) -> set[str]:
    """Build branch/name spellings that can identify ``cs``."""
    project = cs.project_basename
    prefix = f"{project}_"
    stripped_prefix = cs.name[len(prefix) :] if cs.name.startswith(prefix) else cs.name
    stripped_suffix = strip_reverted_suffix(cs.name)
    stripped_both = (
        stripped_suffix[len(prefix) :]
        if stripped_suffix.startswith(prefix)
        else stripped_suffix
    )

    candidates: set[str] = set()
    for value in (
        cs.name,
        stripped_prefix,
        stripped_suffix,
        stripped_both,
        stripped_prefix.replace("_", "-"),
        stripped_both.replace("_", "-"),
        patch_name_to_branch(cs.name, project),
        patch_name_to_branch_with_suffix(cs.name, project),
    ):
        _add_if_present(candidates, value)

    if provider is not None:
        for method_name in ("derive_branch_name", "derive_branch_name_with_suffix"):
            try:
                derived = getattr(provider, method_name)(cs.name, project)
            except Exception:
                derived = None
            _add_if_present(candidates, derived)

    normalized: set[str] = set()
    for candidate in candidates:
        normalized.add(candidate)
        normalized.add(_normalize_branch_name(candidate))
    return normalized


def _scoped_patches(patches: list[Patch], project: str | None) -> list[Patch]:
    """Limit Patches to the current project when one is known."""
    if not project:
        return patches
    return [cs for cs in patches if cs.project_basename == project]


def _dedupe_patches(patches: list[Patch]) -> list[Patch]:
    """Deduplicate matched Patches without changing order."""
    seen: set[tuple[str, str, int]] = set()
    deduped: list[Patch] = []
    for cs in patches:
        key = (cs.name, cs.file_path, cs.line_number)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cs)
    return deduped


def _find_current_patch(
    patches: list[Patch],
    context: _CurrentContext,
    provider: VCSProvider | None,
) -> list[Patch]:
    """Resolve the current checkout to matching Patches."""
    scoped = _scoped_patches(patches, context.project)

    if context.change_url:
        url_matches = [cs for cs in scoped if cs.pr_url == context.change_url]
        if url_matches:
            return _dedupe_patches(url_matches)

    if context.branch:
        branch = _normalize_branch_name(context.branch)
        branch_matches = [
            cs for cs in scoped if branch in _branch_candidates_for_patch(cs, provider)
        ]
        if branch_matches:
            return _dedupe_patches(branch_matches)

    return []


def _file_location(cs: Patch) -> str:
    """Return a user-facing file:line location."""
    file_path = cs.file_path.replace(str(Path.home()), "~")
    return f"{file_path}:{cs.line_number}"


def _patch_payload(cs: Patch) -> dict[str, object]:
    """Stable JSON-serializable representation for ``patch current``."""
    return {
        "name": cs.name,
        "project": cs.project_basename,
        "status": cs.status,
        "parent": cs.parent,
        "cl": cs.pr_url,
        "refs": list(cs.refs or ()),
        "file_path": cs.file_path,
        "line_number": cs.line_number,
    }


def _display_current_markdown(cs: Patch) -> None:
    """Print one Patch in compact agent-friendly markdown."""
    print("# Current Patch")
    print("")
    print(f"## {humanize_cl_name(cs.name)}")
    print("")
    print(f"- **Project:** {project_display_name_for(cs.project_basename)}")
    print(f"- **Status:** {cs.status}")
    print(f"- **Parent:** {humanize_cl_name(cs.parent) if cs.parent else 'None'}")
    print(f"- **PR:** {cs.pr_url or 'None'}")
    print(f"- **Location:** `{_file_location(cs)}`")
    if cs.refs:
        print("")
        print("## References")
        print("")
        for reference in cs.refs:
            print(f"- `{reference}`")


def _display_current_plain(cs: Patch) -> None:
    """Print one Patch as stable key/value lines."""
    print(f"NAME: {humanize_cl_name(cs.name)}")
    print(f"PROJECT: {project_display_name_for(cs.project_basename)}")
    print(f"STATUS: {cs.status}")
    print(f"PARENT: {humanize_cl_name(cs.parent) if cs.parent else 'None'}")
    print(f"PR: {cs.pr_url or 'None'}")
    if cs.refs:
        print("REFS:")
        for reference in cs.refs:
            print(f"  {reference}")
    print(f"FILE: {cs.file_path}")
    print(f"LINE: {cs.line_number}")


def _display_current_json(cs: Patch) -> None:
    """Print one Patch as JSON."""
    print(json.dumps(_patch_payload(cs), sort_keys=True))


def _diagnostic_lines(context: _CurrentContext) -> list[str]:
    """Diagnostic context for resolver failures."""
    return [
        f"project: {project_display_name_for(context.project) if context.project else 'unknown'}",
        f"project_file: {context.project_file or 'unknown'}",
        f"branch: {context.branch or 'unknown'}",
        f"change_url: {context.change_url or 'unknown'}",
    ]


def _handle_current(args: argparse.Namespace) -> int:
    project, project_file = _resolve_project_context(args.project_file)
    cwd = os.getcwd()
    provider = _get_current_provider(cwd)
    context = _CurrentContext(
        project=project,
        project_file=project_file,
        branch=_get_current_branch(provider, cwd),
        change_url=_get_current_change_url(provider, cwd),
    )

    matches = _find_current_patch(find_all_patches(), context, provider)
    if not matches:
        print(
            f"[{_command_prefix(args, 'current')}] could not find a Patch "
            "for the current checkout.",
            file=sys.stderr,
        )
        for line in _diagnostic_lines(context):
            print(f"  {line}", file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(
            f"[{_command_prefix(args, 'current')}] multiple Patches match "
            "the current checkout:",
            file=sys.stderr,
        )
        for cs in matches:
            print(
                f"  {humanize_cl_name(cs.name)} ({_file_location(cs)})",
                file=sys.stderr,
            )
        for line in _diagnostic_lines(context):
            print(f"  {line}", file=sys.stderr)
        return 1

    cs = matches[0]
    if args.format == "json":
        _display_current_json(cs)
    elif args.format == "plain":
        _display_current_plain(cs)
    else:
        _display_current_markdown(cs)
    return 0


def _resolve_ref_patch(name: str | None, args: argparse.Namespace) -> Patch | None:
    """Resolve an explicit name or the current checkout to one Patch."""

    patches = find_all_patches()
    if name:
        matches = [patch for patch in patches if patch.name == name]
        if not matches:
            print(
                f"[{_command_prefix(args, 'ref')}] Patch not found: {name}",
                file=sys.stderr,
            )
            return None
        if len(matches) > 1:
            print(
                f"[{_command_prefix(args, 'ref')}] multiple Patches are named {name}:",
                file=sys.stderr,
            )
            for patch in matches:
                print(f"  {_file_location(patch)}", file=sys.stderr)
            return None
        return matches[0]

    project, project_file = _resolve_project_context(None)
    cwd = os.getcwd()
    provider = _get_current_provider(cwd)
    context = _CurrentContext(
        project=project,
        project_file=project_file,
        branch=_get_current_branch(provider, cwd),
        change_url=_get_current_change_url(provider, cwd),
    )
    matches = _find_current_patch(patches, context, provider)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        print(
            f"[{_command_prefix(args, 'ref')}] could not find a Patch for the "
            f"current checkout; pass {_target_option(args)}.",
            file=sys.stderr,
        )
    else:
        print(
            f"[{_command_prefix(args, 'ref')}] multiple Patches match the current "
            f"checkout; pass {_target_option(args)}.",
            file=sys.stderr,
        )
    return None


def _artifact_reference_context(project: str) -> ArtifactRefContext | None:
    """Build the current workspace's reference context without failing a read."""

    from sase.artifact_ref_context import artifact_ref_context
    from sase.sdd.plan_refs import workspace_context_for_plan_resolution

    try:
        workspace_dir, workspace_num = workspace_context_for_plan_resolution(Path.cwd())
        return artifact_ref_context(workspace_dir, workspace_num, project)
    except Exception:
        return None


def _render_ref_list(patch: Patch, *, resolve: bool, as_json: bool) -> int:
    refs = tuple(patch.refs or ())
    entries: tuple[ArtifactRefListEntry | str, ...]
    if resolve and refs:
        context = _artifact_reference_context(patch.project_basename)
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


def _handle_ref(args: argparse.Namespace) -> int:
    patch = _resolve_ref_patch(_patch_target(args), args)
    if patch is None:
        return 1

    if args.ref_action == "list":
        return _render_ref_list(
            patch,
            resolve=bool(args.resolve),
            as_json=bool(args.json),
        )

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
        print(f"[{_command_prefix(args, 'ref')}] {exc}", file=sys.stderr)
        return 1

    if not update_patch_refs_field(
        patch.file_path,
        patch.name,
        updated,
    ):
        print(
            f"[{_command_prefix(args, 'ref')}] failed to update {patch.name}",
            file=sys.stderr,
        )
        return 1

    print(
        f"{verb} {len(changed)} artifact reference"
        f"{'' if len(changed) == 1 else 's'} "
        f"{'to' if args.ref_action == 'add' else 'from'} {patch.name}."
    )
    return 0


def _handle_sync_deltas(args: argparse.Namespace) -> int:
    project_file = _resolve_project_file(args.project_file)
    if not project_file:
        print(
            f"[{_command_prefix(args, 'sync-deltas')}] could not infer project file; "
            "pass -p/--project-file or run inside a sase workspace.",
            file=sys.stderr,
        )
        return 1
    if not os.path.isfile(project_file):
        print(
            f"[{_command_prefix(args, 'sync-deltas')}] project file not found: "
            f"{project_file}",
            file=sys.stderr,
        )
        return 1

    workspace_dir = args.workspace_dir or os.getcwd()
    ok = refresh_deltas_for_patch(project_file, args.cl_name, workspace_dir)
    if ok:
        print(f"DELTAS refreshed for {args.cl_name} in {project_file}")
        return 0
    print(
        f"[{_command_prefix(args, 'sync-deltas')}] failed to refresh DELTAS for "
        f"{args.cl_name}; "
        "DELTAS preserved as-is. See logs for details.",
        file=sys.stderr,
    )
    return 1


def _handle_sync_external(args: argparse.Namespace) -> int:
    from rich.table import Table

    from sase.axe.state import ensure_lumberjack_dirs
    from sase.core.paths import sase_projects_dir
    from sase.core.project_lifecycle_facade import list_project_records
    from sase.core.project_lifecycle_wire import effective_project_name
    from sase.external_mirror.pr_sync import sync_external_pull_requests
    from sase.output import console
    from sase.project_aliases import resolve_project_alias_ref

    records = [
        record
        for record in list_project_records(
            sase_projects_dir(),
            "enabled",
            include_home=False,
            projects_only=True,
        )
        if record.is_project and record.vcs_kind in {"git", "gh"}
    ]
    if args.project:
        selected = _select_sync_external_project(
            records,
            resolve_project_alias_ref(str(args.project)),
        )
        if selected is None:
            print(
                f"[{_command_prefix(args, 'sync-external')}] project not found: "
                f"{args.project}",
                file=sys.stderr,
            )
            return 1
        records = [selected]

    if args.dry_run:
        console.print("[bold yellow]Dry run:[/bold yellow] no Patches will be written.")

    state_dir = ensure_lumberjack_dirs("checks")
    table = Table(title="External PR Mirror")
    table.add_column("Project", style="cyan")
    table.add_column("Fetched", justify="right")
    table.add_column("Adopted", justify="right", style="green")
    table.add_column("Repaired", justify="right", style="green")
    table.add_column("Skipped", justify="right")
    table.add_column("Errors", justify="right", style="red")
    table.add_column("Reason")

    exit_code = 0
    for record in sorted(records, key=lambda item: effective_project_name(item)):
        project_label = effective_project_name(record)
        if not record.workspace_dir:
            table.add_row(project_label, "0", "0", "0", "0", "1", "missing_workspace")
            exit_code = 1
            continue
        try:
            provider = get_vcs_provider(record.workspace_dir)
            report = sync_external_pull_requests(
                project_key=record.project_name,
                workspace_dir=record.workspace_dir,
                state_dir=state_dir,
                provider=provider,
                now=datetime.now(UTC),
                dry_run=bool(args.dry_run),
                full=bool(args.full),
            )
        except Exception as exc:  # noqa: BLE001 - CLI reports per-project failures.
            table.add_row(project_label, "0", "0", "0", "0", "1", str(exc))
            exit_code = 1
            continue
        if report.errors:
            exit_code = 1
        table.add_row(
            project_label,
            str(report.fetched),
            str(report.created),
            str(report.repaired),
            str(report.skipped),
            str(report.errors),
            report.reason() or "",
        )

    console.print(table)
    return exit_code


def _select_sync_external_project(
    records: list[ProjectRecordWire],
    project_ref: str,
) -> ProjectRecordWire | None:
    from sase.core.project_lifecycle_wire import effective_project_name

    folded = project_ref.casefold()
    for record in records:
        if record.project_name == project_ref:
            return record
    for record in records:
        if effective_project_name(record).casefold() == folded:
            return record
        if any(alias.casefold() == folded for alias in record.aliases):
            return record
    return None


def _resolve_set_origin_patch(
    name: str, project_file: str | None, args: argparse.Namespace
) -> Patch | None:
    """Resolve the named Patch, scoped to a project file when given."""

    if project_file:
        from sase.ace.patch import parse_project_file

        resolved_project_file = os.path.expanduser(project_file)
        if not os.path.isfile(resolved_project_file):
            print(
                f"[{_command_prefix(args, 'set-origin')}] project file not found: "
                f"{resolved_project_file}",
                file=sys.stderr,
            )
            return None
        patches = parse_project_file(resolved_project_file)
    else:
        patches = find_all_patches()

    matches = [patch for patch in patches if patch.name == name]
    if not matches:
        print(
            f"[{_command_prefix(args, 'set-origin')}] Patch not found: {name}",
            file=sys.stderr,
        )
        return None
    if len(matches) > 1:
        print(
            f"[{_command_prefix(args, 'set-origin')}] multiple Patches are named "
            f"{name}:",
            file=sys.stderr,
        )
        for patch in matches:
            print(f"  {_file_location(patch)}", file=sys.stderr)
        return None
    return matches[0]


def _handle_set_origin(args: argparse.Namespace) -> int:
    from sase.status_state_machine import update_patch_pr_origin_atomic

    patch = _resolve_set_origin_patch(args.name, args.project_file, args)
    if patch is None:
        return 1

    update_patch_pr_origin_atomic(patch.file_path, patch.name, args.origin)
    print(f"PR_ORIGIN set to {args.origin} for {humanize_cl_name(patch.name)}")
    return 0


def _handle_migrate_extension(args: argparse.Namespace) -> int:
    """Run the ``.gp`` → ``.sase`` migration helper."""
    from pathlib import Path

    from sase.ace.patch.project_spec_migration import migrate_all_projects

    projects_dir = Path(args.projects_dir).expanduser() if args.projects_dir else None
    report = migrate_all_projects(projects_dir, force=bool(args.force))

    for legacy, canonical in report.migrated:
        print(f"renamed {legacy} -> {canonical}")
    for legacy in report.skipped_identical:
        print(f"skipped (identical canonical sibling): {legacy}")
    for legacy, reason in report.conflicts:
        print(f"conflict: {legacy}: {reason}", file=sys.stderr)

    print(
        f"migrated={report.migrated_count} "
        f"skipped={report.skipped_count} "
        f"conflicts={report.conflict_count}"
    )
    return 0 if report.conflict_count == 0 else 1


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
    "_handle_ref",
    "handle_patch_command",
    "handle_patch_command",
]
