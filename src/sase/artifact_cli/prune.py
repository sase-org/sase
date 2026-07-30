"""Implementation of dry-run-first ``sase artifact prune``."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sase.config import get_artifact_retention_keep_per_label
from sase.core.artifact_file_explicit import read_artifact_file_index
from sase.core.artifact_file_protection import collect_protected_artifact_ids
from sase.core.artifact_file_retention import (
    RetentionPlan,
    RetentionPolicy,
    plan_artifact_file_retention,
)
from sase.core.artifact_file_trash import TrashResult, trash_artifact_files
from sase.project_display_names import (
    ProjectRefDisplaySnapshot,
    load_project_ref_display_snapshot,
)


ARTIFACT_PRUNE_SCHEMA_VERSION = 1


def handle_prune(args: argparse.Namespace) -> int:
    """Plan artifact retention and apply it only when explicitly requested."""

    projects = load_project_ref_display_snapshot()
    raw_project = getattr(args, "project", None)
    project = None if raw_project is None else projects.project_key_for_ref(raw_project)
    if raw_project is not None and project is None:
        print(f"Error: unknown project reference: {raw_project}", file=sys.stderr)
        return 2

    protections = collect_protected_artifact_ids()
    limit = getattr(args, "limit", None)
    keep_generations = getattr(args, "keep_generations", None)
    policy = RetentionPolicy(
        now=datetime.now(UTC).isoformat(),
        keep_per_label=(
            get_artifact_retention_keep_per_label()
            if keep_generations is None
            else keep_generations
        ),
        before=getattr(args, "before", None),
        kinds=(None if getattr(args, "kind", None) is None else tuple(args.kind)),
        project=project,
        min_size_bytes=getattr(args, "min_size", None),
        protected_ids=protections.ids,
        limit=None if limit == 0 else limit,
    )
    plan = plan_artifact_file_retention(policy)
    apply = bool(getattr(args, "apply", False))
    unavailable = protections.sources_unavailable

    execution: TrashResult | None = None
    blocked = apply and bool(unavailable)
    if apply and not blocked:
        selected_ids = {item.id for item in plan.selected}
        rows_by_id = {row.id: row for row in read_artifact_file_index()}
        missing = sorted(selected_ids - rows_by_id.keys())
        if missing:
            print(
                "Error: planned artifact rows disappeared before apply: "
                + ", ".join(missing),
                file=sys.stderr,
            )
            return 1
        execution = trash_artifact_files(
            [rows_by_id[item.id] for item in plan.selected],
            reason="pruned",
            now=policy.now,
        )

    payload = {
        "schema_version": ARTIFACT_PRUNE_SCHEMA_VERSION,
        "mode": "apply" if apply else "dry_run",
        "blocked": blocked,
        "sources_unavailable": list(unavailable),
        "policy": {
            "now": policy.now,
            "keep_per_label": policy.keep_per_label,
            "before": policy.before,
            "kinds": None if policy.kinds is None else list(policy.kinds),
            "project": policy.project,
            "min_size_bytes": policy.min_size_bytes,
            "protected_ids": sorted(policy.protected_ids),
            "limit": policy.limit,
        },
        "plan": plan.to_json_dict(),
        "execution": None if execution is None else execution.to_json_dict(),
    }
    if bool(getattr(args, "json", False)):
        json.dump(payload, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        _print_plan(plan, projects=projects)
        for source in unavailable:
            Console().print(f"[yellow]Protection source unavailable:[/yellow] {source}")
        if blocked:
            Console().print(
                "[red]Apply refused:[/red] every required protection source "
                "must be readable."
            )
        elif execution is not None:
            Console().print(
                f"[green]Trashed {execution.rows_trashed} rows "
                f"({_human_size(execution.bytes_reclaimed)} reclaimed).[/green] "
                f"Trash: {execution.trash_root}"
            )
        else:
            Console().print(
                "[cyan]Dry run only; pass --apply to move these rows to trash.[/cyan]"
            )
    return 1 if blocked else 0


def _print_plan(
    plan: RetentionPlan,
    *,
    projects: ProjectRefDisplaySnapshot,
) -> None:
    table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
    table.add_column("REF", style="bold")
    table.add_column("LABEL")
    table.add_column("KIND")
    table.add_column("PROJECT")
    table.add_column("SIZE", justify="right")
    table.add_column("REASON")
    for item in plan.selected:
        table.add_row(
            f"file:{item.id}",
            item.label,
            item.kind,
            projects.display_snapshot.label_for(item.project) if item.project else "-",
            _human_size(item.size_bytes),
            item.reason,
        )
    if not plan.selected:
        table.add_row("[dim]none[/dim]", "-", "-", "-", "-", "-")
    title = (
        f"Artifact Prune Plan ({plan.counts.selected} selected, "
        f"{_human_size(plan.reclaimable_bytes)} reclaimable"
        f"{f', {plan.truncated} truncated' if plan.truncated else ''})"
    )
    Console().print(Panel(table, title=title, border_style="cyan"))


def _human_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "-"
    value = float(size_bytes)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024 or unit == "TiB":
            return f"{int(value)} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size_bytes} B"


__all__ = ["ARTIFACT_PRUNE_SCHEMA_VERSION", "handle_prune"]
