"""Configuration and project-name helpers for ``sase init memory``."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
import re
import subprocess
from typing import Any

import yaml  # type: ignore[import-untyped]

from .constants import COMMAND_LABEL
from .models import SiblingMemoryEntry

_WORKSPACE_SUFFIX_RE = re.compile(r"_\d+$")


def project_config_path() -> Path:
    return Path.cwd() / "sase.yml"


def _project_name_from_checkout_marker(root: Path) -> str | None:
    try:
        from sase.workspace_provider.marker import find_marker_from_cwd

        found = find_marker_from_cwd(str(root))
    except Exception:
        return None
    if found is None:
        return None
    _, marker = found
    project_name = marker.project_name.strip()
    return project_name or None


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


def _load_yaml_mapping(path: Path) -> tuple[Mapping[str, Any], str | None]:
    if not path.exists():
        return {}, None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return {}, f"{path}: failed to parse YAML: {exc}"
    except OSError as exc:
        return {}, f"{path}: failed to read file: {exc}"
    if data is None:
        return {}, None
    if not isinstance(data, Mapping):
        return {}, f"{path}: expected a YAML mapping at the top level"
    return data, None


def sibling_entries_from_config(
    config_path: Path, *, label: str
) -> tuple[tuple[SiblingMemoryEntry, ...], tuple[str, ...]]:
    config, load_error = _load_yaml_mapping(config_path)
    if load_error is not None:
        return (), (load_error,)

    raw = config.get("sibling_repos", [])
    if raw is None:
        return (), ()
    if not isinstance(raw, list):
        return (), (f"{config_path}: sibling_repos must be a list",)

    entries: list[SiblingMemoryEntry] = []
    errors: list[str] = []
    for index, item in enumerate(raw):
        prefix = f"{config_path}: sibling_repos[{index}]"
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

        entries.append(
            SiblingMemoryEntry(
                name=name.strip(),
                description=" ".join(description.strip().split()),
            )
        )

    if errors:
        errors.insert(
            0,
            f"{COMMAND_LABEL}: cannot generate {label} memory until "
            "sibling repo descriptions are complete",
        )
    return tuple(entries), tuple(errors)
