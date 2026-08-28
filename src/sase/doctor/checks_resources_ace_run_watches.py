"""ACE ace-run shard-watch coverage checks for ``sase doctor``."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from sase.ace.tui.util.fs_watcher import (
    iter_future_ace_run_month_dirs,
    iter_startup_ace_run_shard_watch_paths,
    live_ace_run_shard_names,
)
from sase.core.time import local_now
from sase.diagnostics import CheckStatus, DiagnosticCheck
from sase.doctor.runner import DoctorContext


def check_ace_run_watches(
    context: DoctorContext,
    *,
    now: datetime | None = None,
    enabled_projects: tuple[str, ...] | None = None,
) -> DiagnosticCheck:
    """Report whether each enabled project's live ace-run shard is watched."""
    current = local_now() if now is None else now
    live_month, live_day = live_ace_run_shard_names(current)
    projects = (
        enabled_projects
        if enabled_projects is not None
        else _enabled_project_keys(context)
    )
    rows = [
        _project_watch_row(
            context,
            project,
            live_month=live_month,
            live_day=live_day,
            now=current,
        )
        for project in projects
    ]
    future_count = sum(int(row["future_month_shard_count"]) for row in rows)
    starved = [row for row in rows if row["starved"]]
    if starved:
        status: CheckStatus = "WARN"
        names = ", ".join(str(row["project"]) for row in starved)
        summary = (
            f"{len(starved)} enabled project(s) have live ace-run shards "
            f"outside ACE's startup watch budget: {names}"
        )
    elif future_count:
        status = "WARN"
        summary = (
            f"{future_count} future-dated ace-run month shard(s) can starve "
            "ACE's artifact watcher"
        )
    elif not rows:
        status = "OK"
        summary = "no enabled projects to check for ace-run watch coverage"
    else:
        status = "OK"
        summary = (
            "live ace-run shards are inside ACE's startup watch budget for "
            f"{len(rows)} enabled project(s)"
        )
    next_steps = _ace_run_watch_next_steps(rows, live_month) if status == "WARN" else ()
    return DiagnosticCheck(
        id="resources.ace_run_watches",
        group="resources",
        status=status,
        title="ACE ace-run watch coverage",
        summary=summary,
        details=_ace_run_watch_details(rows),
        next_steps=next_steps,
        data={
            "live_month": live_month,
            "live_day": live_day,
            "future_month_shard_count": future_count,
            "starved_projects": [str(row["project"]) for row in starved],
            "projects": rows,
        },
    )


def _enabled_project_keys(context: DoctorContext) -> tuple[str, ...]:
    try:
        from sase.core.project_lifecycle_facade import list_project_records

        records = list_project_records(
            context.sase_home / "projects",
            "enabled",
            include_home=False,
            projects_only=True,
        )
    except Exception:  # noqa: BLE001 - doctor isolates project listing
        return ()
    return tuple(record.project_name for record in records if record.is_project)


def _project_watch_row(
    context: DoctorContext,
    project: str,
    *,
    live_month: str,
    live_day: str,
    now: datetime,
) -> dict[str, Any]:
    workflow_dir = context.sase_home / "projects" / project / "artifacts" / "ace-run"
    selected = tuple(iter_startup_ace_run_shard_watch_paths(workflow_dir, now=now))
    selected_set = set(selected)
    live_month_dir = workflow_dir / live_month
    live_day_dir = live_month_dir / live_day
    live_month_exists = live_month_dir.is_dir()
    live_day_exists = live_day_dir.is_dir()
    live_month_watched = live_month_dir in selected_set
    live_day_watched = live_day_dir in selected_set
    starved = (live_month_exists and not live_month_watched) or (
        live_day_exists and not live_day_watched
    )
    future_dirs = tuple(iter_future_ace_run_month_dirs(workflow_dir, now=now))
    return {
        "project": project,
        "workflow_dir": str(workflow_dir),
        "live_month_exists": live_month_exists,
        "live_day_exists": live_day_exists,
        "live_month_watched": live_month_watched,
        "live_day_watched": live_day_watched,
        "starved": starved,
        "future_month_shard_count": len(future_dirs),
        "selected_watch_paths": [str(path) for path in selected],
    }


def _ace_run_watch_details(rows: list[dict[str, Any]]) -> tuple[str, ...]:
    details: list[str] = []
    for row in rows:
        project = row["project"]
        future_count = int(row["future_month_shard_count"])
        if row["starved"]:
            details.append(
                f"{project}: live ace-run shard is outside the startup watch budget"
            )
        if future_count:
            details.append(
                f"{project}: {future_count} future-dated ace-run month shard(s)"
            )
    return tuple(details)


def _ace_run_watch_next_steps(
    rows: list[dict[str, Any]],
    live_month: str,
) -> tuple[str, ...]:
    steps: list[str] = []
    for row in rows:
        future_count = int(row["future_month_shard_count"])
        if future_count == 0:
            continue
        workflow_dir = row["workflow_dir"]
        steps.append(
            f"{row['project']}: {future_count} future-dated empty ace-run "
            f"month shard(s) (names > {live_month}). Remove only empty ones "
            "with: "
            'python3 -c "'
            "from pathlib import Path;"
            f"root=Path({workflow_dir!r});cur={live_month!r};"
            "ms=[p for p in root.iterdir() if p.is_dir() and p.name.isdigit() "
            "and len(p.name)==6 and p.name>cur];"
            "[c.rmdir() for m in ms if not any(p.is_file() for p in m.rglob('*')) "
            "for c in [*list(m.iterdir()), m] if c.is_dir() and not any(c.iterdir())]"
            '"'
        )
    if not steps:
        steps.append(
            "Inspect ACE's inotify watch set and confirm the live ace-run "
            "month and day shards are installed."
        )
    return tuple(steps)
