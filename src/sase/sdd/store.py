"""SDD storage policy resolution.

This module owns the Python-side policy that maps config, provider metadata,
and an optional materialized-store record to concrete SDD paths. The Rust core
continues to receive fully resolved paths.
"""

from __future__ import annotations

import logging
from pathlib import Path
import subprocess
from typing import Any, cast

from sase.config import load_merged_config
from sase.sdd._paths import get_primary_workspace_dir
from sase.sdd._store_link import ensure_workspace_sdd_clone as _ensure_sdd_clone
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
from sase.sdd._store_types import (
    _CONFIGURED_STORAGE_VALUES,
    _STORAGE_VALUES,
    SDD_STORAGE_AUTO,
    SDD_STORAGE_IN_TREE,
    SDD_STORAGE_LOCAL,
    SDD_STORAGE_SEPARATE_REPO,
    SDD_STORE_RECORD_FILENAME,
    SddConfiguredStorage,
    SddMaterializationError,
    SddPushAfterCommit,
    SddStorage,
    SddStore,
    SddStoreRecord,
)

_logger = logging.getLogger(__name__)

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
    "SDD_STORAGE_AUTO",
    "SDD_STORAGE_IN_TREE",
    "SDD_STORAGE_LOCAL",
    "SDD_STORAGE_SEPARATE_REPO",
    "SDD_STORE_RECORD_FILENAME",
    "SddConfiguredStorage",
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
    "delete_sdd_store_record",
    "ensure_workspace_sdd_clone",
    "get_configured_sdd_storage",
    "materialize_sdd_store",
    "normalize_sdd_store_record",
    "read_sdd_store_record",
    "resolve_sdd_dir",
    "resolve_sdd_store",
    "sdd_dir_for_in_tree_bool",
    "write_sdd_store_record",
]


def get_configured_sdd_storage(
    config: dict[str, Any] | None = None,
) -> SddConfiguredStorage:
    """Return the configured SDD storage enum, applying the legacy alias.

    ``sdd.storage`` values other than ``auto`` win over the legacy
    ``sdd.version_controlled`` alias. When storage is ``auto``, the legacy
    boolean maps ``true`` to ``in_tree`` and ``false`` to ``auto``.
    """

    data = load_merged_config() if config is None else config
    raw_sdd = data.get("sdd", {})
    sdd_config = raw_sdd if isinstance(raw_sdd, dict) else {}

    storage = _coerce_configured_storage(sdd_config.get("storage", SDD_STORAGE_AUTO))
    if storage != SDD_STORAGE_AUTO:
        return storage
    if sdd_config.get("version_controlled") is True:
        return SDD_STORAGE_IN_TREE
    return SDD_STORAGE_AUTO


def resolve_sdd_dir(workspace_dir: str | Path, workspace_num: int) -> Path:
    """Resolve only the effective SDD root directory.

    Separate-repo storage reads the primary checkout's store record, but the
    effective working tree is workspace-local: ``<workspace>/.sase/sdd``.
    """

    storage, _record, _primary = _resolve_sdd_storage(workspace_dir, workspace_num)
    return _sdd_dir_for_storage(workspace_dir, workspace_num, storage)


def resolve_sdd_store(workspace_dir: str | Path, workspace_num: int) -> SddStore:
    """Resolve the effective SDD storage policy and paths."""

    storage, record, _primary = _resolve_sdd_storage(workspace_dir, workspace_num)

    sdd_dir = _sdd_dir_for_storage(workspace_dir, workspace_num, storage)
    provider = (
        record.provider if record and storage == SDD_STORAGE_SEPARATE_REPO else None
    )
    remote_url = (
        record.remote_url if record and storage == SDD_STORAGE_SEPARATE_REPO else None
    )
    return SddStore(
        storage=storage,
        sdd_dir=sdd_dir,
        repo_root=sdd_dir,
        provider=provider,
        remote_url=remote_url,
    )


