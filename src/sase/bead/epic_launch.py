"""Shared host-side launch helpers for approved epic plans."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.core.agent_tribe import canonicalize_agent_tribe_metadata


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


@dataclass(frozen=True)
class _DetachedEpicLaunch:
    """One successfully submitted detached epic-launch worker."""

    pid: int
    log_path: Path


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
    project_dir: str | Path,
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


def spawn_detached_epic_launch(
    plan_file: str | Path,
    *,
    cwd: str | Path,
    log_path: str | Path,
    artifacts_dir: str | Path | None = None,
    cl_name: str | None = None,
) -> _DetachedEpicLaunch:
    """Start a detached worker that logs, records, and reports epic completion."""
    resolved_log = Path(log_path).expanduser().resolve(strict=False)
    resolved_log.parent.mkdir(parents=True, exist_ok=True)
    argv = [
        sys.executable,
        "-m",
        "sase.bead.epic_launch",
        "--worker",
        "--plan-file",
        str(plan_file),
        "--cwd",
        str(cwd),
        "--log-path",
        str(resolved_log),
    ]
    if artifacts_dir is not None:
        argv.extend(["--artifacts-dir", str(artifacts_dir)])
    if cl_name:
        argv.extend(["--cl-name", cl_name])
    process = subprocess.Popen(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        close_fds=True,
    )
    return _DetachedEpicLaunch(pid=process.pid, log_path=resolved_log)


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
    log_path = Path(args.log_path).expanduser()
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
            returncode = completed.returncode
        except OSError as exc:
            log_file.write(f"Could not start epic launch: {exc}\n")
            returncode = -1

    try:
        output = log_path.read_text(encoding="utf-8")
    except OSError:
        output = ""
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
    parser.add_argument("--log-path", required=True)
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
    "build_epic_launch_argv",
    "parse_epic_launch_output",
    "resolve_epic_launch_cwd",
    "run_epic_launch_foreground",
    "spawn_detached_epic_launch",
    "update_epic_launch_metadata",
]
