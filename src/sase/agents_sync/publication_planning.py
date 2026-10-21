"""Plan exact writes for owner-sharded hood publication."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sase._git_remote import github_commit_url
from sase.agents_sync.bead_links import build_bead_page_links
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.links import hosted_provider
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_snapshot import build_hood_snapshot
from sase.agents_sync.publication_validation import (
    load_validated_publication,
    previous_snapshot,
    snapshot_path,
)
from sase.agents_sync.rendering import (
    render_browsing_payload,
    render_targeted_browsing_payload,
)
from sase.agents_sync.v2_io import (
    check_manifest_write_size,
    content_digest,
    owner_hood_directory_names,
    owner_manifest_path,
    read_owner_manifest,
    v2_json_bytes,
    v2_schema_document,
)
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2PublicationCounts,
    is_session_container,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity

_SnapshotKey = tuple[str, str, str]

# Transaction-scoped reuse of already-validated unselected snapshots. The
# commit-drain transaction enables this around its per-hood publishes so
# several selected hoods share one validation/index load instead of
# re-reading every snapshot file per hood. Cleared on context exit and
# before retry prepares (upstream may have changed). No on-disk schema.
_TARGETED_CACHE_ENABLED = False
_TARGETED_SNAPSHOT_CACHE: dict[str, dict[_SnapshotKey, V2HoodSnapshot]] = {}


@contextmanager
def shared_targeted_planning() -> Iterator[None]:
    """Share validated snapshots across targeted plans in one transaction."""

    global _TARGETED_CACHE_ENABLED
    previous_enabled = _TARGETED_CACHE_ENABLED
    previous_cache = {
        key: dict(value) for key, value in _TARGETED_SNAPSHOT_CACHE.items()
    }
    _TARGETED_CACHE_ENABLED = True
    _TARGETED_SNAPSHOT_CACHE.clear()
    try:
        yield
    finally:
        _TARGETED_SNAPSHOT_CACHE.clear()
        _TARGETED_SNAPSHOT_CACHE.update(previous_cache)
        _TARGETED_CACHE_ENABLED = previous_enabled


def invalidate_shared_targeted_planning(repo_root: Path | None = None) -> None:
    """Drop cached snapshots so the next plan reloads from fresh upstream."""

    if repo_root is None:
        _TARGETED_SNAPSHOT_CACHE.clear()
        return
    _TARGETED_SNAPSHOT_CACHE.pop(str(repo_root.resolve()), None)


def _targeted_cache_for(repo_root: Path) -> dict[_SnapshotKey, V2HoodSnapshot] | None:
    if not _TARGETED_CACHE_ENABLED:
        return None
    key = str(repo_root.resolve())
    return _TARGETED_SNAPSHOT_CACHE.setdefault(key, {})


def plan_hoods(
    target: ProjectTarget,
    repo_root: Path,
    inventory: ProjectHoodInventory,
    hoods: tuple[str, ...],
    owner: AgentOwnerIdentity,
) -> tuple[dict[str, bytes], V2PublicationCounts]:
    project = V2ProjectIdentity(target.project_key, target.project)
    on_disk_hoods = owner_hood_directory_names(repo_root, owner)
    manifest_relative_path = owner_manifest_path(owner)
    if not (repo_root / manifest_relative_path).is_file() and on_disk_hoods:
        raise AgentsSyncFormatError(
            f"owner manifest {manifest_relative_path!r} is missing but "
            f"{len(on_disk_hoods)} on-disk hood director"
            f"{'y' if len(on_disk_hoods) == 1 else 'ies'} exist; refusing to "
            "republish from an empty manifest"
        )
    previous_manifest = read_owner_manifest(repo_root, owner, project)
    entries = previous_manifest.by_hood()
    manifest_diagnostics: tuple[str, ...] = ()
    unreferenced_hoods = sorted(set(on_disk_hoods) - set(entries))
    if unreferenced_hoods:
        manifest_diagnostics = (
            f"owner manifest {manifest_relative_path!r} omits "
            f"{len(unreferenced_hoods)} on-disk hood(s) "
            f"({', '.join(unreferenced_hoods)}); run "
            "`sase agent sync --repair-manifest` to restore them",
        )
    payload: dict[str, bytes] = {
        "schema.json": v2_json_bytes(v2_schema_document()),
        "agents/.gitkeep": b"",
        "families/.gitkeep": b"",
        "sessions/.gitkeep": b"",
    }
    current_snapshots: dict[tuple[str, str, str], V2HoodSnapshot] = {}
    published = refreshed = unchanged = sessions = runs = 0

    for hood in sorted(set(hoods)):
        previous = previous_snapshot(repo_root, owner, hood, entries.get(hood))
        hood_snapshot, hood_payload = build_hood_snapshot(
            repo_root,
            project,
            owner,
            hood,
            inventory,
            previous,
        )
        hood_snapshot_path = snapshot_path(owner, hood)
        snapshot_bytes = v2_json_bytes(hood_snapshot.to_json_dict())
        hood_payload[hood_snapshot_path] = snapshot_bytes
        # Owner-manifest writes always omit the per-hood file list; old
        # explicit lists on disk are still read and validated.
        entry = V2OwnerHoodEntry(
            content_digest(snapshot_bytes),
            None,
            len(hood_snapshot.runs),
            sum(is_session_container(item.kind) for item in hood_snapshot.containers),
        )
        existing = entries.get(hood)
        if existing is None:
            published += 1
        elif existing.digest == entry.digest:
            unchanged += 1
        else:
            refreshed += 1
        if existing is None or existing.digest != entry.digest:
            sessions += entry.agent_session_count
            runs += entry.run_count
        entries[hood] = entry
        payload.update(hood_payload)
        current_snapshots[(owner.username, owner.machine_name, hood)] = hood_snapshot

    manifest = V2OwnerManifest(owner, project, tuple(sorted(entries.items())))
    manifest_bytes = v2_json_bytes(manifest.to_json_dict())
    check_manifest_write_size(len(manifest.hoods), manifest_bytes)
    payload[owner_manifest_path(owner)] = manifest_bytes
    manifests, snapshots, diagnostics = load_validated_publication(
        repo_root,
        override_manifest=manifest,
        override_snapshots=current_snapshots,
        override_payload=payload,
    )
    bead_links, bead_diagnostics = build_bead_page_links(
        snapshots.values(),
        primary_root=target.primary_checkout,
        project=target.project,
    )
    payload.update(
        render_browsing_payload(
            manifests,
            snapshots,
            commit_url_base=_commit_url_base(inventory.primary_remote_url),
            commit_repo_name=inventory.primary_repo_name,
            bead_links=bead_links,
        )
    )
    counts = V2PublicationCounts(
        hoods_published=published,
        hoods_refreshed=refreshed,
        hoods_unchanged=unchanged,
        agent_sessions_published=sessions,
        runs_published=runs,
        diagnostics=tuple(
            dict.fromkeys(
                (
                    *manifest_diagnostics,
                    *inventory.diagnostics,
                    *diagnostics,
                    *bead_diagnostics,
                )
            )
        ),
    )
    return payload, counts


def plan_targeted_hoods(
    target: ProjectTarget,
    repo_root: Path,
    inventory: ProjectHoodInventory,
    hoods: tuple[str, ...],
    owner: AgentOwnerIdentity,
) -> tuple[dict[str, bytes], V2PublicationCounts]:
    """Plan a targeted payload for exactly the selected hoods.

    The payload contains selected snapshots and run files, selected
    hood/agent/session/legacy pages, the changed owner manifest, and the
    affected root/user/machine indexes. Unrelated pages are omitted so the
    payload scales with the selection. Complete manifest entries are retained
    for every unselected hood and owner, and aggregate indexes keep complete
    totals and machine states.
    """

    selected = tuple(sorted(set(hoods)))
    if not selected:
        return {
            "schema.json": v2_json_bytes(v2_schema_document()),
            "agents/.gitkeep": b"",
            "families/.gitkeep": b"",
            "sessions/.gitkeep": b"",
        }, V2PublicationCounts()
    project = V2ProjectIdentity(target.project_key, target.project)
    on_disk_hoods = owner_hood_directory_names(repo_root, owner)
    manifest_relative_path = owner_manifest_path(owner)
    if not (repo_root / manifest_relative_path).is_file() and on_disk_hoods:
        raise AgentsSyncFormatError(
            f"owner manifest {manifest_relative_path!r} is missing but "
            f"{len(on_disk_hoods)} on-disk hood director"
            f"{'y' if len(on_disk_hoods) == 1 else 'ies'} exist; refusing to "
            "republish from an empty manifest"
        )
    previous_manifest = read_owner_manifest(repo_root, owner, project)
    entries = previous_manifest.by_hood()
    manifest_diagnostics: tuple[str, ...] = ()
    unreferenced_hoods = sorted(set(on_disk_hoods) - set(entries))
    if unreferenced_hoods:
        manifest_diagnostics = (
            f"owner manifest {manifest_relative_path!r} omits "
            f"{len(unreferenced_hoods)} on-disk hood(s) "
            f"({', '.join(unreferenced_hoods)}); run "
            "`sase agent sync --repair-manifest` to restore them",
        )
    payload: dict[str, bytes] = {
        "schema.json": v2_json_bytes(v2_schema_document()),
        "agents/.gitkeep": b"",
        "families/.gitkeep": b"",
        "sessions/.gitkeep": b"",
    }
    cache = _targeted_cache_for(repo_root)
    current_snapshots: dict[tuple[str, str, str], V2HoodSnapshot] = {}
    published = refreshed = unchanged = sessions = runs = 0
    for hood in selected:
        entry = entries.get(hood)
        previous = _cached_previous_snapshot(repo_root, owner, hood, entry, cache)
        if previous is None:
            previous = previous_snapshot(repo_root, owner, hood, entry)
        hood_snapshot, hood_payload = build_hood_snapshot(
            repo_root,
            project,
            owner,
            hood,
            inventory,
            previous,
        )
        hood_snapshot_path = snapshot_path(owner, hood)
        snapshot_bytes = v2_json_bytes(hood_snapshot.to_json_dict())
        hood_payload[hood_snapshot_path] = snapshot_bytes
        entry_new = V2OwnerHoodEntry(
            content_digest(snapshot_bytes),
            None,
            len(hood_snapshot.runs),
            sum(is_session_container(item.kind) for item in hood_snapshot.containers),
        )
        existing = entries.get(hood)
        if existing is None:
            published += 1
        elif existing.digest == entry_new.digest:
            unchanged += 1
        else:
            refreshed += 1
        if existing is None or existing.digest != entry_new.digest:
            sessions += entry_new.agent_session_count
            runs += entry_new.run_count
        entries[hood] = entry_new
        payload.update(hood_payload)
        key = (owner.username, owner.machine_name, hood)
        current_snapshots[key] = hood_snapshot

    manifest = V2OwnerManifest(owner, project, tuple(sorted(entries.items())))
    manifest_bytes = v2_json_bytes(manifest.to_json_dict())
    check_manifest_write_size(len(manifest.hoods), manifest_bytes)
    payload[owner_manifest_path(owner)] = manifest_bytes
    base = dict(cache) if cache is not None else None
    if base is not None:
        for key in current_snapshots:
            base.pop(key, None)
    manifests, snapshots, diagnostics = load_validated_publication(
        repo_root,
        override_manifest=manifest,
        override_snapshots=current_snapshots,
        override_payload=payload,
        base_snapshots=base,
    )
    # Cache unselected snapshots only: selected snapshots are rebuilt fresh
    # on every plan (and applied to disk by the caller), so caching them
    # would serve unapplied bytes to a later plan. Unselected snapshots never
    # change during a transaction, so they are safe to reuse.
    if cache is not None:
        cache.update(
            {
                key: value
                for key, value in snapshots.items()
                if key not in current_snapshots
            }
        )
    selected_keys = frozenset(current_snapshots)
    # Bead links stay best-effort and scoped: only pages being written need
    # link resolution, so only selected snapshots are gathered.
    bead_links, bead_diagnostics = build_bead_page_links(
        tuple(snapshots[key] for key in sorted(selected_keys) if key in snapshots),
        primary_root=target.primary_checkout,
        project=target.project,
    )
    payload.update(
        render_targeted_browsing_payload(
            manifests,
            snapshots,
            selected_keys,
            commit_url_base=_commit_url_base(inventory.primary_remote_url),
            commit_repo_name=inventory.primary_repo_name,
            bead_links=bead_links,
        )
    )
    counts = V2PublicationCounts(
        hoods_published=published,
        hoods_refreshed=refreshed,
        hoods_unchanged=unchanged,
        agent_sessions_published=sessions,
        runs_published=runs,
        diagnostics=tuple(
            dict.fromkeys(
                (
                    *manifest_diagnostics,
                    *inventory.diagnostics,
                    *diagnostics,
                    *bead_diagnostics,
                )
            )
        ),
    )
    return payload, counts


def _cached_previous_snapshot(
    repo_root: Path,
    owner: AgentOwnerIdentity,
    hood: str,
    entry: V2OwnerHoodEntry | None,
    cache: dict[tuple[str, str, str], V2HoodSnapshot] | None,
) -> V2HoodSnapshot | None:
    if cache is None or entry is None:
        return None
    key = (owner.username, owner.machine_name, hood)
    cached = cache.get(key)
    if cached is None:
        return None
    if cached.owner != owner or cached.local_hood != hood:
        return None
    if content_digest(v2_json_bytes(cached.to_json_dict())) == entry.digest:
        return cached
    # On-disk snapshot bytes may be non-canonical, so a canonical
    # re-serialization can mismatch a valid manifest digest. Fall back to the
    # on-disk bytes before discarding the cached snapshot.
    try:
        raw = (repo_root / snapshot_path(owner, hood)).read_bytes()
    except OSError:
        return None
    if content_digest(raw) != entry.digest:
        return None
    return cached


def _commit_url_base(remote_url: str | None) -> str | None:
    if remote_url is None:
        return None
    sentinel_sha = "0" * 7
    commit_url = github_commit_url(
        remote_url,
        provider=hosted_provider(remote_url),
        sha=sentinel_sha,
    )
    if commit_url is None:
        return None
    return commit_url.removesuffix(f"/{sentinel_sha}")
