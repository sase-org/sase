"""Project-scoped paths for memory proposal storage."""

from __future__ import annotations

from pathlib import Path

from sase.main.init_memory.config import project_memory_name


def memory_proposal_ledger_path(
    project: str | None = None, *, cwd: Path | None = None
) -> Path:
    """Return the project-scoped memory-proposal JSONL ledger path."""
    project_name = project or project_memory_name(cwd or Path.cwd())
    return Path.home() / ".sase" / "projects" / project_name / "memory_proposals.jsonl"


def memory_proposal_lock_path(
    project: str | None = None,
    *,
    cwd: Path | None = None,
    ledger_path: Path | None = None,
) -> Path:
    """Return the lock companion for a memory-proposal ledger path."""
    path = ledger_path or memory_proposal_ledger_path(project, cwd=cwd)
    return path.with_suffix(".lock")
