"""Pure deterministic Markdown rendering for browsable v2 publications."""

from __future__ import annotations

from collections import defaultdict
import posixpath
from urllib.parse import quote

from sase.agents_sync.v2_models import (
    V2ContainerRecord,
    V2FileReference,
    V2HoodSnapshot,
    V2OwnerManifest,
    V2RunRecord,
)
from sase.core.agent_identity_facade import (
    AgentFamilyNameKind,
    agent_link_target,
    parse_agent_family_name,
)


def render_browsing_payload(
    manifests: tuple[V2OwnerManifest, ...],
    snapshots: dict[tuple[str, str, str], V2HoodSnapshot],
) -> dict[str, bytes]:
    """Render every derived page from validated manifests and snapshots."""

    payload: dict[str, bytes] = {}
    ordered = tuple(
        sorted(
            manifests,
            key=lambda item: (item.owner.username, item.owner.machine_name),
        )
    )
    payload["README.md"] = _bytes(_render_root(ordered))

    by_user: dict[str, list[V2OwnerManifest]] = defaultdict(list)
    for manifest in ordered:
        by_user[manifest.owner.username].append(manifest)
    for username, user_manifests in sorted(by_user.items()):
        payload[f"users/{username}/README.md"] = _bytes(
            _render_user(username, tuple(user_manifests))
        )
        for manifest in user_manifests:
            machine_root = f"users/{username}/machines/{manifest.owner.machine_name}"
            machine_snapshots = tuple(
                snapshots[(username, manifest.owner.machine_name, hood)]
                for hood, _entry in manifest.hoods
            )
            payload[f"{machine_root}/README.md"] = _bytes(
                _render_machine(manifest, machine_snapshots)
            )
            for snapshot in machine_snapshots:
                hood_root = f"{machine_root}/hoods/{snapshot.local_hood}"
                payload[f"{hood_root}/README.md"] = _bytes(
                    _render_hood(snapshot, hood_root)
                )
                payload.update(_render_run_pages(snapshot))
    return payload


