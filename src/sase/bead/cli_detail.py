"""Public bead detail API and human-readable rendering."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import sase
from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.cli_common import status_icon
from sase.bead.cli_dep_render import ANSI_BOLD_BLUE
from sase.bead.cli_detail_context import (
    artifact_reference_context,
    design_paths_are_relative,
    plan_reference_roots,
    resolve_bead_creator_url,
    resolve_bead_page_url,
)
from sase.bead.cli_detail_json import (
    issue_to_wire_dict,
    ref_to_wire_dict,
    render_issue_detail_json,
)
from sase.bead.cli_detail_prose import highlight_prose
from sase.bead.cli_detail_resolution import (
    IssueDetail,
    IssueDetailIndex,
    IssueRef,
    resolve_issue_detail,
)
from sase.bead.cli_detail_style import DetailPalette, DetailStyle
from sase.bead.flag_due import flag_removal_due
from sase.bead.flag_fields import FlagFields, flag_fields
from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.bead.plus_one_presentation import (
    PLUS_ONE_CLI_STYLE,
    PLUS_ONE_SECTION_LABEL,
    POST_CLOSE_CLI_STYLE,
    POST_CLOSE_EVIDENCE_MARKER,
    evidence_recorded_after_current_close,
    post_close_plus_one_badge,
    post_close_plus_one_count,
    plus_one_badge,
    plus_one_evidence_label,
)
from sase.bead.reopen_presentation import (
    REOPEN_CLI_STYLE,
    REOPEN_EVIDENCE_MARKER,
    REOPEN_SECTION_LABEL,
    close_history_display_order,
    close_record_label,
    close_record_reopened_label,
    evidence_reopened_bead,
    reopen_badge,
)
from sase.bead.snooze_presentation import (
    SNOOZE_CLI_STYLE,
    SNOOZE_SECTION_LABEL,
    snooze_plus_one_label,
    snooze_until_label,
)
from sase.bead_status_presentation import bead_status_presentation
from sase.bead_time_presentation import (
    BEAD_TIME_CLI_STYLE,
    BEAD_TIME_UNKNOWN_LABEL,
    bead_created_label,
    bead_instant_label,
)
from sase.bead_type_presentation import bead_type_presentation
from sase.core import time as core_time
from sase.core.agent_identity_facade import present_agent_name
from sase.markdown_wrap import MIN_PROSE_WRAP_WIDTH, wrap_markdown
from sase.phase_size_presentation import (
    PHASE_SIZE_DEFAULT_MARKER,
    phase_size_cli_style,
)
from sase.task_type_presentation import task_type_presentation
from sase.task_types import (
    TASK_TYPE_BODY_SEPARATOR,
    issue_task_type_slug,
    render_task_type_display_block,
)


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
) -> str:
    """Render the established human-readable bead detail block.

    Styling is purely additive ANSI: for any *detail*, *style*, and *wrap*,
    stripping SGR escapes from the output reproduces the matching
    ``DetailStyle.PLAIN`` bytes exactly.
    """
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
        lines.append(f"{palette.label('Size:')} {_phase_size_field(issue, palette)}")
    if issue.issue_type is IssueType.TASK:
        lines.append(
            f"{palette.label('Task type:')} {_task_type_field(issue, palette)}"
        )

    created_label = bead_created_label(issue.created_at)
    created_value = (
        palette.placeholder(created_label)
        if created_label == BEAD_TIME_UNKNOWN_LABEL
        else palette.accent(created_label, BEAD_TIME_CLI_STYLE)
    )
    lines.extend(["", palette.section("CREATED"), f"  {created_value}"])

    if issue.created_by:
        try:
            creator_label = present_agent_name(issue.created_by)
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
            _render_snooze_lines(
                issue,
                palette=palette,
                style=style,
                wrap=wrap,
            )
        )

    if flag_fields(issue) is not None:
        lines.extend(_render_flag_lines(issue, palette=palette))

    if issue.close_history:
        lines.extend(
            _render_close_history_lines(
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
                    f"{_lineage_kind(ancestor.issue)} "
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
                    f"{_phase_size_field(child, palette)}"
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

    description_lines = _description_and_task_type_lines(issue, style=style, wrap=wrap)
    if description_lines:
        lines.extend(["", palette.section("DESCRIPTION"), *description_lines])
    if issue.notes.strip():
        lines.extend(
            [
                "",
                palette.section("NOTES"),
                *_prose_lines(
                    issue.notes,
                    style=style,
                    wrap=wrap,
                    indent="  ",
                ),
            ]
        )
    if issue.plus_one_evidence:
        lines.extend(
            _render_plus_one_evidence_lines(
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
            for line in _display_design_path(
                plan.path,
                relativize=relativize_design,
                plan_roots=plan_roots,
            )
        )

    if issue.links:
        lines.extend(["", palette.section("LINKS")])
        for link in issue.links:
            lines.append(
                f"  {palette.label(link.relation)}  "
                f"{palette.path(link.target_ref)}  {link.description}"
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


def _description_and_task_type_lines(
    issue: Issue,
    *,
    style: DetailStyle,
    wrap: int | None,
) -> list[str]:
    lines: list[str] = []
    if issue.description:
        lines.extend(
            _prose_lines(
                issue.description,
                style=style,
                wrap=wrap,
                indent="  ",
            )
        )
    body = render_task_type_display_block(issue)
    if body:
        if lines:
            lines.extend(["", f"  {TASK_TYPE_BODY_SEPARATOR}", ""])
        lines.extend(_prose_lines(body, style=style, wrap=wrap, indent="  "))
    return lines


def _render_snooze_lines(
    issue: Issue,
    *,
    palette: DetailPalette,
    style: DetailStyle,
    wrap: int | None,
) -> list[str]:
    """Render the wake conditions a snoozed task is currently waiting on."""

    record = issue.snooze
    assert record is not None
    lines = [
        "",
        palette.accent(SNOOZE_SECTION_LABEL, SNOOZE_CLI_STYLE),
        f"  {palette.label('Until:')} "
        f"{palette.accent(snooze_until_label(record.until), SNOOZE_CLI_STYLE)}",
    ]
    if plus_one := snooze_plus_one_label(issue):
        lines.append(f"  {palette.label('+1 target:')} {plus_one}")
    lines.append(
        f"  {palette.label('Snoozed by:')} {record.snoozed_by} "
        f"{palette.separator('·')} {bead_instant_label(record.snoozed_at)}"
    )
    if record.reason:
        lines.append(f"  {palette.label('Reason:')}")
        lines.extend(_prose_lines(record.reason, style=style, wrap=wrap, indent="    "))
    return lines


def _render_flag_lines(issue: Issue, *, palette: DetailPalette) -> list[str]:
    """Render a flag bead's registry key, removal thresholds, and due state."""

    fields: FlagFields | None = flag_fields(issue)
    assert fields is not None
    due_state = flag_removal_due(
        fields.remove_by_date,
        fields.remove_by_release,
        today=core_time.local_now().date(),
        release=sase.__version__,
    )
    return [
        "",
        palette.section("FLAG"),
        f"  {palette.label('Key:')} {fields.key}",
        f"  {palette.label('Remove by:')} {fields.remove_by_date} "
        f"{palette.separator('·')} {fields.remove_by_release}",
        f"  {palette.label('Due state:')} {due_state}",
    ]


