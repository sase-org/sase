"""Configuration and root discovery for ``sase memory init`` agent documents."""

from __future__ import annotations

from pathlib import Path
import re

import sase.config.core as config_core

from ._shared import load_yaml_mapping

_WORKSPACE_SUFFIX_RE = re.compile(r"_\d+$")
_PROJECT_TITLE_SUFFIX = "Agent Instructions"


def _validate_amd_h1_title(raw: object, *, path: Path) -> tuple[str | None, str | None]:
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        return None, f"{path}: amd_h1_title must be a string or null"
    title = raw.strip()
    if not title:
        return None, f"{path}: amd_h1_title must not be empty"
    return title, None


def _load_project_amd_h1_title(root: Path) -> tuple[str | None, str | None]:
    config_path = root / "sase.yml"
    if not config_path.exists():
        return None, None
    data, load_error = load_yaml_mapping(config_path)
    if load_error is not None:
        return None, load_error
    if data is None or "amd_h1_title" not in data:
        return None, None
    return _validate_amd_h1_title(data["amd_h1_title"], path=config_path)


def _same_resolved_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def _user_config_dir_for_home_amd_root(root: Path) -> Path | None:
    if _same_resolved_path(root, Path.home()):
        return config_core.CONFIG_DIR
    if _same_resolved_path(root, config_core.CHEZMOI_HOME):
        return config_core.CHEZMOI_HOME / "dot_config" / "sase"
    return None


def _user_config_paths(config_dir: Path) -> tuple[Path, ...]:
    overlays = sorted(config_dir.glob("sase_*.yml")) if config_dir.is_dir() else []
    return (config_dir / "sase.yml", *overlays)


def _load_user_amd_h1_title(config_dir: Path) -> tuple[str | None, str | None]:
    title: str | None = None
    for config_path in _user_config_paths(config_dir):
        if not config_path.exists():
            continue
        data, load_error = load_yaml_mapping(config_path)
        if load_error is not None:
            return None, load_error
        if data is None or "amd_h1_title" not in data:
            continue
        title, title_error = _validate_amd_h1_title(
            data["amd_h1_title"],
            path=config_path,
        )
        if title_error is not None:
            return None, title_error
    return title, None


def _load_amd_h1_title(root: Path) -> tuple[str | None, str | None]:
    title, title_error = _load_project_amd_h1_title(root)
    if title is not None or title_error is not None:
        return title, title_error

    config_dir = _user_config_dir_for_home_amd_root(root)
    if config_dir is None:
        return None, None
    return _load_user_amd_h1_title(config_dir)


def _project_name(root: Path) -> str:
    name = root.resolve(strict=False).name
    stripped = _WORKSPACE_SUFFIX_RE.sub("", name)
    return stripped or name or "Project"


def _project_fallback_title(root: Path) -> str:
    return f"{_project_name(root)} - {_PROJECT_TITLE_SUFFIX}"


def resolve_amd_h1_title(
    root: Path, *, derive_project_title: bool = False
) -> tuple[str | None, str | None]:
    """Resolve the AMD H1 title, optionally deriving a project title.

    Explicit project / user configuration always wins, and invalid configured
    values still surface as errors. Project memory initialization passes
    *derive_project_title* only after the local ``memory.enabled`` opt-in has
    been validated, making that boolean sufficient by itself.
    """
    title, title_error = _load_amd_h1_title(root)
    if title is not None or title_error is not None:
        return title, title_error
    if not derive_project_title:
        return None, None
    return _project_fallback_title(root), None
