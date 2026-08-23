"""Handler for the ``sase stitch`` CLI subcommand."""

from __future__ import annotations

import argparse
import os
import sys


def _handle_list(args: argparse.Namespace) -> int:
    """Render the cross-repository commit timeline.

    Exits ``0`` when at least one repo was read (even if it had no commits);
    ``1`` when nothing readable was found (e.g. the current directory is not
    a SASE workspace or a VCS repository). Warnings are surfaced in every
    format.
    """
    from sase.vcs_log.collect import run_vcs_log
    from sase.vcs_log.dates import VcsLogDateError, parse_time_bound
    from sase.vcs_log.models import CommitFilterSpec
    from sase.vcs_log.progress import make_fetch_progress
    from sase.vcs_log.render import render

    try:
        since_bound = parse_time_bound(args.since) if args.since else None
        until_bound = parse_time_bound(args.until) if args.until else None
    except VcsLogDateError as exc:
        print(f"sase stitch list: {exc}", file=sys.stderr)
        return 2

    filter_spec = CommitFilterSpec(
        since=since_bound,
        until=until_bound,
        authors=tuple(args.authors or ()),
        merges=args.merges,
        origins=tuple(args.origins or ()),
    )

    try:
        result = run_vcs_log(
            cwd=os.getcwd(),
            limit=args.limit,
            filter_spec=filter_spec,
            repo_filters=args.repos,
            all_projects=args.all,
            current_only=args.current_only,
            include_sidecars=args.sdd,
            no_fetch=args.no_fetch,
            force_fetch=args.force_fetch,
            remote_ref=args.remote_ref,
            fetch_progress=make_fetch_progress(args.color),
        )
    except VcsLogDateError as exc:
        print(f"sase stitch list: {exc}", file=sys.stderr)
        return 2
    render(
        result,
        fmt=args.format,
        color=args.color,
        limit=args.limit,
        reverse=args.reverse,
        show_tags=args.show_tags,
        all_projects=args.all,
    )
    return 0 if result.repos else 1


def _handle_post_write(args: argparse.Namespace) -> int:
    """Handle the internal durable post-write action command."""
    from collections.abc import Sequence

    from sase.ops.cli import load_request
    from sase.ops.commands.common import run_and_finish
    from sase.ops.names import GIT_POST_WRITE
    from sase.post_write_operations import (
        GitCommitPushResult,
        run_chezmoi_apply_sync,
        run_git_commit_push_sync,
        run_post_write_command_sync,
    )

    def _body() -> tuple[bool, str, dict[str, object]]:
        request = load_request(GIT_POST_WRITE, args, required=True)
        kind = str(args.kind)
        result: GitCommitPushResult
        if kind == "commit-push":
            git_root = request.payload.get("git_root")
            file_path = request.payload.get("file_path")
            commit_message = request.payload.get("commit_message")
            if not isinstance(git_root, str) or not git_root:
                return False, "post-write commit request must include git_root", {}
            if not isinstance(file_path, str) or not file_path:
                return False, "post-write commit request must include file_path", {}
            if not isinstance(commit_message, str) or not commit_message:
                return (
                    False,
                    "post-write commit request must include commit_message",
                    {},
                )
            result = run_git_commit_push_sync(
                git_root=git_root,
                file_path=file_path,
                commit_message=commit_message,
            )
        elif kind == "chezmoi-apply":
            target = request.payload.get("apply_target")
            if not isinstance(target, str) or not target:
                return False, "post-write chezmoi request must include apply_target", {}
            result = run_chezmoi_apply_sync(target)
        else:
            command = request.payload.get("command")
            cwd = request.payload.get("cwd")
            if not isinstance(command, Sequence) or isinstance(command, (str, bytes)):
                return False, "post-write command request must include command list", {}
            command_words = [str(word) for word in command]
            if not command_words:
                return False, "post-write command request must include command list", {}
            if cwd is not None and not isinstance(cwd, str):
                return (
                    False,
                    "post-write command request cwd must be a string or null",
                    {},
                )
            result = run_post_write_command_sync(command_words, cwd=cwd)
        return (
            result.success,
            result.message,
            {
                "index_lock_removed": result.index_lock_removed,
                "kind": kind,
                "subject": str(args.subject),
            },
        )

    return run_and_finish(operation=GIT_POST_WRITE, body=_body, args=args)


_HANDLERS = {
    "list": _handle_list,
    "post-write": _handle_post_write,
}


def handle_stitch_command(args: argparse.Namespace) -> None:
    """Dispatch a parsed ``sase stitch ...`` command to its handler."""
    sub = getattr(args, "stitch_subcommand", None)
    if sub == "create":
        from sase.main.stitch_create_handler import handle_stitch_create_command

        handle_stitch_create_command(args)
    handler = _HANDLERS.get(sub) if isinstance(sub, str) else None
    if handler is None:
        print("Usage: sase stitch {create,list}", file=sys.stderr)
        sys.exit(2)
    sys.exit(handler(args))


handle_vcs_command = handle_stitch_command  # legacy handler alias


__all__ = [
    "_handle_list",
    "handle_stitch_command",
    "handle_vcs_command",  # legacy handler alias
]