def _render_close_history_lines(
    issue: Issue,
    *,
    palette: DetailPalette,
    style: DetailStyle,
    wrap: int | None,
) -> list[str]:
    """Render archived close episodes newest first.

    This block never renders relative time: it is persisted verbatim into gate
    previews that gate validation re-derives and byte-compares, and the
    absolute date is the more useful fact at a go/no-go decision anyway.
    """

    lines = [
        "",
        palette.accent(REOPEN_SECTION_LABEL, REOPEN_CLI_STYLE),
    ]
    for record in close_history_display_order(issue.close_history):
        lines.append(
            f"  {palette.accent(close_record_label(record), REOPEN_CLI_STYLE)}"
        )
        if record.close_reason:
            lines.append(f"    {palette.label('Reason:')}")
            lines.extend(
                _prose_lines(
                    record.close_reason,
                    style=style,
                    wrap=wrap,
                    indent="      ",
                )
            )
        else:
            # "No reason was ever recorded" is itself information, so this
            # renders a placeholder line rather than omitting the field.
            lines.append(
                f"    {palette.label('Reason:')} {palette.placeholder('(none)')}"
            )
        lines.append(f"    {close_record_reopened_label(record)}")
    return lines


def _render_plus_one_evidence_lines(
    issue: Issue,
    *,
    palette: DetailPalette,
    style: DetailStyle,
    wrap: int | None,
    reference_context: ArtifactRefContext | None,
) -> list[str]:
    """Render structured corroboration without performing extra store reads."""

    from sase.artifact_ref_lists import (
        ArtifactRefListEntry,
        artifact_ref_list_display_lines,
        resolve_artifact_ref_list,
    )

    lines = [
        "",
        palette.accent(PLUS_ONE_SECTION_LABEL, PLUS_ONE_CLI_STYLE),
    ]
    for evidence in issue.plus_one_evidence:
        label = palette.accent(plus_one_evidence_label(evidence), PLUS_ONE_CLI_STYLE)
        if evidence_reopened_bead(evidence, issue.close_history):
            label += f"  {palette.accent(REOPEN_EVIDENCE_MARKER, REOPEN_CLI_STYLE)}"
        if evidence_recorded_after_current_close(issue, evidence):
            label += (
                f"  {palette.accent(POST_CLOSE_EVIDENCE_MARKER, POST_CLOSE_CLI_STYLE)}"
            )
        lines.append(f"  {label}")
        if evidence.observed_since:
            lines.append(
                f"    {palette.label('Observed since:')} {evidence.observed_since}"
            )
        lines.extend(_prose_lines(evidence.note, style=style, wrap=wrap, indent="    "))
        if not evidence.refs:
            continue
        resolved_refs: Iterable[ArtifactRefListEntry | str] = evidence.refs
        if reference_context is not None:
            try:
                resolved_refs = resolve_artifact_ref_list(
                    evidence.refs,
                    context=reference_context,
                )
            except (OSError, RuntimeError, ValueError):
                pass
        lines.append(f"    {palette.label('Refs:')}")
        lines.extend(
            f"      {palette.path(line)}"
            for line in artifact_ref_list_display_lines(resolved_refs)
        )
    return lines


