"""Pure deterministic Markdown rendering for browsable v2 publications."""

from __future__ import annotations

from collections import defaultdict

from sase.agents_sync.rendering_agent_page import render_agent_page
from sase.agents_sync.rendering_family_page import render_family_page
from sase.agents_sync.rendering_index_pages import (
    render_hood_page,
    render_machine_page,
    render_root_page,
    render_user_page,
)
from sase.agents_sync.rendering_kinship import build_hood_kinship
from sase.agents_sync.rendering_markdown import page_bytes
from sase.agents_sync.v2_models import (
    V2ContainerRecord,
    V2HoodSnapshot,
    V2OwnerManifest,
)


def render_browsing_payload(
    manifests: tuple[V2OwnerManifest, ...],
    snapshots: dict[tuple[str, str, str], V2HoodSnapshot],
    *,
    commit_url_base: str | None = None,
    commit_repo_name: str | None = None,
) -> dict[str, bytes]:
    """Render every derived page from validated manifests and snapshots."""

    payload: dict[str, bytes] = {}
    ordered = tuple(
        sorted(
            manifests,
            key=lambda item: (item.owner.username, item.owner.machine_name),
        )
    )
    payload["README.md"] = page_bytes(render_root_page(ordered))

    by_user: dict[str, list[V2OwnerManifest]] = defaultdict(list)
    for manifest in ordered:
        by_user[manifest.owner.username].append(manifest)
    for username, user_manifests in sorted(by_user.items()):
        payload[f"users/{username}/README.md"] = page_bytes(
            render_user_page(username, tuple(user_manifests))
        )
        for manifest in user_manifests:
            machine_root = f"users/{username}/machines/{manifest.owner.machine_name}"
            machine_snapshots = tuple(
                snapshots[(username, manifest.owner.machine_name, hood)]
                for hood, _entry in manifest.hoods
            )
            payload[f"{machine_root}/README.md"] = page_bytes(
                render_machine_page(manifest, machine_snapshots)
            )
            for snapshot in machine_snapshots:
                hood_root = f"{machine_root}/hoods/{snapshot.local_hood}"
                payload[f"{hood_root}/README.md"] = page_bytes(
                    render_hood_page(snapshot, hood_root)
                )
                payload.update(
                    _render_run_pages(
                        snapshot,
                        commit_url_base=commit_url_base,
                        commit_repo_name=commit_repo_name,
                    )
                )
    return payload


def _render_run_pages(
    snapshot: V2HoodSnapshot,
    *,
    commit_url_base: str | None,
    commit_repo_name: str | None,
) -> dict[str, bytes]:
    payload: dict[str, bytes] = {}
    by_id = {run.source_run_id: run for run in snapshot.runs}
    kinship = build_hood_kinship(snapshot)
    families_by_member: dict[str, V2ContainerRecord] = {}
    for container in snapshot.containers:
        if container.kind != "family":
            continue
        for source_id in container.member_source_run_ids:
            families_by_member[source_id] = container
        payload[f"families/{container.global_name}.md"] = page_bytes(
            render_family_page(
                snapshot,
                container,
                by_id,
                commit_url_base=commit_url_base,
                commit_repo_name=commit_repo_name,
                kinship=kinship,
            )
        )
    for run in snapshot.runs:
        payload[f"agents/{run.global_name}/README.md"] = page_bytes(
            render_agent_page(
                snapshot,
                run,
                family=families_by_member.get(run.source_run_id),
                commit_url_base=commit_url_base,
                commit_repo_name=commit_repo_name,
                kinship=kinship,
            )
        )
    return payload


__all__ = ["render_browsing_payload"]
