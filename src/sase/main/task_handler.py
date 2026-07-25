"""Handler for the 'sase task' CLI subcommand."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn, TextIO

from rich.console import Console

from sase.sessions import (
    SessionRefError,
    live_sessions,
    resolve_session_ref,
    short_session_handle,
)
from sase.tasks import (
    ACTIVE_TASK_STATUSES,
    TERMINAL_TASK_STATUSES,
    BackgroundTask,
    TaskControlError,
    TaskRefError,
    TaskSubmitError,
    get_task,
    kill_task,
    read_task_log_tail,
    read_tasks,
    reconcile_running_tasks,
    resolve_task_ref,
    short_task_id,
    submit_task,
    wait_for_task,
)

from .task_render import (
    empty_task_panel,
    task_detail,
    task_list_json,
    task_show_json,
    task_table,
)

# Large enough to mean "every retained line" for a size-bounded task log.
_ALL_LOG_LINES = 1_000_000
_LABEL_MAX_CHARS = 72
_KILLED_EXIT_CODE = 130


def handle_task_command(args: argparse.Namespace) -> NoReturn:
    """Dispatch background-task subcommands."""
    subcommand = getattr(args, "task_subcommand", None)
    if subcommand in (None, "list"):
        sys.exit(_handle_task_list(args))
    if subcommand == "run":
        sys.exit(_handle_task_run(args))
    if subcommand == "show":
        sys.exit(_handle_task_show(args))
    print("Usage: sase task {list,run,show}", file=sys.stderr)
    sys.exit(1)


@dataclass(frozen=True)
class _ListScope:
    """Which sessions' tasks ``sase task list`` should include."""

    all_sessions: bool
    session_id: str | None
    include_unattributed: bool
    ref: str | None

    def matches(self, task: BackgroundTask) -> bool:
        if self.all_sessions:
            return True
        if task.session_id is None:
            return self.include_unattributed
        return task.session_id == self.session_id

    def label(self) -> str:
        if self.all_sessions:
            return "all sessions"
        if self.session_id is None:
            return "unattributed"
        handle = short_session_handle(self.session_id)
        if self.ref is None:
            return f"this session ({handle}) + unattributed"
        return f"session {handle}"

    def to_json(self) -> dict[str, Any]:
        return {
            "all": self.all_sessions,
            "include_unattributed": self.all_sessions or self.include_unattributed,
            "ref": self.ref,
            "session_id": None if self.all_sessions else self.session_id,
        }


def _handle_task_list(args: argparse.Namespace) -> int:
    """Render durable background tasks as a table or JSON envelope."""
    if getattr(args, "all", False) and getattr(args, "session", None):
        print(
            "sase task list: --all cannot be combined with --session", file=sys.stderr
        )
        return 2

    _reconcile_quietly()
    try:
        scope = _resolve_list_scope(args)
    except SessionRefError as exc:
        print(f"sase task list: {exc}", file=sys.stderr)
        return 2

    try:
        matched = read_tasks(
            status=_requested_statuses(args),
            project=getattr(args, "project", None),
            tag=getattr(args, "tag", None),
            query=getattr(args, "query", None),
        )
    except Exception as exc:
        print(f"sase task list: cannot read tasks: {exc}", file=sys.stderr)
        return 1

    scoped = [task for task in matched if scope.matches(task)]
    hidden = len(matched) - len(scoped)
    tasks = scoped[: _list_limit(args)]
    live_ids = _live_session_ids()

    if bool(getattr(args, "json", False)):
        payload = task_list_json(
            tasks, scope=scope.to_json(), live_session_ids=live_ids
        )
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    console = Console()
    title = f"Tasks · {scope.label()} ({len(tasks)})"
    if tasks:
        console.print(task_table(tasks, title=title, live_session_ids=live_ids))
    else:
        console.print(empty_task_panel(title, hint=_hidden_hint(hidden)))
    return 0


