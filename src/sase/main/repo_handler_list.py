"""Implementation and presentation for ``sase repo list``."""

from __future__ import annotations

import argparse
from collections import defaultdict
from collections.abc import Callable, Sequence
import json
from pathlib import Path
import sys

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from sase.repo_inventory import (
    RepoInventory,
    RepoInventoryProjectNotFoundError,
    RepoRecord,
)

from .repo_handler_common import (
    InventoryCollector,
    ProjectContextResolver,
    RepoOpenResolutionError,
    clone_for_workspace,
)
from .workspace_handler_context import ProjectContext


_KIND_STYLES = {
    "primary": "bold #00D7AF",
    "sidecar": "bold #AF87FF",
    "linked": "bold #87D7FF",
    "external": "bold #FFAF00",
}

WorkspaceResolver = Callable[[ProjectContext, int | None], int]
WorkspaceValidator = Callable[..., None]


def handle_list_command(
    args: argparse.Namespace,
    *,
    collect_inventory: InventoryCollector,
    resolve_project_context: ProjectContextResolver,
    resolve_workspace_num: WorkspaceResolver,
    validate_workspace: WorkspaceValidator,
) -> int:
    all_projects = bool(getattr(args, "all_projects", False))
    requested_project = getattr(args, "project", None)
    if all_projects and requested_project:
        print("--all cannot be combined with --project", file=sys.stderr)
        return 2

    if all_projects:
        inventory = collect_inventory(include_disabled=True)
        if getattr(args, "json", False):
            payload = inventory_json_payload(inventory, workspace_num=0)
            payload["all_projects"] = True
            print(json.dumps(payload, indent=2, sort_keys=True))
            print_inventory_issues_stderr(inventory)
        else:
            print_human(inventory, workspace_num=0, project=None)
        return 0

    ctx = resolve_project_context(requested_project)
    try:
        workspace_num = resolve_workspace_num(
            ctx,
            getattr(args, "workspace", None),
        )
    except RepoOpenResolutionError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        inventory = collect_inventory(project=ctx.project_name)
    except RepoInventoryProjectNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    try:
        display_project = next(
            (record.project for record in inventory.records),
            ctx.project_name,
        )
        validate_workspace(
            inventory.records,
            project=display_project,
            workspace_num=workspace_num,
        )
    except RepoOpenResolutionError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if getattr(args, "json", False):
        payload = inventory_json_payload(inventory, workspace_num=workspace_num)
        payload["project"] = display_project
        payload["workspace_num"] = workspace_num
        print(json.dumps(payload, indent=2, sort_keys=True))
        print_inventory_issues_stderr(inventory)
    else:
        print_human(
            inventory,
            workspace_num=workspace_num,
            project=display_project,
        )
    return 0


def print_human(
    inventory: RepoInventory,
    *,
    workspace_num: int,
    project: str | None,
    console: Console | None = None,
) -> None:
    output = console or Console()
    grouped: dict[str, list[RepoRecord]] = defaultdict(list)
    for record in inventory.records:
        grouped[record.project].append(record)

    if project is not None:
        output.print(
            repo_panel(
                grouped.get(project, list(inventory.records)),
                project=project,
                workspace_num=workspace_num,
            )
        )
    elif grouped:
        for project_name in sorted(grouped, key=str.casefold):
            output.print(
                repo_panel(
                    grouped[project_name],
                    project=project_name,
                    workspace_num=workspace_num,
                )
            )
    else:
        output.print(Text("No repositories found.", style="dim"))

    if inventory.issues:
        warnings = Text()
        for index, issue in enumerate(inventory.issues):
            if index:
                warnings.append("\n")
            warnings.append(f"[{issue.project}] ", style="bold #FFD700")
            warnings.append(issue.message, style="dim")
        output.print(
            Panel(
                warnings,
                title="Inventory warnings",
                border_style="#FFD700",
                box=box.ROUNDED,
            )
        )


def repo_panel(
    records: Sequence[RepoRecord],
    *,
    project: str,
    workspace_num: int,
) -> Panel:
    table = Table(
        box=box.SIMPLE_HEAD,
        expand=True,
        pad_edge=False,
        show_edge=False,
    )
    table.add_column("NAME", style="bold", no_wrap=True)
    table.add_column("KIND", no_wrap=True)
    table.add_column("CLONED", justify="center", no_wrap=True)
    table.add_column("WORKSPACES", justify="right", no_wrap=True)
    table.add_column("PATH", overflow="ellipsis", no_wrap=True, ratio=1)

    for record in records:
        clone = clone_for_workspace(record, workspace_num)
        cloned_count = sum(item.exists for item in record.clones)
        total_count = len(record.clones)
        if not record.clones:
            cloned_count = int(record.exists)
            total_count = 1
        table.add_row(
            Text(record.name),
            Text(record.kind, style=_KIND_STYLES[record.kind]),
            Text(
                "✓" if clone.exists else "✗",
                style="green" if clone.exists else "#FFD700",
            ),
            f"{cloned_count}/{total_count}",
            Text(compact_path(clone.path), style="dim" if clone.exists else "#FFD700"),
        )

    if not records:
        table.add_row(Text("No repositories found.", style="dim"), "", "", "", "")

    return Panel(
        table,
        title=f"Repos · {project} · workspace #{workspace_num}",
        title_align="left",
        border_style="#00D7AF",
        box=box.ROUNDED,
    )


def compact_path(path: str, *, max_len: int = 72) -> str:
    value = path or "-"
    home = str(Path.home())
    if value == home or value.startswith(f"{home}/"):
        value = f"~{value[len(home) :]}"
    if len(value) <= max_len:
        return value
    return f"…{value[-(max_len - 1) :]}"


def inventory_json_payload(
    inventory: RepoInventory,
    *,
    workspace_num: int,
) -> dict[str, object]:
    return {
        "repos": [
            record.to_json_dict(workspace_num=workspace_num)
            for record in inventory.records
        ],
        "issues": [issue.to_json_dict() for issue in inventory.issues],
    }


def print_inventory_issues_stderr(inventory: RepoInventory) -> None:
    for issue in inventory.issues:
        print(f"warning [{issue.project}]: {issue.message}", file=sys.stderr)
