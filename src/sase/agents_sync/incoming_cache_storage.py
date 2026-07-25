"""Filesystem storage and validation for immutable incoming cache objects."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import tempfile

from sase.agents_sync.incoming_cache_legacy import (
    legacy_family_count,
    legacy_entry_top_hood,
    legacy_group_digest,
)
from sase.agents_sync.incoming_cache_metadata import (
    _DIGEST_RE,
    captured_incoming_hood_from_json,
    receipt_matches,
    same_cached_content,
)
from sase.agents_sync.incoming_cache_paths import (
    cache_object_path,
    cache_objects_dir,
    cache_staging_dir,
)
from sase.agents_sync.incoming_cache_receipts import read_project_receipts
from sase.agents_sync.io import (
    AgentsSyncFormatError,
    atomic_write_json,
    read_bundle,
    read_manifest,
)
from sase.agents_sync.models import (
    AgentHoodImportReceipt,
    AgentsManifest,
    CapturedIncomingHood,
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
    validate_relative_path,
)
from sase.agents_sync.v2_models import V2ProjectIdentity
from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    LegacyV1GroupOwnershipClassification,
    LegacyV1GroupOwnershipEvidence,
    classify_legacy_v1_group_ownership,
)

_RECENT_SUPERSEDED_PER_HOOD = 2


@dataclass(frozen=True, slots=True)
class _LoadedCachedHood:
    """A strictly revalidated cached payload ready for its existing importer."""

    item: CapturedIncomingHood
    payload_root: Path
    v2_package: ValidatedV2HoodPackage | None = None
    legacy_manifest: AgentsManifest | None = None


def cached_item_is_available(item: CapturedIncomingHood) -> bool:
    """Perform the metadata-only availability check allowed on short status."""

    try:
        stored = _read_cache_metadata(cache_object_path(item.cache_id))
    except (AgentsSyncFormatError, OSError):
        return False
    return stored == item


def publish_cache_object(
    item: CapturedIncomingHood,
    payload: Mapping[str, bytes],
) -> CapturedIncomingHood:
    """Validate and atomically publish one immutable content-addressed object."""

    decoded = captured_incoming_hood_from_json(item.to_json_dict())
    objects = cache_objects_dir()
    staging = cache_staging_dir()
    objects.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging.mkdir(parents=True, exist_ok=True, mode=0o700)
    destination = cache_object_path(decoded.cache_id)
    if destination.exists() or destination.is_symlink():
        stored = _read_cache_metadata(destination)
        if stored.cache_id != decoded.cache_id or not same_cached_content(
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
            if not same_cached_content(stored, decoded):
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

    staging = cache_staging_dir()
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
    root = object_path or cache_object_path(decoded.cache_id)
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
            or legacy_entry_top_hood(legacy_entry) != decoded.top_hood
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
    owner: AgentOwnerIdentity,
    owner_v2_hoods: Sequence[str],
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
    discarded: list[CapturedIncomingHood] = []
    published_hoods = frozenset(owner_v2_hoods)
    for item in items:
        if item.project_key != project_key:
            diagnostics.append(
                f"{item.cache_id}: cached project key does not match status"
            )
            continue
        if receipt_matches(receipts.get(item.source_hood_key), item):
            continue
        if item.format_version == 1:
            ownership = classify_legacy_v1_group_ownership(
                item.source_machine,
                owner,
                LegacyV1GroupOwnershipEvidence(
                    v2_hood_published=item.top_hood in published_hoods,
                    proven_entry_count=0,
                    total_entry_count=item.run_count,
                ),
            )
            if ownership is LegacyV1GroupOwnershipClassification.OWNER_OBSERVED:
                discarded.append(item)
                continue
        if not cached_item_is_available(item):
            diagnostics.append(
                f"{item.cache_id}: pending cache object is missing or invalid"
            )
            continue
        pending.append(item)
    prune_project_cache(
        project_key,
        pending_items=tuple(pending),
        receipts=tuple(receipts.values()),
        discarded_hood_keys=tuple(item.source_hood_key for item in discarded),
    )
    return tuple(pending), tuple(diagnostics)


def prune_project_cache(
    project_key: str,
    *,
    pending_items: Sequence[CapturedIncomingHood],
    receipts: Sequence[AgentHoodImportReceipt],
    keep_recent: int = _RECENT_SUPERSEDED_PER_HOOD,
    discarded_hood_keys: Sequence[tuple[str, str | None, str, str]] = (),
) -> None:
    """Bound superseded objects while preserving pending and receipt evidence."""

    objects = cache_objects_dir()
    if not objects.is_dir() or objects.is_symlink():
        return
    protected = {item.cache_id for item in pending_items}
    protected.update(receipt.cache_id for receipt in receipts)
    discarded = frozenset(discarded_hood_keys)
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
            if item.source_hood_key in discarded and item.cache_id not in protected:
                shutil.rmtree(path)
                continue
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
            path = cache_object_path(item.cache_id)
            if path.parent == objects and path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)


def find_cached_evidence(
    project_key: str,
    key: tuple[str, str | None, str, str],
    digest: str,
) -> CapturedIncomingHood | None:
    objects = cache_objects_dir()
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
    objects = cache_objects_dir().resolve(strict=False)
    staging = cache_staging_dir().resolve(strict=False)
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
