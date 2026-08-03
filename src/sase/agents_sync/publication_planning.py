"""Plan exact writes for owner-sharded hood publication."""

from __future__ import annotations

from pathlib import Path

from sase._git_remote import github_commit_url
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.links import hosted_provider
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_snapshot import build_hood_snapshot
from sase.agents_sync.publication_validation import (
    hood_file_set,
    load_validated_publication,
    previous_snapshot,
    snapshot_path,
)
from sase.agents_sync.rendering import render_browsing_payload
from sase.agents_sync.v2_io import (
    content_digest,
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
)
from sase.core.agent_identity_facade import AgentOwnerIdentity


def plan_hoods(
    target: ProjectTarget,
    repo_root: Path,
    inventory: ProjectHoodInventory,
    hoods: tuple[str, ...],
    owner: AgentOwnerIdentity,
) -> tuple[dict[str, bytes], V2PublicationCounts]:
    project = V2ProjectIdentity(target.project_key, target.project)
    previous_manifest = read_owner_manifest(repo_root, owner, project)
    entries = previous_manifest.by_hood()
    payload: dict[str, bytes] = {
        "schema.json": v2_json_bytes(v2_schema_document()),
        "agents/.gitkeep": b"",
        "families/.gitkeep": b"",
    }
    current_snapshots: dict[tuple[str, str, str], V2HoodSnapshot] = {}
    published = refreshed = unchanged = families = runs = 0

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
        files = hood_file_set(hood_snapshot)
        entry = V2OwnerHoodEntry(
            content_digest(snapshot_bytes),
            files,
            len(hood_snapshot.runs),
            sum(item.kind == "family" for item in hood_snapshot.containers),
        )
        existing = entries.get(hood)
        if existing is None:
            published += 1
        elif existing.digest == entry.digest:
            unchanged += 1
        else:
            refreshed += 1
        if existing is None or existing.digest != entry.digest:
            families += entry.family_count
            runs += entry.run_count
        entries[hood] = entry
        payload.update(hood_payload)
        current_snapshots[(owner.username, owner.machine_name, hood)] = hood_snapshot

    manifest = V2OwnerManifest(owner, project, tuple(sorted(entries.items())))
    payload[owner_manifest_path(owner)] = v2_json_bytes(manifest.to_json_dict())
    manifests, snapshots = load_validated_publication(
        repo_root,
        override_manifest=manifest,
        override_snapshots=current_snapshots,
        override_payload=payload,
    )
    payload.update(
        render_browsing_payload(
            manifests,
            snapshots,
            commit_url_base=_commit_url_base(inventory.primary_remote_url),
            commit_repo_name=inventory.primary_repo_name,
        )
    )
    counts = V2PublicationCounts(
        hoods_published=published,
        hoods_refreshed=refreshed,
        hoods_unchanged=unchanged,
        families_published=families,
        runs_published=runs,
        diagnostics=inventory.diagnostics,
    )
    return payload, counts


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
