"""Configuration and root discovery for ``sase memory init`` agent documents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import sase.config.core as config_core
from sase.content_layout import resolve_project_config_read_path
from sase.glossary_config import MEMORY_CONFIG_KEY

from ._shared import load_yaml_mapping

_WORKSPACE_SUFFIX_RE = re.compile(r"_\d+$")
_PROJECT_TITLE_SUFFIX = "Agent Instructions"
_MANAGED_TEMPLATE_KEY = "amd_agents_template"
_MINIMAL_TEMPLATE_KEY = "amd_agents_minimal_template"
_MEMORY_H1_TITLE_KEY = "h1_title"
_MEMORY_H1_TITLE_PATH = f"{MEMORY_CONFIG_KEY}.{_MEMORY_H1_TITLE_KEY}"


@dataclass(frozen=True)
class _AmdH1TitleResolution:
    value: Any | None = None
    display_path: str = _MEMORY_H1_TITLE_PATH
    declared: bool = False
    error: str | None = None


def _validate_amd_h1_title(
    raw: object, *, path: Path, display_path: str
) -> tuple[str | None, str | None]:
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        return None, f"{path}: {display_path} must be a string or null"
    title = raw.strip()
    if not title:
        return None, f"{path}: {display_path} must not be empty"
    return title, None


def _resolve_amd_h1_title_config(data: Mapping[str, Any]) -> _AmdH1TitleResolution:
    if MEMORY_CONFIG_KEY in data:
        memory = data[MEMORY_CONFIG_KEY]
        if not isinstance(memory, Mapping):
            return _AmdH1TitleResolution(
                declared=True,
                display_path=MEMORY_CONFIG_KEY,
                error=f"{MEMORY_CONFIG_KEY} must be a mapping",
            )
        if _MEMORY_H1_TITLE_KEY in memory:
            return _AmdH1TitleResolution(
                value=memory[_MEMORY_H1_TITLE_KEY],
                display_path=_MEMORY_H1_TITLE_PATH,
                declared=True,
            )
    return _AmdH1TitleResolution()


def _load_project_amd_h1_title(
    root: Path,
) -> tuple[str | None, str | None, bool]:
    config_path = resolve_project_config_read_path(root)
    if config_path is None:
        return None, None, False
    data, load_error = load_yaml_mapping(config_path)
    if load_error is not None:
        return None, load_error, False
    if data is None:
        return None, None, False
    resolved = _resolve_amd_h1_title_config(data)
    if resolved.error is not None:
        return None, f"{config_path}: {resolved.error}", True
    if not resolved.declared:
        return None, None, False
    title, title_error = _validate_amd_h1_title(
        resolved.value,
        path=config_path,
        display_path=resolved.display_path,
    )
    return title, title_error, True


def _same_resolved_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def _user_config_dir_for_home_root(root: Path) -> Path | None:
    if _same_resolved_path(root, Path.home()):
        return config_core.CONFIG_DIR
    if _same_resolved_path(root, config_core.CHEZMOI_HOME):
        return config_core.CHEZMOI_HOME / "dot_config" / "sase"
    return None


def _validate_template_path(
    raw: object,
    *,
    root: Path,
    config_path: Path,
    key: str,
) -> tuple[Path | None, str | None]:
    if raw is None:
        return None, None
    if not isinstance(raw, str):
        return None, f"{config_path}: {key} must be a root-relative path or null"
    value = raw.strip()
    if not value:
        return None, f"{config_path}: {key} must not be empty"
    relative = Path(value)
    if relative.is_absolute():
        return None, f"{config_path}: {key} must be a root-relative path"

    resolved_root = root.resolve(strict=False)
    resolved_path = (root / relative).resolve(strict=False)
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        return None, f"{config_path}: {key} must stay within {root}"
    return resolved_path, None


def resolve_markdown_template_override(
    root: Path,
    *,
    key: str,
    user_filename: str,
) -> tuple[Path | None, str | None]:
    """Resolve a project or user override for a Markdown template."""
    project_config = resolve_project_config_read_path(root)
    if project_config is not None:
        data, load_error = load_yaml_mapping(project_config)
        if load_error is not None:
            return None, load_error
        if data is not None and key in data:
            path, path_error = _validate_template_path(
                data[key],
                root=root,
                config_path=project_config,
                key=key,
            )
            if path is not None or path_error is not None:
                return path, path_error

    config_dir = _user_config_dir_for_home_root(root)
    if config_dir is None:
        return None, None
    user_template = config_dir / user_filename
    if user_template.exists():
        return user_template, None
    return None, None


def resolve_amd_template_override(
    root: Path,
    *,
    minimal: bool = False,
) -> tuple[Path | None, str | None]:
    """Resolve a project or user override for an AMD agent template."""
    key = _MINIMAL_TEMPLATE_KEY if minimal else _MANAGED_TEMPLATE_KEY
    user_filename = "AGENTS.minimal.template.md" if minimal else "AGENTS.template.md"

    return resolve_markdown_template_override(
        root,
        key=key,
        user_filename=user_filename,
    )


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
        if data is None:
            continue
        resolved = _resolve_amd_h1_title_config(data)
        if resolved.error is not None:
            return None, f"{config_path}: {resolved.error}"
        if not resolved.declared:
            continue
        title, title_error = _validate_amd_h1_title(
            resolved.value,
            path=config_path,
            display_path=resolved.display_path,
        )
        if title_error is not None:
            return None, title_error
    return title, None


def _load_amd_h1_title(root: Path) -> tuple[str | None, str | None]:
    title, title_error, project_declared = _load_project_amd_h1_title(root)
    if title is not None or title_error is not None or project_declared:
        return title, title_error

    config_dir = _user_config_dir_for_home_root(root)
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
    *derive_project_title* only after the local ``is_sase_managed`` marker has
    been validated, making that boolean sufficient by itself.
    """
    title, title_error = _load_amd_h1_title(root)
    if title is not None or title_error is not None:
        return title, title_error
    if not derive_project_title:
        return None, None
    return _project_fallback_title(root), None
