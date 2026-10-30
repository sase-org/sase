"""Entry point and orchestration for the historical prompt migration."""

from __future__ import annotations

import argparse
from pathlib import Path
import json

from rich.table import Table

from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.migration._common import (
    PromptMigrationReport,
    PromptMigrationSkip,
)
from sase.agents_sync.prompt_archive.migration.apply import apply_month
from sase.agents_sync.prompt_archive.migration.planning import (
    filter_publishable_migration_items,
    plan_items,
)
from sase.agents_sync.prompt_archive.migration.publishing import (
    publish_migration_sidecars,
)
from sase.output import console, error_console


def migrate_prompt_archive(
    args: argparse.Namespace,
    *,
    target: ProjectTarget,
    plans_repo: Path,
) -> int:
    """Run and render one prompt-archive migration command."""

    try:
        report = _migrate_prompt_archive_repositories(
            target,
            plans_repo,
            month=getattr(args, "month", None),
            write=bool(getattr(args, "write", False)),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        error_console.print(f"[red]Error:[/red] {exc}")
        return 1
    if getattr(args, "json", False):
        print(json.dumps(report.to_json_dict(), indent=2))
    else:
        _print_report(report)
    return 0


def _migrate_prompt_archive_repositories(
    target: ProjectTarget,
    plans_repo: Path,
    *,
    month: str | None = None,
    write: bool = False,
    git_runner: GitRunner | None = None,
) -> PromptMigrationReport:
    """Plan or apply the historical prompt migration for one project."""

    agents_repo = target.sidecar_path
    _require_repository(plans_repo, "plans")
    _require_repository(agents_repo, "agents")
    planned = plan_items(plans_repo, agents_repo, month=month)
    items, protection_skips = filter_publishable_migration_items(
        target, plans_repo, planned
    )
    if write:
        _require_clean(plans_repo, "plans")
        _require_clean(agents_repo, "agents")
    moved = 0
    relinked = 0
    months_committed = 0
    active_repos: set[Path] = set()
    skips: list[PromptMigrationSkip] = list(protection_skips)
    for prompt_month in sorted({item.month for item in items}):
        month_items = tuple(item for item in items if item.month == prompt_month)
        movable = month_items
        skips.extend(skip for item in month_items for skip in item.skips)
        moved += len(movable)
        relinked += sum(item.plan_changed for item in movable)
        if write and movable:
            active_repos.update((agents_repo, plans_repo))
            apply_month(
                target,
                plans_repo,
                prompt_month,
                movable,
            )
            months_committed += 1
    if write:
        publish_migration_sidecars(
            target,
            plans_repo,
            month=month,
            active_repos=active_repos,
            git_runner=git_runner or run_git,
        )
    return PromptMigrationReport(
        project=target.project,
        write=write,
        prompts_moved=moved,
        plans_relinked=relinked,
        months_committed=months_committed,
        skipped=tuple(skips),
    )


def _require_repository(repo: Path, label: str) -> None:
    if not repo.is_dir() or not (repo / ".git").exists():
        raise ValueError(f"{label} sidecar is unavailable: {repo}")


def _require_clean(repo: Path, label: str) -> None:
    status = run_git(repo, ["status", "--porcelain"], op="prompt_migrate.status")
    if status.returncode != 0:
        raise RuntimeError(
            status.stderr.strip() or f"could not inspect {label} sidecar"
        )
    if status.stdout.strip():
        raise ValueError(f"{label} sidecar has uncommitted changes")


def _print_report(report: PromptMigrationReport) -> None:
    table = Table(title=f"Prompt archive migration · {report.project}", box=None)
    table.add_column("MODE")
    table.add_column("PROMPTS MOVED", justify="right")
    table.add_column("PLANS RELINKED", justify="right")
    table.add_column("FILES SKIPPED", justify="right")
    table.add_row(
        "write" if report.write else "report",
        str(report.prompts_moved),
        str(report.plans_relinked),
        str(len(report.skipped)),
    )
    console.print(table)
    for skip in report.skipped:
        console.print(f"[yellow]skip:[/yellow] {skip.path}: {skip.reason}")


__all__ = [
    "migrate_prompt_archive",
]
