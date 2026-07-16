"""Public facade for provider-owned SDD storage."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.workspace_provider import SddSidecarPreflight

from sase.sdd._paths import get_primary_workspace_dir
from sase.sdd._store_materialization import (
    SddInitOutcome,
    _ensure_materialized_store_initialized,
    _finalize_existing_store,
    _is_remote_backed_record,
    _is_sidecar_record,
    _legacy_adoption_needed,
    _materialize_sdd_store,
    _positive_result,
    _provider_materialization_result,
    _provider_options,
    _sdd_creation_authorized,
    _usable_primary_record,
    create_and_materialize_sdd_store as _create_and_materialize_sdd_store,
    materialize_sdd_store as _materialize_store,
    preflight_sdd_sidecar as _preflight_sdd_sidecar,
    refresh_materialized_store as _refresh_materialized_store,
)
from sase.sdd._store_records import (
    coerce_sdd_store_record,
    delete_sdd_store_record,
    is_materialized_record,
    load_sdd_store_record,
    normalize_sdd_store_record,
    optional_str,
    read_sdd_store_record,
    record_cache,
    record_to_json,
    sdd_store_record_path,
    store_not_materialized_message,
    write_sdd_store_record,
)
from sase.sdd._store_resolution import (
    _resolve_sdd_storage,
    _sdd_dir_for_storage,
    detect_vcs_name as _detect_vcs_name,
    materialized_sdd_clone as _materialized_sdd_clone,
    provider_sdd_storage_policy as _provider_sdd_storage_policy,
    resolve_sdd_store as _resolve_sdd_store,
)
from sase.sdd._store_types import (
    _STORAGE_VALUES,
    SDD_STORAGE_IN_TREE,
    SDD_STORAGE_LOCAL,
    SDD_STORAGE_SEPARATE_REPO,
    SDD_STORAGE_SIDECAR_REPOS,
    SDD_STORE_RECORD_FILENAME,
    SddMaterializationError,
    SddPushAfterCommit,
    SddSidecar,
    SddStorage,
    SddStore,
    SddStoreRecord,
)
from sase.sdd._store_workspace import (
    _inherited_sdd_record_owner_anchor,
    ensure_sdd_kind_clone as _ensure_sdd_kind_clone,
    ensure_workspace_sdd_clone as _ensure_workspace_sdd_clone,
)

_coerce_sdd_store_record = coerce_sdd_store_record
_is_materialized_record = is_materialized_record
_load_sdd_store_record = load_sdd_store_record
_optional_str = optional_str
_record_cache = record_cache
_record_to_json = record_to_json
_sdd_store_record_path = sdd_store_record_path
_store_not_materialized_message = store_not_materialized_message
_write_sdd_store_record = write_sdd_store_record

__all__ = [
    "SDD_STORAGE_IN_TREE",
    "SDD_STORAGE_LOCAL",
    "SDD_STORAGE_SIDECAR_REPOS",
    "SDD_STORAGE_SEPARATE_REPO",
    "SDD_STORE_RECORD_FILENAME",
    "SddInitOutcome",
    "SddSidecar",
    "SddMaterializationError",
    "SddPushAfterCommit",
    "SddStorage",
    "SddStore",
    "SddStoreRecord",
    "_coerce_sdd_store_record",
    "_is_materialized_record",
    "_load_sdd_store_record",
    "_optional_str",
    "_record_cache",
    "_record_to_json",
    "_refresh_materialized_store",
    "_sdd_store_record_path",
    "_store_not_materialized_message",
    "_write_sdd_store_record",
    "create_and_materialize_sdd_store",
    "delete_sdd_store_record",
    "ensure_workspace_sdd_clone",
    "ensure_sdd_kind_clone",
    "materialized_sdd_clone",
    "materialize_sdd_store",
    "preflight_sdd_sidecar",
    "normalize_sdd_store_record",
    "read_sdd_store_record",
    "resolve_sdd_dir",
    "resolve_sdd_kind_dir",
    "resolve_sdd_store",
    "write_sdd_store_record",
]


def resolve_sdd_dir(workspace_dir: str | Path, workspace_num: int) -> Path:
    """Resolve the effective SDD root without network or filesystem writes."""

    return resolve_sdd_store(workspace_dir, workspace_num).sdd_dir


def resolve_sdd_kind_dir(
    workspace_dir: str | Path, workspace_num: int, kind: str
) -> Path:
    """Resolve one logical SDD kind without materializing its backing clone."""

    return resolve_sdd_store(workspace_dir, workspace_num).kind_root(kind)


def resolve_sdd_store(workspace_dir: str | Path, workspace_num: int) -> SddStore:
    """Resolve provider-owned storage policy and concrete filesystem paths."""

    return _resolve_sdd_store(
        workspace_dir,
        workspace_num,
        primary_workspace_resolver=get_primary_workspace_dir,
    )


def materialized_sdd_clone(primary_workspace_dir: str | Path) -> Path | None:
    """Return the primary sidecar clone when its store was materialized."""

    return _materialized_sdd_clone(
        primary_workspace_dir,
        primary_workspace_resolver=get_primary_workspace_dir,
    )


def materialize_sdd_store(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    sdd_creation_authorized: bool | None = None,
) -> SddStore:
    """Materialize the provider-selected store or fail without a local fallback.

    Remote-backed stores require ``is_sase_managed: true`` in the target
    repository's ``sase.yml``. ``sdd_creation_authorized`` is the additional
    explicit-init guard: omitting it authorizes creation for a managed repo,
    while ``False`` still permits discovery but must prevent remote creation.
    """

    return _materialize_store(
        workspace_dir,
        workspace_num,
        sdd_creation_authorized=sdd_creation_authorized,
    )


def preflight_sdd_sidecar(
    workspace_dir: str | Path,
    workspace_num: int,
) -> SddSidecarPreflight:
    """Return authoritative, read-only provider discovery for explicit init."""

    return _preflight_sdd_sidecar(workspace_dir, workspace_num)


def create_and_materialize_sdd_store(
    workspace_dir: str | Path,
    workspace_num: int,
) -> SddInitOutcome:
    """Compatibility name for the unified provider-owned materialization path."""

    return _create_and_materialize_sdd_store(workspace_dir, workspace_num)


def ensure_workspace_sdd_clone(
    workspace_dir: str | Path,
    workspace_num: int,
    *,
    strict: bool = False,
) -> None:
    """Ensure a workspace-local clone, optionally failing the setup transaction."""

    _ensure_workspace_sdd_clone(
        workspace_dir,
        workspace_num,
        strict=strict,
        resolve_store=resolve_sdd_store,
        primary_workspace_resolver=get_primary_workspace_dir,
    )


def ensure_sdd_kind_clone(
    workspace_dir: str | Path,
    workspace_num: int,
    kind: str,
    *,
    strict: bool = False,
) -> Path:
    """Materialize and synchronize the sidecar clone backing *kind*."""

    return _ensure_sdd_kind_clone(
        workspace_dir,
        workspace_num,
        kind,
        strict=strict,
        resolve_store=resolve_sdd_store,
        primary_workspace_resolver=get_primary_workspace_dir,
    )
