"""Agent browsing page rendering."""

from __future__ import annotations

from sase.agents_sync.rendering_markdown import (
    md_code,
    md_escape,
    relative_page_url,
    run_timing,
)
from sase.agents_sync.v2_models import (
    V2ContainerRecord,
    V2HoodSnapshot,
    V2RunRecord,
)


def render_agent_page(
    snapshot: V2HoodSnapshot,
    run: V2RunRecord,
    *,
    family: V2ContainerRecord | None,
) -> str:
    """Render one agent run page."""

    metadata = dict(run.metadata)
    source_path = f"agents/{run.global_name}/README.md"
    lines = [
        f"# Agent: {md_escape(run.local_name)}",
        "",
        _breadcrumb(snapshot, run, source_path, family),
        "",
        f"**Global name:** `{md_code(run.global_name)}` · **State:** "
        f"{md_escape(run.state)} · **Source run:** `{md_code(run.source_run_id)}`",
        "",
        f"**Owner:** `{md_code(snapshot.owner.username)}."
        f"{md_code(snapshot.owner.machine_name)}` · "
        f"**Project:** {md_escape(snapshot.project.name)} · "
        f"**Hood:** {md_escape(snapshot.local_hood)}",
        "",
        "## Summary",
        "",
        f"- Model: {md_escape(_text(metadata.get('model')) or '—')}",
        f"- Provider: {md_escape(_text(metadata.get('llm_provider')) or '—')}",
        f"- Timing: {md_escape(run_timing(run))}",
        f"- Commits: {len(run.commits)}",
        "",
    ]
    refs = dict(run.files)
    links = [
        f"[{kind.title()}]({relative_page_url(source_path, ref.path)})"
        for kind, ref in sorted(refs.items())
        if kind in {"prompt", "chat"}
    ]
    if links:
        lines.extend(["## Files", "", " · ".join(links), ""])
    return "\n".join(lines)


def _breadcrumb(
    snapshot: V2HoodSnapshot,
    run: V2RunRecord,
    source_path: str,
    family: V2ContainerRecord | None,
) -> str:
    owner = snapshot.owner
    parts = [
        f"[Agent Hoods]({relative_page_url(source_path, 'README.md')})",
        f"[{md_escape(owner.username)}]"
        f"({relative_page_url(source_path, f'users/{owner.username}/README.md')})",
        f"[{md_escape(owner.machine_name)}]"
        f"({relative_page_url(source_path, f'users/{owner.username}/machines/{owner.machine_name}/README.md')})",
        f"[{md_escape(snapshot.local_hood)}]"
        f"({relative_page_url(source_path, f'users/{owner.username}/machines/{owner.machine_name}/hoods/{snapshot.local_hood}/README.md')})",
    ]
    if family is not None:
        local_family = family.global_name.removeprefix(
            f"{owner.username}.{owner.machine_name}."
        )
        parts.append(
            f"[{md_escape(local_family)}]"
            f"({relative_page_url(source_path, f'families/{family.global_name}.md')})"
        )
    parts.append(md_escape(run.local_name))
    return " / ".join(parts)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = ["render_agent_page"]
