"""Configuration and root discovery for ``sase amd init``."""

from __future__ import annotations

from pathlib import Path

import sase.config.core as config_core

from ._shared import load_yaml_mapping


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


def _dedupe_roots_by_resolved_path(roots: tuple[Path, ...]) -> tuple[Path, ...]:
    selected: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        resolved = root.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        selected.append(root)
    return tuple(selected)


def amd_init_roots(cwd: Path) -> tuple[Path, ...]:
    if not config_core.get_use_chezmoi():
        return (cwd,)

    chezmoi_home = config_core.CHEZMOI_HOME
    if _same_resolved_path(cwd, Path.home()):
        return _dedupe_roots_by_resolved_path((chezmoi_home,))
    return _dedupe_roots_by_resolved_path((cwd, chezmoi_home))


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


def load_amd_h1_title(root: Path) -> tuple[str | None, str | None]:
    title, title_error = _load_project_amd_h1_title(root)
    if title is not None or title_error is not None:
        return title, title_error

    config_dir = _user_config_dir_for_home_amd_root(root)
    if config_dir is None:
        return None, None
    return _load_user_amd_h1_title(config_dir)
