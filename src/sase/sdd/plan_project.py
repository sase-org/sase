"""Read and manage the machine-local project identity on plan proposals."""

from __future__ import annotations

from pathlib import Path

from sase.sdd.frontmatter import parse_frontmatter, remove_frontmatter_fields

PLAN_PROJECT_FIELD = "project"


def _read_plan_project(content: str) -> str | None:
    """Return a non-empty project value from valid plan frontmatter."""
    if not isinstance(content, str):
        return None
    try:
        frontmatter, _body, had_frontmatter = parse_frontmatter(content)
    except Exception:  # noqa: BLE001 - metadata readers must tolerate malformed input.
        return None
    if not had_frontmatter:
        return None
    value = frontmatter.get(PLAN_PROJECT_FIELD)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def read_plan_project_file(path: str | Path) -> str | None:
    """Read a plan's project value, returning ``None`` for unreadable files."""
    try:
        return _read_plan_project(Path(path).expanduser().read_text(encoding="utf-8"))
    except (OSError, UnicodeError):
        return None


def strip_plan_project(content: str) -> str:
    """Remove SASE's local project-routing field from an archived copy."""
    return remove_frontmatter_fields(content, (PLAN_PROJECT_FIELD,))


def plan_project_for_artifacts_dir(artifacts_dir: str) -> str | None:
    """Return the effective display name for a registered proposing project."""
    try:
        from sase.project_aliases import (
            effective_project_name,
            registered_project_records,
        )
        from sase.turns.settlement import project_name_from_artifacts_dir

        project_key = project_name_from_artifacts_dir(artifacts_dir)
        if not project_key or project_key.casefold() == "home":
            return None
        record = next(
            (
                item
                for item in registered_project_records()
                if item.project_name == project_key
            ),
            None,
        )
        return effective_project_name(record) if record is not None else None
    except Exception:  # noqa: BLE001 - stamping is best-effort metadata.
        return None


__all__ = [
    "PLAN_PROJECT_FIELD",
    "plan_project_for_artifacts_dir",
    "read_plan_project_file",
    "strip_plan_project",
]
