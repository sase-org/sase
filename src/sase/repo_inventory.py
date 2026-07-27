"""Frontend-neutral inventory of repositories known by SASE.

This module is intentionally a thin Python domain adapter. Project discovery
is Rust-owned, while linked-repository configuration and SDD store records are
still Python-owned. If those inputs move into ``sase-core``, this adapter is the
migration seam; CLI and TUI consumers should keep using this inventory API.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from pathlib import Path
import re
from typing import Any

from sase._linked_repo_config import (
    DEFAULT_AGENTS_DESCRIPTION,
    DEFAULT_BEADS_DESCRIPTION,
    DEFAULT_PLANS_DESCRIPTION,
    DEFAULT_RESEARCH_DESCRIPTION,
    HIDDEN_SIDECAR_ROLES,
    _DEFAULT_LINKED_REPO_MARKER,
    _SIDECAR_REMOTE_URL_KEY,
    _SIDECAR_REPO_MARKER,
    _SIDECAR_ROLE_KEY,
    _SIDECAR_SLUG_KEY,
    inject_default_linked_repos,
    merged_repo_entries_from_config,
    read_project_local_config,
    resolution_config,
    resolve_config_path,
)
from sase._repo_inventory_models import (
    RepoCloneRecord,
    RepoInventory,
    RepoInventoryIssue,
    RepoInventoryProjectNotFoundError,
    RepoKind,
    RepoRecord,
)
from sase._repo_inventory_workspaces import (
    external_repo_records,
    normalize_path,
    repo_clones,
    workspace_checkouts,
)
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)
from sase.linked_repos import (
    hidden_sidecar_clone_dir,
    sidecar_repo_clone_dir,
    sdd_sidecar_clone_dirname,
)
from sase.sdd.store import SddMaterializationError, read_sdd_store_record

_KIND_ORDER: dict[RepoKind, int] = {
    "primary": 0,
    "sidecar": 1,
    "linked": 2,
    "external": 3,
}
_ENV_INVALID_CHARS = re.compile(r"[^A-Za-z0-9]+")


def collect_repo_inventory(
    projects_root: Path | str | None = None,
    *,
    project: str | None = None,
    include_disabled: bool = False,
) -> RepoInventory:
    """Collect repositories for enabled projects or one explicit project.

    An explicit project is looked up across enabled and disabled projects.
    ``home`` is admitted only as a host for linked repositories; it does not
    gain a primary-repository row because it is system-managed, not a true
    project.
    """

    root = Path(projects_root) if projects_root is not None else sase_projects_dir()
    include_states: Sequence[str] | str = (
        "all" if project is not None or include_disabled else "enabled"
    )
    discovered = list_project_records(
        root,
        include_states,
        include_home=True,
        projects_only=False,
    )
    hosts = [
        record
        for record in discovered
        if record.is_project
        or (record.system_managed and record.project_name == "home")
    ]
    if project is not None:
        hosts = [record for record in hosts if _record_matches_project(record, project)]
        if not hosts:
            raise RepoInventoryProjectNotFoundError(
                f"project '{project}' was not found"
            )

    records: list[RepoRecord] = []
    issues: list[RepoInventoryIssue] = []
    for host in hosts:
        host_records, host_issues = _collect_project_repos(host)
        records.extend(host_records)
        issues.extend(host_issues)

    records = _dedupe_records(records)
    records.sort(
        key=lambda record: (
            record.project.casefold(),
            _KIND_ORDER[record.kind],
            record.name.casefold(),
            record.path,
        )
    )
    return RepoInventory(tuple(records), tuple(issues))


def _collect_project_repos(
    host: ProjectRecordWire,
) -> tuple[list[RepoRecord], list[RepoInventoryIssue]]:
    project = effective_project_name(host)
    project_key = host.project_name
    records: list[RepoRecord] = []
    issues: list[RepoInventoryIssue] = []
    raw_primary = (host.workspace_dir or "").strip()

    if host.is_project:
        primary_path = normalize_path(raw_primary) if raw_primary else ""
        records.append(
            RepoRecord(
                name=Path(primary_path).name if primary_path else project,
                kind="primary",
                project=project,
                project_key=project_key,
                path=primary_path,
                exists=bool(primary_path and Path(primary_path).is_dir()),
                auto_clone=False,
                description=None,
                source="ProjectSpec",
                env_name=None,
            )
        )

    if not raw_primary:
        issues.append(
            RepoInventoryIssue(project, f"{host.project_file} has no WORKSPACE_DIR")
        )
        return records, issues

    primary = normalize_path(raw_primary)
    entries: list[Mapping[str, Any]] = []
    resolved_config: Mapping[str, Any] | None = None
    try:
        local_config = read_project_local_config(primary)
        resolved_config = resolution_config(primary, None)
        entries, merge_warnings = merged_repo_entries_from_config(
            resolved_config,
            primary_workspace_dir=primary,
        )
        entries = inject_default_linked_repos(
            entries,
            primary_workspace_dir=primary,
            local_config=local_config,
            config=resolved_config,
        )
        issues.extend(
            RepoInventoryIssue(project, warning) for warning in merge_warnings
        )
    except Exception as exc:
        issues.append(
            RepoInventoryIssue(project, f"Unable to resolve linked repos: {exc}")
        )

    env_names = _entry_env_names(entries)
    entry_metadata = _entry_metadata_by_name(entries, env_names)
    materialized_sidecars: set[str] = set()
    disabled_sidecars = {
        token
        for entry in entries
        if entry.get(_SIDECAR_REPO_MARKER) is True and entry.get("disabled") is True
        for token in (
            _optional_text(entry.get(_SIDECAR_ROLE_KEY)),
            _optional_text(entry.get(_SIDECAR_SLUG_KEY)),
        )
        if token is not None
    }

    try:
        store_record = read_sdd_store_record(primary)
    except (OSError, SddMaterializationError, ValueError) as exc:
        store_record = None
        issues.append(RepoInventoryIssue(project, str(exc)))

    if store_record is not None and store_record.discovery != "not_found":
        if store_record.is_sidecar_storage:
            for kind in ("plans", "research", "beads"):
                sidecar = store_record.sidecar_for_kind(kind)
                if sidecar is None:
                    continue
                store_slug = _repo_basename(sidecar.repo)
                if kind in disabled_sidecars or store_slug in disabled_sidecars:
                    continue
                metadata = entry_metadata.get(kind) or entry_metadata.get(
                    store_slug, {}
                )
                role = _optional_text(metadata.get("role")) or store_slug
                slug = _optional_text(metadata.get("slug")) or store_slug
                materialized_sidecars.update({role, slug})
                path = (
                    _optional_text(metadata.get("path"))
                    if metadata.get("is_configured_sidecar") is True
                    else None
                ) or sidecar_repo_clone_dir(primary, kind)
                default_description = {
                    "plans": DEFAULT_PLANS_DESCRIPTION,
                    "research": DEFAULT_RESEARCH_DESCRIPTION,
                    "beads": DEFAULT_BEADS_DESCRIPTION,
                }[kind]
                records.append(
                    RepoRecord(
                        name=role,
                        kind="sidecar",
                        project=project,
                        project_key=project_key,
                        path=path,
                        exists=Path(path).is_dir(),
                        auto_clone=bool(
                            metadata.get("auto_clone", kind in {"plans", "beads"})
                        ),
                        description=_optional_text(metadata.get("description"))
                        or default_description,
                        source=(
                            "repos.sidecar config"
                            if metadata.get("is_configured_sidecar") is True
                            else "SDD store record"
                        ),
                        env_name=_optional_text(metadata.get("env_name"))
                        or _sanitize_env_name(role),
                        slug=slug,
                        remote_url=(
                            _optional_text(metadata.get("remote_url"))
                            or sidecar.remote_url
                        ),
                        sdd_storage=store_record.storage,
                    )
                )
        elif store_record.repo:
            name = _repo_basename(store_record.repo)
            if name in disabled_sidecars or "plans" in disabled_sidecars:
                name = ""
            if not name:
                store_record = None
            else:
                materialized_sidecars.add(name)
                path = str(Path(primary) / ".sase" / "sdd")
                records.append(
                    RepoRecord(
                        name=name,
                        kind="sidecar",
                        project=project,
                        project_key=project_key,
                        path=path,
                        exists=Path(path).is_dir(),
                        auto_clone=True,
                        description="Durable SASE development artifacts.",
                        source="SDD store record",
                        env_name=_sanitize_env_name(name),
                        slug=name,
                        remote_url=store_record.remote_url,
                        sdd_storage=store_record.storage,
                    )
                )

    for index, entry in enumerate(entries):
        if entry.get("disabled") is True:
            continue
        linked_name = _optional_text(entry.get("name"))
        raw_path = _optional_text(entry.get("path"))
        if linked_name is None or raw_path is None:
            issues.append(
                RepoInventoryIssue(
                    project,
                    "Skipping linked repo with missing name or path",
                )
            )
            continue

        sidecar_kind = sdd_sidecar_clone_dirname(
            primary,
            linked_name,
            config=resolved_config,
        )
        is_sidecar = (
            entry.get(_SIDECAR_REPO_MARKER) is True
            or entry.get(_DEFAULT_LINKED_REPO_MARKER) is True
            or sidecar_kind is not None
        )
        sidecar_role = _optional_text(entry.get(_SIDECAR_ROLE_KEY))
        entry_slug = _optional_text(entry.get(_SIDECAR_SLUG_KEY))
        if is_sidecar and sidecar_role in HIDDEN_SIDECAR_ROLES:
            try:
                hidden_path = hidden_sidecar_clone_dir(project_key, sidecar_role)
            except ValueError as exc:
                issues.append(
                    RepoInventoryIssue(
                        project,
                        f"Unable to resolve hidden sidecar {sidecar_role!r}: {exc}",
                    )
                )
                continue
            records.append(
                RepoRecord(
                    name=sidecar_role,
                    kind="sidecar",
                    project=project,
                    project_key=project_key,
                    path=hidden_path,
                    exists=Path(hidden_path).is_dir(),
                    auto_clone=False,
                    description=_optional_text(entry.get("description"))
                    or DEFAULT_AGENTS_DESCRIPTION,
                    source=(
                        "auto-injected sidecar"
                        if entry.get(_DEFAULT_LINKED_REPO_MARKER) is True
                        else "repos.sidecar config"
                    ),
                    env_name=None,
                    slug=entry_slug,
                    remote_url=_optional_text(entry.get(_SIDECAR_REMOTE_URL_KEY)),
                    sdd_storage=None,
                )
            )
            continue
        if (
            linked_name in materialized_sidecars
            or (entry_slug is not None and entry_slug in materialized_sidecars)
            or _repo_basename(linked_name) in materialized_sidecars
        ):
            continue

        try:
            path = resolve_config_path(raw_path, relative_to=primary)
        except (OSError, ValueError) as exc:
            issues.append(
                RepoInventoryIssue(
                    project,
                    f"Unable to resolve linked repo {linked_name!r}: {exc}",
                )
            )
            continue

        auto_clone = entry.get("auto_clone") is True
        if (
            is_sidecar
            and (sidecar_role == "beads" or sidecar_kind == "beads")
            and (store_record is None or store_record.sidecar_for_kind("beads") is None)
        ):
            auto_clone = False

        records.append(
            RepoRecord(
                name=linked_name,
                kind="sidecar" if is_sidecar else "linked",
                project=project,
                project_key=project_key,
                path=path,
                exists=Path(path).is_dir(),
                auto_clone=auto_clone,
                description=_optional_text(entry.get("description")),
                source=(
                    "auto-injected sidecar"
                    if entry.get(_DEFAULT_LINKED_REPO_MARKER) is True
                    else (
                        "repos.sidecar config"
                        if entry.get(_SIDECAR_REPO_MARKER) is True
                        else "repos.linked config"
                    )
                ),
                env_name=env_names.get(index),
                slug=entry_slug if is_sidecar else None,
                remote_url=(
                    _optional_text(entry.get(_SIDECAR_REMOTE_URL_KEY))
                    if is_sidecar
                    else None
                ),
                sdd_storage=None,
            )
        )

    workspace_clones, clone_issues = workspace_checkouts(
        primary,
        project=project,
        config=resolved_config,
    )
    issues.extend(clone_issues)
    records = [
        replace(
            record,
            clones=repo_clones(
                record,
                host_primary=primary,
                workspace_checkouts=workspace_clones,
            ),
        )
        for record in records
    ]
    external_records, external_issues = external_repo_records(
        project=project,
        project_key=project_key,
        workspace_checkouts=workspace_clones,
    )
    records.extend(external_records)
    issues.extend(external_issues)
    return records, issues


def _record_matches_project(record: ProjectRecordWire, project: str) -> bool:
    candidate = project.strip()
    return candidate in {
        record.project_name,
        effective_project_name(record),
        *record.aliases,
    }


def _entry_env_names(entries: Sequence[Mapping[str, Any]]) -> dict[int, str]:
    used: set[str] = set()
    names: dict[int, str] = {}
    for index, entry in enumerate(entries):
        if entry.get("disabled") is True:
            continue
        name = _optional_text(entry.get("name"))
        if name is None:
            continue
        base = _sanitize_env_name(name)
        env_name = base
        suffix = 2
        while env_name in used:
            env_name = f"{base}_{suffix}"
            suffix += 1
        used.add(env_name)
        names[index] = env_name
    return names


def _entry_metadata_by_name(
    entries: Sequence[Mapping[str, Any]],
    env_names: Mapping[int, str],
) -> dict[str, dict[str, object]]:
    metadata: dict[str, dict[str, object]] = {}
    for index, entry in enumerate(entries):
        if entry.get("disabled") is True:
            continue
        name = _optional_text(entry.get("name"))
        if name is None:
            continue
        role = _optional_text(entry.get(_SIDECAR_ROLE_KEY))
        slug = _optional_text(entry.get(_SIDECAR_SLUG_KEY))
        payload: dict[str, object] = {
            "auto_clone": entry.get("auto_clone") is True,
            "description": entry.get("description"),
            "env_name": env_names.get(index),
            "is_configured_sidecar": (
                entry.get(_SIDECAR_REPO_MARKER) is True
                and entry.get(_DEFAULT_LINKED_REPO_MARKER) is not True
            ),
            "path": entry.get("path"),
            "remote_url": entry.get(_SIDECAR_REMOTE_URL_KEY),
            "role": role,
            "slug": slug,
        }
        for key in {name, role, slug}:
            if key is not None:
                if payload["is_configured_sidecar"] is True:
                    metadata[key] = payload
                else:
                    metadata.setdefault(key, payload)
    return metadata


def _dedupe_records(records: Sequence[RepoRecord]) -> list[RepoRecord]:
    deduped: list[RepoRecord] = []
    seen: set[tuple[str, RepoKind, str, str]] = set()
    for record in records:
        key = (record.project_key, record.kind, record.name, record.path)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(record)
    return deduped


def _repo_basename(repo: str) -> str:
    return repo.rstrip("/").rsplit("/", 1)[-1]


def _sanitize_env_name(name: str) -> str:
    env_name = _ENV_INVALID_CHARS.sub("_", name).strip("_").upper()
    return env_name or "REPO"


def _optional_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


__all__ = [
    "RepoCloneRecord",
    "RepoInventory",
    "RepoInventoryIssue",
    "RepoInventoryProjectNotFoundError",
    "RepoKind",
    "RepoRecord",
    "collect_repo_inventory",
]
