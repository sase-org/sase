"""Path discovery and display helpers for the plan inventory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.core.paths import iter_sharded_files, sase_home
from sase.main.plan_inventory_models import DisplayPathRoots


@dataclass(frozen=True)
class _PlanPathMetadata:
    """Best-effort metadata read from one plan-file snapshot."""

    title: str | None
    tier: str


def display_path_roots() -> DisplayPathRoots:
    """Return resolved roots used to shorten paths for display."""
    return DisplayPathRoots(
        sase_root=sase_home().expanduser().resolve(strict=False),
        home=Path.home().expanduser().resolve(strict=False),
    )


def archived_plan_paths() -> tuple[Path, ...]:
    """Return all archived plan proposal paths."""
    return tuple(
        path for path in iter_sharded_files("plans", pattern="*.md") if path.is_file()
    )


def display_path(
    path: str | None,
    *,
    display_roots: DisplayPathRoots | None = None,
) -> str:
    """Shorten a path beneath the SASE or user home directory."""
    if not path:
        return "-"
    roots = display_roots or display_path_roots()
    candidate = Path(path).expanduser()
    resolved = candidate.resolve(strict=False)
    try:
        return f"~/.sase/{resolved.relative_to(roots.sase_root)}"
    except ValueError:
        pass

    try:
        relative = resolved.relative_to(roots.home)
    except ValueError:
        return str(path)
    return "~" if not relative.parts else f"~/{relative}"


def plan_metadata_for_path(path: str | None) -> _PlanPathMetadata:
    """Return normalized title and tier from one best-effort plan-file read."""
    unavailable = _PlanPathMetadata(title=None, tier="-")
    if not path:
        return unavailable
    from sase.sdd.plan_tiers import normalize_plan_tier, parse_plan_frontmatter

    candidate = Path(path).expanduser()
    try:
        content = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return unavailable

    frontmatter, error = parse_plan_frontmatter(content)
    if error is not None:
        return unavailable
    raw_title = frontmatter.get("title")
    title = " ".join(raw_title.split()) if isinstance(raw_title, str) else None
    return _PlanPathMetadata(
        title=title or None,
        tier=normalize_plan_tier(frontmatter.get("tier")) or "-",
    )