def materialize_sdd_store(workspace_dir: str | Path, workspace_num: int) -> SddStore:
    """Run setup-time SDD store materialization when a provider opts in.

    Providers are only consulted when either config explicitly requests
    ``separate_repo`` storage or the detected provider declares that policy.
    Existing records are trusted and keep this path local-only.
    """

    workspace = Path(workspace_dir).expanduser()
    primary = Path(get_primary_workspace_dir(str(workspace), workspace_num))
    configured = get_configured_sdd_storage()
    record = read_sdd_store_record(primary)
    if record is not None:
        if configured == SDD_STORAGE_SEPARATE_REPO and not _is_materialized_record(
            record
        ):
            raise SddMaterializationError(_store_not_materialized_message(record))
        store = resolve_sdd_store(workspace, workspace_num)
        if store.storage == SDD_STORAGE_SEPARATE_REPO:
            ensure_workspace_sdd_clone(workspace, workspace_num)
        return resolve_sdd_store(workspace, workspace_num)

    policy = _provider_sdd_storage_policy(workspace)
    if configured != SDD_STORAGE_SEPARATE_REPO and policy != SDD_STORAGE_SEPARATE_REPO:
        return resolve_sdd_store(workspace, workspace_num)

    result = _dispatch_materialize_sdd_store(
        primary,
        workspace,
        workspace_num=workspace_num,
        configured_storage=configured,
        provider_policy=policy,
    )
    if result is None:
        if configured == SDD_STORAGE_SEPARATE_REPO:
            raise SddMaterializationError(_store_not_materialized_message(None))
        return resolve_sdd_store(workspace, workspace_num)

    written_record = _write_sdd_store_record(primary, result)
    if not _is_materialized_record(written_record):
        if configured == SDD_STORAGE_SEPARATE_REPO:
            raise SddMaterializationError(
                _store_not_materialized_message(written_record)
            )
        return resolve_sdd_store(workspace, workspace_num)

    ensure_workspace_sdd_clone(workspace, workspace_num)
    store = resolve_sdd_store(workspace, workspace_num)
    if store.sdd_dir.exists():
        _refresh_materialized_store(store.sdd_dir)
        _ensure_materialized_store_initialized(store)
    return resolve_sdd_store(workspace, workspace_num)


def ensure_workspace_sdd_clone(workspace_dir: str | Path, workspace_num: int) -> None:
    """Best-effort workspace-local clone of a separate-repo SDD store."""

    _ensure_sdd_clone(
        workspace_dir,
        workspace_num,
        resolve_store=resolve_sdd_store,
        primary_workspace_dir=get_primary_workspace_dir,
    )


def sdd_dir_for_in_tree_bool(
    workspace_dir: str | Path, workspace_num: int, in_tree: bool
) -> Path:
    """Compatibility path helper for the legacy boolean API."""

    storage = SDD_STORAGE_IN_TREE if in_tree else SDD_STORAGE_LOCAL
    return _sdd_dir_for_storage(workspace_dir, workspace_num, storage)


def _resolve_sdd_storage(
    workspace_dir: str | Path,
    workspace_num: int,
) -> tuple[SddStorage, SddStoreRecord | None, Path]:
    workspace = Path(workspace_dir).expanduser()
    primary = Path(get_primary_workspace_dir(str(workspace), workspace_num))
    record = read_sdd_store_record(primary)

    configured = get_configured_sdd_storage()
    if configured != SDD_STORAGE_AUTO:
        return cast(SddStorage, configured), record, primary
    if _is_materialized_record(record):
        return SDD_STORAGE_SEPARATE_REPO, record, primary

    policy = _provider_sdd_storage_policy(workspace)
    storage = (
        SDD_STORAGE_IN_TREE if policy == SDD_STORAGE_IN_TREE else SDD_STORAGE_LOCAL
    )
    return storage, record, primary


