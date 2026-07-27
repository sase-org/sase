"""Root, owner, machine, and hood browsing pages."""

from __future__ import annotations

from collections import defaultdict

from sase.agents_sync.rendering_markdown import (
    md_cell,
    md_code,
    md_escape,
    page_url,
    relative_page_url,
    run_timing,
    state_counts,
)
from sase.agents_sync.v2_models import V2HoodSnapshot, V2OwnerManifest
from sase.core.agent_identity_facade import agent_link_target


def render_root_page(manifests: tuple[V2OwnerManifest, ...]) -> str:
    """Render the sidecar root index."""

    users: dict[str, list[V2OwnerManifest]] = defaultdict(list)
    for manifest in manifests:
        users[manifest.owner.username].append(manifest)
    hood_count = sum(len(manifest.hoods) for manifest in manifests)
    run_count = sum(
        entry.run_count for manifest in manifests for _hood, entry in manifest.hoods
    )
    lines = [
        "# SASE Agent Hoods",
        "",
        "Deterministic, owner-sharded snapshots published by SASE.",
        "",
        f"**Owners:** {len(users)} · **Machines:** {len(manifests)} · "
        f"**Hoods:** {hood_count} · **Runs:** {run_count}",
        "",
    ]
    if not users:
        lines.extend(
            [
                "No agent hoods have been published yet.",
                "",
                "This sidecar may contain active prompts and later transcript "
                "refreshes. Keep it private or disable it when that scope is "
                "not acceptable.",
                "",
            ]
        )
        return "\n".join(lines)
    lines.extend(
        ["## Users", "", "| User | Machines | Hoods | Runs |", "|---|---:|---:|---:|"]
    )
    for username, rows in sorted(users.items()):
        hoods = sum(len(item.hoods) for item in rows)
        runs = sum(entry.run_count for item in rows for _hood, entry in item.hoods)
        lines.append(
            f"| [{md_cell(username)}]({page_url(f'users/{username}/README.md')}) "
            f"| {len(rows)} | {hoods} | {runs} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_user_page(username: str, manifests: tuple[V2OwnerManifest, ...]) -> str:
    """Render one owner's machine index."""

    lines = [
        f"# {md_escape(username)}",
        "",
        "[Agent Hoods](../../README.md) / " + md_escape(username),
        "",
        f"**Machines:** {len(manifests)} · **Hoods:** "
        f"{sum(len(item.hoods) for item in manifests)} · **Runs:** "
        f"{sum(entry.run_count for item in manifests for _hood, entry in item.hoods)}",
        "",
        "| Machine | Project | Hoods | Runs |",
        "|---|---|---:|---:|",
    ]
    for manifest in sorted(manifests, key=lambda item: item.owner.machine_name):
        machine = manifest.owner.machine_name
        lines.append(
            f"| [{md_cell(machine)}]({page_url(f'machines/{machine}/README.md')}) "
            f"| {md_cell(manifest.project.name)} | {len(manifest.hoods)} | "
            f"{sum(entry.run_count for _hood, entry in manifest.hoods)} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_machine_page(
    manifest: V2OwnerManifest, snapshots: tuple[V2HoodSnapshot, ...]
) -> str:
    """Render one machine's hood index."""

    username = manifest.owner.username
    machine = manifest.owner.machine_name
    lines = [
        f"# {md_escape(username)} / {md_escape(machine)}",
        "",
        "[Agent Hoods](../../../../README.md) / "
        f"[{md_escape(username)}](../../README.md) / {md_escape(machine)}",
        "",
        f"**Project:** {md_escape(manifest.project.name)} · **Hoods:** "
        f"{len(snapshots)} · **Runs:** {sum(len(item.runs) for item in snapshots)}",
        "",
        "| Hood | Runs | Families | States |",
        "|---|---:|---:|---|",
    ]
    for snapshot in sorted(snapshots, key=lambda item: item.local_hood):
        states = state_counts(snapshot.runs)
        lines.append(
            f"| [{md_cell(snapshot.local_hood)}]"
            f"({page_url(f'hoods/{snapshot.local_hood}/README.md')}) "
            f"| {len(snapshot.runs)} | "
            f"{sum(item.kind == 'family' for item in snapshot.containers)} "
            f"| {md_cell(states)} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_hood_page(snapshot: V2HoodSnapshot, hood_root: str) -> str:
    """Render a hood's run roster."""

    owner = snapshot.owner
    machine_rel = "../../README.md"
    user_rel = "../../../../README.md"
    root_rel = "../../../../../../README.md"
    lines = [
        f"# Hood: {md_escape(snapshot.local_hood)}",
        "",
        f"[Agent Hoods]({page_url(root_rel)}) / "
        f"[{md_escape(owner.username)}]({page_url(user_rel)}) / "
        f"[{md_escape(owner.machine_name)}]({page_url(machine_rel)}) / "
        f"{md_escape(snapshot.local_hood)}",
        "",
        f"**Global hood:** `{md_code(snapshot.global_hood)}` · "
        f"**Runs:** {len(snapshot.runs)} · **Families:** "
        f"{sum(item.kind == 'family' for item in snapshot.containers)} · "
        f"**States:** {md_escape(state_counts(snapshot.runs))}",
        "",
        "| Agent | State | Model / provider | Timing | Commits | Files |",
        "|---|---|---|---|---:|---|",
    ]
    for run in snapshot.runs:
        target = agent_link_target(run.local_name, owner)
        target_path = target.path + (
            f"#{target.anchor}" if target.anchor is not None else ""
        )
        link = relative_page_url(f"{hood_root}/README.md", target_path)
        metadata = dict(run.metadata)
        model = " / ".join(
            value
            for value in (
                _text(metadata.get("model")),
                _text(metadata.get("llm_provider")),
            )
            if value
        )
        file_links = ", ".join(
            f"[{md_escape(kind)}]"
            f"({relative_page_url(f'{hood_root}/README.md', ref.path)})"
            for kind, ref in run.files
            if kind in {"prompt", "chat"}
        )
        lines.append(
            f"| [{md_cell(run.local_name)}]({link}) | {md_cell(run.state)} "
            f"| {md_cell(model or '—')} | {md_cell(run_timing(run))} "
            f"| {len(run.commits)} | {file_links or '—'} |"
        )
    lines.append("")
    return "\n".join(lines)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = [
    "render_hood_page",
    "render_machine_page",
    "render_root_page",
    "render_user_page",
]
