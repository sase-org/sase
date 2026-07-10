"""Path resolution retained for the provider-owned SDD init command."""

from __future__ import annotations

from pathlib import Path


def resolve_sdd_init_config_path(
    path: str | Path | None = None,
    *,
    cwd: Path | None = None,
) -> Path:
    """Resolve the project-local ``sase.yml`` path for an SDD init target."""

    from sase.sdd._paths import resolve_sdd_readme_path

    path_arg = str(path) if path is not None else None
    sdd_root = resolve_sdd_readme_path(path_arg, cwd=cwd).parent
    if sdd_root.name == "sdd" and sdd_root.parent.name == ".sase":
        return (sdd_root.parent.parent / "sase.yml").resolve()
    return (sdd_root.parent / "sase.yml").resolve()


__all__ = ["resolve_sdd_init_config_path"]
