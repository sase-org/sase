"""Frontend-neutral inventory of repositories known by SASE.

This module is intentionally a thin Python domain adapter. Project discovery
is Rust-owned, while linked-repository configuration and SDD store records are
still Python-owned. If those inputs move into ``sase-core``, this adapter is the
migration seam; CLI and TUI consumers should keep using this inventory API.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
import os
from pathlib import Path
import re
from typing import Any, Literal

from sase._linked_repo_config import (
    DEFAULT_PLANS_DESCRIPTION,
    DEFAULT_RESEARCH_DESCRIPTION,
    _DEFAULT_LINKED_REPO_MARKER,
    inject_default_linked_repos,
    merged_entries_from_config,
    read_project_local_config,
    resolution_config,
    resolve_config_path,
)
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)
from sase.external_repos import (
    EXTERNAL_PROJECTS_NAMESPACE,
    external_repo_clone_parts_from_name,
    external_repo_name_from_clone_parts,
)
from sase.linked_repos import (
    EXTERNAL_REPO_CLONES_SUBDIR,
    external_repo_clone_dir,
    linked_repo_clone_dir,
    sidecar_repo_clone_dir,
    sdd_sidecar_clone_dirname,
)
from sase.sdd.store import SddMaterializationError, read_sdd_store_record
from sase.workspace_provider.registry import (
    WorkspaceRegistryError,
    load_registry,
)
from sase.workspace_provider.store import WorkspaceStore

RepoKind = Literal["primary", "sidecar", "linked", "external"]

_KIND_ORDER: dict[RepoKind, int] = {
    "primary": 0,
    "sidecar": 1,
    "linked": 2,
    "external": 3,
}
_ENV_INVALID_CHARS = re.compile(r"[^A-Za-z0-9]+")


@dataclass(frozen=True)
class RepoCloneRecord:
    """One repository's path and presence in a registered workspace."""

    workspace_num: int
    path: str
    exists: bool

    def to_json_dict(self) -> dict[str, object]:
        """Return a stable JSON-safe representation of this clone."""

        return asdict(self)


@dataclass(frozen=True)
class RepoRecord:
    """One primary, sidecar, linked, or external repository known by SASE."""

    name: str
    kind: RepoKind
    project: str
    project_key: str
    path: str
    exists: bool
    auto_clone: bool
    description: str | None
    source: str
    env_name: str | None
    sdd_storage: str | None = None
    clones: tuple[RepoCloneRecord, ...] = ()

    def clone_for_workspace(self, workspace_num: int) -> RepoCloneRecord | None:
        """Return this repo's clone record for *workspace_num*, if registered."""

        return next(
            (clone for clone in self.clones if clone.workspace_num == workspace_num),
            None,
        )

    def to_json_dict(self, *, workspace_num: int | None = None) -> dict[str, object]:
        """Return a stable JSON-safe representation of this record."""

        selected = (
            self.clone_for_workspace(workspace_num)
            if workspace_num is not None
            else None
        )
        return {
            "name": self.name,
            "kind": self.kind,
            "project": self.project,
            "project_key": self.project_key,
            "path": selected.path if selected is not None else self.path,
            "exists": selected.exists if selected is not None else self.exists,
            "auto_clone": self.auto_clone,
            "description": self.description,
            "source": self.source,
            "env_name": self.env_name,
            "sdd_storage": self.sdd_storage,
            "clones": [clone.to_json_dict() for clone in self.clones],
        }


@dataclass(frozen=True)
class RepoInventoryIssue:
    """A non-fatal problem isolated to one host project."""

    project: str
    message: str

    def to_json_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True)
class RepoInventory:
    """Repository records plus non-fatal per-project issues."""

    records: tuple[RepoRecord, ...]
    issues: tuple[RepoInventoryIssue, ...] = ()

    def to_json_dict(self) -> dict[str, object]:
        return {
            "repos": [record.to_json_dict() for record in self.records],
            "issues": [issue.to_json_dict() for issue in self.issues],
        }


