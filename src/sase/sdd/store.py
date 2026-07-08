"""SDD storage policy resolution.

This module owns the Python-side policy that maps config, provider metadata,
and an optional materialized-store record to concrete SDD paths. The Rust core
continues to receive fully resolved paths.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Literal, cast

from sase.config import load_merged_config
from sase.sdd._paths import get_primary_workspace_dir

SddStorage = Literal["in_tree", "local", "separate_repo"]
SddConfiguredStorage = Literal["auto", "in_tree", "local", "separate_repo"]

SDD_STORAGE_AUTO: SddConfiguredStorage = "auto"
SDD_STORAGE_IN_TREE: SddStorage = "in_tree"
SDD_STORAGE_LOCAL: SddStorage = "local"
SDD_STORAGE_SEPARATE_REPO: SddStorage = "separate_repo"

SDD_STORE_RECORD_FILENAME = "sdd-store.json"

_CONFIGURED_STORAGE_VALUES: frozenset[str] = frozenset(
    {"auto", "in_tree", "local", "separate_repo"}
)
_STORAGE_VALUES: frozenset[str] = frozenset({"in_tree", "local", "separate_repo"})


@dataclass(frozen=True)
class SddStoreRecord:
    """Persisted metadata for a materialized SDD store."""

    schema_version: int
    storage: SddStorage
    provider: str | None = None
    host: str | None = None
    repo: str | None = None
    remote_url: str | None = None
    discovery: str | None = None


@dataclass(frozen=True)
class SddStore:
    """Resolved SDD storage policy and concrete filesystem locations."""

    storage: SddStorage
    sdd_dir: Path
    repo_root: Path
    provider: str | None = None
    remote_url: str | None = None

    @property
    def is_in_tree(self) -> bool:
        return self.storage == SDD_STORAGE_IN_TREE


_RecordCacheToken = tuple[int, int]
_RecordCacheEntry = tuple[_RecordCacheToken, SddStoreRecord | None]
_record_cache: dict[Path, _RecordCacheEntry] = {}


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

    This intentionally does not read the store record. In-tree storage is the
    only decision that affects the physical directory; local and separate-repo
    storage both live under ``<primary>/.sase/sdd`` in v1.
    """

    configured = get_configured_sdd_storage()
    if configured == SDD_STORAGE_IN_TREE:
        return _sdd_dir_for_storage(workspace_dir, workspace_num, SDD_STORAGE_IN_TREE)
    if configured in (SDD_STORAGE_LOCAL, SDD_STORAGE_SEPARATE_REPO):
        return _sdd_dir_for_storage(workspace_dir, workspace_num, SDD_STORAGE_LOCAL)

    policy = _provider_sdd_storage_policy(workspace_dir)
    if policy == SDD_STORAGE_IN_TREE:
        return _sdd_dir_for_storage(workspace_dir, workspace_num, SDD_STORAGE_IN_TREE)
    return _sdd_dir_for_storage(workspace_dir, workspace_num, SDD_STORAGE_LOCAL)


def resolve_sdd_store(workspace_dir: str | Path, workspace_num: int) -> SddStore:
    """Resolve the effective SDD storage policy and paths."""

    configured = get_configured_sdd_storage()
    primary = Path(
        get_primary_workspace_dir(str(Path(workspace_dir).expanduser()), workspace_num)
    )
    record = read_sdd_store_record(primary)

    storage: SddStorage
    if configured != SDD_STORAGE_AUTO:
        storage = cast(SddStorage, configured)
    elif _is_materialized_record(record):
        storage = SDD_STORAGE_SEPARATE_REPO
    else:
        policy = _provider_sdd_storage_policy(workspace_dir)
        storage = (
            SDD_STORAGE_IN_TREE if policy == SDD_STORAGE_IN_TREE else SDD_STORAGE_LOCAL
        )

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


def read_sdd_store_record(primary_workspace_dir: str | Path) -> SddStoreRecord | None:
    """Read the optional store record with an mtime/size cache."""

    record_path = _sdd_store_record_path(primary_workspace_dir)
    try:
        stat = record_path.stat()
    except FileNotFoundError:
        _record_cache.pop(record_path, None)
        return None

    token = (stat.st_mtime_ns, stat.st_size)
    cached = _record_cache.get(record_path)
    if cached and cached[0] == token:
        return cached[1]

    record = _load_sdd_store_record(record_path)
    _record_cache[record_path] = (token, record)
    return record


def _sdd_store_record_path(primary_workspace_dir: str | Path) -> Path:
    """Return the record path next to the SDD store."""

    return (
        Path(primary_workspace_dir).expanduser() / ".sase" / SDD_STORE_RECORD_FILENAME
    )


def sdd_dir_for_in_tree_bool(
    workspace_dir: str | Path, workspace_num: int, in_tree: bool
) -> Path:
    """Compatibility path helper for the legacy boolean API."""

    storage = SDD_STORAGE_IN_TREE if in_tree else SDD_STORAGE_LOCAL
    return _sdd_dir_for_storage(workspace_dir, workspace_num, storage)


def _sdd_dir_for_storage(
    workspace_dir: str | Path, workspace_num: int, storage: SddStorage
) -> Path:
    workspace = Path(workspace_dir)
    if storage == SDD_STORAGE_IN_TREE:
        return workspace / "sdd"
    primary = get_primary_workspace_dir(str(workspace), workspace_num)
    return Path(primary) / ".sase" / "sdd"


def _provider_sdd_storage_policy(workspace_dir: str | Path) -> SddStorage | None:
    try:
        from sase.vcs_provider import detect_vcs
        from sase.workspace_provider import get_sdd_storage_policy_by_vcs

        vcs_name = detect_vcs(str(Path(workspace_dir).expanduser()))
        if not vcs_name:
            return None
        policy = get_sdd_storage_policy_by_vcs(vcs_name)
    except Exception:
        return None

    if policy in _STORAGE_VALUES:
        return cast(SddStorage, policy)
    return None


def _load_sdd_store_record(record_path: Path) -> SddStoreRecord | None:
    try:
        raw = json.loads(record_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(raw, dict):
        return None

    storage = raw.get("storage")
    if storage not in _STORAGE_VALUES:
        return None

    schema_version = raw.get("schema_version", 1)
    try:
        schema_version_int = int(schema_version)
    except (TypeError, ValueError):
        schema_version_int = 1

    return SddStoreRecord(
        schema_version=schema_version_int,
        storage=cast(SddStorage, storage),
        provider=_optional_str(raw.get("provider")),
        host=_optional_str(raw.get("host")),
        repo=_optional_str(raw.get("repo")),
        remote_url=_optional_str(raw.get("remote_url")),
        discovery=_optional_str(raw.get("discovery")),
    )


def _is_materialized_record(record: SddStoreRecord | None) -> bool:
    if record is None:
        return False
    return (
        record.storage == SDD_STORAGE_SEPARATE_REPO and record.discovery != "not_found"
    )


def _coerce_configured_storage(value: object) -> SddConfiguredStorage:
    if isinstance(value, str) and value in _CONFIGURED_STORAGE_VALUES:
        return cast(SddConfiguredStorage, value)
    return SDD_STORAGE_AUTO


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
