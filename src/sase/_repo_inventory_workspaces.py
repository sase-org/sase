"""Workspace clone discovery for the repository inventory."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
from typing import Any

from sase._repo_inventory_models import (
    RepoCloneRecord,
    RepoInventoryIssue,
    RepoRecord,
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
from sase.workspace_provider.registry import (
    WorkspaceRegistryError,
    load_registry,
)
from sase.workspace_provider.store import WorkspaceStore


def workspace_checkouts(
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
        checkouts.append((workspace_num, normalize_path(checkout)))

    checkouts.sort(key=lambda item: (item[0], item[1]))
    return tuple(checkouts), issues


def repo_clones(
    record: RepoRecord,
    *,
    host_primary: str,
    workspace_checkouts: Sequence[tuple[int, str]],
) -> tuple[RepoCloneRecord, ...]:
    """Build one repository's clone matrix across registered workspaces."""

    clones: list[RepoCloneRecord] = []
    normalized_primary = normalize_path(host_primary)
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


def external_repo_records(
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


def normalize_path(path: str) -> str:
    """Return an absolute, normalized path without requiring it to exist."""

    return str(Path(os.path.expandvars(path)).expanduser().resolve(strict=False))


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
    if normalize_path(host_checkout) == host_primary:
        return record.path

    if record.kind == "sidecar":
        if sidecar_dirname is not None:
            return sidecar_repo_clone_dir(host_checkout, sidecar_dirname)
        try:
            relative = Path(record.path).relative_to(host_primary)
        except ValueError:
            return sidecar_repo_clone_dir(host_checkout, record.name)
        return normalize_path(str(Path(host_checkout) / relative))

    if record.kind == "external":
        clone_parts = external_repo_clone_parts_from_name(record.name)
        return external_repo_clone_dir(
            host_checkout,
            clone_parts[0],
            *clone_parts[1:],
        )

    return linked_repo_clone_dir(host_checkout, record.name)