def _prose_lines(
    text: str,
    *,
    style: DetailStyle,
    wrap: int | None,
    indent: str,
) -> list[str]:
    body = text
    if wrap is not None:
        content_width = wrap - len(indent)
        if content_width >= MIN_PROSE_WRAP_WIDTH:
            body = wrap_markdown(text, width=content_width)

    plain_lines = body.split("\n")
    styled_lines = highlight_prose(body, style=style).split("\n")
    if len(styled_lines) != len(plain_lines):
        styled_lines = plain_lines
    return [
        f"{indent}{styled}" if plain else ""
        for plain, styled in zip(plain_lines, styled_lines, strict=True)
    ]


def _lineage_kind(issue: Issue) -> str:
    if issue.issue_type is not IssueType.PLAN:
        return issue.issue_type.value
    return "epic" if issue.tier == BeadTier.EPIC else "plan"


def _phase_size_display(issue: Issue) -> tuple[str, bool]:
    return (issue.size.value, False) if issue.size else ("small", True)


def _phase_size_field(issue: Issue, palette: DetailPalette) -> str:
    value, defaulted = _phase_size_display(issue)
    field = palette.accent(value, phase_size_cli_style(value))
    if defaulted:
        field += f" {palette.placeholder(PHASE_SIZE_DEFAULT_MARKER)}"
    return field


def _task_type_field(issue: Issue, palette: DetailPalette) -> str:
    presentation = task_type_presentation(issue.task_type)
    slug = issue_task_type_slug(issue.task_type)
    return palette.accent(f"{presentation.glyph} {slug}", presentation.cli_style)


def _display_design_path(
    design: str,
    *,
    relativize: bool,
    plan_roots: tuple[Path, ...],
) -> tuple[str, ...]:
    """Render the stable reference and where it currently resolves."""
    from sase.sdd.plan_ref_display import describe_design_reference

    return describe_design_reference(
        design,
        roots=plan_roots,
        cwd=Path.cwd(),
        relativize=relativize,
    ).lines


__all__ = [
    "IssueDetail",
    "IssueDetailIndex",
    "IssueRef",
    "artifact_reference_context",
    "design_paths_are_relative",
    "issue_to_wire_dict",
    "plan_reference_roots",
    "ref_to_wire_dict",
    "render_issue_detail",
    "render_issue_detail_json",
    "resolve_bead_creator_url",
    "resolve_bead_page_url",
    "resolve_issue_detail",
]
