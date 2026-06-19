"""Configuration and root discovery for ``sase amd init``."""

from __future__ import annotations

from pathlib import Path
import re

import sase.config.core as config_core

from sase.memory.notes import discover_memory_notes

from ._shared import load_yaml_mapping

_WORKSPACE_SUFFIX_RE = re.compile(r"_\d+$")
_ONBOARDING_TITLE_SUFFIX = "Agent Instructions"
# The minimal ``AGENTS.md`` template references only the generated short note,
# so a project that has *only* this note never needs managed instructions.
_GENERATED_SHORT_MEMORY_RELATIVE_PATH = "memory/sase.md"


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


def _load_amd_h1_title(root: Path) -> tuple[str | None, str | None]:
    title, title_error = _load_project_amd_h1_title(root)
    if title is not None or title_error is not None:
        return title, title_error

    config_dir = _user_config_dir_for_home_amd_root(root)
    if config_dir is None:
        return None, None
    return _load_user_amd_h1_title(config_dir)


def _is_home_amd_root(root: Path) -> bool:
    """Return whether *root* is a home / chezmoi-home AMD root.

    Home roots derive their title from user config only; the onboarding
    fallback never applies to them.
    """
    return _user_config_dir_for_home_amd_root(root) is not None


def _project_has_onboarding_memory(root: Path) -> bool:
    """Return whether *root* has memory the minimal template can't reference.

    The minimal ``AGENTS.md`` references only the generated ``memory/sase.md``
    short note, so any other discovered note would be left unreferenced. Such a
    project needs managed instructions to keep its memory graph reachable.
    """
    return any(
        note.relative_path != _GENERATED_SHORT_MEMORY_RELATIVE_PATH
        for note in discover_memory_notes(root)
    )


def _onboarding_project_name(root: Path) -> str:
    name = root.resolve(strict=False).name
    stripped = _WORKSPACE_SUFFIX_RE.sub("", name)
    return stripped or name or "Project"


def _onboarding_fallback_title(root: Path) -> str:
    return f"{_onboarding_project_name(root)} - {_ONBOARDING_TITLE_SUFFIX}"


def resolve_amd_h1_title(
    root: Path, *, onboarding: bool = False
) -> tuple[str | None, str | None]:
    """Resolve the AMD H1 title, optionally deriving an onboarding fallback.

    Explicit project / user configuration always wins, and invalid configured
    values still surface as errors. When *onboarding* is enabled and a project
    root has SASE memory the minimal instruction file would leave unreferenced,
    derive a stable, directory-based title (``<project> - Agent Instructions``)
    so onboarding can write managed instructions instead of blocking.
    """
    title, title_error = _load_amd_h1_title(root)
    if title is not None or title_error is not None:
        return title, title_error
    if not onboarding or _is_home_amd_root(root):
        return None, None
    if not _project_has_onboarding_memory(root):
        return None, None
    return _onboarding_fallback_title(root), None
