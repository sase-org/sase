"""Plan exact writes and deletes for owner-sharded hood publication."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sase._git_remote import github_commit_url
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.links import hosted_provider
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_models import (
    V2SidecarDelete,
    V2SidecarRegenerationPlan,
    V2SidecarWrite,
)
from sase.agents_sync.publication_snapshot import build_hood_snapshot
from sase.agents_sync.publication_validation import (
    hood_file_set,
    hood_readme_path,
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
    V2CompatibilityAlias,
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2PublicationCounts,
)
from sase.core.agent_identity_facade import AgentOwnerIdentity, agent_local_hood


def plan_hoods(
    target: ProjectTarget,
    repo_root: Path,
    inventory: ProjectHoodInventory,
    hoods: tuple[str, ...],
    owner: AgentOwnerIdentity,
    *,
    compatibility_aliases: tuple[V2CompatibilityAlias, ...] = (),
) -> V2SidecarRegenerationPlan:
    project = V2ProjectIdentity(target.project_key, target.project)
    previous_manifest = read_owner_manifest(repo_root, owner, project)
    entries = previous_manifest.by_hood()
    retired_globals = _retired_alias_globals(compatibility_aliases)
    retired_hoods = _retired_alias_hoods(owner, compatibility_aliases)
    for hood in retired_hoods - set(hoods):
        entries.pop(hood, None)
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
            retired_global_names=retired_globals,
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

    manifest = V2OwnerManifest(
        owner,
        project,
        tuple(sorted(entries.items())),
        tuple(sorted(compatibility_aliases, key=_alias_sort_key)),
    )
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
    deletes = _planned_deletes(
        repo_root,
        previous_manifest,
        manifest,
        payload,
        retired_hoods,
    )
    counts = V2PublicationCounts(
        hoods_published=published,
        hoods_refreshed=refreshed,
        hoods_unchanged=unchanged,
        families_published=families,
        runs_published=runs,
        diagnostics=inventory.diagnostics,
    )
    return V2SidecarRegenerationPlan(
        _planned_writes(repo_root, payload),
        deletes,
        manifest.compatibility_aliases,
        counts,
    )


def _planned_writes(
    repo_root: Path,
    payload: dict[str, bytes],
) -> tuple[V2SidecarWrite, ...]:
    writes: list[V2SidecarWrite] = []
    for path, postimage in sorted(payload.items()):
        preimage = _read_optional_bytes(repo_root / path)
        if preimage == postimage:
            continue
        writes.append(
            V2SidecarWrite(
                path,
                _sha256(preimage) if preimage is not None else None,
                _sha256(postimage),
                postimage,
            )
        )
    return tuple(writes)


def _planned_deletes(
    repo_root: Path,
    previous_manifest: V2OwnerManifest,
    manifest: V2OwnerManifest,
    payload: dict[str, bytes],
    retired_hoods: frozenset[str],
) -> tuple[V2SidecarDelete, ...]:
    previous_hoods = previous_manifest.by_hood()
    current_hoods = manifest.by_hood()
    paths: set[str] = set()
    for hood in sorted(retired_hoods):
        if hood in current_hoods:
            continue
        previous = previous_hoods.get(hood)
        if previous is not None:
            paths.update(previous.files)
            paths.add(snapshot_path(previous_manifest.owner, hood))
            paths.add(hood_readme_path(previous_manifest.owner, hood))
    for hood, previous in previous_hoods.items():
        current = current_hoods.get(hood)
        if current is None:
            continue
        paths.update(set(previous.files) - set(current.files))
    previous_alias_paths = {
        _alias_page_path(alias) for alias in previous_manifest.compatibility_aliases
    }
    current_alias_paths = {
        _alias_page_path(alias) for alias in manifest.compatibility_aliases
    }
    paths.update(previous_alias_paths - current_alias_paths)
    deletes: list[V2SidecarDelete] = []
    for path in sorted(paths - set(payload)):
        preimage = _read_optional_bytes(repo_root / path)
        if preimage is None:
            continue
        deletes.append(V2SidecarDelete(path, _sha256(preimage)))
    return tuple(deletes)


def _retired_alias_globals(
    compatibility_aliases: tuple[V2CompatibilityAlias, ...],
) -> frozenset[str]:
    return frozenset(alias.source_global_name for alias in compatibility_aliases)


def _retired_alias_hoods(
    owner: AgentOwnerIdentity,
    compatibility_aliases: tuple[V2CompatibilityAlias, ...],
) -> frozenset[str]:
    prefix = f"{owner.username}.{owner.machine_name}."
    hoods: set[str] = set()
    for alias in compatibility_aliases:
        if not alias.source_global_name.startswith(prefix):
            continue
        local = alias.source_global_name.removeprefix(prefix)
        hood = agent_local_hood(local)
        if hood:
            hoods.add(hood)
    return frozenset(hoods)


def _alias_sort_key(alias: V2CompatibilityAlias) -> tuple[str, str]:
    return (alias.page_kind, alias.source_global_name)


def _alias_page_path(alias: V2CompatibilityAlias) -> str:
    if alias.page_kind == "agent":
        return f"agents/{alias.source_global_name}/README.md"
    return f"families/{alias.source_global_name}.md"


def _read_optional_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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