def _handle_task_run(args: argparse.Namespace) -> int:
    """Submit a detached background task and optionally wait for it."""
    command = _run_command(args)
    if not command:
        print(
            "sase task run: no command given; pass it after -- "
            "(e.g. sase task run -- just check)",
            file=sys.stderr,
        )
        return 2

    cwd = Path(getattr(args, "cwd", None) or Path.cwd()).expanduser()
    try:
        session_id = _resolve_session_id(getattr(args, "session", None))
    except SessionRefError as exc:
        print(f"sase task run: {exc}", file=sys.stderr)
        return 2

    project, workspace_num = _infer_attribution(cwd, getattr(args, "project", None))
    try:
        task = submit_task(
            command,
            label=getattr(args, "label", None) or _derived_label(command),
            cwd=cwd,
            session_id=session_id,
            project=project,
            workspace_num=workspace_num,
            tags=getattr(args, "tag", None) or (),
            origin="cli",
        )
    except TaskSubmitError as exc:
        print(f"sase task run: {exc}", file=sys.stderr)
        return 1

    as_json = bool(getattr(args, "json", False))
    wait = bool(getattr(args, "wait", False))
    if as_json and not wait:
        _print_task_json(task)
    elif bool(getattr(args, "quiet", False)):
        print(task.task_id)
    elif not as_json and not wait:
        # Waiting prints the task's own output instead: keep stdout clean.
        print(task.task_id)
        print(f"monitor with: sase task show {short_task_id(task.task_id)} --follow")

    if not wait:
        return 0

    # With ``--json`` the envelope is what a caller parses, so the streamed log
    # goes to stderr and the finished task is the only thing on stdout.
    exit_code = _wait_and_report(task, stream=sys.stderr if as_json else sys.stdout)
    if as_json:
        _print_task_json(get_task(task.task_id) or task)
    return exit_code


def _print_task_json(task: BackgroundTask) -> None:
    json.dump(
        task_show_json(task, log="", live_session_ids=_live_session_ids()),
        sys.stdout,
        indent=2,
    )
    sys.stdout.write("\n")


