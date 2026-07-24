"""Immutable foreign-hood cache objects and durable import receipts."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
import time

from sase.agents_sync.io import (
    AgentsSyncFormatError,
    atomic_write_json,
    canonical_json_bytes,
    read_bundle,
    read_manifest,
    validate_machine,
)
from sase.agents_sync.models import (
    CACHE_SCHEMA_VERSION,
    RECEIPT_SCHEMA_VERSION,
    AgentHoodImportReceipt,
    AgentsManifest,
    CapturedIncomingHood,
    ManifestEntry,
    SourceOwnerKind,
)
from sase.agents_sync.v2_import_package import (
    ValidatedV2HoodPackage,
    validate_v2_hood_package,
)
from sase.agents_sync.v2_io import (
    MAX_JSON_BYTES,
    MAX_PAYLOAD_BYTES,
    MAX_TEXT_BYTES,
    owner_manifest_from_bytes,
    owner_manifest_path,
    validate_component,
    validate_relative_path,
)
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    agent_local_hood,
    validate_agent_owner,
)
from sase.core.paths import sase_home

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_SHA_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_DISMISSED_PREFIX_RE = re.compile(r"^\d{6}\.(.+)$")
_RECEIPTS_DOCUMENT_VERSION = 1
_RECENT_SUPERSEDED_PER_HOOD = 2
_CAPTURED_KEYS = {
    "schema_version",
    "project_key",
    "project",
    "fetched_ref",
    "fetched_sha",
    "cache_id",
    "format_version",
    "source_owner_kind",
    "source_username",
    "source_machine",
    "top_hood",
    "hood_digest",
    "run_count",
    "family_count",
    "cache_created_at",
}
_RECEIPT_KEYS = {
    "schema_version",
    "project_key",
    "project",
    "source_owner_kind",
    "source_username",
    "source_machine",
    "top_hood",
    "hood_digest",
    "cache_id",
    "fetched_ref",
    "fetched_sha",
    "cache_created_at",
    "applied_at",
}


@dataclass(frozen=True, slots=True)
class _LoadedCachedHood:
    """A strictly revalidated cached payload ready for its existing importer."""

    item: CapturedIncomingHood
    payload_root: Path
    v2_package: ValidatedV2HoodPackage | None = None
    legacy_manifest: AgentsManifest | None = None


def _agents_sync_state_root() -> Path:
    return sase_home() / "agents_sync"


def _cache_id_for(
    *,
    project_key: str,
    project: str,
    format_version: int,
    source_owner_kind: SourceOwnerKind,
    source_username: str | None,
    source_machine: str,
    top_hood: str,
    hood_digest: str,
) -> str:
    """Return the stable content address for one semantic source hood."""

    identity = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "project_key": project_key,
        "project": project,
        "format_version": format_version,
        "source_owner_kind": source_owner_kind,
        "source_username": source_username,
        "source_machine": source_machine,
        "top_hood": top_hood,
        "hood_digest": hood_digest,
    }
    return hashlib.sha256(canonical_json_bytes(identity)).hexdigest()


def captured_incoming_hood_from_json(value: object) -> CapturedIncomingHood:
    row = _exact_object(value, "captured incoming hood", _CAPTURED_KEYS)
    if row["schema_version"] != CACHE_SCHEMA_VERSION:
        raise AgentsSyncFormatError("unsupported captured incoming hood schema")
    kind, username = _source_owner(row)
    format_version = _nonnegative_int(row["format_version"], "format_version")
    if format_version not in {1, 2}:
        raise AgentsSyncFormatError("format_version must be 1 or 2")
    item = CapturedIncomingHood(
        project_key=_component(row["project_key"], "project key"),
        project=_project_name(row["project"]),
        fetched_ref=_fetched_ref(row["fetched_ref"]),
        fetched_sha=_sha(row["fetched_sha"], "fetched SHA"),
        cache_id=_digest(row["cache_id"], "cache ID"),
        format_version=format_version,
        source_owner_kind=kind,
        source_username=username,
        source_machine=_component(row["source_machine"], "source machine"),
        top_hood=_component(row["top_hood"], "top hood"),
        hood_digest=_digest(row["hood_digest"], "hood digest"),
        run_count=_nonnegative_int(row["run_count"], "run_count"),
        family_count=_nonnegative_int(row["family_count"], "family_count"),
        cache_created_at=_finite_time(row["cache_created_at"], "cache creation time"),
    )
    _validate_source_hood(
        item.source_owner_kind,
        item.source_username,
        item.source_machine,
        item.top_hood,
    )
    if item.cache_id != _item_cache_id(item):
        raise AgentsSyncFormatError("captured incoming hood cache ID is inconsistent")
    return item


def _import_receipt_from_json(value: object) -> AgentHoodImportReceipt:
    row = _exact_object(value, "agent hood import receipt", _RECEIPT_KEYS)
    if row["schema_version"] != RECEIPT_SCHEMA_VERSION:
        raise AgentsSyncFormatError("unsupported agent hood receipt schema")
    kind, username = _source_owner(row)
    receipt = AgentHoodImportReceipt(
        project_key=_component(row["project_key"], "project key"),
        project=_project_name(row["project"]),
        source_owner_kind=kind,
        source_username=username,
        source_machine=_component(row["source_machine"], "source machine"),
        top_hood=_component(row["top_hood"], "top hood"),
        hood_digest=_digest(row["hood_digest"], "hood digest"),
        cache_id=_digest(row["cache_id"], "cache ID"),
        fetched_ref=_fetched_ref(row["fetched_ref"]),
        fetched_sha=_sha(row["fetched_sha"], "fetched SHA"),
        cache_created_at=_finite_time(row["cache_created_at"], "cache creation time"),
        applied_at=_finite_time(row["applied_at"], "receipt application time"),
    )
    _validate_source_hood(
        receipt.source_owner_kind,
        receipt.source_username,
        receipt.source_machine,
        receipt.top_hood,
    )
    expected = _cache_id_for(
        project_key=receipt.project_key,
        project=receipt.project,
        format_version=(1 if receipt.source_owner_kind == "username_unknown_v1" else 2),
        source_owner_kind=receipt.source_owner_kind,
        source_username=receipt.source_username,
        source_machine=receipt.source_machine,
        top_hood=receipt.top_hood,
        hood_digest=receipt.hood_digest,
    )
    if receipt.cache_id != expected:
        raise AgentsSyncFormatError("agent hood receipt cache ID is inconsistent")
    return receipt


def read_project_receipts(project_key: str) -> tuple[AgentHoodImportReceipt, ...]:
    path = _receipts_path(project_key)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return ()
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentsSyncFormatError(f"could not read import receipts: {exc}") from exc
    row = _exact_object(
        raw,
        "agent hood receipts document",
        {"schema_version", "project_key", "project", "receipts"},
    )
    if row["schema_version"] != _RECEIPTS_DOCUMENT_VERSION:
        raise AgentsSyncFormatError("unsupported import receipts document schema")
    if _component(row["project_key"], "project key") != project_key:
        raise AgentsSyncFormatError("import receipts project key does not match path")
    project = _project_name(row["project"])
    raw_receipts = row["receipts"]
    if not isinstance(raw_receipts, list):
        raise AgentsSyncFormatError("import receipts must be a list")
    receipts = tuple(_import_receipt_from_json(item) for item in raw_receipts)
    if any(
        receipt.project_key != project_key or receipt.project != project
        for receipt in receipts
    ):
        raise AgentsSyncFormatError("import receipt project identity disagrees")
    keys = [receipt.source_hood_key for receipt in receipts]
    if len(keys) != len(set(keys)):
        raise AgentsSyncFormatError("import receipts repeat a source hood")
    return receipts


def write_import_receipt(receipt: AgentHoodImportReceipt) -> None:
    """Atomically advance exactly one project's source-hood receipt."""

    decoded = _import_receipt_from_json(receipt.to_json_dict())
    existing = read_project_receipts(decoded.project_key)
    if any(item.project != decoded.project for item in existing):
        raise AgentsSyncFormatError(
            "existing import receipt project name does not match target"
        )
    receipts = {item.source_hood_key: item for item in existing}
    receipts[decoded.source_hood_key] = decoded
    atomic_write_json(
        _receipts_path(decoded.project_key),
        {
            "schema_version": _RECEIPTS_DOCUMENT_VERSION,
            "project_key": decoded.project_key,
            "project": decoded.project,
            "receipts": [
                item.to_json_dict()
                for item in sorted(
                    receipts.values(),
                    key=lambda row: (
                        row.source_owner_kind,
                        row.source_username or "",
                        row.source_machine,
                        row.top_hood,
                    ),
                )
            ],
        },
    )


