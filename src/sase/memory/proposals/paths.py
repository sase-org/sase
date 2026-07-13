"""Project-scoped paths for memory proposal storage."""

from __future__ import annotations

from pathlib import Path

from sase.core.paths import sase_projects_dir
from sase.main.init_memory.config import project_memory_name
from sase.project_aliases import resolve_project_alias_ref


def memory_proposal_ledger_path(
    project: str | None = None, *, cwd: Path | None = None
) -> Path:
    """Return the project-scoped memory-proposal JSONL ledger path."""
    project_name = resolve_project_alias_ref(
        project or project_memory_name(cwd or Path.cwd())
    )
    return sase_projects_dir() / project_name / "memory_proposals.jsonl"


def memory_proposal_lock_path(
    project: str | None = None,
    *,
    cwd: Path | None = None,
    ledger_path: Path | None = None,
) -> Path:
    """Return the lock sidecar for a memory-proposal ledger path."""
    path = ledger_path or memory_proposal_ledger_path(project, cwd=cwd)
    return path.with_suffix(".lock")
