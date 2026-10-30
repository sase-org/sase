"""Shared migration models and helpers used by more than one module."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PromptMigrationSkip:
    path: str
    reason: str


@dataclass(frozen=True, slots=True)
class PromptMigrationReport:
    project: str
    write: bool
    prompts_moved: int
    plans_relinked: int
    months_committed: int
    skipped: tuple[PromptMigrationSkip, ...]

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
class MigrationItem:
    month: str
    source: Path
    destination: Path
    prompt_content: str
    plan_path: Path | None
    plan_content: str | None
    plan_changed: bool
    displaced_destination: Path | None = None
    displaced_content: str | None = None
    skips: tuple[PromptMigrationSkip, ...] = ()


def relpath(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


__all__ = [
    "MigrationItem",
    "PromptMigrationReport",
    "PromptMigrationSkip",
    "relpath",
]
