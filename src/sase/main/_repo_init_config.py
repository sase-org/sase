"""Configuration and project-state helpers for repository initialization."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping, MutableSequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase._linked_repo_config import (
    AGENTS_SIDECAR_ROLE,
    DEFAULT_AGENTS_DESCRIPTION,
    DEFAULT_RESEARCH_DESCRIPTION,
)
from sase.config import ConfigEditError, set_key
from sase.content_layout import LayoutCollisionError, resolve_project_layout
from sase.project_management import ProjectManagementStatus, project_management_status

if TYPE_CHECKING:
    from sase.sdd._sidecar_init import SidecarInitSpec


@dataclass(frozen=True)
class ConfigUpdate:
    """A pending update to the project-local repository configuration."""

    path: Path
    current_text: str
    updated_text: str
    error: str | None = None
    added_roles: tuple[str, ...] = ()

    @property
    def changed(self) -> bool:
        """Whether applying this update would change the configuration."""

        return self.error is None and self.updated_text != self.current_text


def configured_sidecar_specs(project_root: Path) -> tuple[SidecarInitSpec, ...]:
    """Resolve the enabled sidecar specifications for ``project_root``."""

    from sase._linked_repo_config import (
        _DEFAULT_LINKED_REPO_MARKER,
        _SIDECAR_REMOTE_URL_KEY,
        _SIDECAR_REPO_REF_KEY,
        _SIDECAR_ROLE_KEY,
        full_github_repo_name,
        inject_default_linked_repos,
        merged_sidecar_entries_from_config,
        read_project_local_config,
        resolution_config,
    )
    from sase.sdd._sidecar_init import SidecarInitSpec

    primary = project_root.expanduser().resolve(strict=False)
    config = resolution_config(str(primary), None)
    entries = merged_sidecar_entries_from_config(
        config,
        primary_workspace_dir=str(primary),
    )
    entries = inject_default_linked_repos(
        entries,
        primary_workspace_dir=str(primary),
        local_config=read_project_local_config(str(primary)),
        config=config,
    )

    specs: list[SidecarInitSpec] = []
    for entry in entries:
        if entry.get("disabled") is True:
            continue
        role = _entry_text(entry, _SIDECAR_ROLE_KEY) or _entry_text(entry, "name")
        if not role:
            continue
        raw_repo = _entry_text(entry, "repo")
        repo: str | None = None
        if raw_repo:
            repo = full_github_repo_name(primary, raw_repo, config=config) or raw_repo
        elif entry.get(_DEFAULT_LINKED_REPO_MARKER) is not True:
            resolved_repo = _entry_text(entry, _SIDECAR_REPO_REF_KEY)
            if "/" in resolved_repo:
                repo = resolved_repo
        visibility = _entry_text(entry, "visibility") or "public"
        specs.append(
            SidecarInitSpec(
                role=role,
                repo=repo,
                remote_url=_entry_text(entry, _SIDECAR_REMOTE_URL_KEY) or None,
                visibility=visibility,
                description=_entry_text(entry, "description") or None,
            )
        )
    return tuple(specs)


def _entry_text(entry: Mapping[str, Any], key: str) -> str:
    value = entry.get(key)
    return value.strip() if isinstance(value, str) else ""


def explicit_sidecar_config_update(config_path: Path) -> ConfigUpdate:
    """Return the update needed to declare the standard sidecars explicitly."""

    try:
        current_text = (
            config_path.read_text(encoding="utf-8") if config_path.exists() else ""
        )
    except OSError as exc:
        return ConfigUpdate(
            config_path, "", "", f"{config_path}: failed to read file: {exc}"
        )

    try:
        from ruamel.yaml.comments import CommentedMap, CommentedSeq

        from sase.config._edit_yaml_io import dump_yaml, make_yaml

        handler = make_yaml()
        data = handler.load(current_text) if current_text.strip() else CommentedMap()
        if not isinstance(data, MutableMapping):
            return ConfigUpdate(
                config_path,
                current_text,
                current_text,
                f"{config_path}: expected a YAML mapping at the top level",
            )
        repos = data.get("repos")
        if repos is not None and not isinstance(repos, MutableMapping):
            return ConfigUpdate(
                config_path,
                current_text,
                current_text,
                f"{config_path}: repos must be a YAML mapping",
            )
        sidecars = repos.get("sidecar") if isinstance(repos, MutableMapping) else None
        if sidecars is not None and not isinstance(sidecars, MutableSequence):
            return ConfigUpdate(
                config_path,
                current_text,
                current_text,
                f"{config_path}: repos.sidecar must be a YAML list",
            )
        existing_roles = {
            _entry_text(entry, "name")
            for entry in sidecars or ()
            if isinstance(entry, Mapping)
        }
        entries = {
            "plans": CommentedMap((("name", "plans"), ("auto_clone", True))),
            "beads": CommentedMap((("name", "beads"), ("auto_clone", True))),
            "research": CommentedMap(
                (
                    ("name", "research"),
                    ("description", DEFAULT_RESEARCH_DESCRIPTION),
                )
            ),
            AGENTS_SIDECAR_ROLE: CommentedMap(
                (
                    ("name", AGENTS_SIDECAR_ROLE),
                    ("description", DEFAULT_AGENTS_DESCRIPTION),
                )
            ),
        }
        added_roles = tuple(role for role in entries if role not in existing_roles)
        if not added_roles:
            return ConfigUpdate(config_path, current_text, current_text)

        new_entries = CommentedSeq(entries[role] for role in added_roles)
        if sidecars is None:
            updated_text = set_key(
                current_text,
                ("repos", "sidecar"),
                new_entries,
            )
        else:
            sidecars.extend(new_entries)
            updated_text = dump_yaml(handler, data)
    except (ConfigEditError, OSError, ValueError) as exc:
        return ConfigUpdate(
            config_path,
            current_text,
            current_text,
            f"{config_path}: failed to update repos.sidecar: {exc}",
        )
    if updated_text != current_text:
        from sase.content_layout import resolve_project_config_write_path

        project_root = (
            config_path.parent.parent
            if config_path.parent.name == "sase"
            else config_path.parent
        )
        write_path = resolve_project_config_write_path(project_root)
        if config_path != write_path:
            return ConfigUpdate(
                config_path,
                current_text,
                current_text,
                f"move legacy project config {config_path} to {write_path} "
                "before running a config-writing init command",
            )
    return ConfigUpdate(
        config_path,
        current_text,
        updated_text,
        added_roles=added_roles,
    )


def sidecar_config_action_detail(roles: tuple[str, ...]) -> str:
    """Describe an explicit sidecar configuration update."""

    joined = format_roles(roles)
    suffix = "sidecar" if len(roles) == 1 else "sidecars"
    return f"declare the managed {joined} {suffix}"


def format_roles(roles: tuple[str, ...]) -> str:
    """Format sidecar roles as a human-readable list."""

    if len(roles) < 3:
        return " and ".join(roles)
    return f"{', '.join(roles[:-1])}, and {roles[-1]}"


def repo_project_management(
    path: str | Path | None,
) -> tuple[Path, ProjectManagementStatus]:
    """Resolve the project root and its SASE management status."""

    project_root = _resolve_project_root(path)
    compatible = resolve_project_layout(project_root).config
    try:
        config_path = compatible.resolve_read("project config") or compatible.write_path
    except LayoutCollisionError as exc:
        return project_root, ProjectManagementStatus(
            compatible.write_path,
            False,
            str(exc),
        )
    return project_root, project_management_status(config_path)


def _resolve_project_root(path: str | Path | None) -> Path:
    """Resolve a repository-init path to its containing VCS root."""

    candidate = Path.cwd() if path is None else Path(path).expanduser()
    candidate = candidate.resolve(strict=False)
    if candidate.name == "sase.yml":
        candidate = (
            candidate.parent.parent
            if candidate.parent.name == "sase"
            else candidate.parent
        )
    if candidate.name == "sdd" and candidate.parent.name == ".sase":
        candidate = candidate.parent.parent
    if candidate.is_file():
        candidate = candidate.parent
    for root in (candidate, *candidate.parents):
        if (root / ".git").exists():
            return root
    return candidate


def project_provider_sdd_policy(project_root: Path) -> str | None:
    """Return the provider's supported SDD storage policy, if available."""

    try:
        from sase.vcs_provider import detect_vcs
        from sase.workspace_provider import get_sdd_storage_policy_by_vcs

        vcs_name = detect_vcs(str(project_root))
        if vcs_name is None:
            return None
        policy = get_sdd_storage_policy_by_vcs(vcs_name)
    except Exception:
        return None
    return policy if policy in {"in_tree", "local", "separate_repo"} else None


def materialized_compatibility_roles(project_root: Path) -> frozenset[str]:
    """Return sidecar roles recorded by the compatibility store record."""

    try:
        from sase.sdd._paths import get_primary_workspace_dir
        from sase.sdd.store import read_sdd_store_record

        primary = Path(get_primary_workspace_dir(str(project_root), 1))
        record = read_sdd_store_record(primary)
    except (OSError, RuntimeError, ValueError):
        return frozenset()
    if record is None or not record.is_sidecar_storage:
        return frozenset()
    return frozenset(record.sidecars)


__all__ = [
    "ConfigUpdate",
    "configured_sidecar_specs",
    "explicit_sidecar_config_update",
    "format_roles",
    "materialized_compatibility_roles",
    "project_provider_sdd_policy",
    "repo_project_management",
    "sidecar_config_action_detail",
]
