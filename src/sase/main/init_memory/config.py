"""Configuration and project-name helpers for ``sase memory init``."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import re
import subprocess
from typing import Any

from sase.linked_repos import LINKED_REPOS_CONFIG_KEY, SIBLING_REPOS_CONFIG_KEY
from sase.project_management import load_local_config

from .constants import COMMAND_LABEL
from .models import LinkedRepoMemoryEntry

_WORKSPACE_SUFFIX_RE = re.compile(r"_\d+$")


def project_config_path() -> Path:
    return Path.cwd() / "sase.yml"


def _project_name_from_checkout_marker(root: Path) -> str | None:
    found = _checkout_marker_from_root(root)
    if found is None:
        return None
    _, marker = found
    project_name = marker.project_name.strip()
    return project_name or None


def _checkout_marker_from_root(root: Path) -> Any | None:
    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        return find_marker_from_cwd(str(root))
    except Exception:
        return None


def _project_name_from_git_url(remote_url: str | None) -> str | None:
    if remote_url is None:
        return None
    url = remote_url.strip().rstrip("/")
    if not url:
        return None
    name = url.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name or None


def _fallback_project_name(name: str) -> str | None:
    name = name.strip()
    if not name:
        return None
    stripped = _WORKSPACE_SUFFIX_RE.sub("", name)
    return stripped or name


def _run_git_stdout(root: Path, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    return text or None


def _project_name_from_git_remote(root: Path) -> str | None:
    remote_url = _run_git_stdout(root, "config", "--get", "remote.origin.url")
    return _project_name_from_git_url(remote_url)


def _project_name_from_git_root(root: Path) -> str | None:
    git_root = _run_git_stdout(root, "rev-parse", "--show-toplevel")
    if git_root is None:
        return None
    return _fallback_project_name(Path(git_root).name)


def project_memory_name(root: Path) -> str:
    marker_project = _project_name_from_checkout_marker(root)
    if marker_project is not None:
        return marker_project

    git_remote_project = _project_name_from_git_remote(root)
    if git_remote_project is not None:
        return git_remote_project

    git_root_project = _project_name_from_git_root(root)
    if git_root_project is not None:
        return git_root_project

    return _fallback_project_name(root.name) or root.name


def _primary_workspace_from_checkout_marker(root: Path) -> Path | None:
    found = _checkout_marker_from_root(root)
    if found is None:
        return None
    _, marker = found
    primary = marker.primary_workspace_dir.strip()
    if not primary:
        return None
    expanded = os.path.expandvars(os.path.expanduser(primary))
    return Path(expanded).resolve(strict=False)


def _primary_workspace_from_adjacent_suffix(root: Path) -> Path | None:
    resolved = root.resolve(strict=False)
    stripped_name = _WORKSPACE_SUFFIX_RE.sub("", resolved.name)
    if stripped_name == resolved.name or not stripped_name:
        return None
    candidate = resolved.with_name(stripped_name)
    if not candidate.is_dir():
        return None
    return candidate.resolve(strict=False)


def primary_workspace_root_for_memory(root: Path) -> Path:
    marker_primary = _primary_workspace_from_checkout_marker(root)
    if marker_primary is not None:
        return marker_primary

    adjacent_primary = _primary_workspace_from_adjacent_suffix(root)
    if adjacent_primary is not None:
        return adjacent_primary

    return root.resolve(strict=False)


def _linked_repos_raw(config: Mapping[str, Any]) -> tuple[Any, str]:
    """Return the configured related-repo list plus the source config key.

    Prefers the canonical ``linked_repos`` key and falls back to the deprecated
    ``sibling_repos`` alias so legacy configs still drive memory generation
    during the compatibility window.
    """

    if LINKED_REPOS_CONFIG_KEY in config:
        return config.get(LINKED_REPOS_CONFIG_KEY, []), LINKED_REPOS_CONFIG_KEY
    if SIBLING_REPOS_CONFIG_KEY in config:
        return config.get(SIBLING_REPOS_CONFIG_KEY, []), SIBLING_REPOS_CONFIG_KEY
    return [], LINKED_REPOS_CONFIG_KEY


def linked_entries_from_config(
    config_path: Path, *, label: str, primary_root: Path | None = None
) -> tuple[tuple[LinkedRepoMemoryEntry, ...], tuple[str, ...]]:
    loaded = load_local_config(config_path)
    if not loaded.valid:
        return (), (loaded.error or f"{config_path}: invalid configuration",)
    config = loaded.config

    raw, source_key = _linked_repos_raw(config)
    if raw is None:
        return (), ()
    if not isinstance(raw, list):
        return (), (f"{config_path}: {source_key} must be a list",)

    entries: list[LinkedRepoMemoryEntry] = []
    errors: list[str] = []
    for index, item in enumerate(raw):
        prefix = f"{config_path}: {source_key}[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{prefix} must be a mapping")
            continue

        name = item.get("name")
        if not isinstance(name, str) or not name.strip():
            errors.append(f"{prefix} is missing required string field 'name'")
            continue

        description = item.get("description")
        if not isinstance(description, str) or not description.strip():
            errors.append(
                f"{prefix} ({name.strip()!r}) is missing required string "
                "field 'description'"
            )
            continue

        raw_path = item.get("path")
        if not isinstance(raw_path, str) or not raw_path.strip():
            errors.append(
                f"{prefix} ({name.strip()!r}) is missing required string field 'path'"
            )
            continue

        path = raw_path.strip()

        entries.append(
            LinkedRepoMemoryEntry(
                name=name.strip(),
                description=" ".join(description.strip().split()),
                path=path,
            )
        )

    if errors:
        errors.insert(
            0,
            f"{COMMAND_LABEL}: cannot generate {label} memory until "
            "linked repo configuration is complete",
        )
    return tuple(entries), tuple(errors)
