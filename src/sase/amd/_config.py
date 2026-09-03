"""Configuration and root discovery for ``sase memory init`` agent documents."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

import sase.config.core as config_core
from sase.config.identity import is_valid_machine_name, overlay_identity
from sase.config.loading import get_overlay_paths
from sase.content_layout import resolve_project_config_read_path
from sase.main._init_chezmoi_ignore import (
    chezmoi_target_entry,
    parse_hostname_ignore_entries,
)
from sase.memory.config_keys import MEMORY_CONFIG_KEY

from ._shared import is_chezmoi_home_root, load_yaml_mapping, read_text

_WORKSPACE_SUFFIX_RE = re.compile(r"_\d+$")
_PROJECT_TITLE_SUFFIX = "Agent Instructions"
_MEMORY_MANAGED_TEMPLATE_KEY = "agents_template"
_MEMORY_MINIMAL_TEMPLATE_KEY = "agents_minimal_template"
_LEGACY_MANAGED_TEMPLATE_KEY = "amd_agents_template"
_LEGACY_MINIMAL_TEMPLATE_KEY = "amd_agents_minimal_template"
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


@dataclass(frozen=True)
class _TemplateOverrideResolution:
    value: Any | None = None
    display_path: str = ""
    declared: bool = False
    error: str | None = None


def _resolve_template_override_config(
    data: Mapping[str, Any], *, memory_key: str, legacy_key: str
) -> _TemplateOverrideResolution:
    memory_path = f"{MEMORY_CONFIG_KEY}.{memory_key}"
    if MEMORY_CONFIG_KEY in data:
        memory = data[MEMORY_CONFIG_KEY]
        if not isinstance(memory, Mapping):
            return _TemplateOverrideResolution(
                declared=True,
                display_path=MEMORY_CONFIG_KEY,
                error=f"{MEMORY_CONFIG_KEY} must be a mapping",
            )
        if memory_key in memory:
            return _TemplateOverrideResolution(
                value=memory[memory_key],
                display_path=memory_path,
                declared=True,
            )
    if legacy_key in data:
        return _TemplateOverrideResolution(
            value=data[legacy_key],
            display_path=legacy_key,
            declared=True,
        )
    return _TemplateOverrideResolution(display_path=memory_path)


def resolve_markdown_template_override(
    root: Path,
    *,
    memory_key: str,
    legacy_key: str,
    user_filename: str,
) -> tuple[Path | None, str | None]:
    """Resolve a project or user override for a Markdown template.

    Reads ``memory.<memory_key>`` first, falling back to the deprecated
    top-level *legacy_key* when the nested form is not declared.
    """
    project_config = resolve_project_config_read_path(root)
    if project_config is not None:
        data, load_error = load_yaml_mapping(project_config)
        if load_error is not None:
            return None, load_error
        if data is not None:
            resolved = _resolve_template_override_config(
                data, memory_key=memory_key, legacy_key=legacy_key
            )
            if resolved.error is not None:
                return None, f"{project_config}: {resolved.error}"
            if resolved.declared:
                path, path_error = _validate_template_path(
                    resolved.value,
                    root=root,
                    config_path=project_config,
                    key=resolved.display_path,
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
    memory_key = (
        _MEMORY_MINIMAL_TEMPLATE_KEY if minimal else _MEMORY_MANAGED_TEMPLATE_KEY
    )
    legacy_key = (
        _LEGACY_MINIMAL_TEMPLATE_KEY if minimal else _LEGACY_MANAGED_TEMPLATE_KEY
    )
    user_filename = "AGENTS.minimal.template.md" if minimal else "AGENTS.template.md"

    return resolve_markdown_template_override(
        root,
        memory_key=memory_key,
        legacy_key=legacy_key,
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


@dataclass(frozen=True)
class _ChezmoiMachineH1Titles:
    """Machine-overlay H1 titles keyed by chezmoi hostname."""

    titles: tuple[tuple[str, str], ...] = ()
    fallback_title: str | None = None
    blockers: tuple[str, ...] = ()


def _missing_hostname_guard_blocker(overlay_path: Path, entry: str) -> str:
    return (
        f"{overlay_path}: memory.h1_title is set but .chezmoiignore has no "
        f"hostname guard for {entry}; add "
        f'`{{{{ if ne .chezmoi.hostname "<hostname>" }}}}` / {entry} / '
        "`{{ end }}` or run `sase config init` on that machine"
    )


def resolve_chezmoi_machine_h1_titles(
    root: Path,
    *,
    chezmoi_home_roots: Iterable[Path] = (),
) -> _ChezmoiMachineH1Titles:
    """Resolve per-machine ``memory.h1_title`` values for a chezmoi home root.

    Returns hostname/title pairs only when at least one machine overlay
    (``sase_*.yml`` with a valid nested ``id.machine_name``, falling back to
    deprecated top-level ``machine_name``) declares a title. Missing
    ``.chezmoiignore`` hostname guards and duplicate hostnames are blockers.
    """
    if not is_chezmoi_home_root(root, chezmoi_home_roots=chezmoi_home_roots):
        return _ChezmoiMachineH1Titles()

    config_dir = root / "dot_config" / "sase"
    fallback_title, fallback_error = _load_user_amd_h1_title(config_dir)
    if fallback_error is not None:
        return _ChezmoiMachineH1Titles(blockers=(fallback_error,))

    ignore_path = root / ".chezmoiignore"
    ignore_text = ""
    if ignore_path.exists():
        loaded_text, ignore_error = read_text(ignore_path)
        if ignore_error is not None or loaded_text is None:
            return _ChezmoiMachineH1Titles(
                fallback_title=fallback_title,
                blockers=(ignore_error or f"{ignore_path}: failed to read file",),
            )
        ignore_text = loaded_text
    guards = parse_hostname_ignore_entries(ignore_text)

    titles_by_host: dict[str, tuple[str, Path]] = {}
    blockers: list[str] = []
    for overlay_path in get_overlay_paths(config_dir):
        data, load_error = load_yaml_mapping(overlay_path)
        if load_error is not None:
            blockers.append(load_error)
            continue
        identity = overlay_identity(overlay_path, data)
        discriminator = identity.discriminator
        if discriminator is None or not is_valid_machine_name(discriminator):
            continue
        if data is None:
            continue
        resolved = _resolve_amd_h1_title_config(data)
        if resolved.error is not None:
            blockers.append(f"{overlay_path}: {resolved.error}")
            continue
        if not resolved.declared:
            continue
        title, title_error = _validate_amd_h1_title(
            resolved.value,
            path=overlay_path,
            display_path=resolved.display_path,
        )
        if title_error is not None:
            blockers.append(title_error)
            continue
        if title is None:
            continue
        entry = chezmoi_target_entry(overlay_path, chezmoi_home=root)
        if entry is None:
            blockers.append(
                f"{overlay_path}: memory.h1_title is set but the overlay is "
                "not under the chezmoi home source root"
            )
            continue
        hostname = guards.get(entry)
        if hostname is None:
            blockers.append(_missing_hostname_guard_blocker(overlay_path, entry))
            continue
        existing = titles_by_host.get(hostname)
        if existing is not None:
            existing_path = existing[1]
            blockers.append(
                f"{overlay_path}: memory.h1_title maps to chezmoi hostname "
                f"{hostname!r} which is already used by {existing_path}"
            )
            continue
        titles_by_host[hostname] = (title, overlay_path)

    titles = tuple(
        sorted((hostname, title) for hostname, (title, _path) in titles_by_host.items())
    )
    return _ChezmoiMachineH1Titles(
        titles=titles,
        fallback_title=fallback_title,
        blockers=tuple(blockers),
    )


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
