"""Family browsing page rendering."""

from __future__ import annotations

from sase.agents_sync.rendering_commits import render_family_commits
from sase.agents_sync.rendering_kinship import (
    HoodKinshipProjection,
    render_neighbors_section,
)
from sase.agents_sync.rendering_markdown import (
    md_cell,
    md_code,
    md_escape,
    md_html_id,
    md_mermaid,
    relative_page_url,
    run_timing,
)
from sase.agents_sync.rendering_variables import render_family_variables
from sase.agents_sync.v2_models import (
    V2ContainerRecord,
    V2FileReference,
    V2HoodSnapshot,
    V2RunRecord,
)
from sase.core.agent_identity_facade import (
    AgentFamilyNameKind,
    parse_agent_family_name,
)


def render_family_page(
    snapshot: V2HoodSnapshot,
    family: V2ContainerRecord,
    by_id: dict[str, V2RunRecord],
    *,
    commit_url_base: str | None,
    commit_repo_name: str | None,
    kinship: HoodKinshipProjection,
) -> str:
    """Render one family container and its member lineage."""

    members = tuple(by_id[source_id] for source_id in family.member_source_run_ids)
    member_roles = tuple((_member_role(run), run) for run in members)
    local_family = _local_family_name(snapshot, family)
    source_path = f"families/{family.global_name}.md"
    lines = [
        f"# Family: {md_escape(local_family)}",
        "",
        _breadcrumb(snapshot, source_path, local_family),
        "",
        f"Owner: `{md_code(snapshot.owner.username)}."
        f"{md_code(snapshot.owner.machine_name)}` · "
        f"Hood: `{md_code(snapshot.local_hood)}` · Members: {len(members)}",
        "",
        "## Lineage",
        "",
        "```mermaid",
        "flowchart TD",
    ]
    for index, run in enumerate(members):
        label = md_mermaid(f"{run.local_name} [{run.state}]")
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
    for role, run in member_roles:
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
        anchor = f'<a id="member-{md_html_id(role)}"></a>'
        commit_count = (
            f"[{len(run.commits)}]"
            f"({relative_page_url(source_path, f'agents/{run.global_name}/README.md#commits')})"
            if run.commits
            else "0"
        )
        lines.append(
            f"| {anchor}{md_cell(role)} | {md_cell(run.local_name)} "
            f"| {md_cell(run.state)} | {md_cell(model or '—')} "
            f"| {md_cell(run_timing(run))} | {commit_count} "
            f"| {prompt} | {chat} |"
        )
    lines.append("")
    member_commits = tuple(
        (commit, _member_role(run)) for run in members for commit in run.commits
    )
    member_commit_shas = {commit.sha for commit, _role in member_commits}
    family_commits = (
        *member_commits,
        *(
            (commit, "—")
            for commit in family.commits
            if commit.sha not in member_commit_shas
        ),
    )
    if family_commits:
        lines.extend(
            [
                "## Commits",
                "",
                *render_family_commits(
                    family_commits,
                    commit_url_base=commit_url_base,
                    commit_repo_name=commit_repo_name,
                ),
                "",
            ]
        )
    lines.extend(render_family_variables(member_roles))
    lines.extend(
        render_neighbors_section(
            kinship,
            lane_name=local_family,
            source_path=source_path,
        )
    )
    return "\n".join(lines)


def _breadcrumb(snapshot: V2HoodSnapshot, source_path: str, local_family: str) -> str:
    owner = snapshot.owner
    return (
        f"[Agent Hoods]({relative_page_url(source_path, 'README.md')}) / "
        f"[{md_escape(owner.username)}]"
        f"({relative_page_url(source_path, f'users/{owner.username}/README.md')}) / "
        f"[{md_escape(owner.machine_name)}]"
        f"({relative_page_url(source_path, f'users/{owner.username}/machines/{owner.machine_name}/README.md')}) / "
        f"[{md_escape(snapshot.local_hood)}]"
        f"({relative_page_url(source_path, f'users/{owner.username}/machines/{owner.machine_name}/hoods/{snapshot.local_hood}/README.md')}) / "
        f"{md_escape(local_family)}"
    )


def _local_family_name(snapshot: V2HoodSnapshot, family: V2ContainerRecord) -> str:
    return family.global_name.removeprefix(
        f"{snapshot.owner.username}.{snapshot.owner.machine_name}."
    )


def _family_file_link(reference: V2FileReference | None, label: str) -> str:
    if reference is None:
        return "—"
    return f"[{label}]({relative_page_url('families/x.md', reference.path)})"


def _member_role(run: V2RunRecord) -> str:
    parsed = parse_agent_family_name(run.local_name)
    return (
        parsed.member_role or "root"
        if parsed.kind is AgentFamilyNameKind.MEMBER
        else "root"
    )


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = ["render_family_page"]
