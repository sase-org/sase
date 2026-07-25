"""Capture independently validated foreign hoods from one fetched Git commit."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import json
import math
from pathlib import Path
import time
from typing import Any

from sase.agents_sync import bundles
from sase.agents_sync.git_objects import FetchedAgentsCommit, LocalGitObjectReader
from sase.agents_sync.incoming_cache import (
    cached_item_is_available,
    legacy_family_count,
    legacy_group_digest,
    legacy_group_machine_hood,
    legacy_manifest_groups,
    prune_project_cache,
    publish_cache_object,
    read_project_receipts,
    receipt_matches,
    validate_unpublished_cache_payload,
    with_cache_id,
)
from sase.agents_sync.io import (
    AgentsSyncFormatError,
    manifest_from_bytes,
)
from sase.agents_sync.models import (
    AgentsManifest,
    CapturedIncomingHood,
    ProjectTarget,
)
from sase.agents_sync.v2_io import (
    MAX_JSON_BYTES,
    MAX_PAYLOAD_BYTES,
    MAX_TEXT_BYTES,
    owner_manifest_from_bytes,
    owner_manifest_path,
    v2_json_bytes,
)
from sase.agents_sync.v2_models import V2OwnerManifest, V2ProjectIdentity
from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    AgentOwnershipClassification,
    AgentSourceOwnerIdentity,
    LegacyV1GroupOwnershipClassification,
    LegacyV1GroupOwnershipEvidence,
    classify_agent_ownership,
    classify_legacy_v1_group_ownership,
)
from sase.core.commit_sha_facade import commit_shas_equivalent
from sase.core.machine_hood_facade import machine_qualify_v1_transport_agent_name

_MAX_V1_MANIFEST_BYTES = 4 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _IncomingCaptureReport:
    """Result of inspecting one exact fetched commit."""

    fetched: FetchedAgentsCommit
    pending_updates: tuple[CapturedIncomingHood, ...]
    validated_foreign_count: int
    exact_owner_count: int
    diagnostics: tuple[str, ...]
    cache_updated_at: float
    owner_v2_hoods: tuple[str, ...] = ()


def capture_fetched_agent_updates(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    reader: LocalGitObjectReader,
    previous_items: Sequence[CapturedIncomingHood] = (),
    now: float | None = None,
) -> _IncomingCaptureReport:
    """Capture every independently valid foreign hood at one fetched commit."""

    captured_at = time.time() if now is None else now
    if not math.isfinite(captured_at) or captured_at < 0:
        raise ValueError("cache creation time must be finite and non-negative")
    fetched = reader.resolve_fetched_commit()
    diagnostics: list[str] = []
    validated_foreign = 0
    exact_owner = 0
    pending = {item.source_hood_key: item for item in previous_items}
    try:
        receipts = {
            receipt.source_hood_key: receipt
            for receipt in read_project_receipts(target.project_key)
        }
    except AgentsSyncFormatError as exc:
        receipts = {}
        diagnostics.append(f"quarantined import receipts: {exc}")

    paths = reader.manifest_paths(fetched.sha)
    legacy: AgentsManifest | None = None
    parsed_v2: list[tuple[str, V2OwnerManifest, AgentOwnershipClassification]] = []
    owner_v2_hoods: set[str] = set()
    for relative in paths:
        if relative == "manifest.json":
            try:
                legacy = manifest_from_bytes(
                    reader.read_bytes(
                        fetched.sha,
                        relative,
                        maximum=_MAX_V1_MANIFEST_BYTES,
                    )
                )
            except (AgentsSyncFormatError, OSError, RuntimeError) as exc:
                diagnostics.append(f"{relative}: quarantined legacy manifest: {exc}")
            continue
        try:
            manifest_bytes = reader.read_bytes(
                fetched.sha,
                relative,
                maximum=MAX_JSON_BYTES,
            )
            manifest = owner_manifest_from_bytes(manifest_bytes)
            _validate_owner_manifest_path(relative, manifest)
            if manifest.project != V2ProjectIdentity(
                target.project_key, target.project
            ):
                raise AgentsSyncFormatError(
                    "owner manifest project identity does not match target"
                )
            classification = classify_agent_ownership(
                AgentSourceOwnerIdentity.v2(manifest.owner),
                owner,
            )
        except (AgentsSyncFormatError, ValueError, RuntimeError, OSError) as exc:
            diagnostics.append(f"{relative}: quarantined v2 owner manifest: {exc}")
            continue
        parsed_v2.append((relative, manifest, classification))
        if classification is AgentOwnershipClassification.EXACT_OWNER:
            owner_v2_hoods.update(hood for hood, _entry in manifest.hoods)

    discarded_hood_keys: list[tuple[str, str | None, str, str]] = []
    if legacy is not None:
        groups = legacy_manifest_groups(legacy)
        artifact_rows = bundles.v1_artifact_rows(target)
        rows_by_timestamp = _artifact_rows_by_timestamp(artifact_rows)
        for group in groups:
            key = _legacy_group_key(group)
            machine, hood = legacy_group_machine_hood(group)
            try:
                proven_entry_count = (
                    _legacy_proven_entry_count(
                        reader,
                        fetched.sha,
                        group,
                        rows_by_timestamp,
                    )
                    if machine == owner.machine_name and hood not in owner_v2_hoods
                    else 0
                )
                ownership = classify_legacy_v1_group_ownership(
                    machine,
                    owner,
                    LegacyV1GroupOwnershipEvidence(
                        v2_hood_published=hood in owner_v2_hoods,
                        proven_entry_count=proven_entry_count,
                        total_entry_count=len(group.entries),
                    ),
                )
                if ownership is LegacyV1GroupOwnershipClassification.OWNER_OBSERVED:
                    exact_owner += 1
                    pending.pop(key, None)
                    discarded_hood_keys.append(key)
                    continue
                payload = _capture_legacy_payload(reader, fetched.sha, group)
                item = legacy_captured_item(
                    target,
                    fetched,
                    group,
                    captured_at,
                )
                validated_foreign += 1
                if receipt_matches(receipts.get(key), item):
                    pending.pop(key, None)
                    continue
                pending[key] = publish_cache_object(item, payload)
            except (AgentsSyncFormatError, OSError, RuntimeError, ValueError) as exc:
                diagnostics.append(f"{key[2]}.{key[3]}: quarantined legacy hood: {exc}")

    for _relative, manifest, classification in parsed_v2:
        if classification is AgentOwnershipClassification.EXACT_OWNER:
            for hood, _entry in manifest.hoods:
                try:
                    payload = _capture_v2_payload(
                        reader,
                        fetched.sha,
                        manifest,
                        hood,
                    )
                    item = v2_captured_item(
                        target,
                        fetched,
                        manifest,
                        hood,
                        captured_at,
                    )
                    validate_unpublished_cache_payload(item, payload)
                    exact_owner += 1
                except (
                    AgentsSyncFormatError,
                    ValueError,
                    RuntimeError,
                    OSError,
                ) as exc:
                    diagnostics.append(
                        f"{manifest.owner.username}.{manifest.owner.machine_name}."
                        f"{hood}: quarantined exact-owner v2 hood: {exc}"
                    )
            continue
        for hood, _entry in manifest.hoods:
            key = ("exact", manifest.owner.username, manifest.owner.machine_name, hood)
            try:
                payload = _capture_v2_payload(
                    reader,
                    fetched.sha,
                    manifest,
                    hood,
                )
                item = v2_captured_item(
                    target,
                    fetched,
                    manifest,
                    hood,
                    captured_at,
                )
                validated_foreign += 1
                if receipt_matches(receipts.get(key), item):
                    pending.pop(key, None)
                    continue
                pending[key] = publish_cache_object(item, payload)
            except (AgentsSyncFormatError, ValueError, RuntimeError, OSError) as exc:
                diagnostics.append(
                    f"{manifest.owner.username}.{manifest.owner.machine_name}.{hood}: "
                    f"quarantined v2 hood: {exc}"
                )

    reconciled: list[CapturedIncomingHood] = []
    for key, item in sorted(
        pending.items(),
        key=lambda row: (
            row[0][0],
            row[0][1] or "",
            row[0][2],
            row[0][3],
        ),
    ):
        if receipt_matches(receipts.get(key), item):
            continue
        if not cached_item_is_available(item):
            diagnostics.append(
                f"{item.cache_id}: pending cache object is missing or invalid"
            )
            continue
        reconciled.append(item)
    prune_project_cache(
        target.project_key,
        pending_items=tuple(reconciled),
        receipts=tuple(receipts.values()),
        discarded_hood_keys=tuple(discarded_hood_keys),
    )
    return _IncomingCaptureReport(
        fetched,
        tuple(reconciled),
        validated_foreign,
        exact_owner,
        tuple(dict.fromkeys(diagnostics)),
        captured_at,
        tuple(sorted(owner_v2_hoods)),
    )


def v2_captured_item(
    target: ProjectTarget,
    fetched: FetchedAgentsCommit,
    manifest: V2OwnerManifest,
    hood: str,
    captured_at: float,
) -> CapturedIncomingHood:
    entry = manifest.by_hood()[hood]
    item = CapturedIncomingHood(
        project_key=target.project_key,
        project=target.project,
        fetched_ref=fetched.ref,
        fetched_sha=fetched.sha,
        cache_id="0" * 64,
        format_version=2,
        source_owner_kind="exact",
        source_username=manifest.owner.username,
        source_machine=manifest.owner.machine_name,
        top_hood=hood,
        hood_digest=entry.digest,
        run_count=entry.run_count,
        family_count=entry.family_count,
        cache_created_at=captured_at,
    )
    return with_cache_id(item)


def legacy_captured_item(
    target: ProjectTarget,
    fetched: FetchedAgentsCommit,
    manifest: AgentsManifest,
    captured_at: float,
) -> CapturedIncomingHood:
    machine, hood = legacy_group_machine_hood(manifest)
    item = CapturedIncomingHood(
        project_key=target.project_key,
        project=target.project,
        fetched_ref=fetched.ref,
        fetched_sha=fetched.sha,
        cache_id="0" * 64,
        format_version=1,
        source_owner_kind="username_unknown_v1",
        source_username=None,
        source_machine=machine,
        top_hood=hood,
        hood_digest=legacy_group_digest(manifest),
        run_count=len(manifest.entries),
        family_count=legacy_family_count(manifest),
        cache_created_at=captured_at,
    )
    return with_cache_id(item)


def _capture_v2_payload(
    reader: LocalGitObjectReader,
    sha: str,
    manifest: V2OwnerManifest,
    hood: str,
) -> dict[str, bytes]:
    entry = manifest.by_hood()[hood]
    total = 0
    payload: dict[str, bytes] = {}
    for relative in entry.files:
        maximum = MAX_JSON_BYTES if relative.endswith(".json") else MAX_TEXT_BYTES
        try:
            content = reader.read_bytes(sha, relative, maximum=maximum)
        except AgentsSyncFormatError as exc:
            diagnostic = reader.owner_manifest_divergence_diagnostic(sha, relative)
            if diagnostic is not None:
                raise AgentsSyncFormatError(diagnostic) from exc
            raise
        total += len(content)
        if total > MAX_PAYLOAD_BYTES:
            raise AgentsSyncFormatError("hood aggregate payload exceeds byte limit")
        payload[relative] = content
    minimal = V2OwnerManifest(
        manifest.owner,
        manifest.project,
        ((hood, entry),),
    )
    payload[owner_manifest_path(manifest.owner)] = v2_json_bytes(minimal.to_json_dict())
    return payload


def _capture_legacy_payload(
    reader: LocalGitObjectReader,
    sha: str,
    manifest: AgentsManifest,
) -> dict[str, bytes]:
    payload = {
        "manifest.json": (
            json.dumps(
                manifest.to_json_dict(),
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )
    }
    total = len(payload["manifest.json"])
    for entry in manifest.entries:
        for name, maximum in (
            ("meta.json", MAX_JSON_BYTES),
            ("commits.json", MAX_JSON_BYTES),
            ("chat.md", MAX_TEXT_BYTES),
        ):
            relative = f"agents/{entry.name}/{name}"
            content = reader.read_bytes(sha, relative, maximum=maximum)
            total += len(content)
            if total > MAX_PAYLOAD_BYTES:
                raise AgentsSyncFormatError(
                    "legacy hood aggregate payload exceeds byte limit"
                )
            payload[relative] = content
    return payload


def _validate_owner_manifest_path(
    relative: str,
    manifest: V2OwnerManifest,
) -> None:
    if relative != owner_manifest_path(manifest.owner):
        raise AgentsSyncFormatError("owner manifest identity does not match path")


def _legacy_group_key(
    manifest: AgentsManifest,
) -> tuple[str, str | None, str, str]:
    machine, hood = legacy_group_machine_hood(manifest)
    return ("username_unknown_v1", None, machine, hood)


def _artifact_rows_by_timestamp(
    rows: Sequence[tuple[Path, dict[str, Any], dict[str, Any]]],
) -> dict[str, tuple[tuple[Path, dict[str, Any], dict[str, Any]], ...]]:
    grouped: dict[
        str,
        list[tuple[Path, dict[str, Any], dict[str, Any]]],
    ] = {}
    for row in rows:
        grouped.setdefault(row[0].name, []).append(row)
    return {timestamp: tuple(values) for timestamp, values in grouped.items()}


def _legacy_proven_entry_count(
    reader: LocalGitObjectReader,
    fetched_sha: str,
    group: AgentsManifest,
    rows_by_timestamp: dict[
        str,
        tuple[tuple[Path, dict[str, Any], dict[str, Any]], ...],
    ],
) -> int:
    proven = 0
    for entry in group.entries:
        source_shas = _legacy_source_commit_shas(
            reader,
            fetched_sha,
            entry.name,
        )
        if not source_shas:
            continue
        for artifact_dir, meta, done in rows_by_timestamp.get(
            entry.artifact_timestamp, ()
        ):
            if meta.get("imported_from_machine") is not None:
                continue
            raw_name = meta.get("name") or done.get("name")
            if not isinstance(raw_name, str):
                continue
            if (
                machine_qualify_v1_transport_agent_name(raw_name, entry.machine)
                != entry.name
            ):
                continue
            local_shas = tuple(
                sha
                for marker in bundles.commit_markers(artifact_dir)
                if (sha := _marker_commit_sha(marker)) is not None
            )
            if any(
                commit_shas_equivalent(source_sha, local_sha)
                for source_sha in source_shas
                for local_sha in local_shas
            ):
                proven += 1
                break
    return proven


def _legacy_source_commit_shas(
    reader: LocalGitObjectReader,
    fetched_sha: str,
    entry_name: str,
) -> tuple[str, ...]:
    relative = f"agents/{entry_name}/commits.json"
    try:
        value = json.loads(
            reader.read_bytes(
                fetched_sha,
                relative,
                maximum=MAX_JSON_BYTES,
            ).decode("utf-8")
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AgentsSyncFormatError(
            f"could not decode commits.json for {entry_name!r}: {exc}"
        ) from exc
    if not isinstance(value, dict) or not isinstance(value.get("commits"), list):
        raise AgentsSyncFormatError(
            f"commits.json for {entry_name!r} has an invalid shape"
        )
    shas: list[str] = []
    for row in value["commits"]:
        if not isinstance(row, dict) or not isinstance(row.get("sha"), str):
            raise AgentsSyncFormatError(
                f"commits.json for {entry_name!r} has an invalid commit row"
            )
        shas.append(row["sha"])
    return tuple(shas)


def _marker_commit_sha(marker: dict[str, Any]) -> str | None:
    for key in ("result", "commit_result", "sha"):
        value = marker.get(key)
        if isinstance(value, str) and value:
            return value
    return None


__all__ = [
    "capture_fetched_agent_updates",
    "legacy_captured_item",
    "v2_captured_item",
]
