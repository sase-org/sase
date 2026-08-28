"""Section and field helpers for human-readable bead detail rendering."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import sase
from sase.artifact_ref_models import ArtifactRefContext
from sase.bead.cli_detail_links import BeadLinkView, uses_label
from sase.bead.cli_detail_prose import highlight_prose
from sase.bead.cli_detail_style import DetailPalette, DetailStyle
from sase.bead.flag_due import flag_removal_due
from sase.bead.flag_fields import FlagFields, flag_fields
from sase.bead.model import BeadTier, Issue, IssueType
from sase.bead.note_presentation import (
    NOTE_CLI_STYLE,
    NOTE_SECTION_LABEL,
    bead_note_label,
)
from sase.bead.plus_one_presentation import (
    PLUS_ONE_CLI_STYLE,
    PLUS_ONE_SECTION_LABEL,
    POST_CLOSE_CLI_STYLE,
    POST_CLOSE_EVIDENCE_MARKER,
    evidence_recorded_after_current_close,
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
)
from sase.bead.snooze_presentation import (
    SNOOZE_CLI_STYLE,
    SNOOZE_SECTION_LABEL,
    snooze_plus_one_label,
    snooze_until_label,
)
from sase.bead_time_presentation import bead_instant_label
from sase.core import time as core_time
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


def render_artifact_link_section_lines(
    views: tuple[BeadLinkView, ...],
    *,
    palette: DetailPalette,
    style: DetailStyle,
    wrap: int | None,
) -> list[str]:
    """Render LINKS and REFERENCED BY from one projected neighborhood."""

    links = tuple(view for view in views if view.section == "links")
    referenced = tuple(view for view in views if view.section == "referenced_by")
    lines: list[str] = []
    if links:
        lines.extend(["", palette.section(f"LINKS ({len(links)})")])
        for view in links:
            lines.extend(
                _render_artifact_link_entry(
                    view, palette=palette, style=style, wrap=wrap
                )
            )
    if referenced:
        lines.extend(["", palette.section(f"REFERENCED BY ({len(referenced)})")])
        for view in referenced:
            lines.extend(
                _render_artifact_link_entry(
                    view, palette=palette, style=style, wrap=wrap
                )
            )
    return lines


def _render_artifact_link_entry(
    view: BeadLinkView,
    *,
    palette: DetailPalette,
    style: DetailStyle,
    wrap: int | None,
) -> list[str]:
    lines = [
        f"  {palette.separator(view.glyph)} {palette.label(view.displayed_relation)} "
        f"{palette.separator('·')} {palette.path(view.counterpart_ref)}"
    ]
    if view.reason:
        lines.extend(_prose_lines(view.reason, style=style, wrap=wrap, indent="    "))
    added = view.timestamp if view.timestamp.strip() else None
    actor = view.actor if view.actor.strip() else None
    added_text = added if added is not None else palette.placeholder("(unknown)")
    actor_text = actor if actor is not None else palette.placeholder("(unknown)")
    origin_text = view.origin_label or palette.placeholder("(unknown)")
    provenance = [origin_text]
    if view.section == "referenced_by":
        provenance.append(uses_label(view.uses))
    provenance.append(f"added {added_text} by {actor_text}")
    lines.append(f"    {palette.separator(' · '.join(provenance))}")
    return lines


def description_and_task_type_lines(
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


def render_snooze_lines(
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


def render_flag_lines(issue: Issue, *, palette: DetailPalette) -> list[str]:
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


def render_close_history_lines(
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


def render_bead_note_lines(
    issue: Issue,
    *,
    palette: DetailPalette,
    style: DetailStyle,
    wrap: int | None,
) -> list[str]:
    """Render one timestamped, attributed block for each note record."""

    if not issue.notes:
        return []
    lines = [
        "",
        palette.accent(f"{NOTE_SECTION_LABEL} ({len(issue.notes)})", NOTE_CLI_STYLE),
    ]
    for ordinal, note in enumerate(issue.notes, start=1):
        if ordinal > 1:
            lines.append("")
        lines.append(
            f"  {palette.accent(bead_note_label(note, ordinal, relative=True), NOTE_CLI_STYLE)}"
        )
        lines.extend(_prose_lines(note.text, style=style, wrap=wrap, indent="     "))
    return lines


def render_plus_one_evidence_lines(
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


def lineage_kind(issue: Issue) -> str:
    if issue.issue_type is not IssueType.PLAN:
        return issue.issue_type.value
    return "epic" if issue.tier == BeadTier.EPIC else "plan"


def _phase_size_display(issue: Issue) -> tuple[str, bool]:
    return (issue.size.value, False) if issue.size else ("small", True)


def phase_size_field(issue: Issue, palette: DetailPalette) -> str:
    value, defaulted = _phase_size_display(issue)
    field = palette.accent(value, phase_size_cli_style(value))
    if defaulted:
        field += f" {palette.placeholder(PHASE_SIZE_DEFAULT_MARKER)}"
    return field


def task_type_field(issue: Issue, palette: DetailPalette) -> str:
    presentation = task_type_presentation(issue.task_type)
    slug = issue_task_type_slug(issue.task_type)
    return palette.accent(f"{presentation.glyph} {slug}", presentation.cli_style)


def display_design_path(
    design: str,
    *,
    relativize: bool,
    plan_roots: tuple[Path, ...],
    cwd: Path | None = None,
) -> tuple[str, ...]:
    """Render the stable reference and where it currently resolves."""
    from sase.sdd.plan_ref_display import describe_design_reference

    return describe_design_reference(
        design,
        roots=plan_roots,
        cwd=Path.cwd() if cwd is None else cwd,
        relativize=relativize,
    ).lines
