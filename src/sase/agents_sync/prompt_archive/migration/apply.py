"""Apply one planned migration month to both sidecar worktrees."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

from sase.agents_sync import git_sync
from sase.agents_sync.git import run_git
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.index import render_prompt_month_index
from sase.agents_sync.prompt_archive.migration._common import MigrationItem, relpath
from sase.sdd._commit_store import commit_sdd_files
from sase.sdd._git_contention import store_git_write_lock


def apply_month(
    target: ProjectTarget,
    plans_repo: Path,
    month: str,
    items: tuple[MigrationItem, ...],
) -> None:
    agents_repo = target.sidecar_path
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
            from sase.agents_sync.prompt_archive.protection import (
                protection_scope_for_target,
                scan_archive_text_bytes,
            )

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
            index_content = render_prompt_month_index(index_path.parent)
            index_verdict = scan_archive_text_bytes(
                index_content.encode("utf-8"),
                scope=protection_scope_for_target(target),
                relative_destination=relpath(agents_repo, index_path),
                affected_requests=(f"migrate:{month}/README.md",),
            )
            if index_verdict.publishable:
                _atomic_write(index_path, index_content)
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
    relpaths = sorted({relpath(repo, path) for path in paths})
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
    from sase.agents_sync.git_sync_ops import AGENTS_SYNC_AUTO_COMMIT_TYPE
    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    committed = run_git(
        repo,
        [
            "-c",
            "user.name=SASE",
            "-c",
            "user.email=sase@localhost",
            "commit",
            "-m",
            apply_auto_commit_type_tag(message, AGENTS_SYNC_AUTO_COMMIT_TYPE),
            "--",
            *relpaths,
        ],
        op="prompt_migrate.commit",
    )
    if committed.returncode != 0:
        raise RuntimeError(committed.stderr.strip() or "could not commit migration")


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


__all__ = [
    "apply_month",
]
