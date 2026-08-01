"""Historical plans-sidecar prompt migration into the canonical archive."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import tempfile

from rich.table import Table

from sase._git_remote import github_blob_url
from sase.agents_sync import git_sync
from sase.agents_sync.git import run_git
from sase.agents_sync.links import hosted_provider
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.index import render_prompt_month_index
from sase.output import console, error_console
from sase.sdd._commit_store import commit_sdd_files
from sase.sdd._git_contention import store_git_write_lock
from sase.sdd._legacy_prompt_files import list_plans_store_prompt_files
from sase.sdd.artifact_links import (
    SddArtifactLinkType,
    update_source_aware_artifact_link,
)
from sase.sdd.hosted_links import resolve_hosted_branch, resolve_origin_remote_url


@dataclass(frozen=True, slots=True)
class _PromptMigrationSkip:
    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class _PromptMigrationReport:
    project: str
    write: bool
    prompts_moved: int
    plans_relinked: int
    months_committed: int
    skipped: tuple[_PromptMigrationSkip, ...]

    def to_json_dict(self) -> dict[str, object]:
        return {
            "project": self.project,
            "write": self.write,
            "prompts_moved": self.prompts_moved,
            "plans_relinked": self.plans_relinked,
            "months_committed": self.months_committed,
            "files_skipped": [asdict(item) for item in self.skipped],
        }


@dataclass(frozen=True, slots=True)
class _MigrationItem:
    month: str
    source: Path
    destination: Path
    prompt_content: str
    plan_path: Path | None
    plan_content: str | None
    plan_changed: bool
    displaced_destination: Path | None = None
    displaced_content: str | None = None
    skips: tuple[_PromptMigrationSkip, ...] = ()


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
) -> _PromptMigrationReport:
    """Plan or apply the historical prompt migration for one project."""

    agents_repo = target.sidecar_path
    _require_repository(plans_repo, "plans")
    _require_repository(agents_repo, "agents")
    items = _plan_items(plans_repo, agents_repo, month=month)
    if write:
        _require_clean(plans_repo, "plans")
        _require_clean(agents_repo, "agents")
    moved = 0
    relinked = 0
    months_committed = 0
    skips: list[_PromptMigrationSkip] = []
    for prompt_month in sorted({item.month for item in items}):
        month_items = tuple(item for item in items if item.month == prompt_month)
        movable = month_items
        skips.extend(skip for item in month_items for skip in item.skips)
        moved += len(movable)
        relinked += sum(item.plan_changed for item in movable)
        if write and movable:
            _apply_month(plans_repo, agents_repo, prompt_month, movable)
            months_committed += 1
    return _PromptMigrationReport(
        project=target.project,
        write=write,
        prompts_moved=moved,
        plans_relinked=relinked,
        months_committed=months_committed,
        skipped=tuple(skips),
    )


def _plan_items(
    plans_repo: Path,
    agents_repo: Path,
    *,
    month: str | None,
) -> tuple[_MigrationItem, ...]:
    plan_url = _hosted_blob_builder(plans_repo)
    prompt_url = _hosted_blob_builder(agents_repo)
    items: list[_MigrationItem] = []
    for source, prompt_month in list_plans_store_prompt_files(plans_repo, month=month):
        destination = agents_repo / "prompts" / prompt_month / source.name
        skips: list[_PromptMigrationSkip] = []
        plan_path = _resolve_plan_path(plans_repo, prompt_month, source.name)
        original_prompt = source.read_text(encoding="utf-8")
        prompt_content = original_prompt
        plan_content: str | None = None
        plan_changed = False
        displaced_destination: Path | None = None
        displaced_content: str | None = None
        if plan_path is None:
            skips.append(
                _PromptMigrationSkip(
                    _relpath(plans_repo, source),
                    "paired plan is missing; moved prompt without adding PLAN",
                )
            )
        else:
            prompt_content, prompt_skip = _rewrite_prompt_link(
                prompt_content,
                plans_repo=plans_repo,
                source=source,
                label=f"{prompt_month}/{source.name}",
                href=plan_url(f"{prompt_month}/{source.name}"),
            )
            if prompt_skip is not None:
                skips.append(prompt_skip)
            original_plan = plan_path.read_text(encoding="utf-8")
            plan_content, plan_skip = _rewrite_plan_link(
                original_plan,
                plans_repo=plans_repo,
                plan_path=plan_path,
                label=f"prompts/{prompt_month}/{source.name}",
                href=prompt_url(f"prompts/{prompt_month}/{source.name}"),
            )
            if plan_skip is not None:
                skips.append(plan_skip)
            plan_changed = plan_content != original_plan
        if (
            destination.is_file()
            and destination.read_text(encoding="utf-8") != prompt_content
        ):
            displaced_content = destination.read_text(encoding="utf-8")
            displaced_destination = _displaced_destination(
                destination,
                displaced_content,
            )
        items.append(
            _MigrationItem(
                prompt_month,
                source,
                destination,
                prompt_content,
                plan_path,
                plan_content,
                plan_changed,
                displaced_destination,
                displaced_content,
                tuple(skips),
            )
        )
    return tuple(items)


def _rewrite_prompt_link(
    content: str,
    *,
    plans_repo: Path,
    source: Path,
    label: str,
    href: str | None,
) -> tuple[str, _PromptMigrationSkip | None]:
    if href is None:
        return content, _PromptMigrationSkip(
            _relpath(plans_repo, source), "plans-sidecar hosted URL is unavailable"
        )
    try:
        return (
            update_source_aware_artifact_link(
                content,
                plans_repo,
                source,
                None,
                SddArtifactLinkType.PLAN,
                target_label=label,
                target_href=href,
                remove_legacy=True,
            ),
            None,
        )
    except ValueError as exc:
        return content, _PromptMigrationSkip(
            _relpath(plans_repo, source), f"PLAN rewrite skipped: {exc}"
        )


def _rewrite_plan_link(
    content: str,
    *,
    plans_repo: Path,
    plan_path: Path,
    label: str,
    href: str | None,
) -> tuple[str, _PromptMigrationSkip | None]:
    if href is None:
        return content, _PromptMigrationSkip(
            _relpath(plans_repo, plan_path),
            "agents-sidecar hosted URL is unavailable",
        )
    try:
        return (
            update_source_aware_artifact_link(
                content,
                plans_repo,
                plan_path,
                None,
                SddArtifactLinkType.PROMPT,
                target_label=label,
                target_href=href,
                remove_legacy=True,
            ),
            None,
        )
    except ValueError as exc:
        fallback = _replace_canonical_link_line(
            content,
            link_type="PROMPT",
            label=label,
            href=href,
        )
        if fallback is not None:
            return fallback, None
        return content, _PromptMigrationSkip(
            _relpath(plans_repo, plan_path), f"PROMPT rewrite skipped: {exc}"
        )


def _apply_month(
    plans_repo: Path,
    agents_repo: Path,
    month: str,
    items: tuple[_MigrationItem, ...],
) -> None:
    lock_path = git_sync.agents_git_dir(agents_repo, run_git) / (
        "sase-agents-sync.lock"
    )
    with store_git_write_lock(
        plans_repo,
        op="prompt_archive.migrate",
        mutates_worktree=True,
    ) as plans_locked:
        if not plans_locked:
            raise RuntimeError("plans-sidecar write lock is busy")
        with git_sync.bounded_agents_lock(
            lock_path,
            git_sync.configured_agents_lock_timeout(),
        ) as agents_locked:
            if not agents_locked:
                raise RuntimeError("agents-sidecar write lock is busy")
            plan_paths: list[Path] = []
            agent_paths: list[Path] = []
            for item in items:
                if (
                    item.displaced_destination is not None
                    and item.displaced_content is not None
                ):
                    _atomic_write(
                        item.displaced_destination,
                        item.displaced_content,
                    )
                    agent_paths.append(item.displaced_destination)
                _atomic_write(item.destination, item.prompt_content)
                agent_paths.append(item.destination)
                if (
                    item.plan_changed
                    and item.plan_path
                    and item.plan_content is not None
                ):
                    _atomic_write(item.plan_path, item.plan_content)
                    plan_paths.append(item.plan_path)
                item.source.unlink()
                plan_paths.append(item.source)
            index_path = agents_repo / "prompts" / month / "README.md"
            _atomic_write(index_path, render_prompt_month_index(index_path.parent))
            agent_paths.append(index_path)
            _commit_paths(
                agents_repo,
                agent_paths,
                f"chore(prompts): migrate {month} prompt archive",
            )
            commit_sdd_files(
                plans_repo,
                f"Migrate {month} prompts to agents sidecar",
                paths=plan_paths,
                sidecar_role="plans",
                already_locked=True,
            )


def _commit_paths(repo: Path, paths: list[Path], message: str) -> None:
    relpaths = sorted({_relpath(repo, path) for path in paths})
    added = run_git(repo, ["add", "--all", "--", *relpaths], op="prompt_migrate.add")
    if added.returncode != 0:
        raise RuntimeError(added.stderr.strip() or "could not stage prompt migration")
    dirty = run_git(
        repo,
        ["diff", "--cached", "--quiet", "--", *relpaths],
        op="prompt_migrate.diff",
    )
    if dirty.returncode == 0:
        return
    if dirty.returncode != 1:
        raise RuntimeError(dirty.stderr.strip() or "could not inspect migration diff")
    committed = run_git(
        repo,
        [
            "-c",
            "user.name=SASE",
            "-c",
            "user.email=sase@localhost",
            "commit",
            "-m",
            message,
            "--",
            *relpaths,
        ],
        op="prompt_migrate.commit",
    )
    if committed.returncode != 0:
        raise RuntimeError(committed.stderr.strip() or "could not commit migration")


def _resolve_plan_path(plans_repo: Path, month: str, name: str) -> Path | None:
    candidates = (
        plans_repo / month / name,
        plans_repo / "plans" / month / name,
    )
    matches = tuple(path for path in candidates if path.is_file())
    return matches[0] if len(matches) == 1 else None


def _displaced_destination(destination: Path, content: str) -> Path:
    counter = 1
    while True:
        candidate = destination.with_name(
            f"{destination.stem}_{counter}{destination.suffix}"
        )
        if not candidate.exists() or candidate.read_text(encoding="utf-8") == content:
            return candidate
        counter += 1


def _replace_canonical_link_line(
    content: str,
    *,
    link_type: str,
    label: str,
    href: str,
) -> str | None:
    """Repair one known header line when unrelated body prose confuses parsing."""

    pattern = re.compile(rf"(?m)^- \*\*{link_type}:\*\*[^\n]*$")
    updated, count = pattern.subn(
        f"- **{link_type}:** [{label}]({href})",
        content,
        count=1,
    )
    return updated if count == 1 else None


def _hosted_blob_builder(repo: Path) -> Callable[[str], str | None]:
    remote = resolve_origin_remote_url(repo)
    branch = resolve_hosted_branch(repo)

    def build(path: str) -> str | None:
        if remote is None or branch is None:
            return None
        return github_blob_url(
            remote,
            provider=hosted_provider(remote),
            branch=branch,
            path=path,
        )

    return build


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


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


def _relpath(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _print_report(report: _PromptMigrationReport) -> None:
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