def _sdd_dir_for_storage(
    workspace_dir: str | Path, workspace_num: int, storage: SddStorage
) -> Path:
    workspace = Path(workspace_dir)
    if storage == SDD_STORAGE_IN_TREE:
        return workspace / "sdd"
    if storage == SDD_STORAGE_SEPARATE_REPO:
        return workspace / ".sase" / "sdd"
    primary = get_primary_workspace_dir(str(workspace), workspace_num)
    return Path(primary) / ".sase" / "sdd"


def _provider_sdd_storage_policy(workspace_dir: str | Path) -> SddStorage | None:
    vcs_name = _detect_vcs_name(workspace_dir)
    if not vcs_name:
        return None
    try:
        from sase.workspace_provider import get_sdd_storage_policy_by_vcs

        policy = get_sdd_storage_policy_by_vcs(vcs_name)
    except Exception:
        return None

    if policy in _STORAGE_VALUES:
        return cast(SddStorage, policy)
    return None


def _detect_vcs_name(workspace_dir: str | Path) -> str | None:
    try:
        from sase.vcs_provider import detect_vcs

        return detect_vcs(str(Path(workspace_dir).expanduser()))
    except Exception:
        return None


def _dispatch_materialize_sdd_store(
    primary: Path,
    workspace: Path,
    *,
    workspace_num: int,
    configured_storage: SddConfiguredStorage,
    provider_policy: SddStorage | None,
) -> dict[str, Any] | None:
    try:
        from sase.workspace_provider import materialize_sdd_store as dispatch

        result = dispatch(
            str(primary),
            str(workspace),
            {
                "workspace_num": workspace_num,
                "configured_storage": configured_storage,
                "provider_policy": provider_policy or "",
                "vcs_name": _detect_vcs_name(workspace) or "",
            },
        )
    except Exception:
        if configured_storage == SDD_STORAGE_SEPARATE_REPO:
            raise
        _logger.warning("SDD store materialization hook failed", exc_info=True)
        return None
    return result


def _refresh_materialized_store(sdd_dir: Path) -> None:
    """Best-effort fast-forward refresh for an existing materialized clone."""

    if not (sdd_dir / ".git").is_dir():
        return
    try:
        from sase.sdd._commit import network_git_timeout

        result = subprocess.run(
            ["git", "pull", "--ff-only"],
            cwd=sdd_dir,
            capture_output=True,
            text=True,
            timeout=network_git_timeout(),
            check=False,
        )
    except Exception:
        _logger.warning("Failed to refresh materialized SDD store", exc_info=True)
        return
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        _logger.warning(
            "Failed to refresh materialized SDD store in %s: %s",
            sdd_dir,
            detail or f"git pull exited {result.returncode}",
        )


def _ensure_materialized_store_initialized(store: SddStore) -> None:
    """Create generated guides and bead files inside a materialized store."""

    from sase.bead.project import BEADS_DIRNAME_NON_VC, BeadProject
    from sase.sdd._commit import commit_sdd_store_files
    from sase.sdd.files import ensure_sdd_initialized

    sdd_dir = store.sdd_dir
    sdd_dir.mkdir(parents=True, exist_ok=True)
    changed_paths: list[Path] = list(ensure_sdd_initialized(sdd_dir))

    gitignore = sdd_dir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("beads/beads.db\n", encoding="utf-8")
        changed_paths.append(gitignore)

    beads_dir = sdd_dir / BEADS_DIRNAME_NON_VC
    if not beads_dir.is_dir():
        BeadProject.init(sdd_dir, beads_dirname=BEADS_DIRNAME_NON_VC)
        changed_paths.append(beads_dir)

    if changed_paths:
        commit_sdd_store_files(
            store,
            "Initialize SDD store",
            auto_commit_type="beads",
            paths=changed_paths,
        )


def _coerce_configured_storage(value: object) -> SddConfiguredStorage:
    if isinstance(value, str) and value in _CONFIGURED_STORAGE_VALUES:
        return cast(SddConfiguredStorage, value)
    return SDD_STORAGE_AUTO