def receipt_for_item(
    item: CapturedIncomingHood,
    *,
    applied_at: float | None = None,
) -> AgentHoodImportReceipt:
    return AgentHoodImportReceipt(
        project_key=item.project_key,
        project=item.project,
        source_owner_kind=item.source_owner_kind,
        source_username=item.source_username,
        source_machine=item.source_machine,
        top_hood=item.top_hood,
        hood_digest=item.hood_digest,
        cache_id=item.cache_id,
        fetched_ref=item.fetched_ref,
        fetched_sha=item.fetched_sha,
        cache_created_at=item.cache_created_at,
        applied_at=time.time() if applied_at is None else applied_at,
    )


def cached_item_is_available(item: CapturedIncomingHood) -> bool:
    """Perform the metadata-only availability check allowed on short status."""

    try:
        stored = _read_cache_metadata(_cache_object_path(item.cache_id))
    except (AgentsSyncFormatError, OSError):
        return False
    return stored == item


def publish_cache_object(
    item: CapturedIncomingHood,
    payload: Mapping[str, bytes],
) -> CapturedIncomingHood:
    """Validate and atomically publish one immutable content-addressed object."""

    decoded = captured_incoming_hood_from_json(item.to_json_dict())
    objects = _cache_objects_dir()
    staging = _cache_staging_dir()
    objects.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = _cache_object_path(decoded.cache_id)
    if destination.exists() or destination.is_symlink():
        stored = _read_cache_metadata(destination)
        if stored.cache_id != decoded.cache_id or not _same_cached_content(
            stored, decoded
        ):
            raise AgentsSyncFormatError(
                "existing cache object does not match its content address"
            )
        load_validated_cache_item(stored)
        return stored

    stage = Path(tempfile.mkdtemp(prefix=".incoming-", dir=staging))
    try:
        payload_root = stage / "payload"
        payload_root.mkdir(mode=0o700)
        for relative, content in sorted(payload.items()):
            validate_relative_path(relative)
            destination_path = payload_root / relative
            if not destination_path.resolve(strict=False).is_relative_to(
                payload_root.resolve(strict=False)
            ):
                raise AgentsSyncFormatError("cache payload path escapes staging")
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            destination_path.write_bytes(bytes(content))
        atomic_write_json(stage / "metadata.json", decoded.to_json_dict())
        load_validated_cache_item(decoded, object_path=stage)
        try:
            os.rename(stage, destination)
        except FileExistsError:
            stored = _read_cache_metadata(destination)
            if not _same_cached_content(stored, decoded):
                raise AgentsSyncFormatError(
                    "raced cache object does not match its content address"
                ) from None
            load_validated_cache_item(stored)
            return stored
        return decoded
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def validate_unpublished_cache_payload(
    item: CapturedIncomingHood,
    payload: Mapping[str, bytes],
) -> None:
    """Validate exact-current observations without publishing cache objects."""

    staging = _cache_staging_dir()
    staging.mkdir(parents=True, exist_ok=True, mode=0o700)
    stage = Path(tempfile.mkdtemp(prefix=".validate-", dir=staging))
    try:
        payload_root = stage / "payload"
        payload_root.mkdir(mode=0o700)
        for relative, content in sorted(payload.items()):
            validate_relative_path(relative)
            destination = payload_root / relative
            if not destination.resolve(strict=False).is_relative_to(
                payload_root.resolve(strict=False)
            ):
                raise AgentsSyncFormatError("cache payload path escapes staging")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(bytes(content))
        atomic_write_json(stage / "metadata.json", item.to_json_dict())
        load_validated_cache_item(item, object_path=stage)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def load_validated_cache_item(
    item: CapturedIncomingHood,
    *,
    object_path: Path | None = None,
) -> _LoadedCachedHood:
    """Strictly revalidate cache metadata, identity, bytes, and whole package."""

    decoded = captured_incoming_hood_from_json(item.to_json_dict())
    root = object_path or _cache_object_path(decoded.cache_id)
    stored = _read_cache_metadata(
        root,
        require_addressed_name=object_path is None,
    )
    if stored != decoded:
        raise AgentsSyncFormatError("cache metadata does not match captured item")
    payload_root = root / "payload"
    if (
        root.is_symlink()
        or payload_root.is_symlink()
        or not root.is_dir()
        or not payload_root.is_dir()
    ):
        raise AgentsSyncFormatError("cache object is missing or uses a symlink")
    actual_files = _cache_payload_files(payload_root)
    if decoded.format_version == 2:
        owner = AgentOwnerIdentity(
            decoded.source_username or "",
            decoded.source_machine,
        )
        manifest_relative = owner_manifest_path(owner)
        manifest = owner_manifest_from_bytes(
            _read_cache_file(payload_root, manifest_relative, MAX_JSON_BYTES)
        )
        expected_project = V2ProjectIdentity(decoded.project_key, decoded.project)
        if manifest.owner != owner or manifest.project != expected_project:
            raise AgentsSyncFormatError("cached v2 owner manifest identity disagrees")
        if len(manifest.hoods) != 1 or manifest.hoods[0][0] != decoded.top_hood:
            raise AgentsSyncFormatError("cached v2 manifest must contain one hood")
        hood, v2_entry = manifest.hoods[0]
        expected_files = {manifest_relative, *v2_entry.files}
        if actual_files != expected_files:
            raise AgentsSyncFormatError("cached v2 payload file set disagrees")
        package = validate_v2_hood_package(
            payload_root,
            manifest,
            hood,
            v2_entry,
        )
        if (
            v2_entry.digest != decoded.hood_digest
            or v2_entry.run_count != decoded.run_count
            or v2_entry.family_count != decoded.family_count
        ):
            raise AgentsSyncFormatError("cached v2 counts or digest disagree")
        return _LoadedCachedHood(decoded, payload_root, v2_package=package)

    if decoded.source_username is not None:
        raise AgentsSyncFormatError("legacy cache item cannot carry a username")
    manifest_path = payload_root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise AgentsSyncFormatError("cached legacy manifest is missing")
    legacy_manifest = read_manifest(manifest_path)
    expected_files = {"manifest.json"}
    total_bytes = manifest_path.stat().st_size
    for legacy_entry in legacy_manifest.entries:
        if (
            legacy_entry.machine != decoded.source_machine
            or _legacy_entry_top_hood(legacy_entry) != decoded.top_hood
        ):
            raise AgentsSyncFormatError("cached legacy source identity disagrees")
        expected_files.update(
            {
                f"agents/{legacy_entry.name}/meta.json",
                f"agents/{legacy_entry.name}/commits.json",
                f"agents/{legacy_entry.name}/chat.md",
            }
        )
        for relative, maximum in (
            (f"agents/{legacy_entry.name}/meta.json", MAX_JSON_BYTES),
            (f"agents/{legacy_entry.name}/commits.json", MAX_JSON_BYTES),
            (f"agents/{legacy_entry.name}/chat.md", MAX_TEXT_BYTES),
        ):
            total_bytes += len(_read_cache_file(payload_root, relative, maximum))
            if total_bytes > MAX_PAYLOAD_BYTES:
                raise AgentsSyncFormatError(
                    "cached legacy payload exceeds the byte limit"
                )
        read_bundle(payload_root, legacy_entry)
    if actual_files != expected_files:
        raise AgentsSyncFormatError("cached legacy payload file set disagrees")
    if (
        legacy_group_digest(legacy_manifest) != decoded.hood_digest
        or len(legacy_manifest.entries) != decoded.run_count
        or legacy_family_count(legacy_manifest) != decoded.family_count
    ):
        raise AgentsSyncFormatError("cached legacy counts or digest disagree")
    return _LoadedCachedHood(
        decoded,
        payload_root,
        legacy_manifest=legacy_manifest,
    )