class RepoInventoryProjectNotFoundError(ValueError):
    """Raised when an explicit project filter matches no inventory host."""


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
        primary_path = _normalize_path(raw_primary) if raw_primary else ""
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

    primary = _normalize_path(raw_primary)
    entries: list[Mapping[str, Any]] = []
    resolved_config: Mapping[str, Any] | None = None
    try:
        local_config = read_project_local_config(primary)
        resolved_config = resolution_config(primary, None)
        entries, merge_warnings = merged_entries_from_config(resolved_config)
        entries = inject_default_linked_repos(
            entries,
            primary_workspace_dir=primary,
            local_config=local_config,
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

    try:
        store_record = read_sdd_store_record(primary)
    except (OSError, SddMaterializationError, ValueError) as exc:
        store_record = None
        issues.append(RepoInventoryIssue(project, str(exc)))

    if store_record is not None and store_record.discovery != "not_found":
        if store_record.is_sidecar_storage:
            for kind in ("plans", "research"):
                sidecar = store_record.sidecar_for_kind(kind)
                if sidecar is None:
                    continue
                name = _repo_basename(sidecar.repo)
                materialized_sidecars.add(name)
                metadata = entry_metadata.get(name, {})
                path = sidecar_repo_clone_dir(primary, kind)
                default_description = (
                    DEFAULT_PLANS_DESCRIPTION
                    if kind == "plans"
                    else DEFAULT_RESEARCH_DESCRIPTION
                )
                records.append(
                    RepoRecord(
                        name=name,
                        kind="sidecar",
                        project=project,
                        project_key=project_key,
                        path=path,
                        exists=Path(path).is_dir(),
                        auto_clone=bool(metadata.get("auto_clone", kind == "plans")),
                        description=_optional_text(metadata.get("description"))
                        or default_description,
                        source="SDD store record",
                        env_name=_optional_text(metadata.get("env_name"))
                        or _sanitize_env_name(name),
                        sdd_storage=store_record.storage,
                    )
                )
        elif store_record.repo:
            name = _repo_basename(store_record.repo)
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
                    sdd_storage=store_record.storage,
                )
            )

    for index, entry in enumerate(entries):
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

        sidecar_kind = sdd_sidecar_clone_dirname(primary, linked_name)
        is_sidecar = (
            entry.get(_DEFAULT_LINKED_REPO_MARKER) is True or sidecar_kind is not None
        )
        if (
            linked_name in materialized_sidecars
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

        records.append(
            RepoRecord(
                name=linked_name,
                kind="sidecar" if is_sidecar else "linked",
                project=project,
                project_key=project_key,
                path=path,
                exists=Path(path).is_dir(),
                auto_clone=entry.get("auto_clone") is True,
                description=_optional_text(entry.get("description")),
                source=(
                    "auto-injected sidecar"
                    if entry.get(_DEFAULT_LINKED_REPO_MARKER) is True
                    else "linked_repos config"
                ),
                env_name=env_names.get(index),
                sdd_storage=None,
            )
        )

    workspace_clones, clone_issues = _workspace_checkouts(
        primary,
        project=project,
        config=resolved_config,
    )
    issues.extend(clone_issues)
    records = [
        replace(
            record,
            clones=_repo_clones(
                record,
                host_primary=primary,
                workspace_checkouts=workspace_clones,
            ),
        )
        for record in records
    ]
    external_records, external_issues = _external_repo_records(
        project=project,
        project_key=project_key,
        workspace_checkouts=workspace_clones,
    )
    records.extend(external_records)
    issues.extend(external_issues)
    return records, issues


def _workspace_checkouts(
    primary: str,
    *,
    project: str,
    config: Mapping[str, Any] | None,
) -> tuple[tuple[tuple[int, str], ...], list[RepoInventoryIssue]]:
    """Return sorted registered workspace checkout paths for one host project."""

    try:
        store = WorkspaceStore(primary, config=config)
        registry = load_registry(store, strict=True)
    except (OSError, RuntimeError, ValueError, WorkspaceRegistryError) as exc:
        return (
            ((0, primary),),
            [
                RepoInventoryIssue(
                    project,
                    f"Unable to resolve workspace clone inventory: {exc}",
                )
            ],
        )

    issues: list[RepoInventoryIssue] = []
    checkouts: list[tuple[int, str]] = []
    for raw_num, entry in registry.workspaces.items():
        try:
            workspace_num = int(raw_num)
        except (TypeError, ValueError):
            issues.append(
                RepoInventoryIssue(
                    project,
                    f"Ignoring non-numeric registry workspace key {raw_num!r}",
                )
            )
            continue
        checkout = entry.checkout_dir.rstrip("/") or entry.checkout_dir
        checkouts.append((workspace_num, _normalize_path(checkout)))

    checkouts.sort(key=lambda item: (item[0], item[1]))
    return tuple(checkouts), issues


def _repo_clones(
    record: RepoRecord,
    *,
    host_primary: str,
    workspace_checkouts: Sequence[tuple[int, str]],
) -> tuple[RepoCloneRecord, ...]:
    clones: list[RepoCloneRecord] = []
    normalized_primary = _normalize_path(host_primary)
    sidecar_dirname = (
        sdd_sidecar_clone_dirname(normalized_primary, record.name)
        if record.kind == "sidecar"
        else None
    )
    for workspace_num, host_checkout in workspace_checkouts:
        path = _repo_path_in_workspace(
            record,
            host_primary=normalized_primary,
            host_checkout=host_checkout,
            sidecar_dirname=sidecar_dirname,
        )
        clones.append(
            RepoCloneRecord(
                workspace_num=workspace_num,
                path=path,
                exists=Path(path).is_dir(),
            )
        )
    return tuple(clones)


def _external_repo_records(
    *,
    project: str,
    project_key: str,
    workspace_checkouts: Sequence[tuple[int, str]],
) -> tuple[list[RepoRecord], list[RepoInventoryIssue]]:
    """Scan registered workspace checkouts for materialized external repos."""

    clone_parts_by_name: dict[str, tuple[str, ...]] = {}
    issues: list[RepoInventoryIssue] = []
    for _workspace_num, host_checkout in workspace_checkouts:
        root = Path(host_checkout).joinpath(*EXTERNAL_REPO_CLONES_SUBDIR)
        try:
            namespaces = _child_directories(root)
            for namespace in namespaces:
                candidates: list[tuple[str, ...]] = []
                if namespace.name == EXTERNAL_PROJECTS_NAMESPACE:
                    candidates.extend(
                        (namespace.name, project_dir.name)
                        for project_dir in _child_directories(namespace)
                    )
                else:
                    candidates.extend(
                        (namespace.name, owner_dir.name, repo_dir.name)
                        for owner_dir in _child_directories(namespace)
                        for repo_dir in _child_directories(owner_dir)
                    )
                for parts in candidates:
                    name = external_repo_name_from_clone_parts(parts)
                    if name is None:
                        continue
                    canonical_parts = external_repo_clone_parts_from_name(name)
                    if tuple(parts) == canonical_parts:
                        clone_parts_by_name.setdefault(name, canonical_parts)
        except OSError as exc:
            issues.append(
                RepoInventoryIssue(
                    project,
                    f"Unable to scan external repos in {root}: {exc}",
                )
            )

    records: list[RepoRecord] = []
    for name, clone_parts in sorted(
        clone_parts_by_name.items(),
        key=lambda item: (item[0].casefold(), item[0]),
    ):
        clones = tuple(
            RepoCloneRecord(
                workspace_num=workspace_num,
                path=(
                    clone_path := external_repo_clone_dir(
                        host_checkout,
                        clone_parts[0],
                        *clone_parts[1:],
                    )
                ),
                exists=Path(clone_path).is_dir(),
            )
            for workspace_num, host_checkout in workspace_checkouts
        )
        existing = next((clone for clone in clones if clone.exists), None)
        if existing is None:
            continue
        records.append(
            RepoRecord(
                name=name,
                kind="external",
                project=project,
                project_key=project_key,
                path=existing.path,
                exists=True,
                auto_clone=False,
                description=None,
                source="opened external",
                env_name=None,
                clones=clones,
            )
        )
    return records, issues


def _child_directories(path: Path) -> tuple[Path, ...]:
    """Return deterministic direct child directories of *path*."""

    if not path.is_dir():
        return ()
    return tuple(
        sorted(
            (child for child in path.iterdir() if child.is_dir()),
            key=lambda child: (child.name.casefold(), child.name),
        )
    )


def _repo_path_in_workspace(
    record: RepoRecord,
    *,
    host_primary: str,
    host_checkout: str,
    sidecar_dirname: str | None,
) -> str:
    if record.kind == "primary":
        return host_checkout

    # The primary workspace uses each secondary repo's configured source
    # checkout. Numbered workspaces use host-scoped materializations.
    if _normalize_path(host_checkout) == host_primary:
        return record.path

    if record.kind == "sidecar":
        if sidecar_dirname is not None:
            return sidecar_repo_clone_dir(host_checkout, sidecar_dirname)
        try:
            relative = Path(record.path).relative_to(host_primary)
        except ValueError:
            return sidecar_repo_clone_dir(host_checkout, record.name)
        return _normalize_path(str(Path(host_checkout) / relative))

    if record.kind == "external":
        clone_parts = external_repo_clone_parts_from_name(record.name)
        return external_repo_clone_dir(
            host_checkout,
            clone_parts[0],
            *clone_parts[1:],
        )

    return linked_repo_clone_dir(host_checkout, record.name)


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
        name = _optional_text(entry.get("name"))
        if name is None:
            continue
        metadata.setdefault(
            name,
            {
                "auto_clone": entry.get("auto_clone") is True,
                "description": entry.get("description"),
                "env_name": env_names.get(index),
            },
        )
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


def _normalize_path(path: str) -> str:
    return str(Path(os.path.expandvars(path)).expanduser().resolve(strict=False))


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
