"""Shared host-side launch helpers for approved epic plans."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.core.agent_tribe import canonicalize_agent_tribe_metadata


if TYPE_CHECKING:
    from sase.tasks.models import BackgroundTask


TASK_LOG_PATH_ENV = "SASE_TASK_LOG_PATH"

_EPIC_LAUNCH_TAGS = ("epic", "launch")
_LOG_SETTLE_SECONDS = 2.0
_LOG_SETTLE_POLL_SECONDS = 0.05

_EPIC_ID_RE = re.compile(r"(?m)^Epic:\s+(\S+)\s*$")
_PLAN_LINK_RE = re.compile(r"(?m)^.*Plan linked\s+bead_id:\s+\S+\s+·\s+(.+?)\s*$")
_ARCHIVED_PLAN_RE = re.compile(
    r"(?m)^.*Archived\s+(.+?)\s+\((?:committed|already archived)\)\s*$"
)


@dataclass(frozen=True)
class _EpicLaunchOutput:
    """Stable values parsed from human ``sase bead work`` output."""

    epic_id: str | None
    archived_plan_path: str | None


def build_epic_launch_argv(plan_file: str | Path) -> list[str]:
    """Build the canonical approved-epic launch command."""
    return ["sase", "bead", "work", str(plan_file), "--yes-to-all"]


def parse_epic_launch_output(output: str) -> _EpicLaunchOutput:
    """Extract the stable epic ID and archived plan path from command output."""
    epic_match = _EPIC_ID_RE.search(output)
    plan_match = _PLAN_LINK_RE.search(output) or _ARCHIVED_PLAN_RE.search(output)
    return _EpicLaunchOutput(
        epic_id=epic_match.group(1) if epic_match else None,
        archived_plan_path=plan_match.group(1).strip() if plan_match else None,
    )


def resolve_epic_launch_cwd(
    project_dir: str | Path | None,
    *,
    agent_project_file: str | Path | None = None,
) -> Path:
    """Resolve an approved epic's canonical project to its primary checkout."""
    project_file_value = (
        str(agent_project_file).strip() if agent_project_file is not None else ""
    )
    if project_file_value:
        project_name = Path(project_file_value).expanduser().parent.name
        from sase.core.paths import is_valid_sase_project_name

        if not is_valid_sase_project_name(project_name):
            raise ValueError(
                "agent project file does not identify a valid SASE project: "
                f"{agent_project_file}"
            )
    else:
        if project_dir is None or not str(project_dir).strip():
            raise ValueError(
                "project_dir or agent_project_file is required to resolve epic "
                "launch cwd"
            )
        project_path = Path(project_dir).expanduser().resolve(strict=False)
        try:
            from sase.workspace_provider import get_workspace_name

            discovered_name = get_workspace_name(str(project_path))
        except Exception:
            discovered_name = None
        if not discovered_name:
            discovered_name = re.sub(r"_\d+$", "", project_path.name)

        from sase.project_aliases import resolve_project_alias_ref

        project_name = resolve_project_alias_ref(discovered_name)

    from sase.running_field import get_workspace_directory

    primary = Path(get_workspace_directory(project_name, 1)).expanduser()
    if not primary.is_dir():
        raise FileNotFoundError(f"primary workspace is missing: {primary}")
    return primary


def run_epic_launch_foreground(
    plan_file: str | Path,
    *,
    cwd: str | Path,
) -> subprocess.CompletedProcess[Any]:
    """Run the canonical epic launch in the foreground with inherited output."""
    return subprocess.run(
        build_epic_launch_argv(plan_file),
        cwd=str(cwd),
        check=False,
    )


def submit_epic_launch_task(
    plan_file: str | Path,
    *,
    cwd: str | Path,
    artifacts_dir: str | Path | None = None,
    cl_name: str | None = None,
    session_id: str | None = None,
) -> BackgroundTask:
    """Submit the epic-launch worker as a durable background task.

    The worker records, reports, and notifies exactly as before; the task
    supervisor owns its process and captures its output, so an approved epic
    is visible work in ``sase task list`` and in the ACE Tasks tab instead of
    an invisible detached fork.

    Raises:
        TaskSubmitError: The task could not be recorded or its supervisor
            could not be started.
    """
    from sase.tasks.runner import submit_task

    argv = [
        sys.executable,
        "-m",
        "sase.bead.epic_launch",
        "--worker",
        "--plan-file",
        str(plan_file),
        "--cwd",
        str(cwd),
    ]
    if artifacts_dir is not None:
        argv.extend(["--artifacts-dir", str(artifacts_dir)])
    if cl_name:
        argv.extend(["--cl-name", cl_name])
    return submit_task(
        argv,
        label=f"Epic launch · {Path(plan_file).stem}",
        cwd=cwd,
        session_id=session_id if session_id is not None else _epic_launch_session_id(),
        tags=_EPIC_LAUNCH_TAGS,
        origin="epic-launch",
        cl_name=cl_name,
    )


def _epic_launch_session_id() -> str | None:
    """Resolve the session an unattributed epic launch should land in."""
    try:
        from sase.sessions import resolve_session_ref

        identity = resolve_session_ref(None)
    except Exception:
        return None
    return identity.session_id if identity is not None else None


