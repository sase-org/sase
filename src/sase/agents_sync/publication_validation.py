"""Validation and path helpers for agent sidecar publication."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.v2_io import (
    MAX_JSON_BYTES,
    content_digest,
    read_all_owner_manifests_lenient,
    read_hood_snapshot,
    v2_json_bytes,
)
from sase.agents_sync.v2_snapshot_io import decode_hood_snapshot
from sase.agents_sync.publication_roster import (
    HoodRosterSummary,
    RosterSummaryKey,
    read_roster_summary_cache,
    roster_summary_key,
    write_roster_summary_cache,
)
from sase.agents_sync.v2_validation import json_from_bytes
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2RunRecord,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.agent_session_manifest import (
    SESSION_MANIFEST_CLASS_CURRENT,
    SESSION_MANIFEST_CLASS_SUPPORTED_LEGACY,
    classify_session_manifest_files,
)


def previous_snapshot(
    repo_root: Path,
    owner: AgentOwnerIdentity,
    hood: str,
    entry: V2OwnerHoodEntry | None,
) -> V2HoodSnapshot | None:
    if entry is None:
        return None
    path = repo_root / snapshot_path(owner, hood)
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise AgentsSyncFormatError(
            f"could not read existing snapshot for hood {hood!r}: {exc}"
        ) from exc
    if size > MAX_JSON_BYTES:
        raise AgentsSyncFormatError(
            f"existing snapshot for hood {hood!r} exceeds the JSON byte limit"
        )
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise AgentsSyncFormatError(
            f"could not read existing snapshot for hood {hood!r}: {exc}"
        ) from exc
    if len(payload) > MAX_JSON_BYTES:
        raise AgentsSyncFormatError(
            f"existing snapshot for hood {hood!r} exceeds the JSON byte limit"
        )
    if content_digest(payload) != entry.digest:
        raise AgentsSyncFormatError(
            f"existing snapshot digest mismatch for hood {hood!r}"
        )
    snapshot = decode_hood_snapshot(json_from_bytes(payload, "hood snapshot"))
    if snapshot.owner != owner or snapshot.local_hood != hood:
        raise AgentsSyncFormatError(
            f"existing snapshot identity mismatch for hood {hood!r}"
        )
    return snapshot


def load_validated_publication(
    repo_root: Path,
    *,
    override_manifest: V2OwnerManifest | None = None,
    override_snapshots: dict[tuple[str, str, str], V2HoodSnapshot] | None = None,
    override_payload: dict[str, bytes] | None = None,
    base_snapshots: dict[tuple[str, str, str], V2HoodSnapshot] | None = None,
    summarize_unselected: bool = False,
    base_summaries: Mapping[RosterSummaryKey, HoodRosterSummary] | None = None,
    summary_cache_stats: dict[str, int] | None = None,
    summary_cache_path: Path | None = None,
) -> tuple[
    tuple[V2OwnerManifest, ...],
    dict[tuple[str, str, str], V2HoodSnapshot],
    dict[tuple[str, str, str], HoodRosterSummary],
    tuple[str, ...],
]:
    """Validate manifests and snapshots, reusing cached snapshots when given.

    ``base_snapshots`` supplies already-validated unselected snapshots so
    targeted planning can share them within one transaction instead of
    re-reading every snapshot file per hood. Digest, identity, and explicit
    file-set checks still apply to reused snapshots; referenced-file checks
    stay scoped to ``override_snapshots`` exactly as before.
    """

    all_manifests, diagnostics = read_all_owner_manifests_lenient(repo_root)
    manifests = {
        (item.owner.username, item.owner.machine_name): item for item in all_manifests
    }
    if override_manifest is not None:
        manifests[
            (
                override_manifest.owner.username,
                override_manifest.owner.machine_name,
            )
        ] = override_manifest
    snapshots: dict[tuple[str, str, str], V2HoodSnapshot] = {}
    summaries: dict[tuple[str, str, str], HoodRosterSummary] = {}
    overrides = override_snapshots or {}
    base = base_snapshots or {}
    memory_summaries = base_summaries or {}
    scoped_verification = override_snapshots is not None
    payload = override_payload or {}
    roster_cache = (
        read_roster_summary_cache(
            repo_root,
            override_manifest.project.key
            if override_manifest is not None
            else next(iter(manifests.values())).project.key,
            path_override=summary_cache_path,
        )
        if summarize_unselected and manifests
        else None
    )
    cache_additions: dict[RosterSummaryKey, HoodRosterSummary] = {}
    cacheable_current_keys: set[RosterSummaryKey] = set()
    if summary_cache_stats is not None:
        summary_cache_stats.clear()
        summary_cache_stats.update(hits=0, misses=0)
    for manifest in manifests.values():
        for hood, entry in manifest.hoods:
            key = (manifest.owner.username, manifest.owner.machine_name, hood)
            snapshot = overrides.get(key)
            from_base = False
            if snapshot is None:
                snapshot = base.get(key)
                from_base = snapshot is not None
            path = snapshot_path(manifest.owner, hood)
            cache_key = roster_summary_key(manifest, hood, entry.digest)
            cacheable = (
                summarize_unselected and key not in overrides and entry.files is None
            )
            if summarize_unselected and entry.files is None:
                cacheable_current_keys.add(cache_key)
            summary: HoodRosterSummary | None = None
            summary_cache_hit = False
            if cacheable and snapshot is None:
                candidate = memory_summaries.get(cache_key)
                if candidate is None and roster_cache is not None:
                    candidate = roster_cache.summaries.get(cache_key)
                if candidate is not None and _summary_matches_entry(
                    candidate, hood, entry
                ):
                    summary = candidate
                    summary_cache_hit = True
                elif candidate is not None and roster_cache is not None:
                    roster_cache.summaries.pop(cache_key, None)
            if from_base:
                # Reused snapshots were validated when they entered the cache.
                # The manifest digest covers the on-disk bytes, which may be
                # non-canonical, so verify those bytes rather than a canonical
                # re-serialization of the cached snapshot.
                raw = _payload_bytes(repo_root, payload, path)
            else:
                raw = (
                    v2_json_bytes(snapshot.to_json_dict())
                    if snapshot is not None
                    else _payload_bytes(repo_root, payload, path)
                )
            if content_digest(raw) != entry.digest:
                raise AgentsSyncFormatError(
                    f"snapshot digest mismatch for {'.'.join(key)!r}"
                )
            if snapshot is None and summary is None:
                snapshot = read_hood_snapshot(repo_root / path)
            if snapshot is not None:
                if (
                    snapshot.owner != manifest.owner
                    or snapshot.project != manifest.project
                    or snapshot.local_hood != hood
                ):
                    raise AgentsSyncFormatError(
                        f"snapshot identity mismatch for {'.'.join(key)!r}"
                    )
                if entry.files is not None:
                    _check_explicit_file_set(snapshot, entry, key)
                if not scoped_verification or key in overrides:
                    for run in snapshot.runs:
                        verify_run_files(repo_root, run, payload)
                summary = HoodRosterSummary.from_snapshot(snapshot)
                snapshots[key] = snapshot
            assert summary is not None
            summaries[key] = summary
            if cacheable:
                cache_additions[cache_key] = summary
                if summary_cache_stats is not None:
                    summary_cache_stats["hits" if summary_cache_hit else "misses"] += 1
    if roster_cache is not None:
        write_roster_summary_cache(
            roster_cache,
            current_keys=cacheable_current_keys,
            additions=cache_additions,
        )
    return (
        tuple(
            sorted(
                manifests.values(),
                key=lambda item: (
                    item.owner.username,
                    item.owner.machine_name,
                ),
            )
        ),
        snapshots,
        summaries,
        diagnostics,
    )


def _summary_matches_entry(
    summary: HoodRosterSummary,
    hood: str,
    entry: V2OwnerHoodEntry,
) -> bool:
    return (
        summary.local_hood == hood
        and summary.run_count == entry.run_count
        and summary.session_count == entry.agent_session_count
    )


def verify_run_files(
    repo_root: Path,
    run: V2RunRecord,
    payload: dict[str, bytes] | None = None,
) -> None:
    for _kind, reference in run.files:
        content = _payload_bytes(repo_root, payload or {}, reference.path)
        if (
            len(content) != reference.size_bytes
            or content_digest(content) != reference.digest
        ):
            raise AgentsSyncFormatError(f"file digest mismatch for {reference.path!r}")


def _payload_bytes(repo_root: Path, payload: dict[str, bytes], path: str) -> bytes:
    if path in payload:
        return payload[path]
    try:
        return (repo_root / path).read_bytes()
    except OSError as exc:
        raise AgentsSyncFormatError(f"could not read referenced file {path!r}") from exc


def _check_explicit_file_set(
    snapshot: V2HoodSnapshot,
    entry: V2OwnerHoodEntry,
    key: tuple[str, str, str],
) -> None:
    """Enforce the explicit manifest file-set policy through the Rust core."""
    assert entry.files is not None
    # Old explicit file sets are still read: the current canonical set and
    # the exact supported legacy family-only set are both accepted.
    decision = classify_session_manifest_files(
        owner_username=snapshot.owner.username,
        owner_machine=snapshot.owner.machine_name,
        local_hood=snapshot.local_hood,
        run_global_names=tuple(run.global_name for run in snapshot.runs),
        run_file_paths=tuple(
            reference.path for run in snapshot.runs for _kind, reference in run.files
        ),
        containers=tuple(
            (container.kind, container.global_name) for container in snapshot.containers
        ),
        explicit_files=entry.files,
    )
    if decision.classification not in {
        SESSION_MANIFEST_CLASS_CURRENT,
        SESSION_MANIFEST_CLASS_SUPPORTED_LEGACY,
    }:
        raise AgentsSyncFormatError(
            f"manifest file set mismatch for {'.'.join(key)!r}: "
            f"{decision.classification}: {decision.reason}"
        )


def snapshot_path(owner: AgentOwnerIdentity, hood: str) -> str:
    return (
        f"users/{owner.username}/machines/{owner.machine_name}/"
        f"hoods/{hood}/snapshot.json"
    )
