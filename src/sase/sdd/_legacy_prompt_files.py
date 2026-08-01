"""Narrow discovery for prompt Markdown that must leave the plans store."""

from __future__ import annotations

from pathlib import Path

from sase.sdd._paths import is_month_dir_name


def list_plans_store_prompt_files(
    root: Path,
    *,
    month: str | None = None,
) -> tuple[tuple[Path, str], ...]:
    """Return historical prompt files with their archive month.

    This inventory is intentionally separate from normal SDD document discovery:
    plans-sidecar prompts are migration inputs (and validation errors), not live
    plan-link graph nodes.
    """

    candidates: list[tuple[Path, str]] = []
    for prompt_dir in _prompt_directories(root):
        prompt_month = _prompt_month(prompt_dir)
        if prompt_month is None or (month is not None and prompt_month != month):
            continue
        candidates.extend(
            (path, prompt_month)
            for path in sorted(prompt_dir.glob("*.md"))
            if path.is_file()
        )
    return tuple(sorted(set(candidates), key=lambda item: item[0].as_posix()))


def _prompt_directories(root: Path) -> tuple[Path, ...]:
    directories = [
        *root.glob("*/prompts"),
        *root.glob("*/specs"),
        *root.glob("plans/*/prompts"),
        *root.glob("plans/*/specs"),
        *root.glob("prompts/*"),
        *root.glob("specs/*"),
    ]
    return tuple(path for path in directories if path.is_dir())


def _prompt_month(prompt_dir: Path) -> str | None:
    if is_month_dir_name(prompt_dir.parent.name):
        return prompt_dir.parent.name
    if is_month_dir_name(prompt_dir.name):
        return prompt_dir.name
    return None


__all__ = ["list_plans_store_prompt_files"]
