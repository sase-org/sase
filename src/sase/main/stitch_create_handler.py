"""Command handler for ``sase stitch create``."""

import argparse
import sys
from typing import NoReturn

from sase.workflows.commit import CommitWorkflow


def _resolve_env_bead_id() -> str | None:
    """Return the SASE_BEAD_ID value for new commit attempts, if set."""
    import os

    bead_id = os.environ.get("SASE_BEAD_ID", "").strip()
    return bead_id or None


def _normalize_excludes(raw_excludes: list[str]) -> list[str]:
    """Normalize ``-x/--exclude`` entries to canonical repo-relative POSIX paths.

    Exits 1 with a printed reason on the first entry that is not a safe,
    literal, repo-relative path — an unmatched or malicious exclude must never
    reach ``git add``, since git silently ignores a pathspec that matches
    nothing.
    """
    import os

    normalized = []
    for raw in raw_excludes:
        path = raw.strip()
        if path.startswith(":"):
            print(
                f"Error: invalid --exclude path {raw!r}: a leading ':' is raw git "
                "pathspec magic, which is not allowed.",
                file=sys.stderr,
            )
            sys.exit(1)
        if path.startswith("./"):
            path = path[2:]
        path = path.rstrip("/")
        if not path or os.path.isabs(path):
            print(
                f"Error: invalid --exclude path {raw!r}: must be a non-empty, "
                "repo-relative path.",
                file=sys.stderr,
            )
            sys.exit(1)
        if any(part == ".." for part in path.split("/")):
            print(
                f"Error: invalid --exclude path {raw!r}: '..' components are not "
                "allowed.",
                file=sys.stderr,
            )
            sys.exit(1)
        normalized.append(path)
    return normalized


def handle_stitch_create_command(args: argparse.Namespace) -> NoReturn:
    """Handle the ``sase stitch create`` command.

    Args:
        args: Parsed command-line arguments.
    """
    import os

    if args.resume:
        from sase.workflows.commit.workflow import EXIT_CODE_CONFLICT, RunResult

        result = CommitWorkflow.resume()
        if result == RunResult.OK:
            try:
                from sase.logs.run_log import log_event

                log_event(event="commit_resumed")
            except Exception:
                pass
            sys.exit(0)
        if result == RunResult.CONFLICT:
            sys.exit(EXIT_CODE_CONFLICT)
        sys.exit(int(result))

    # Resolve commit message from inline string or file. Message files are
    # deleted only after a successful workflow so failed attempts are retryable.
    message = ""
    message_file_path: str | None = None
    if args.message:
        message = args.message
    elif args.message_file:
        path = args.message_file
        if not os.path.isfile(path):
            print(f"Error: message file not found: {path}", file=sys.stderr)
            sys.exit(1)
        with open(path) as f:
            message = f.read().rstrip()
        message_file_path = path

    from sase.workflows.commit.workflow import METHOD_ALIASES

    cli_method = args.method
    env_method = os.environ.get("SASE_COMMIT_METHOD", "")

    # Canonicalize both sources independently.
    if cli_method:
        cli_method = METHOD_ALIASES.get(cli_method, cli_method)
    if env_method:
        env_method = METHOD_ALIASES.get(env_method, env_method)

    # Detect conflicting CLI vs env methods.
    if (
        cli_method
        and env_method
        and cli_method != env_method
        and not os.environ.get("SASE_COMMIT_METHOD_ALLOW_OVERRIDE")
    ):
        print(
            f"Error: CLI commit method '{cli_method}' conflicts with "
            f"SASE_COMMIT_METHOD='{env_method}'. "
            "Set SASE_COMMIT_METHOD_ALLOW_OVERRIDE=1 to force the CLI method.",
            file=sys.stderr,
        )
        sys.exit(1)

    method = cli_method or env_method or "create_commit"

    if args.only_files and args.exclude:
        print(
            "Error: --only-file and -x/--exclude are mutually exclusive.",
            file=sys.stderr,
        )
        sys.exit(1)

    payload: dict[str, object] = {
        "message": message,
        "files": args.only_files or [],
        "exclude": _normalize_excludes(args.exclude),
    }
    if args.name:
        payload["name"] = args.name
    if bead_id := _resolve_env_bead_id():
        payload["bead_id"] = bead_id
    if args.bug_id:
        payload["bug_id"] = str(args.bug_id)
    if args.do_not_close_bead:
        payload["do_not_close_bead"] = True
    if args.checkout_target != "HEAD~1":
        payload["checkout_target"] = args.checkout_target
    if args.parent:
        payload["parent"] = args.parent
    from sase.workflows.commit.workflow import EXIT_CODE_CONFLICT, RunResult

    workflow = CommitWorkflow(payload=payload, method=method)
    result = workflow.run()
    if result == RunResult.OK:
        if message_file_path:
            try:
                os.remove(message_file_path)
            except OSError:
                pass
        try:
            from sase.logs.run_log import log_event

            log_event(event="commit_created", method=method)
        except Exception:
            pass
        sys.exit(0)
    if message_file_path:
        print(
            "Commit message preserved at "
            f"{message_file_path} — re-run with the same -M flag after fixing.",
            file=sys.stderr,
        )
    if result == RunResult.CONFLICT:
        try:
            from sase.logs.run_log import log_event

            log_event(event="commit_conflict", method=method)
        except Exception:
            pass
        sys.exit(EXIT_CODE_CONFLICT)
    sys.exit(int(result))