def reconcile_pending_items(
    items: Sequence[CapturedIncomingHood],
    *,
    project_key: str,
) -> tuple[tuple[CapturedIncomingHood, ...], tuple[str, ...]]:
    """Reconcile persisted items using metadata and receipts only."""

    diagnostics: list[str] = []
    try:
        receipts = {
            receipt.source_hood_key: receipt
            for receipt in read_project_receipts(project_key)
        }
    except AgentsSyncFormatError as exc:
        receipts = {}
        diagnostics.append(f"quarantined import receipts: {exc}")
    pending: list[CapturedIncomingHood] = []
    for item in items:
        if item.project_key != project_key:
            diagnostics.append(
                f"{item.cache_id}: cached project key does not match status"
            )
            continue
        if receipt_matches(receipts.get(item.source_hood_key), item):
            continue
        if not cached_item_is_available(item):
            diagnostics.append(
                f"{item.cache_id}: pending cache object is missing or invalid"
            )
            continue
        pending.append(item)
    return tuple(pending), tuple(diagnostics)


def legacy_manifest_groups(manifest: AgentsManifest) -> tuple[AgentsManifest, ...]:
    grouped: dict[tuple[str, str], list[ManifestEntry]] = defaultdict(list)
    for entry in manifest.entries:
        grouped[(entry.machine, _legacy_entry_top_hood(entry))].append(entry)
    return tuple(
        AgentsManifest(tuple(sorted(entries, key=lambda row: row.name)))
        for _key, entries in sorted(grouped.items())
    )


