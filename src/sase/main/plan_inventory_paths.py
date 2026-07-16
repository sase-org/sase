"""Path discovery and display helpers for the plan inventory."""

from __future__ import annotations

from pathlib import Path

from sase.core.paths import iter_sharded_files, sase_home
from sase.main.plan_inventory_models import DisplayPathRoots


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


def tier_for_path(path: str | None) -> str:
    """Return the plan tier declared by a path, if available."""
    if not path:
        return "-"
    from sase.sdd.plan_tiers import read_plan_tier

    candidate = Path(path).expanduser()
    tier = read_plan_tier(candidate) if candidate.exists() else None
    return tier or "-"
