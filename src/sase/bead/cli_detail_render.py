"""Top-level human-readable bead detail rendering."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.cli_common import status_icon
from sase.bead.cli_dep_render import ANSI_BOLD_BLUE
from sase.bead.cli_detail_resolution import IssueDetail
from sase.bead.cli_detail_sections import (
    description_and_task_type_lines,
    display_design_path,
    lineage_kind,
    phase_size_field,
    prose_lines,
    render_artifact_link_section_lines,
    render_close_history_lines,
    render_flag_lines,
    render_plus_one_evidence_lines,
    render_snooze_lines,
    task_type_field,
)
from sase.bead.cli_detail_style import DetailPalette, DetailStyle
from sase.bead.flag_fields import flag_fields
from sase.bead.model import BeadTier, IssueType, Status
from sase.bead.plus_one_presentation import (
    PLUS_ONE_CLI_STYLE,
    POST_CLOSE_CLI_STYLE,
    post_close_plus_one_badge,
    post_close_plus_one_count,
    plus_one_badge,
)
from sase.bead.reopen_presentation import REOPEN_CLI_STYLE, reopen_badge
from sase.bead_status_presentation import bead_status_presentation
from sase.bead_time_presentation import (
    BEAD_TIME_CLI_STYLE,
    BEAD_TIME_UNKNOWN_LABEL,
    bead_created_label,
)
from sase.bead_type_presentation import bead_type_presentation


def render_issue_detail(
    detail: IssueDetail,
    *,
    relativize_design: bool,
    plan_roots: tuple[Path, ...] = (),
    reference_context: ArtifactRefContext | None = None,
    creator_url: str | None = None,
    page_url: str | None = None,
    style: DetailStyle = DetailStyle.PLAIN,
    wrap: int | None = None,
    present_creator: Callable[[str], str],
) -> str:
    """Render the established human-readable bead detail block."""
    issue = detail.issue
    palette = DetailPalette.for_style(style)
    status = bead_status_presentation(issue.status)
    badge = plus_one_badge(issue.plus_one_count)
    reopened = reopen_badge(len(issue.close_history))
    post_close = post_close_plus_one_badge(post_close_plus_one_count(issue))
    lines = [
        (
            f"{palette.accent(status_icon(issue.status), status.cli_style)} "
            f"{palette.accent(issue.id, ANSI_BOLD_BLUE)} "
            f"{palette.separator('·')} {palette.title(issue.title)}"
            f"   {palette.accent(f'[{issue.status.value.upper()}]', status.cli_style)}"
            + (f" {palette.accent(f'[{badge}]', PLUS_ONE_CLI_STYLE)}" if badge else "")
            + (
                f" {palette.accent(f'[{reopened}]', REOPEN_CLI_STYLE)}"
                if reopened
                else ""
            )
            + (
                f" {palette.accent(f'[{post_close}]', POST_CLOSE_CLI_STYLE)}"
                if post_close
                else ""
            )
        )
    ]
    type_value = palette.accent(
        issue.issue_type.value, bead_type_presentation(issue.issue_type).cli_style
    )
    tier = (
        f" {palette.separator('·')} {palette.label('Tier:')} "
        f"{palette.tier(issue.tier.value)}"
        if issue.tier
        else ""
    )
    owner = issue.owner or palette.placeholder("(none)")
    lines.append(
        f"{palette.label('Type:')} {type_value}{tier} "
        f"{palette.separator('·')} {palette.label('Owner:')} {owner}"
    )
    if issue.assignee:
        lines.append(f"{palette.label('Assignee:')} {issue.assignee}")
    if issue.status == Status.CLAIMED:
        lines.append(
            f"{palette.label('Claimed by:')} {issue.assignee} "
            "(agent has not started working yet)"
        )
    if issue.model:
        lines.append(f"{palette.label('Model:')} {issue.model}")
    if issue.issue_type in {IssueType.PHASE, IssueType.TASK}:
        lines.append(f"{palette.label('Size:')} {phase_size_field(issue, palette)}")
    if issue.issue_type is IssueType.TASK:
        lines.append(f"{palette.label('Task type:')} {task_type_field(issue, palette)}")

    created_label = bead_created_label(issue.created_at)
    created_value = (
        palette.placeholder(created_label)
        if created_label == BEAD_TIME_UNKNOWN_LABEL
        else palette.accent(created_label, BEAD_TIME_CLI_STYLE)
    )
    lines.extend(["", palette.section("CREATED"), f"  {created_value}"])

    if issue.created_by:
        try:
            creator_label = present_creator(issue.created_by)
        except Exception:
            creator_label = issue.created_by
        lines.extend(["", palette.section("CREATED BY"), f"  {creator_label}"])
        if creator_url:
            lines.append(f"  {palette.separator('→')} {palette.url(creator_url)}")

    if page_url:
        lines.extend(["", palette.section("PAGE"), f"  {palette.url(page_url)}"])

    if issue.status == Status.CLOSED:
        resolution_value = (
            issue.resolution.value
            if issue.resolution
            else palette.placeholder("(unrecorded)")
        )
        close_reason_value = issue.close_reason or palette.placeholder("(none)")
        closed_at_value = issue.closed_at or palette.placeholder("(unknown)")
        lines.extend(
            [
                "",
                palette.section("RESOLUTION"),
                f"  {palette.label('Resolution:')} {resolution_value}",
                f"  {palette.label('Close reason:')} {close_reason_value}",
                f"  {palette.label('Closed at:')} {closed_at_value}",
            ]
        )

    if issue.snooze is not None:
        lines.extend(
            render_snooze_lines(
                issue,
                palette=palette,
                style=style,
                wrap=wrap,
            )
        )

    if flag_fields(issue) is not None:
        lines.extend(render_flag_lines(issue, palette=palette))

    if issue.close_history:
        lines.extend(
            render_close_history_lines(
                issue,
                palette=palette,
                style=style,
                wrap=wrap,
            )
        )

    if issue.parent_id:
        lineage = [palette.accent(issue.id, ANSI_BOLD_BLUE)]
        for ancestor in detail.ancestors:
            if ancestor.issue is None:
                lineage.append(
                    f"{palette.accent(ancestor.issue_id, ANSI_BOLD_BLUE)} "
                    f"{palette.dangling('(not found)')}"
                )
            else:
                lineage.append(
                    f"{lineage_kind(ancestor.issue)} "
                    f"{palette.accent(ancestor.issue.id, ANSI_BOLD_BLUE)}"
                )
        arrow = f" {palette.separator('←')} "
        lines.extend(
            [
                "",
                palette.section("PARENT"),
                f"  {palette.separator('↑')} {arrow.join(lineage)}",
            ]
        )

    if detail.phases or detail.child_epics:
        lines.extend(["", palette.section("CHILDREN")])
        if detail.phases:
            lines.append(f"  {palette.subsection('PHASES')}")
            for child_ref in detail.phases:
                child = child_ref.issue
                assert child is not None
                child_status = bead_status_presentation(child.status)
                lines.append(
                    f"    {palette.accent(status_icon(child.status), child_status.cli_style)}"
                    f" {palette.accent(child.id, ANSI_BOLD_BLUE)}: {child.title}"
                    "   "
                    f"{palette.accent(f'[{child.status.value.upper()}]', child_status.cli_style)}"
                    f" {palette.separator('·')} {palette.label('Size:')} "
                    f"{phase_size_field(child, palette)}"
                )
        if detail.child_epics:
            lines.append(f"  {palette.subsection('CHILD EPICS')}")
            for child_ref in detail.child_epics:
                child = child_ref.issue
                assert child is not None
                child_status = bead_status_presentation(child.status)
                child_tier = (
                    palette.tier(child.tier.value)
                    if child.tier
                    else palette.placeholder("(none)")
                )
                lines.append(
                    f"    {palette.accent(status_icon(child.status), child_status.cli_style)}"
                    f" {palette.accent(child.id, ANSI_BOLD_BLUE)}: {child.title}"
                    "   "
                    f"{palette.accent(f'[{child.status.value.upper()}]', child_status.cli_style)}"
                    f" {palette.separator('·')} {palette.label('Tier:')} {child_tier}"
                )

    if detail.depends_on:
        lines.extend(["", palette.section("DEPENDS ON")])
        for dependency in detail.depends_on:
            dep_issue = dependency.issue
            if dep_issue is None:
                lines.append(
                    f"  {palette.separator('→')} "
                    f"{palette.accent(dependency.issue_id, ANSI_BOLD_BLUE)} "
                    f"{palette.dangling('(not found)')}"
                )
            else:
                dep_status = bead_status_presentation(dep_issue.status)
                lines.append(
                    f"  {palette.separator('→')} "
                    f"{palette.accent(status_icon(dep_issue.status), dep_status.cli_style)}"
                    f" {palette.accent(dep_issue.id, ANSI_BOLD_BLUE)}:"
                    f" {dep_issue.title}   "
                    f"{palette.accent(f'[{dep_issue.status.value.upper()}]', dep_status.cli_style)}"
                )

    if detail.blocks:
        lines.extend(["", palette.section("BLOCKS")])
        for blocked_ref in detail.blocks:
            blocked = blocked_ref.issue
            if blocked is None:
                lines.append(
                    f"  {palette.separator('←')} "
                    f"{palette.accent(blocked_ref.issue_id, ANSI_BOLD_BLUE)} "
                    f"{palette.dangling('(not found)')}"
                )
            else:
                blocked_status = bead_status_presentation(blocked.status)
                lines.append(
                    f"  {palette.separator('←')} "
                    f"{palette.accent(status_icon(blocked.status), blocked_status.cli_style)}"
                    f" {palette.accent(blocked.id, ANSI_BOLD_BLUE)}:"
                    f" {blocked.title}   "
                    f"{palette.accent(f'[{blocked.status.value.upper()}]', blocked_status.cli_style)}"
                )

    if detail.include_links:
        lines.extend(
            render_artifact_link_section_lines(
                detail.artifact_links,
                palette=palette,
                style=style,
                wrap=wrap,
            )
        )

    description_lines = description_and_task_type_lines(issue, style=style, wrap=wrap)
    if description_lines:
        lines.extend(["", palette.section("DESCRIPTION"), *description_lines])
    if issue.notes_text.strip():
        lines.extend(
            [
                "",
                palette.section("NOTES"),
                *prose_lines(
                    issue.notes_text,
                    style=style,
                    wrap=wrap,
                    indent="  ",
                ),
            ]
        )
    if issue.plus_one_evidence:
        lines.extend(
            render_plus_one_evidence_lines(
                issue,
                palette=palette,
                style=style,
                wrap=wrap,
                reference_context=reference_context,
            )
        )
    if issue.issue_type == IssueType.PLAN and (
        issue.changespec_name or issue.changespec_bug_id
    ):
        lines.extend(["", palette.section("PATCH")])
        if issue.changespec_name:
            lines.append(f"  {palette.label('Name:')} {issue.changespec_name}")
        if issue.changespec_bug_id:
            lines.append(f"  {palette.label('Bug ID:')} {issue.changespec_bug_id}")

    if issue.external_ref:
        lines.extend(["", palette.section("EXTERNAL")])
        lines.append(f"  {palette.label('Ref:')} {issue.external_ref}")

    if detail.plan is not None:
        plan = detail.plan
        lines.extend(["", palette.section(plan.section)])
        if plan.from_ref is not None:
            resolved_parent = plan.from_ref.issue
            assert resolved_parent is not None
            parent_kind = "epic" if resolved_parent.tier == BeadTier.EPIC else "plan"
            lines.append(
                f"  {palette.separator(f'From parent {parent_kind} bead')} "
                f"{palette.accent(resolved_parent.id, ANSI_BOLD_BLUE)} "
                f"{palette.separator('·')} {resolved_parent.title}"
            )
        lines.extend(
            f"  {palette.path(line)}"
            for line in display_design_path(
                plan.path,
                relativize=relativize_design,
                plan_roots=plan_roots,
            )
        )

    if issue.refs:
        from sase.artifact_ref_lists import (
            ArtifactRefListEntry,
            artifact_ref_list_display_lines,
            resolve_artifact_ref_list,
        )

        resolved_refs: Iterable[ArtifactRefListEntry | str] = issue.refs
        if reference_context is not None:
            try:
                resolved_refs = resolve_artifact_ref_list(
                    issue.refs,
                    context=reference_context,
                )
            except (OSError, RuntimeError, ValueError):
                pass
        lines.extend(["", palette.section("REFS")])
        lines.extend(
            f"  {palette.path(line)}"
            for line in artifact_ref_list_display_lines(resolved_refs)
        )

    return "\n".join(lines) + "\n"
