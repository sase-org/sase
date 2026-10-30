"""CLI rendering for ``sase agent sync`` mutation and status checks."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from rich.console import Console
from rich.table import Table
from rich.text import Text

from sase.agents_sync.git_sync import sync_agents
from sase.agents_sync.models import ProjectSyncStatus, SyncOutcome
from sase.agents_sync.publication_repair import (
    repair_agent_hood_digests,
    repair_agent_owner_manifests,
)
from sase.agents_sync.publication_revision_repair import (
    repair_stale_publication_revisions,
)
from sase.agents_sync.publication_state_repair import (
    StateRepairReport,
    repair_agent_run_states,
)
from sase.agents_sync.status import get_agents_sync_status
from sase.core.time import format_local


def handle_agents_sync(args: argparse.Namespace) -> int:
    """Run the selected sync mode, render it, and return a truthful exit code."""

    projects = tuple(getattr(args, "project", ()) or ())
    as_json = bool(getattr(args, "json", False))
    if bool(getattr(args, "repair_digests", False)):
        outcomes = repair_agent_hood_digests(projects)
        _emit_sync_outcomes(outcomes, mode="repair-digests", as_json=as_json)
        return int(any(outcome.error is not None for outcome in outcomes))
    if bool(getattr(args, "repair_manifest", False)):
        outcomes = repair_agent_owner_manifests(projects)
        _emit_sync_outcomes(outcomes, mode="repair-manifest", as_json=as_json)
        return int(any(outcome.error is not None for outcome in outcomes))
    if bool(getattr(args, "repair_revisions", False)):
        outcomes = repair_stale_publication_revisions(
            projects,
            apply=bool(getattr(args, "apply", False)),
        )
        _emit_sync_outcomes(outcomes, mode="repair-revisions", as_json=as_json)
        return int(any(outcome.error is not None for outcome in outcomes))
    if bool(getattr(args, "repair_states", False)):
        reports = repair_agent_run_states(
            projects,
            apply=bool(getattr(args, "apply", False)),
            state_limit=getattr(args, "state_limit", None),
            state_after=getattr(args, "state_after", None),
        )
        _emit_state_repair(reports, as_json=as_json)
        return int(any(report.error is not None for report in reports))
    if bool(getattr(args, "check", False)):
        snapshot = get_agents_sync_status(
            projects,
            refresh=bool(getattr(args, "refresh", False)),
        )
        if as_json:
            json.dump(
                {
                    "schema_version": snapshot.schema_version,
                    "mode": "check",
                    "checked_at": snapshot.checked_at,
                    "projects": [status.to_json_dict() for status in snapshot.projects],
                },
                sys.stdout,
                indent=2,
                sort_keys=True,
            )
            sys.stdout.write("\n")
        else:
            _render_status(snapshot.projects)
        return int(
            any(
                status.state in {"configuration_error", "error"}
                for status in snapshot.projects
            )
        )

    outcomes = sync_agents(
        projects,
        retry_quarantined=bool(getattr(args, "retry_quarantined", False)),
        retry_retired=bool(getattr(args, "retry_retired", False)),
        drop_retired=bool(getattr(args, "drop_retired", False)),
        retry_limit=getattr(args, "retry_limit", None),
        retry_error_classes=tuple(getattr(args, "retry_error_class", ()) or ()),
        retry_key=getattr(args, "retry_key", None),
    )
    _emit_sync_outcomes(outcomes, mode="sync", as_json=as_json)
    return int(any(outcome.error is not None for outcome in outcomes))


def _emit_sync_outcomes(
    outcomes: tuple[SyncOutcome, ...],
    *,
    mode: str,
    as_json: bool,
) -> None:
    if as_json:
        json.dump(
            {
                "schema_version": 2,
                "mode": mode,
                "projects": [outcome.to_json_dict() for outcome in outcomes],
            },
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
    else:
        _render_outcomes(outcomes)


def _emit_state_repair(
    reports: tuple[StateRepairReport, ...], *, as_json: bool
) -> None:
    if as_json:
        json.dump(
            {
                "schema_version": 1,
                "mode": "repair-states",
                "projects": [report.to_json_dict() for report in reports],
            },
            sys.stdout,
            indent=2,
            sort_keys=True,
        )
        sys.stdout.write("\n")
    else:
        _render_state_repair(reports)


def _render_state_repair(reports: tuple[StateRepairReport, ...]) -> None:
    table = Table(title="Agent State Repair", header_style="bold cyan")
    table.add_column("PROJECT", style="bold")
    table.add_column("EXAMINED", justify="right")
    table.add_column("CHANGED", justify="right")
    table.add_column("CURRENT", justify="right")
    table.add_column("LIVE", justify="right")
    table.add_column("UNRESOLVED", justify="right")
    table.add_column("WITHHELD", justify="right")
    table.add_column("FAILED", justify="right")
    table.add_column("RESULT")
    for report in reports:
        if report.error:
            result = Text(report.error, style="red")
        elif report.skip_reason:
            result = Text(report.skip_reason, style="yellow")
        elif report.mode == "apply" and report.committed and report.pushed:
            result = Text("applied", style="green")
        elif report.mode == "apply":
            result = Text("applied (no push)", style="green")
        else:
            result = Text("reported", style="green")
        table.add_row(
            report.project or report.project_key,
            str(report.examined),
            str(report.changed),
            str(report.already_current),
            str(report.live),
            str(report.unresolved),
            str(report.withheld),
            str(report.failed),
            result,
        )
    console = Console()
    console.print(table)
    for report in reports:
        name = report.project or report.project_key
        for affected in report.affected:
            console.print(
                Text(
                    f"{name}: {affected.global_name} "
                    f"({affected.local_hood}/{affected.source_run_id}) -> "
                    f"{affected.selected_state}",
                    style="green",
                )
            )
        if report.next_cursor is not None:
            console.print(
                Text(
                    f"{name}: next cursor {report.next_cursor} "
                    f"(pass_complete={str(report.pass_complete).lower()})"
                )
            )
        for diagnostic in report.diagnostics:
            console.print(Text(f"{name}: {diagnostic}", style="yellow"))


def _render_outcomes(outcomes: tuple[SyncOutcome, ...]) -> None:
    table = Table(title="Agent Sync", header_style="bold cyan")
    table.add_column("PROJECT", style="bold")
    table.add_column("V1", justify="right")
    table.add_column("HOODS", justify="right")
    table.add_column("RUNS", justify="right")
    table.add_column("RESULT")
    for outcome in outcomes:
        result: Text
        if outcome.error:
            result = Text(outcome.error, style="red")
        elif outcome.skip_reason:
            result = Text(outcome.skip_reason, style="yellow")
        else:
            result = Text("synchronized", style="green")
        table.add_row(
            outcome.project,
            str(outcome.exported + outcome.export_refreshed),
            str(outcome.hoods_published + outcome.hoods_refreshed),
            str(outcome.runs_published),
            result,
        )
    console = Console()
    console.print(table)
    for outcome in outcomes:
        for diagnostic in outcome.diagnostics:
            console.print(Text(f"{outcome.project}: {diagnostic}", style="yellow"))


def _render_status(statuses: Sequence[ProjectSyncStatus]) -> None:
    table = Table(title="Agent Sync Status", header_style="bold cyan")
    table.add_column("PROJECT", style="bold")
    table.add_column("STATE")
    table.add_column("BEHIND", justify="right")
    table.add_column("AHEAD", justify="right")
    table.add_column("LAST FETCH")
    table.add_column("DETAIL")
    for status in statuses:
        style = (
            "red"
            if status.state in {"configuration_error", "error"}
            else "yellow"
            if status.state != "ready"
            else "green"
        )
        table.add_row(
            status.project,
            Text(status.state, style=style),
            _number(status.behind),
            _number(status.ahead),
            _timestamp(status.last_fetch_time),
            _status_detail(status),
        )
    Console().print(table)


def _status_detail(status: ProjectSyncStatus) -> str:
    parts = tuple(
        part
        for part in (
            status.error,
            status.detail,
            *status.quarantine_diagnostics,
        )
        if part
    )
    return "; ".join(dict.fromkeys(parts)) if parts else "-"


def _number(value: int | None) -> str:
    return "-" if value is None else str(value)


def _timestamp(value: float | None) -> str:
    if value is None:
        return "-"
    return format_local(value, "%Y-%m-%d %H:%M %Z", default="-")


__all__ = ["handle_agents_sync"]