def _legacy_entry_top_hood(entry: ManifestEntry) -> str:
    core = entry.name
    dismissed = _DISMISSED_PREFIX_RE.fullmatch(core)
    if dismissed is not None:
        core = dismissed.group(1)
    prefix = f"{entry.machine}."
    if not core.startswith(prefix) or core == prefix:
        raise AgentsSyncFormatError("legacy entry is not machine qualified")
    hood = agent_local_hood(core[len(prefix) :])
    return validate_component(hood, label="legacy top hood")


def legacy_group_digest(manifest: AgentsManifest) -> str:
    return hashlib.sha256(canonical_json_bytes(manifest.to_json_dict())).hexdigest()


def legacy_family_count(manifest: AgentsManifest) -> int:
    return int(any("--" in _legacy_local_name(entry) for entry in manifest.entries))


def prune_project_cache(
    project_key: str,
    *,
    pending_items: Sequence[CapturedIncomingHood],
    receipts: Sequence[AgentHoodImportReceipt],
    keep_recent: int = _RECENT_SUPERSEDED_PER_HOOD,
) -> None:
    """Bound superseded objects while preserving pending and receipt evidence."""

    objects = _cache_objects_dir()
    if not objects.is_dir() or objects.is_symlink():
        return
    protected = {item.cache_id for item in pending_items}
    protected.update(receipt.cache_id for receipt in receipts)
    by_hood: dict[
        tuple[str, str | None, str, str],
        list[CapturedIncomingHood],
    ] = defaultdict(list)
    for path in objects.iterdir():
        if (
            path.is_symlink()
            or not path.is_dir()
            or _DIGEST_RE.fullmatch(path.name) is None
        ):
            continue
        try:
            item = _read_cache_metadata(path)
        except AgentsSyncFormatError:
            continue
        if item.project_key == project_key:
            by_hood[item.source_hood_key].append(item)
    for rows in by_hood.values():
        superseded = [
            item
            for item in sorted(
                rows,
                key=lambda row: (row.cache_created_at, row.cache_id),
                reverse=True,
            )
            if item.cache_id not in protected
        ]
        for item in superseded[max(keep_recent, 0) :]:
            path = _cache_object_path(item.cache_id)
            if path.parent == objects and path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)


