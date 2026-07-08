"""SDD storage policy resolution.

This module owns the Python-side policy that maps config, provider metadata,
and an optional materialized-store record to concrete SDD paths. The Rust core
continues to receive fully resolved paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
import subprocess
from typing import Any, Literal, cast
from collections.abc import Mapping

from sase.config import load_merged_config
from sase.sdd._paths import get_primary_workspace_dir

_logger = logging.getLogger(__name__)

SddStorage = Literal["in_tree", "local", "separate_repo"]
SddConfiguredStorage = Literal["auto", "in_tree", "local", "separate_repo"]
SddPushAfterCommit = bool | Literal["async"]

SDD_STORAGE_AUTO: SddConfiguredStorage = "auto"
SDD_STORAGE_IN_TREE: SddStorage = "in_tree"
SDD_STORAGE_LOCAL: SddStorage = "local"
SDD_STORAGE_SEPARATE_REPO: SddStorage = "separate_repo"

SDD_STORE_RECORD_FILENAME = "sdd-store.json"

_CONFIGURED_STORAGE_VALUES: frozenset[str] = frozenset(
    {"auto", "in_tree", "local", "separate_repo"}
)
_STORAGE_VALUES: frozenset[str] = frozenset({"in_tree", "local", "separate_repo"})
_DISCOVERY_VALUES: frozenset[str] = frozenset({"found", "not_found"})


class SddMaterializationError(RuntimeError):
    """Raised when explicit separate-repo SDD storage cannot be materialized."""


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
    probed_at: str | None = None


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

    store = resolve_sdd_store(workspace, workspace_num)
    _refresh_materialized_store(store.sdd_dir)
    _ensure_materialized_store_initialized(store)
    return resolve_sdd_store(workspace, workspace_num)


def ensure_workspace_sdd_link(workspace_dir: str | Path, workspace_num: int) -> None:
    """Best-effort workspace-local view of a non-in-tree SDD store.

    Managed workspaces validate relative prompt references from their own CWD,
    while local/separate SDD stores live under the primary checkout.  Link the
    workspace's ``.sase/sdd`` to that primary store so relative references such
    as ``@.sase/sdd/tales/...`` resolve before prompt validation runs.
    """

    workspace = Path(workspace_dir).expanduser()
    try:
        store = resolve_sdd_store(workspace, workspace_num)
        if store.is_in_tree:
            return

        workspace_sdd = workspace / ".sase" / "sdd"
        if _paths_same_file(workspace_sdd, store.sdd_dir):
            _refresh_materialized_store(store.sdd_dir)
            return

        if not store.sdd_dir.exists():
            try:
                store = materialize_sdd_store(workspace, workspace_num)
            except Exception:
                _logger.warning(
                    "Failed to materialize SDD store for workspace %s",
                    workspace,
                    exc_info=True,
                )
                return
            if not store.sdd_dir.exists():
                _logger.warning(
                    "SDD store directory does not exist for workspace %s: %s",
                    workspace,
                    store.sdd_dir,
                )
                return

        _refresh_materialized_store(store.sdd_dir)

        if _paths_same_file(workspace_sdd, store.sdd_dir):
            return

        workspace_sdd.parent.mkdir(parents=True, exist_ok=True)
        if workspace_sdd.is_symlink():
            workspace_sdd.unlink()
        elif os.path.lexists(workspace_sdd):
            _logger.warning(
                "Refusing to overwrite real SDD directory at %s",
                workspace_sdd,
            )
            return

        workspace_sdd.symlink_to(store.sdd_dir, target_is_directory=True)
    except Exception:
        _logger.warning(
            "Failed to ensure workspace SDD link for workspace %s",
            workspace,
            exc_info=True,
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


def write_sdd_store_record(
    primary_workspace_dir: str | Path,
    record: SddStoreRecord | Mapping[str, Any],
) -> SddStoreRecord:
    """Validate and atomically write the materialized-store record."""

    return _write_sdd_store_record(primary_workspace_dir, record)


def normalize_sdd_store_record(
    record: SddStoreRecord | Mapping[str, Any],
) -> SddStoreRecord:
    """Validate and normalize a materialized-store record without writing it."""

    return _coerce_sdd_store_record(record)


def delete_sdd_store_record(primary_workspace_dir: str | Path) -> bool:
    """Delete the optional store record, returning true when it existed."""

    record_path = _sdd_store_record_path(primary_workspace_dir)
    try:
        record_path.unlink()
    except FileNotFoundError:
        _record_cache.pop(record_path, None)
        return False
    _record_cache.pop(record_path, None)
    return True


def _write_sdd_store_record(
    primary_workspace_dir: str | Path,
    record: SddStoreRecord | Mapping[str, Any],
) -> SddStoreRecord:
    """Validate and atomically write the materialized-store record."""

    normalized = _coerce_sdd_store_record(record)
    record_path = _sdd_store_record_path(primary_workspace_dir)
    record_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = record_path.with_name(f".{record_path.name}.tmp")
    temp_path.write_text(
        json.dumps(_record_to_json(normalized), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(record_path)
    _record_cache.pop(record_path, None)
    return normalized


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


def _paths_same_file(left: Path, right: Path) -> bool:
    if left.expanduser().absolute() == right.expanduser().absolute():
        return True
    try:
        return left.samefile(right)
    except OSError:
        return False


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
) -> Mapping[str, Any] | None:
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
        probed_at=_optional_str(raw.get("probed_at")),
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


def _coerce_sdd_store_record(
    record: SddStoreRecord | Mapping[str, Any],
) -> SddStoreRecord:
    if isinstance(record, SddStoreRecord):
        raw: Mapping[str, Any] = _record_to_json(record)
    else:
        raw = record

    storage = raw.get("storage")
    if storage != SDD_STORAGE_SEPARATE_REPO:
        raise ValueError("SDD store record storage must be 'separate_repo'")

    discovery = raw.get("discovery") or "found"
    if discovery not in _DISCOVERY_VALUES:
        raise ValueError("SDD store record discovery must be 'found' or 'not_found'")

    schema_version = raw.get("schema_version", 1)
    try:
        schema_version_int = int(schema_version)
    except (TypeError, ValueError) as exc:
        raise ValueError("SDD store record schema_version must be an integer") from exc

    return SddStoreRecord(
        schema_version=schema_version_int,
        storage=SDD_STORAGE_SEPARATE_REPO,
        provider=_optional_str(raw.get("provider")),
        host=_optional_str(raw.get("host")),
        repo=_optional_str(raw.get("repo")),
        remote_url=_optional_str(raw.get("remote_url")),
        discovery=cast(str, discovery),
        probed_at=_optional_str(raw.get("probed_at")) or _utc_now_iso(),
    )


def _record_to_json(record: SddStoreRecord) -> dict[str, Any]:
    data: dict[str, Any] = {
        "schema_version": record.schema_version,
        "storage": record.storage,
    }
    for key in ("provider", "host", "repo", "remote_url", "discovery", "probed_at"):
        value = getattr(record, key)
        if value is not None:
            data[key] = value
    return data


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _store_not_materialized_message(record: SddStoreRecord | None) -> str:
    repo = record.repo if record is not None and record.repo else None
    target = f"'{repo}'" if repo else "the expected SDD companion repository"
    return (
        f"SDD storage is configured as separate_repo, but {target} is not "
        "materialized. Run `sase sdd migrate` to create or connect the "
        "companion repository before using separate_repo storage."
    )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None