def _handle_task_show(args: argparse.Namespace) -> int:
    """Show one task's detail panel and captured output."""
    _reconcile_quietly()
    try:
        task = resolve_task_ref(getattr(args, "task_id", ""), read_tasks())
    except TaskRefError as exc:
        print(f"sase task show: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"sase task show: cannot read tasks: {exc}", file=sys.stderr)
        return 1

    output_only = bool(getattr(args, "output_only", False))
    follow = bool(getattr(args, "follow", False))
    if getattr(args, "format", "markdown") == "json":
        # JSON is a snapshot, so following means "wait, then report the result".
        if follow and task.status not in TERMINAL_TASK_STATUSES:
            try:
                task = wait_for_task(task.task_id)
            except KeyboardInterrupt:
                return _KILLED_EXIT_CODE
            except TaskControlError as exc:
                print(f"sase task show: {exc}", file=sys.stderr)
                return 1
        payload = task_show_json(
            task,
            log=_log_text(task, args),
            live_session_ids=_live_session_ids(),
        )
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 0

    if not output_only:
        Console().print(
            task_detail(task, live_session_ids=_live_session_ids()),
        )

    if follow:
        return _follow_log(task, args)

    log = _log_text(task, args)
    if log:
        sys.stdout.write(log if log.endswith("\n") else f"{log}\n")
    elif not output_only:
        print("(no output captured yet)")
    return 0


def _follow_log(task: BackgroundTask, args: argparse.Namespace) -> int:
    """Print the retained log, then stream new lines until the task ends."""
    retained = read_task_log_tail(task.task_id, _ALL_LOG_LINES).splitlines()
    lines = _log_lines(args)
    for line in retained[-lines:] if lines > 0 else []:
        print(line)

    # ``wait_for_task`` replays the log it reads before streaming new output,
    # so drop exactly the lines that were already retained when we read above.
    remaining = len(retained)

    def on_line(line: str) -> None:
        nonlocal remaining
        if remaining > 0:
            remaining -= 1
            return
        print(line)

    try:
        wait_for_task(task.task_id, on_line=on_line)
    except KeyboardInterrupt:
        return _KILLED_EXIT_CODE
    except TaskControlError as exc:
        print(f"sase task show: {exc}", file=sys.stderr)
        return 1
    return 0


def _wait_and_report(task: BackgroundTask, *, stream: TextIO) -> int:
    """Stream a submitted task's output and return its exit code."""
    try:
        finished = wait_for_task(
            task.task_id, on_line=lambda line: print(line, file=stream)
        )
    except KeyboardInterrupt:
        print(f"\nkilling task {short_task_id(task.task_id)}…", file=sys.stderr)
        try:
            kill_task(task.task_id)
        except TaskControlError as exc:
            print(f"sase task run: {exc}", file=sys.stderr)
        return _KILLED_EXIT_CODE
    except TaskControlError as exc:
        print(f"sase task run: {exc}", file=sys.stderr)
        return 1

    if finished.exit_code is not None:
        # A signalled child records a negative code; report it as a shell would.
        if finished.exit_code < 0:
            return 128 - finished.exit_code
        return finished.exit_code
    if finished.status == "success":
        return 0
    if finished.status == "killed":
        return _KILLED_EXIT_CODE
    return 1


def _resolve_list_scope(args: argparse.Namespace) -> _ListScope:
    if bool(getattr(args, "all", False)):
        return _ListScope(
            all_sessions=True, session_id=None, include_unattributed=True, ref=None
        )
    ref = getattr(args, "session", None)
    session_id = _resolve_session_id(ref)
    return _ListScope(
        all_sessions=False,
        session_id=session_id,
        include_unattributed=ref is None or session_id is None,
        ref=ref,
    )


def _resolve_session_id(ref: str | None) -> str | None:
    identity = resolve_session_ref(ref)
    return identity.session_id if identity is not None else None


def _requested_statuses(args: argparse.Namespace) -> set[str] | None:
    statuses: set[str] = {str(value) for value in getattr(args, "status", None) or ()}
    if bool(getattr(args, "running", False)):
        statuses |= set(ACTIVE_TASK_STATUSES)
    return statuses or None


def _list_limit(args: argparse.Namespace) -> int:
    limit = getattr(args, "limit", None)
    if limit is None:
        from sase.config.core import get_task_history_limit

        limit = get_task_history_limit()
    return max(0, limit)


def _hidden_hint(hidden: int) -> str | None:
    if hidden <= 0:
        return None
    noun, verb = ("task", "is") if hidden == 1 else ("tasks", "are")
    return f"{hidden} {noun} from other sessions {verb} hidden; pass -a/--all."


def _log_lines(args: argparse.Namespace) -> int:
    if bool(getattr(args, "all_lines", False)):
        return _ALL_LOG_LINES
    return max(0, getattr(args, "log_lines", 200))


def _log_text(task: BackgroundTask, args: argparse.Namespace) -> str:
    try:
        return read_task_log_tail(task.task_id, _log_lines(args))
    except (OSError, ValueError):
        return ""


def _run_command(args: argparse.Namespace) -> list[str]:
    command = [str(part) for part in getattr(args, "task_command", None) or []]
    if command and command[0] == "--":
        command = command[1:]
    return command


def _derived_label(command: list[str]) -> str:
    label = " ".join(command)
    if len(label) <= _LABEL_MAX_CHARS:
        return label
    return f"{label[: _LABEL_MAX_CHARS - 1]}…"


def _infer_attribution(cwd: Path, project: str | None) -> tuple[str | None, int | None]:
    """Return the project and workspace number a task should be attributed to."""
    name = project
    if not name:
        try:
            from sase.bead.project_name import infer_project_name_from_cwd

            name = infer_project_name_from_cwd(str(cwd))
        except Exception:
            name = None
    if not name:
        return None, None
    match = re.search(rf"(?:^|/){re.escape(name)}_(\d+)(?:/|$)", str(cwd))
    return name, int(match.group(1)) if match else None


def _live_session_ids() -> set[str]:
    try:
        return {identity.session_id for identity in live_sessions()}
    except Exception:
        return set()


def _reconcile_quietly() -> None:
    """Sweep orphaned rows; a reconciliation failure must not break output."""
    try:
        reconcile_running_tasks()
    except Exception:
        pass


__all__ = [
    "handle_task_command",
]