def find_cached_evidence(
    project_key: str,
    key: tuple[str, str | None, str, str],
    digest: str,
) -> CapturedIncomingHood | None:
    objects = _cache_objects_dir()
    if not objects.is_dir() or objects.is_symlink():
        return None
    matches: list[CapturedIncomingHood] = []
    for path in objects.iterdir():
        if path.is_symlink() or not path.is_dir():
            continue
        try:
            item = _read_cache_metadata(path)
        except AgentsSyncFormatError:
            continue
        if (
            item.project_key == project_key
            and item.source_hood_key == key
            and item.hood_digest == digest
        ):
            matches.append(item)
    return max(matches, key=lambda row: row.cache_created_at, default=None)


def _read_cache_metadata(
    root: Path,
    *,
    require_addressed_name: bool = True,
) -> CapturedIncomingHood:
    objects = _cache_objects_dir().resolve(strict=False)
    staging = _cache_staging_dir().resolve(strict=False)
    resolved = root.resolve(strict=False)
    if root.is_symlink() or not (
        resolved.is_relative_to(objects) or resolved.is_relative_to(staging)
    ):
        raise AgentsSyncFormatError("cache object path escapes the cache root")
    metadata = root / "metadata.json"
    if metadata.is_symlink() or not metadata.is_file():
        raise AgentsSyncFormatError("cache metadata is missing or uses a symlink")
    try:
        raw = json.loads(metadata.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentsSyncFormatError(f"could not read cache metadata: {exc}") from exc
    item = captured_incoming_hood_from_json(raw)
    if require_addressed_name and root.name != item.cache_id:
        raise AgentsSyncFormatError("cache directory name does not match metadata")
    return item


def _cache_payload_files(payload_root: Path) -> set[str]:
    root = payload_root.resolve(strict=False)
    files: set[str] = set()
    for path in payload_root.rglob("*"):
        if path.is_symlink():
            raise AgentsSyncFormatError("cache payload contains a symlink")
        if path.is_dir():
            continue
        if not path.is_file() or not path.resolve(strict=False).is_relative_to(root):
            raise AgentsSyncFormatError("cache payload contains an unsafe file")
        relative = path.relative_to(payload_root).as_posix()
        validate_relative_path(relative)
        files.add(relative)
    return files


def _read_cache_file(root: Path, relative: str, maximum: int) -> bytes:
    validate_relative_path(relative)
    path = root / relative
    if path.is_symlink() or not path.is_file():
        raise AgentsSyncFormatError(f"cached file {relative!r} is missing")
    try:
        if path.stat().st_size > maximum:
            raise AgentsSyncFormatError(
                f"cached file {relative!r} exceeds the byte limit"
            )
        return path.read_bytes()
    except OSError as exc:
        raise AgentsSyncFormatError(
            f"could not read cached file {relative!r}: {exc}"
        ) from exc


def _receipts_path(project_key: str) -> Path:
    safe = _component(project_key, "project key")
    return _agents_sync_state_root() / "receipts" / f"{safe}.json"


def _cache_objects_dir() -> Path:
    return _agents_sync_state_root() / "cache" / "objects"


def _cache_staging_dir() -> Path:
    return _agents_sync_state_root() / "cache" / "staging"


def _cache_object_path(cache_id: str) -> Path:
    safe = _digest(cache_id, "cache ID")
    return _cache_objects_dir() / safe


def legacy_group_machine_hood(manifest: AgentsManifest) -> tuple[str, str]:
    if not manifest.entries:
        raise AgentsSyncFormatError("legacy cache group cannot be empty")
    machines = {entry.machine for entry in manifest.entries}
    hoods = {_legacy_entry_top_hood(entry) for entry in manifest.entries}
    if len(machines) != 1 or len(hoods) != 1:
        raise AgentsSyncFormatError("legacy cache group spans source hoods")
    return next(iter(machines)), next(iter(hoods))


def _legacy_local_name(entry: ManifestEntry) -> str:
    core = entry.name
    dismissed = _DISMISSED_PREFIX_RE.fullmatch(core)
    if dismissed is not None:
        core = dismissed.group(1)
    return core.removeprefix(f"{entry.machine}.")


def with_cache_id(item: CapturedIncomingHood) -> CapturedIncomingHood:
    return CapturedIncomingHood(
        project_key=item.project_key,
        project=item.project,
        fetched_ref=item.fetched_ref,
        fetched_sha=item.fetched_sha,
        cache_id=_item_cache_id(item),
        format_version=item.format_version,
        source_owner_kind=item.source_owner_kind,
        source_username=item.source_username,
        source_machine=item.source_machine,
        top_hood=item.top_hood,
        hood_digest=item.hood_digest,
        run_count=item.run_count,
        family_count=item.family_count,
        cache_created_at=item.cache_created_at,
    )


def _item_cache_id(item: CapturedIncomingHood) -> str:
    return _cache_id_for(
        project_key=item.project_key,
        project=item.project,
        format_version=item.format_version,
        source_owner_kind=item.source_owner_kind,
        source_username=item.source_username,
        source_machine=item.source_machine,
        top_hood=item.top_hood,
        hood_digest=item.hood_digest,
    )


def _same_cached_content(
    left: CapturedIncomingHood,
    right: CapturedIncomingHood,
) -> bool:
    return (
        left.project_key,
        left.project,
        left.cache_id,
        left.format_version,
        left.source_owner_kind,
        left.source_username,
        left.source_machine,
        left.top_hood,
        left.hood_digest,
        left.run_count,
        left.family_count,
    ) == (
        right.project_key,
        right.project,
        right.cache_id,
        right.format_version,
        right.source_owner_kind,
        right.source_username,
        right.source_machine,
        right.top_hood,
        right.hood_digest,
        right.run_count,
        right.family_count,
    )


def receipt_matches(
    receipt: AgentHoodImportReceipt | None,
    item: CapturedIncomingHood,
) -> bool:
    return receipt is not None and receipt.hood_digest == item.hood_digest


def _source_owner(
    row: Mapping[str, object],
) -> tuple[SourceOwnerKind, str | None]:
    kind = row["source_owner_kind"]
    username = row["source_username"]
    if kind == "exact":
        return "exact", _component(username, "source username")
    if kind == "username_unknown_v1" and username is None:
        return "username_unknown_v1", None
    raise AgentsSyncFormatError("source owner kind and username are inconsistent")


def _validate_source_hood(
    kind: SourceOwnerKind,
    username: str | None,
    machine: str,
    hood: str,
) -> None:
    try:
        if kind == "exact":
            assert username is not None
            validate_agent_owner(AgentOwnerIdentity(username, machine))
        else:
            validate_machine(machine)
        if agent_local_hood(hood) != hood:
            raise AgentsSyncFormatError("top hood is not a semantic hood root")
    except (ValueError, RuntimeError) as exc:
        raise AgentsSyncFormatError(f"invalid source hood identity: {exc}") from exc


def _exact_object(
    value: object,
    label: str,
    keys: set[str],
) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise AgentsSyncFormatError(f"{label} must be a JSON object")
    if set(value) != keys:
        raise AgentsSyncFormatError(f"{label} has an invalid shape")
    return value


def _component(value: object, label: str) -> str:
    return validate_component(value, label=label)


def _project_name(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or len(value.encode("utf-8")) > 1024
    ):
        raise AgentsSyncFormatError("project name is invalid")
    return value


def _fetched_ref(value: object) -> str:
    if value == "HEAD":
        return "HEAD"
    if (
        not isinstance(value, str)
        or not value.startswith("refs/remotes/")
        or len(value.encode("utf-8")) > 1024
        or any(ord(char) <= 32 or char in "~^:?*[\\" for char in value)
        or ".." in value
        or value.endswith((".", "/"))
    ):
        raise AgentsSyncFormatError(f"fetched ref is invalid: {value!r}")
    return value


def _sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA_RE.fullmatch(value) is None:
        raise AgentsSyncFormatError(f"{label} is invalid")
    return value


def _digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise AgentsSyncFormatError(f"{label} is invalid")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise AgentsSyncFormatError(f"{label} must be a non-negative integer")
    return value


def _finite_time(value: object, label: str) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise AgentsSyncFormatError(f"{label} must be a finite non-negative number")
    return float(value)


__all__ = [
    "cached_item_is_available",
    "captured_incoming_hood_from_json",
    "find_cached_evidence",
    "legacy_family_count",
    "legacy_group_digest",
    "legacy_group_machine_hood",
    "legacy_manifest_groups",
    "load_validated_cache_item",
    "prune_project_cache",
    "publish_cache_object",
    "read_project_receipts",
    "receipt_for_item",
    "receipt_matches",
    "reconcile_pending_items",
    "validate_unpublished_cache_payload",
    "with_cache_id",
    "write_import_receipt",
]