def update_epic_launch_metadata(
    artifacts_dir: str | Path | None,
    *,
    epic_id: str,
    sdd_plan_path: str,
    started_at: str | None = None,
) -> None:
    """Best-effort back-fill of planner metadata after a host launch."""
    if artifacts_dir is None:
        return
    artifacts_path = Path(artifacts_dir).expanduser()
    meta_path = artifacts_path / "agent_meta.json"
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    data.update(
        {
            "epic_bead_id": epic_id,
            "epic_started_at": started_at or datetime.now(UTC).isoformat(),
            "plan_committed": True,
            "sdd_plan_path": sdd_plan_path,
        }
    )
    canonicalize_agent_tribe_metadata(data)
    try:
        meta_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        from sase.core.agent_artifact_index_lifecycle import (
            update_agent_artifact_index_for_marker_mutation,
        )

        update_agent_artifact_index_for_marker_mutation(artifacts_path)
    except Exception:
        return


def _run_detached_worker(args: argparse.Namespace) -> int:
    task_log = os.environ.get(TASK_LOG_PATH_ENV, "").strip()
    if task_log:
        log_path = Path(task_log).expanduser()
        returncode = _run_launch_with_inherited_output(args)
        # The supervisor drains our inherited output into the task log from
        # another process, so give the last lines a bounded moment to land.
        settle = returncode == 0
    elif args.log_path:
        log_path = Path(args.log_path).expanduser()
        returncode = _run_launch_into_log(args, log_path)
        settle = False
    else:
        return 2

    output = _read_launch_output(log_path, settle=settle)
    parsed = parse_epic_launch_output(output)
    success = returncode == 0 and parsed.epic_id is not None
    if success:
        assert parsed.epic_id is not None
        update_epic_launch_metadata(
            args.artifacts_dir,
            epic_id=parsed.epic_id,
            sdd_plan_path=parsed.archived_plan_path or args.plan_file,
        )
    _notify_detached_completion(
        success=success,
        epic_id=parsed.epic_id,
        plan_file=args.plan_file,
        cl_name=args.cl_name,
        log_path=log_path,
        returncode=returncode,
    )
    return 0 if success else 1


def _run_launch_with_inherited_output(args: argparse.Namespace) -> int:
    """Run the launch with output inherited by the task supervisor."""
    try:
        completed = subprocess.run(
            build_epic_launch_argv(args.plan_file),
            cwd=args.cwd,
            check=False,
        )
    except OSError as exc:
        print(f"Could not start epic launch: {exc}", flush=True)
        return -1
    return completed.returncode


def _run_launch_into_log(args: argparse.Namespace, log_path: Path) -> int:
    """Run the launch into a private log file (pre-task-runner workers)."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_file:
        try:
            completed = subprocess.run(
                build_epic_launch_argv(args.plan_file),
                cwd=args.cwd,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        except OSError as exc:
            log_file.write(f"Could not start epic launch: {exc}\n")
            return -1
    return completed.returncode


def _read_launch_output(log_path: Path, *, settle: bool) -> str:
    """Read the retained launch output, optionally waiting for it to settle."""
    deadline = time.monotonic() + _LOG_SETTLE_SECONDS
    while True:
        output = _read_retained_log(log_path)
        if not settle or parse_epic_launch_output(output).epic_id is not None:
            return output
        if time.monotonic() >= deadline:
            return output
        time.sleep(_LOG_SETTLE_POLL_SECONDS)


def _read_retained_log(log_path: Path) -> str:
    chunks: list[str] = []
    for candidate in (log_path.with_name(f"{log_path.name}.1"), log_path):
        try:
            chunks.append(candidate.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            pass
    return "".join(chunks)


def _notify_detached_completion(
    *,
    success: bool,
    epic_id: str | None,
    plan_file: str,
    cl_name: str | None,
    log_path: Path,
    returncode: int,
) -> None:
    try:
        from sase.notifications.senders import notify_workflow_complete

        if success:
            notes = [
                f"Epic {epic_id} launched from {Path(plan_file).name}",
                f"Launch log: {log_path}",
            ]
        else:
            resume = shlex.join(build_epic_launch_argv(plan_file))
            notes = [
                f"Epic launch failed with exit code {returncode}",
                f"Resume with: {resume}",
                f"Launch log: {log_path}",
            ]
        notify_workflow_complete(
            "epic-launch",
            cl_name,
            success,
            notes,
            extra_files=[str(log_path)],
            tags=["epic", "launch"],
        )
    except Exception:
        return


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--plan-file", required=True)
    parser.add_argument("--cwd", required=True)
    # Still accepted so a worker spawned by a pre-task-runner version that is
    # in flight during an upgrade keeps behaving.
    parser.add_argument("--log-path")
    parser.add_argument("--artifacts-dir")
    parser.add_argument("--cl-name")
    return parser


def _main() -> int:
    args = _parser().parse_args()
    if not args.worker:
        return 2
    return _run_detached_worker(args)


if __name__ == "__main__":
    raise SystemExit(_main())


__all__ = [
    "TASK_LOG_PATH_ENV",
    "build_epic_launch_argv",
    "parse_epic_launch_output",
    "resolve_epic_launch_cwd",
    "run_epic_launch_foreground",
    "submit_epic_launch_task",
    "update_epic_launch_metadata",
]
