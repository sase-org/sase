"""Durable diagnostic logging for ProjectSpec creation.

Every brand-new project ProjectSpec created through
``create_project_file()`` is written to two canonical files under
``~/.sase/logs/``:

- ``project_creation.jsonl`` -- one structured record per creation.
- ``project_creation.log`` -- a formatted, human-readable block per creation.

Logging is best-effort and must never affect project creation. The records are
intended to identify unexpected project materialization by preserving the cwd,
resolved workspace name, SASE environment, argv, and full caller stack.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.paths import sase_projects_dir, sase_subdir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.time import get_timezone

log = logging.getLogger(__name__)

# Module-level path overrides for tests (same pattern as ``launch_log``).
LOGS_DIR: str | None = None
PROJECT_CREATION_LOG: str | None = None
PROJECT_CREATION_JSONL: str | None = None


def _logs_dir() -> str:
    return LOGS_DIR or str(sase_subdir("logs"))


def project_creation_log_path() -> Path:
    """Canonical path of the human-readable project-creation log."""
    return Path(
        PROJECT_CREATION_LOG or os.path.join(_logs_dir(), "project_creation.log")
    )


def project_creation_jsonl_path() -> Path:
    """Canonical path of the structured project-creation JSONL log."""
    return Path(
        PROJECT_CREATION_JSONL or os.path.join(_logs_dir(), "project_creation.jsonl")
    )


def _append_locked(path: Path, text: str) -> None:
    """Append *text* to *path* with an exclusive file lock (creates dirs)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            f.write(text)
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def log_project_creation(*, project: str, project_file: str) -> None:
    """Durably record creation of a new project ProjectSpec file.

    Appends a structured record to ``project_creation.jsonl`` AND a formatted,
    human-readable block to ``project_creation.log``. Never raises: any error
    is swallowed and surfaced through the module logger so diagnostics can
    never break the caller that just created the ProjectSpec.
    """
    try:
        _write_project_creation(project=project, project_file=project_file)
    except Exception:  # pragma: no cover - logging must never break creation
        log.warning("Failed to write project-creation log", exc_info=True)


def _write_project_creation(*, project: str, project_file: str) -> None:
    now = datetime.now(get_timezone())
    cwd = _get_cwd()
    alias_conflict, alias_conflict_owner = _detect_alias_conflict(project)
    record: dict[str, Any] = {
        "timestamp": now.strftime("%y%m%d_%H%M%S"),
        "project": project,
        "project_file": project_file,
        "cwd": cwd,
        "resolved_workspace_name": _resolve_workspace_name(cwd),
        "alias_conflict": alias_conflict,
        "alias_conflict_owner": alias_conflict_owner,
        "argv": list(sys.argv),
        "sase_env": _sase_env(),
        "stack": _caller_stack(),
    }

    _append_jsonl_record(record)
    _append_human_block(now=now, record=record)
    _warn_alias_conflict(record)


def _get_cwd() -> str | None:
    try:
        return os.getcwd()
    except OSError:
        return None


def _resolve_workspace_name(cwd: str | None) -> str | None:
    if cwd is None:
        return None
    try:
        from sase.workspace_provider import get_workspace_name

        return get_workspace_name(cwd)
    except Exception:
        return None


def _detect_alias_conflict(project: str) -> tuple[bool | None, str | None]:
    try:
        alias_owners: dict[str, str] = {}
        for record in list_project_records(
            sase_projects_dir(), "all", include_home=False
        ):
            if (
                record.project_name == project
                or record.project_name == "home"
                or record.system_managed
            ):
                continue
            display_name = record.display_name or ""
            for ref in (display_name, *record.aliases):
                normalized = ref.strip()
                if normalized and normalized not in alias_owners:
                    alias_owners[normalized] = record.project_name
        owner = alias_owners.get(project)
        return owner is not None, owner
    except Exception:
        log.warning("Failed to detect project alias conflict", exc_info=True)
        return None, None


def _sase_env() -> dict[str, str]:
    return {
        key: os.environ[key] for key in sorted(os.environ) if key.startswith("SASE_")
    }


def _caller_stack() -> str:
    frames = traceback.extract_stack()[:-1]
    while frames and frames[-1].filename == __file__:
        frames.pop()
    return "".join(traceback.format_list(frames))


def _append_jsonl_record(record: dict[str, Any]) -> None:
    _append_locked(
        project_creation_jsonl_path(), json.dumps(record, default=str) + "\n"
    )


def _append_human_block(*, now: datetime, record: dict[str, Any]) -> None:
    header_ts = now.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    conflict_marker = ""
    if record["alias_conflict"]:
        conflict_marker = f" ⚠ ALIAS CONFLICT with {record['alias_conflict_owner']}"

    lines = [
        "=" * 72,
        f"[{header_ts}] project creation: {record['project']}{conflict_marker}",
        f"  project_file: {record['project_file']}",
        f"  cwd: {record['cwd']}",
        f"  resolved_workspace_name: {record['resolved_workspace_name']}",
        f"  alias_conflict: {record['alias_conflict']}",
        f"  alias_conflict_owner: {record['alias_conflict_owner']}",
        f"  argv: {json.dumps(record['argv'], default=str)}",
    ]
    sase_env = record["sase_env"]
    if sase_env:
        lines.append("  sase_env:")
        for key, value in sase_env.items():
            lines.append(f"    {key}: {value}")
    else:
        lines.append("  sase_env: {}")

    lines.append("")
    lines.append("  stack:")
    stack = str(record["stack"]).rstrip("\n")
    if stack:
        lines.extend("    " + stack_line for stack_line in stack.splitlines())
    lines.append("")
    _append_locked(project_creation_log_path(), "\n".join(lines) + "\n")


def _warn_alias_conflict(record: dict[str, Any]) -> None:
    if not record["alias_conflict"]:
        return
    from sase.output import print_status

    print_status(
        f"Created project {record['project']!r}, which collides with a "
        f"PROJECT_NAME or alias owned by {record['alias_conflict_owner']!r}; "
        "this will break alias resolution. See "
        "~/.sase/logs/project_creation.log.",
        "warning",
    )
