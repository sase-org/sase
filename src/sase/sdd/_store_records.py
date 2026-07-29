"""Persistence helpers for materialized SDD store records."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, cast

from sase._git_remote import (
    SidecarRemotePolicyError,
    enforce_sidecar_remote_policy,
)
from sase.sdd._store_types import (
    _DISCOVERY_VALUES,
    _STORAGE_VALUES,
    SDD_STORAGE_SIDECAR_REPOS,
    SDD_STORAGE_SEPARATE_REPO,
    SDD_STORE_RECORD_FILENAME,
    SddSidecar,
    SddMaterializationError,
    SddStorage,
    SddStoreRecord,
)

_MAX_SUPPORTED_SCHEMA_VERSION = 3

# Read-only compatibility for split-store records written before the sidecar
# terminology shipped. Serialization always uses the canonical spellings.
_LEGACY_STORAGE_VALUE = "companion_repos"
_LEGACY_SIDECARS_KEY = "companions"

_RecordCacheToken = tuple[int, int]
_RecordCacheEntry = tuple[_RecordCacheToken, SddStoreRecord | None]
_record_cache: dict[Path, _RecordCacheEntry] = {}


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
    if not _is_materialized_record(normalized):
        raise ValueError("only positive materialized SDD store records may be written")
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


def _load_sdd_store_record(record_path: Path) -> SddStoreRecord | None:
    try:
        raw = json.loads(record_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise _foreign_record_error(record_path) from exc
    if not isinstance(raw, dict):
        raise _foreign_record_error(record_path)

    storage = _normalize_storage_value(raw.get("storage"))
    if storage not in _STORAGE_VALUES:
        raise _foreign_record_error(record_path)

    schema_version = raw.get("schema_version", 1)
    try:
        schema_version_int = int(schema_version)
    except (TypeError, ValueError) as exc:
        raise _foreign_record_error(record_path) from exc
    if not 1 <= schema_version_int <= _MAX_SUPPORTED_SCHEMA_VERSION:
        raise _foreign_record_error(record_path)

    discovery = raw.get("discovery")
    if discovery is not None and discovery not in _DISCOVERY_VALUES:
        raise _foreign_record_error(record_path)

    provider = _optional_str(raw.get("provider"))
    host = _optional_str(raw.get("host"))
    sidecars = _sidecars_from_raw(raw, provider=provider, host=host)
    beads = sidecars.get("beads")
    if beads is not None and schema_version_int < 3:
        raise _foreign_record_error(record_path)
    if discovery == "not_found":
        return SddStoreRecord(
            schema_version=schema_version_int,
            storage=cast(SddStorage, storage),
            provider=provider,
            host=host,
            repo=_optional_str(raw.get("repo")),
            remote_url=_optional_str(raw.get("remote_url")),
            discovery="not_found",
            probed_at=_optional_str(raw.get("probed_at")),
            sidecars=sidecars,
        )
    if storage == SDD_STORAGE_SIDECAR_REPOS and (
        schema_version_int < 2 or sidecars.get("plans") is None
    ):
        raise _foreign_record_error(record_path)
    normalized_schema_version = (
        3
        if storage == SDD_STORAGE_SIDECAR_REPOS and beads is not None
        else 2
        if storage == SDD_STORAGE_SIDECAR_REPOS
        else schema_version_int
    )
    return SddStoreRecord(
        schema_version=normalized_schema_version,
        storage=cast(SddStorage, storage),
        provider=provider,
        host=host,
        repo=_optional_str(raw.get("repo")),
        remote_url=_optional_str(raw.get("remote_url")),
        discovery=_optional_str(raw.get("discovery")),
        probed_at=_optional_str(raw.get("probed_at")),
        sidecars=sidecars,
    )


def _foreign_record_error(record_path: Path) -> SddMaterializationError:
    return SddMaterializationError(
        f"SDD store record {record_path} uses a format this process does not "
        "understand. Either this long-running sase process predates the record "
        "(retry/relaunch the agent; a fresh process will read it), or this sase "
        "install is older than the record's writer (upgrade sase); refusing to "
        "touch it."
    )


def _is_materialized_record(record: SddStoreRecord | None) -> bool:
    if record is None:
        return False
    if record.discovery == "not_found":
        return False
    if record.storage == SDD_STORAGE_SEPARATE_REPO:
        return True
    return bool(
        record.storage == SDD_STORAGE_SIDECAR_REPOS and record.plans is not None
    )


def _coerce_sdd_store_record(
    record: SddStoreRecord | Mapping[str, Any],
) -> SddStoreRecord:
    if isinstance(record, SddStoreRecord):
        if record.beads is not None and record.schema_version < 3:
            raise ValueError("beads sidecars require schema_version >= 3")
        raw: Mapping[str, Any] = _record_to_json(record)
    else:
        raw = record

    storage = _normalize_storage_value(raw.get("storage"))
    if storage not in {SDD_STORAGE_SEPARATE_REPO, SDD_STORAGE_SIDECAR_REPOS}:
        raise ValueError(
            "SDD store record storage must be 'separate_repo' or 'sidecar_repos'"
        )

    discovery = raw.get("discovery") or "found"
    if discovery not in _DISCOVERY_VALUES:
        raise ValueError("SDD store record discovery must be 'found' or 'not_found'")

    schema_version = raw.get("schema_version", 1)
    try:
        schema_version_int = int(schema_version)
    except (TypeError, ValueError) as exc:
        raise ValueError("SDD store record schema_version must be an integer") from exc
    if not 1 <= schema_version_int <= _MAX_SUPPORTED_SCHEMA_VERSION:
        raise ValueError(
            "SDD store record schema_version is newer than this sase build supports"
        )

    provider = _optional_str(raw.get("provider"))
    host = _optional_str(raw.get("host"))
    sidecars = _sidecars_from_raw(raw, provider=provider, host=host)
    beads = sidecars.get("beads")
    if beads is not None and schema_version_int < 3:
        raise ValueError("beads sidecars require schema_version >= 3")
    if storage == SDD_STORAGE_SIDECAR_REPOS:
        if schema_version_int < 2:
            raise ValueError("sidecar SDD store records require schema_version >= 2")
        if sidecars.get("plans") is None:
            raise ValueError("sidecar SDD store records require a plans mapping")

    normalized_schema_version = (
        3
        if storage == SDD_STORAGE_SIDECAR_REPOS and beads is not None
        else 2
        if storage == SDD_STORAGE_SIDECAR_REPOS
        else schema_version_int
    )
    return SddStoreRecord(
        schema_version=normalized_schema_version,
        storage=cast(SddStorage, storage),
        provider=provider,
        host=host,
        repo=_optional_str(raw.get("repo")),
        remote_url=_optional_str(raw.get("remote_url")),
        discovery=cast(str, discovery),
        probed_at=_optional_str(raw.get("probed_at")) or _utc_now_iso(),
        sidecars=sidecars,
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
    if record.storage == SDD_STORAGE_SIDECAR_REPOS:
        sidecars = {
            role: _sidecar_to_json(sidecar) for role, sidecar in record.sidecars.items()
        }
        # Extra document roles are additive keys that older SASE releases
        # safely ignore, so only the split-beads role requires schema v3.
        data["schema_version"] = 3 if record.beads is not None else 2
        data["sidecars"] = sidecars
    return data


def _sidecars_from_raw(
    raw: Mapping[str, Any],
    *,
    provider: str | None,
    host: str | None,
) -> dict[str, SddSidecar]:
    sidecars = raw.get("sidecars")
    if not isinstance(sidecars, Mapping) and "sidecars" not in raw:
        sidecars = raw.get(_LEGACY_SIDECARS_KEY)
    if not isinstance(sidecars, Mapping):
        return {}
    result: dict[str, SddSidecar] = {}
    for role, value in sidecars.items():
        if not isinstance(role, str) or not role:
            continue
        sidecar = _coerce_sidecar(
            value,
            provider=provider,
            host=host,
            kind=role,
        )
        if sidecar is not None:
            result[role] = sidecar
    return result


def _coerce_sidecar(
    value: object,
    *,
    provider: str | None,
    host: str | None,
    kind: str,
) -> SddSidecar | None:
    if not isinstance(value, Mapping):
        return None
    repo = _optional_str(value.get("repo"))
    remote_url = _optional_str(value.get("remote_url"))
    if repo is None or remote_url is None:
        return None
    try:
        approved_remote = enforce_sidecar_remote_policy(
            remote_url,
            provider=provider,
            host=host,
            repo=repo,
        )
    except SidecarRemotePolicyError as exc:
        raise SddMaterializationError(
            f"Invalid {kind} SDD sidecar metadata: {exc}"
        ) from exc
    return SddSidecar(repo=repo, remote_url=approved_remote)


def _sidecar_to_json(sidecar: SddSidecar | None) -> dict[str, str]:
    if sidecar is None:
        return {}
    return {"repo": sidecar.repo, "remote_url": sidecar.remote_url}


def _normalize_storage_value(value: object) -> object:
    if value == _LEGACY_STORAGE_VALUE:
        return SDD_STORAGE_SIDECAR_REPOS
    return value


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


record_cache = _record_cache


def is_materialized_record(record: SddStoreRecord | None) -> bool:
    return _is_materialized_record(record)


def optional_str(value: object) -> str | None:
    return _optional_str(value)


def record_to_json(record: SddStoreRecord) -> dict[str, Any]:
    return _record_to_json(record)


def sdd_store_record_path(primary_workspace_dir: str | Path) -> Path:
    return _sdd_store_record_path(primary_workspace_dir)
