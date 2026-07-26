"""Read-only resolution for provider-owned SDD stores."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

from sase.sdd._paths import get_primary_workspace_dir
from sase.sdd._store_adoption import clone_matches_record
from sase.sdd._store_records import is_materialized_record, read_sdd_store_record
from sase.sdd._store_types import (
    _STORAGE_VALUES,
    SDD_STORAGE_IN_TREE,
    SDD_STORAGE_LOCAL,
    SDD_STORAGE_SEPARATE_REPO,
    SDD_STORAGE_SIDECAR_REPOS,
    SddMaterializationError,
    SddStorage,
    SddStore,
    SddStoreRecord,
)

PrimaryWorkspaceResolver = Callable[[str, int], str]


def resolve_sdd_dir(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    primary_workspace_resolver: PrimaryWorkspaceResolver = get_primary_workspace_dir,
) -> Path:
    """Resolve the effective SDD root without network or filesystem writes."""

    return resolve_sdd_store(
        workspace_dir,
        workspace_num,
        primary_workspace_resolver=primary_workspace_resolver,
    ).sdd_dir


def resolve_sdd_kind_dir(
    workspace_dir: str | Path,
    workspace_num: int,
    kind: str,
    *,
    primary_workspace_resolver: PrimaryWorkspaceResolver = get_primary_workspace_dir,
) -> Path:
    """Resolve one logical SDD kind without materializing its backing clone."""

    return resolve_sdd_store(
        workspace_dir,
        workspace_num,
        primary_workspace_resolver=primary_workspace_resolver,
    ).kind_root(kind)


def resolve_sdd_store(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    primary_workspace_resolver: PrimaryWorkspaceResolver = get_primary_workspace_dir,
) -> SddStore:
    """Resolve provider-owned storage policy and concrete filesystem paths."""

    storage, record, _primary = _resolve_sdd_storage(
        workspace_dir,
        workspace_num,
        primary_workspace_resolver=primary_workspace_resolver,
    )
    if storage == SDD_STORAGE_SIDECAR_REPOS:
        assert record is not None and record.plans is not None
        assert record.research is not None
        from sase.linked_repos import sidecar_repo_clone_dir

        plans_dir = Path(sidecar_repo_clone_dir(workspace_dir, "plans"))
        research_dir = Path(sidecar_repo_clone_dir(workspace_dir, "research"))
        return SddStore(
            storage=storage,
            sdd_dir=plans_dir,
            repo_root=plans_dir,
            provider=record.provider,
            remote_url=record.plans.remote_url,
            research_dir=research_dir,
            research_remote_url=record.research.remote_url,
        )

    sdd_dir = _sdd_dir_for_storage(
        workspace_dir,
        workspace_num,
        storage,
        primary_workspace_resolver=primary_workspace_resolver,
    )
    provider: str | None = None
    remote_url: str | None = None
    if is_materialized_record(record) and storage == SDD_STORAGE_SEPARATE_REPO:
        assert record is not None
        provider = record.provider
        remote_url = record.remote_url
    return SddStore(
        storage=storage,
        sdd_dir=sdd_dir,
        repo_root=sdd_dir,
        provider=provider,
        remote_url=remote_url,
    )


def materialized_sdd_clone(
    primary_workspace_dir: str | Path,
    *,
    primary_workspace_resolver: PrimaryWorkspaceResolver = get_primary_workspace_dir,
) -> Path | None:
    """Return the primary sidecar clone when its store was materialized."""

    primary = Path(primary_workspace_dir).expanduser()
    record = read_sdd_store_record(primary)
    if not is_materialized_record(record):
        return None

    assert record is not None
    if record.is_sidecar_storage:
        if record.plans is None:
            return None
        from sase.linked_repos import sidecar_repo_clone_dir

        clone = Path(sidecar_repo_clone_dir(primary, "plans"))
        store = resolve_sdd_store(
            primary,
            1,
            primary_workspace_resolver=primary_workspace_resolver,
        )
        from sase.sdd._store_link import is_matching_store_clone

        return (
            clone if clone.is_dir() and is_matching_store_clone(clone, store) else None
        )

    clone = primary / ".sase" / "sdd"
    if not clone.is_dir():
        return None

    return clone if clone_matches_record(clone, record) else None


def _resolve_sdd_storage(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    primary_workspace_resolver: PrimaryWorkspaceResolver = get_primary_workspace_dir,
) -> tuple[SddStorage, SddStoreRecord | None, Path]:
    workspace = Path(workspace_dir).expanduser()
    primary = Path(primary_workspace_resolver(str(workspace), workspace_num))
    record = read_sdd_store_record(primary)
    if is_materialized_record(record):
        assert record is not None
        return record.storage, record, primary

    policy = provider_sdd_storage_policy(workspace)
    storage = policy if policy in _STORAGE_VALUES else SDD_STORAGE_LOCAL
    return cast(SddStorage, storage), record, primary


def _sdd_dir_for_storage(
    workspace_dir: str | Path,
    workspace_num: int,
    storage: SddStorage,
    *,
    primary_workspace_resolver: PrimaryWorkspaceResolver = get_primary_workspace_dir,
) -> Path:
    workspace = Path(workspace_dir)
    if storage == SDD_STORAGE_IN_TREE:
        return workspace / "sdd"
    if storage == SDD_STORAGE_SEPARATE_REPO:
        return workspace / ".sase" / "sdd"
    primary = primary_workspace_resolver(str(workspace), workspace_num)
    return Path(primary) / ".sase" / "sdd"


def provider_sdd_storage_policy(workspace_dir: str | Path) -> SddStorage | None:
    vcs_name = detect_vcs_name(workspace_dir)
    if not vcs_name:
        return None
    try:
        from sase.workspace_provider import get_sdd_storage_policy_by_vcs

        policy = get_sdd_storage_policy_by_vcs(vcs_name)
    except Exception as exc:
        raise SddMaterializationError(
            f"could not resolve SDD storage policy for workspace provider "
            f"{vcs_name!r}: {str(exc) or type(exc).__name__}"
        ) from exc
    if policy is None or policy == "":
        return None
    if policy not in _STORAGE_VALUES:
        raise SddMaterializationError(
            f"workspace provider {vcs_name!r} declared invalid SDD storage policy "
            f"{policy!r}"
        )
    return cast(SddStorage, policy)


def detect_vcs_name(workspace_dir: str | Path) -> str | None:
    try:
        from sase.vcs_provider import detect_vcs

        return detect_vcs(str(Path(workspace_dir).expanduser()))
    except Exception:
        return None