def _render_root(manifests: tuple[V2OwnerManifest, ...]) -> str:
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
            f"| [{_cell(username)}]({_url(f'users/{username}/README.md')}) "
            f"| {len(rows)} | {hoods} | {runs} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_user(username: str, manifests: tuple[V2OwnerManifest, ...]) -> str:
    lines = [
        f"# {_md(username)}",
        "",
        "[Agent Hoods](../../README.md) / " + _md(username),
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
            f"| [{_cell(machine)}]({_url(f'machines/{machine}/README.md')}) "
            f"| {_cell(manifest.project.name)} | {len(manifest.hoods)} | "
            f"{sum(entry.run_count for _hood, entry in manifest.hoods)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_machine(
    manifest: V2OwnerManifest, snapshots: tuple[V2HoodSnapshot, ...]
) -> str:
    username = manifest.owner.username
    machine = manifest.owner.machine_name
    lines = [
        f"# {_md(username)} / {_md(machine)}",
        "",
        "[Agent Hoods](../../../../README.md) / "
        f"[{_md(username)}](../../README.md) / {_md(machine)}",
        "",
        f"**Project:** {_md(manifest.project.name)} · **Hoods:** "
        f"{len(snapshots)} · **Runs:** {sum(len(item.runs) for item in snapshots)}",
        "",
        "| Hood | Runs | Families | States |",
        "|---|---:|---:|---|",
    ]
    for snapshot in sorted(snapshots, key=lambda item: item.local_hood):
        states = _state_counts(snapshot.runs)
        lines.append(
            f"| [{_cell(snapshot.local_hood)}]"
            f"({_url(f'hoods/{snapshot.local_hood}/README.md')}) "
            f"| {len(snapshot.runs)} | "
            f"{sum(item.kind == 'family' for item in snapshot.containers)} "
            f"| {_cell(states)} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_hood(snapshot: V2HoodSnapshot, hood_root: str) -> str:
    owner = snapshot.owner
    machine_rel = "../../README.md"
    user_rel = "../../../../README.md"
    root_rel = "../../../../../../README.md"
    lines = [
        f"# Hood: {_md(snapshot.local_hood)}",
        "",
        f"[Agent Hoods]({_url(root_rel)}) / "
        f"[{_md(owner.username)}]({_url(user_rel)}) / "
        f"[{_md(owner.machine_name)}]({_url(machine_rel)}) / "
        f"{_md(snapshot.local_hood)}",
        "",
        f"**Global hood:** `{_code(snapshot.global_hood)}` · "
        f"**Runs:** {len(snapshot.runs)} · **Families:** "
        f"{sum(item.kind == 'family' for item in snapshot.containers)} · "
        f"**States:** {_md(_state_counts(snapshot.runs))}",
        "",
        "| Agent | State | Model / provider | Timing | Commits | Files |",
        "|---|---|---|---|---:|---|",
    ]
    for run in snapshot.runs:
        target = agent_link_target(run.local_name, owner)
        target_path = target.path + (
            f"#{target.anchor}" if target.anchor is not None else ""
        )
        link = _relative_url(f"{hood_root}/README.md", target_path)
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
            f"[{_md(kind)}]({_relative_url(f'{hood_root}/README.md', ref.path)})"
            for kind, ref in run.files
            if kind in {"prompt", "chat"}
        )
        lines.append(
            f"| [{_cell(run.local_name)}]({link}) | {_cell(run.state)} "
            f"| {_cell(model or '—')} | {_cell(_timing(run))} "
            f"| {len(run.commits)} | {file_links or '—'} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_run_pages(snapshot: V2HoodSnapshot) -> dict[str, bytes]:
    payload: dict[str, bytes] = {}
    by_id = {run.source_run_id: run for run in snapshot.runs}
    family_ids: set[str] = set()
    for container in snapshot.containers:
        if container.kind != "family":
            continue
        family_ids.update(container.member_source_run_ids)
        payload[f"families/{container.global_name}.md"] = _bytes(
            _render_family(snapshot, container, by_id)
        )
    for run in snapshot.runs:
        payload[f"agents/{run.global_name}/README.md"] = _bytes(
            _render_agent(snapshot, run, in_family=run.source_run_id in family_ids)
        )
    return payload


def _render_family(
    snapshot: V2HoodSnapshot,
    family: V2ContainerRecord,
    by_id: dict[str, V2RunRecord],
) -> str:
    members = tuple(by_id[source_id] for source_id in family.member_source_run_ids)
    local_family = family.global_name.removeprefix(
        f"{snapshot.owner.username}.{snapshot.owner.machine_name}."
    )
    lines = [
        f"# Family: {_md(local_family)}",
        "",
        f"Owner: `{_code(snapshot.owner.username)}."
        f"{_code(snapshot.owner.machine_name)}` · "
        f"Hood: `{_code(snapshot.local_hood)}` · Members: {len(members)}",
        "",
        "## Lineage",
        "",
        "```mermaid",
        "flowchart TD",
    ]
    for index, run in enumerate(members):
        label = _mermaid(f"{run.local_name} [{run.state}]")
        lines.append(f'  n{index}["{label}"]')
        if index:
            lines.append(f"  n0 --> n{index}")
    lines.extend(
        [
            "```",
            "",
            "The diagram is an optional enhancement; the ordered table below "
            "contains the same lineage in accessible text.",
            "",
            "| Role | Agent | State | Model / provider | Timing | Commits | Prompt | Chat |",
            "|---|---|---|---|---|---:|---|---|",
        ]
    )
    for run in members:
        parsed = parse_agent_family_name(run.local_name)
        role = (
            parsed.member_role or "root"
            if parsed.kind is AgentFamilyNameKind.MEMBER
            else "root"
        )
        metadata = dict(run.metadata)
        model = " / ".join(
            value
            for value in (
                _text(metadata.get("model")),
                _text(metadata.get("llm_provider")),
            )
            if value
        )
        refs = dict(run.files)
        prompt = _family_file_link(refs.get("prompt"), "Prompt")
        chat = _family_file_link(refs.get("chat"), "Chat")
        anchor = f'<a id="member-{_html_id(role)}"></a>'
        lines.append(
            f"| {anchor}{_cell(role)} | {_cell(run.local_name)} | {_cell(run.state)} "
            f"| {_cell(model or '—')} | {_cell(_timing(run))} "
            f"| {len(run.commits)} | {prompt} | {chat} |"
        )
    lines.append("")
    return "\n".join(lines)


def _render_agent(
    snapshot: V2HoodSnapshot, run: V2RunRecord, *, in_family: bool
) -> str:
    metadata = dict(run.metadata)
    lines = [
        f"# Agent: {_md(run.local_name)}",
        "",
        f"**Global name:** `{_code(run.global_name)}` · **State:** "
        f"{_md(run.state)} · **Source run:** `{_code(run.source_run_id)}`",
        "",
        f"**Owner:** `{_code(snapshot.owner.username)}."
        f"{_code(snapshot.owner.machine_name)}` · "
        f"**Project:** {_md(snapshot.project.name)} · "
        f"**Hood:** {_md(snapshot.local_hood)}",
        "",
    ]
    if in_family:
        target = agent_link_target(run.local_name, snapshot.owner)
        if target.anchor:
            lines.extend(
                [
                    f"This run is represented in its "
                    f"[family lineage]({_relative_url(f'agents/{run.global_name}/README.md', target.path + '#' + target.anchor)}).",
                    "",
                ]
            )
    lines.extend(
        [
            "## Summary",
            "",
            f"- Model: {_md(_text(metadata.get('model')) or '—')}",
            f"- Provider: {_md(_text(metadata.get('llm_provider')) or '—')}",
            f"- Timing: {_md(_timing(run))}",
            f"- Commits: {len(run.commits)}",
            "",
        ]
    )
    refs = dict(run.files)
    links = [
        f"[{kind.title()}]({_relative_url(f'agents/{run.global_name}/README.md', ref.path)})"
        for kind, ref in sorted(refs.items())
        if kind in {"prompt", "chat"}
    ]
    if links:
        lines.extend(["## Files", "", " · ".join(links), ""])
    return "\n".join(lines)


def _family_file_link(reference: V2FileReference | None, label: str) -> str:
    if reference is None:
        return "—"
    return f"[{label}]({_relative_url('families/x.md', reference.path)})"


def _relative_url(source: str, target: str) -> str:
    path, marker, anchor = target.partition("#")
    relative = posixpath.relpath(path, posixpath.dirname(source))
    suffix = f"#{quote(anchor, safe='-._')}" if marker else ""
    return _url(relative) + suffix


def _state_counts(runs: tuple[V2RunRecord, ...]) -> str:
    counts: dict[str, int] = defaultdict(int)
    for run in runs:
        counts[run.state] += 1
    return ", ".join(f"{state} {count}" for state, count in sorted(counts.items()))


def _timing(run: V2RunRecord) -> str:
    if run.started_at and run.finished_at:
        return f"{run.started_at} → {run.finished_at}"
    return run.started_at or run.finished_at or run.dismissed_at or "—"


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _bytes(text: str) -> bytes:
    return text.encode("utf-8")


def _md(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("`", "\\`")
        .replace("*", "\\*")
        .replace("_", "\\_")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace("|", "\\|")
        .replace("<", "\\<")
        .replace(">", "\\>")
    )


def _cell(value: str) -> str:
    return _md(value).replace("\r", " ").replace("\n", "<br>")


def _code(value: str) -> str:
    return value.replace("`", "\\`").replace("\r", " ").replace("\n", " ")


def _mermaid(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", " ")
        .replace("\n", " ")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _html_id(value: str) -> str:
    return quote(value, safe="-._")


def _url(value: str) -> str:
    return quote(value, safe="/.-_")


__all__ = ["render_browsing_payload"]
