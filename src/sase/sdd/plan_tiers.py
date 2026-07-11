"""Shared plan-file tier and canonical/legacy path helpers."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

PLAN_TIERS = ("tale", "epic")
PLAN_DIRS = ("plans", "tales", "epics")


def normalize_plan_tier(value: object) -> str | None:
    """Return a normalized supported plan-file tier, or ``None``."""
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    return normalized if normalized in PLAN_TIERS else None


def tier_for_plan_kind(kind: str) -> str:
    """Map accepted writer kind aliases to their plan-file tier."""
    normalized = kind.strip().lower()
    if normalized in {"epic", "epics"}:
        return "epic"
    if normalized in {"tale", "tales", "plan", "plans"}:
        return "tale"
    raise ValueError(
        f"invalid SDD plan kind {kind!r}; expected one of "
        "['epic', 'epics', 'plan', 'plans', 'tale', 'tales']"
    )


def read_plan_frontmatter(path: Path) -> tuple[dict[str, Any], str | None]:
    """Read YAML frontmatter best-effort, returning a parse error if invalid."""
    try:
        content = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {}, str(exc)
    if not content.startswith("---\n"):
        return {}, None
    end = content.find("\n---\n", 4)
    if end == -1:
        return {}, "frontmatter closing marker not found"
    try:
        parsed = yaml.safe_load(content[4:end]) or {}
    except yaml.YAMLError as exc:
        return {}, f"invalid YAML frontmatter: {exc}"
    if not isinstance(parsed, dict):
        return {}, "frontmatter must be a YAML mapping"
    return dict(parsed), None


def read_plan_tier(path: Path) -> str | None:
    """Read a valid explicit plan-file tier, returning ``None`` otherwise."""
    frontmatter, error = read_plan_frontmatter(path)
    if error is not None:
        return None
    return normalize_plan_tier(frontmatter.get("tier"))


def classify_plan_file(path: Path, frontmatter: dict[str, Any] | None = None) -> str:
    """Classify a canonical or legacy plan path with frontmatter precedence."""
    if frontmatter is None:
        frontmatter, _ = read_plan_frontmatter(path)
    explicit = normalize_plan_tier(frontmatter.get("tier"))
    if explicit is not None:
        return explicit
    directory = _plan_directory(path)
    return "epic" if directory == "epics" else "tale"


def _plan_path_alias_candidates(path: Path) -> tuple[Path, ...]:
    """Return original and canonical/legacy aliases in lookup order."""
    parts = list(path.parts)
    index = next(
        (i for i in range(len(parts) - 1, -1, -1) if parts[i] in PLAN_DIRS),
        None,
    )
    if index is None:
        return (path,)
    physical = parts[index]
    aliases = {
        "plans": ("tales", "epics"),
        "tales": ("plans",),
        "epics": ("plans",),
    }[physical]
    candidates = [path]
    for alias in aliases:
        candidate_parts = [*parts]
        candidate_parts[index] = alias
        candidate = Path(*candidate_parts)
        if candidate not in candidates:
            candidates.append(candidate)
    return tuple(candidates)


def existing_plan_path(path: Path) -> Path | None:
    """Resolve a possibly stale plan path through layout aliases."""
    return next(
        (
            candidate
            for candidate in _plan_path_alias_candidates(path)
            if candidate.exists()
        ),
        None,
    )


def iter_link_aliases(link: str) -> Iterator[str]:
    """Yield canonical/legacy spellings for a relative frontmatter link."""
    path = Path(link)
    for candidate in _plan_path_alias_candidates(path):
        yield candidate.as_posix()


def _plan_directory(path: Path) -> str | None:
    return next((part for part in reversed(path.parts[:-1]) if part in PLAN_DIRS), None)
