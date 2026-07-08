"""Linux inotify-limit checks for ``sase doctor`` resources."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from sase.ace.tui.util.fs_watcher import MAX_INOTIFY_WATCHES
from sase.diagnostics import CheckStatus, DiagnosticCheck

_INOTIFY_PROC_DIR = Path("/proc/sys/fs/inotify")
_INOTIFY_LIMIT_NAMES = ("max_user_watches", "max_user_instances", "max_queued_events")
_INOTIFY_MIN_USER_INSTANCES = 8
INOTIFY_MIN_USER_INSTANCES = _INOTIFY_MIN_USER_INSTANCES


def check_inotify(
    *,
    platform: str | None = None,
    proc_dir: Path | None = None,
) -> DiagnosticCheck:
    """Check Linux inotify sysctl limits used by ACE event refresh."""
    platform = platform or sys.platform
    proc_dir = proc_dir or _INOTIFY_PROC_DIR
    if not platform.startswith("linux"):
        return DiagnosticCheck(
            id="resources.inotify",
            group="resources",
            status="SKIP",
            title="Linux inotify limits",
            summary="inotify is Linux-only; ACE will use polling fallback here",
            data={"platform": platform, "proc_dir": str(proc_dir), "limits": []},
        )

    rows = _read_inotify_limits(proc_dir)
    readable = [row for row in rows if row["status"] != "SKIP"]
    if not readable:
        return DiagnosticCheck(
            id="resources.inotify",
            group="resources",
            status="SKIP",
            title="Linux inotify limits",
            summary="inotify sysctl limits are unavailable",
            details=tuple(str(row["problem"]) for row in rows if row.get("problem")),
            data={"platform": platform, "proc_dir": str(proc_dir), "limits": rows},
        )

    problems = _inotify_problems(rows)
    status: CheckStatus = "WARN" if problems else "OK"
    summary = (
        "inotify limits look high enough for ACE event refresh"
        if status == "OK"
        else "inotify limits may force ACE event refresh back to polling"
    )
    return DiagnosticCheck(
        id="resources.inotify",
        group="resources",
        status=status,
        title="Linux inotify limits",
        summary=summary,
        details=tuple(problems),
        next_steps=_inotify_next_steps() if problems else (),
        data={
            "platform": platform,
            "proc_dir": str(proc_dir),
            "limits": rows,
            "watch_floor": MAX_INOTIFY_WATCHES,
            "instance_floor": _INOTIFY_MIN_USER_INSTANCES,
        },
    )


_check_inotify = check_inotify


def _read_inotify_limits(proc_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in _INOTIFY_LIMIT_NAMES:
        path = proc_dir / name
        try:
            raw = path.read_text(encoding="utf-8").strip()
            value = int(raw)
        except FileNotFoundError:
            rows.append(
                {
                    "name": name,
                    "path": str(path),
                    "status": "SKIP",
                    "value": None,
                    "problem": f"{path} is missing",
                }
            )
        except (OSError, ValueError) as exc:
            rows.append(
                {
                    "name": name,
                    "path": str(path),
                    "status": "SKIP",
                    "value": None,
                    "problem": f"{path} could not be read: {type(exc).__name__}: {exc}",
                }
            )
        else:
            rows.append(
                {
                    "name": name,
                    "path": str(path),
                    "status": "OK",
                    "value": value,
                    "problem": None,
                }
            )
    return rows


def _inotify_problems(rows: list[dict[str, Any]]) -> list[str]:
    by_name = {str(row["name"]): row for row in rows}
    problems: list[str] = []
    watches = by_name.get("max_user_watches", {}).get("value")
    if isinstance(watches, int) and watches < MAX_INOTIFY_WATCHES:
        problems.append(
            f"max_user_watches={watches} is below ACE's {MAX_INOTIFY_WATCHES} watch ceiling"
        )
    instances = by_name.get("max_user_instances", {}).get("value")
    if isinstance(instances, int) and instances < _INOTIFY_MIN_USER_INSTANCES:
        problems.append(
            f"max_user_instances={instances} leaves little room for concurrent ACE/prompt watchers"
        )
    return problems


def _inotify_next_steps() -> tuple[str, ...]:
    return (
        "Raise the reported `/proc/sys/fs/inotify/*` limit(s) with sysctl if ACE refreshes are falling back to polling.",
        "Close unused ACE sessions to release inotify instances and watches.",
    )
