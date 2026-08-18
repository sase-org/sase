"""Noninteractive Patch operation runners."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any

from sase.ops.cli import add_operation_io_flags, load_request
from sase.ops.commands.common import run_and_finish
from sase.ops.names import (
    PATCH_ACCEPT,
    PATCH_ARCHIVE,
    PATCH_MAIL,
    PATCH_REBASE,
    PATCH_RESTORE,
    PATCH_REVERT,
    PATCH_REWIND,
    PATCH_REWORD,
    PATCH_STATUS,
    PATCH_SUBMIT,
    PATCH_SYNC,
    PATCH_TAG,
)


def add_patch_operation_parsers(subparsers: argparse._SubParsersAction) -> None:
    """Register focused noninteractive Patch operation commands."""
    _status = subparsers.add_parser(
        "status",
        help="Transition a Patch STATUS through the domain state machine",
        description=(
            "Apply a Patch STATUS transition by name. Required identifiers are "
            "positional; optional project and operation sidecars use flags."
        ),
    )
    _status.add_argument("name", help="Patch NAME to transition")
    _status.add_argument("status", help="Target STATUS (WIP, Draft, Ready, ...)")
    _add_project_and_io(_status)
    _status.set_defaults(changespec_subcommand="status", patch_subcommand="status")

    for verb, help_text, extra in (
        ("accept", "Accept proposal commits onto a Patch", (("entries", True),)),
        ("archive", "Archive a Patch", ()),
        ("mail", "Mail a Ready Patch", ()),
        ("rebase", "Rebase a Patch onto a new parent", (("parent", True),)),
        ("restore", "Restore a Reverted Patch", (("status", False),)),
        ("revert", "Revert a Patch", ()),
        ("rewind", "Rewind a Patch to a history entry", (("entry", True),)),
        ("reword", "Reword a Patch description from the request sidecar", ()),
        ("submit", "Submit a Patch", ()),
        ("sync", "Sync a Patch workspace from its VCS remote", ()),
        ("tag", "Add a tag to a Patch description", (("tag", True), ("value", False))),
    ):
        parser = subparsers.add_parser(verb, help=help_text, description=help_text)
        parser.add_argument("name", help="Patch NAME")
        for dest, required in extra:
            if dest == "entries":
                continue
            kwargs: dict[str, Any] = {"help": dest}
            if not required:
                kwargs["nargs"] = "?"
            parser.add_argument(dest, **kwargs)
        _add_project_and_io(parser)
        parser.set_defaults(changespec_subcommand=verb, patch_subcommand=verb)


def handle_patch_operation(args: argparse.Namespace) -> int:
    """Dispatch one focused Patch operation command."""
    verb = getattr(args, "patch_subcommand", None) or getattr(
        args, "changespec_subcommand", None
    )
    runners = {
        "accept": (PATCH_ACCEPT, lambda: _run_accept(args)),
        "archive": (PATCH_ARCHIVE, lambda: _run_archive(args)),
        "mail": (PATCH_MAIL, lambda: _run_mail(args)),
        "rebase": (PATCH_REBASE, lambda: _run_rebase(args)),
        "restore": (PATCH_RESTORE, lambda: _run_restore(args)),
        "revert": (PATCH_REVERT, lambda: _run_revert(args)),
        "rewind": (PATCH_REWIND, lambda: _run_rewind(args)),
        "reword": (PATCH_REWORD, lambda: _run_reword(args)),
        "status": (PATCH_STATUS, lambda: _run_status(args)),
        "submit": (PATCH_SUBMIT, lambda: _run_submit(args)),
        "sync": (PATCH_SYNC, lambda: _run_sync(args)),
        "tag": (PATCH_TAG, lambda: _run_tag(args)),
    }
    if verb not in runners:
        return 2
    operation, body = runners[verb]
    return run_and_finish(operation=operation, body=body, args=args)


def _add_project_and_io(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-p",
        "--project-file",
        dest="project_file",
        default=None,
        help="Path to the project .sase file (default: inferred from the workspace)",
    )
    add_operation_io_flags(parser)


def _project_file(args: argparse.Namespace) -> str:
    from sase.main.patch_common import resolve_project_file
    from sase.workflows.utils import get_project_file_path, get_project_from_workspace

    path = resolve_project_file(
        getattr(args, "project_file", None),
        get_project_from_workspace_fn=get_project_from_workspace,
        get_project_file_path_fn=get_project_file_path,
    )
    if not path:
        raise RuntimeError("could not resolve the project file")
    return path


def _project_basename(project_file: str) -> str:
    from sase.ace.patch.project_spec_path import project_spec_basename

    return project_spec_basename(project_file)


def _run_status(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from rich.console import Console

    from sase.core.status_facade import transition_patch_status
    from sase.project_display_names import humanize_cl_name

    project_file = _project_file(args)
    success, old_status, error, siblings = transition_patch_status(
        project_file, args.name, args.status, validate=False, console=Console()
    )
    if not success:
        return False, error or f"Failed to transition {args.name}", {}
    msg_parts = [f"Status updated: {old_status} -> {args.status}"]
    reverted = [humanize_cl_name(item.name) for item in siblings if item.success]
    failed = [humanize_cl_name(item.name) for item in siblings if not item.success]
    if reverted:
        msg_parts.append(f"Auto-reverted siblings: {', '.join(reverted)}")
    if failed:
        msg_parts.append(f"Failed to revert: {', '.join(failed)}")
    return (
        True,
        "\n".join(msg_parts),
        {
            "name": args.name,
            "old_status": old_status,
            "status": args.status,
            "sibling_count": len(siblings),
        },
    )


def _run_submit(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from sase.workspace_provider import submit_patch
    from rich.console import Console

    project_file = _project_file(args)
    success, error = submit_patch(
        project_file, args.name, _project_basename(project_file), Console()
    )
    if not success:
        return False, error or f"Failed to submit {args.name}", {}
    return True, f"Submitted {args.name}", {"name": args.name}


def _run_archive(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from sase.ace.archive import archive_patch
    from rich.console import Console

    project_file = _project_file(args)
    patch = _load_patch(project_file, args.name)
    success, error = archive_patch(patch, Console())
    if not success:
        return False, error or f"Failed to archive {args.name}", {}
    return True, f"Archived {args.name}", {"name": args.name}


def _run_restore(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from rich.console import Console

    from sase.ace.restore import restore_patch
    from sase.core.patch import strip_reverted_suffix
    from sase.core.status_facade import transition_patch_status

    project_file = _project_file(args)
    target = getattr(args, "status", None) or "WIP"
    patch = _load_patch(project_file, args.name)
    success, error = restore_patch(patch, Console())
    if not success:
        return False, error or f"Failed to restore {args.name}", {}
    if target in ("Draft", "Ready"):
        from sase.ace.patch import parse_project_file

        base_name = strip_reverted_suffix(args.name)
        restored = next(
            (
                item
                for item in parse_project_file(project_file)
                if strip_reverted_suffix(item.name) == base_name
                and item.status == "WIP"
            ),
            None,
        )
        if restored is not None:
            moved, _, move_error, _ = transition_patch_status(
                project_file, restored.name, target, validate=False
            )
            if not moved:
                return (
                    False,
                    move_error or f"Restored but failed to transition to {target}",
                    {},
                )
    return True, f"Restored {args.name}", {"name": args.name, "status": target}


def _run_revert(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from rich.console import Console

    from sase.ace.revert import revert_patch

    project_file = _project_file(args)
    patch = _load_patch(project_file, args.name)
    success, error = revert_patch(patch, Console())
    if not success:
        return False, error or f"Failed to revert {args.name}", {}
    return True, f"Reverted {args.name}", {"name": args.name}


def _run_reword(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from sase.ace.handlers.reword import reword_execute_task

    request = load_request(PATCH_REWORD, args, required=True)
    description = request.payload.get("description")
    if not isinstance(description, str) or not description.strip():
        return False, "reword request payload must include description", {}
    project_file = _project_file(args)
    success, message = reword_execute_task(
        args.name, project_file, _project_basename(project_file), description
    )
    return success, message, {"name": args.name}


def _run_tag(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from sase.ace.handlers.reword import add_tag_task

    request = load_request(PATCH_TAG, args)
    tag = getattr(args, "tag", None) or request.payload.get("tag")
    value = getattr(args, "value", None) or request.payload.get("value") or ""
    if not isinstance(tag, str) or not tag:
        return False, "tag name is required", {}
    project_file = _project_file(args)
    success, message = add_tag_task(
        args.name,
        project_file,
        _project_basename(project_file),
        tag,
        str(value),
    )
    return success, message, {"name": args.name, "tag": tag, "value": value}


def _run_mail(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from sase.ace.handlers.mail import mail_execute_task
    from sase.running_field import (
        WorkspaceClaimError,
        claim_next_axe_workspace_dir,
        claim_workspace,
        get_workspace_directory_for_num,
        release_workspace,
    )

    request = load_request(PATCH_MAIL, args)
    project_file = _project_file(args)
    patch = _load_patch(project_file, args.name)
    workspace_num = request.payload.get("workspace_num")
    workspace_dir = request.payload.get("workspace_dir")
    settlement_owns_release = bool(request.payload.get("settlement_owns_release", True))
    if workspace_num is None:
        try:
            workspace_num, resolved_dir, _ = claim_next_axe_workspace_dir(
                project_file,
                "mail",
                __import__("os").getpid(),
                _project_basename(project_file),
                cl_name=args.name,
            )
        except WorkspaceClaimError as exc:
            return False, str(exc), {}
        if not isinstance(workspace_dir, str) or not workspace_dir:
            workspace_dir = resolved_dir
    else:
        workspace_num = int(workspace_num)
        if not isinstance(workspace_dir, str) or not workspace_dir:
            claimed = claim_workspace(
                project_file,
                workspace_num,
                "mail",
                __import__("os").getpid(),
                args.name,
            )
            if not claimed.success:
                return False, claimed.error or "failed to claim workspace", {}
            try:
                workspace_dir, _ = get_workspace_directory_for_num(
                    workspace_num, _project_basename(project_file)
                )
            except RuntimeError as exc:
                if not settlement_owns_release:
                    release_workspace(project_file, workspace_num, "mail", args.name)
                return False, str(exc), {}
    success, message = mail_execute_task(
        patch,
        str(workspace_dir),
        workspace_num,
        release=not settlement_owns_release,
    )
    return success, message, {"name": args.name}


def _run_accept(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from sase.ace.tui.actions.proposal_rebase import accept_task

    request = load_request(PATCH_ACCEPT, args, required=True)
    raw_entries = request.payload.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        return False, "accept request payload must include entries", {}
    entries = [
        (str(item[0]), item[1] if len(item) > 1 else None) for item in raw_entries
    ]
    project_file = _project_file(args)
    success, message = accept_task(
        entries,
        args.name,
        project_file,
        bool(request.payload.get("mark_ready_to_mail", False)),
        bool(request.payload.get("skip_amend", False)),
    )
    return success, message, {"name": args.name}


def _run_rebase(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from sase.ace.tui.actions.proposal_rebase import rebase_task

    request = load_request(PATCH_REBASE, args)
    parent = getattr(args, "parent", None) or request.payload.get("parent")
    if not isinstance(parent, str) or not parent:
        return False, "rebase parent is required", {}
    project_file = _project_file(args)
    success, message = rebase_task(
        args.name,
        project_file,
        _project_basename(project_file),
        parent,
        request.payload.get("old_parent"),
        workspace_num=request.payload.get("workspace_num"),
        workspace_dir=request.payload.get("workspace_dir"),
        release=not bool(request.payload.get("settlement_owns_release", True)),
    )
    return (
        success,
        message,
        {"name": args.name, "parent": parent},
    )


def _run_sync(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from sase.ace.tui.actions.sync import sync_task

    request = load_request(PATCH_SYNC, args)
    project_file = _project_file(args)
    success, message = sync_task(
        args.name,
        project_file,
        _project_basename(project_file),
        workspace_num=request.payload.get("workspace_num"),
        workspace_dir=request.payload.get("workspace_dir"),
        release=not bool(request.payload.get("settlement_owns_release", True)),
    )
    return (
        success,
        message,
        {"name": args.name, "project_file": project_file},
    )


def _run_rewind(args: argparse.Namespace) -> tuple[bool, str, Mapping[str, Any]]:
    from sase.workflows.rewind import RewindWorkflow

    request = load_request(PATCH_REWIND, args)
    raw_entry = getattr(args, "entry", None) or request.payload.get("entry")
    if raw_entry is None:
        return False, "rewind entry number is required", {}
    project_file = _project_file(args)
    success, message = RewindWorkflow(
        cl_name=args.name,
        project_file=project_file,
        selected_entry_num=int(raw_entry),
        skip_vcs=bool(request.payload.get("skip_vcs", False)),
    ).run()
    return success, message, {"name": args.name, "entry": int(raw_entry)}


def _load_patch(project_file: str, name: str) -> Any:
    from sase.ace.patch import parse_project_file

    patches = parse_project_file(project_file)
    patch = next((item for item in patches if item.name == name), None)
    if patch is None:
        raise RuntimeError(f"Patch {name!r} not found")
    return patch


__all__ = ["add_patch_operation_parsers", "handle_patch_operation"]
