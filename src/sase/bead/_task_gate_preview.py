"""Human-facing text rendered by the TaskTriage gate.

Every renderer here is reconstructed byte for byte by gate validation, so all
of it is a pure function of persisted fields: absolute instants and stored
counts, never a recomputed age or a live lookup. The Notes section is
conditional: it is omitted entirely when a bead's notes are blank, rather than
rendered with a placeholder.
"""

from __future__ import annotations

from collections.abc import Sequence

from sase.bead.model import CloseRecord, ReopenCause, TaskPlusOneEvidence
from sase.bead.plus_one_presentation import (
    PLUS_ONE_SECTION_LABEL,
    plus_one_badge,
    plus_one_evidence_label,
)
from sase.bead.reopen_presentation import (
    REOPEN_EVIDENCE_MARKER,
    REOPEN_GLYPH,
    close_history_display_order,
    evidence_reopened_bead,
    reopen_badge,
)
from sase.bead_time_presentation import bead_created_cli, bead_created_label

_MAX_GATE_TITLE_LENGTH = 120


def bounded_gate_title(bead_id: str, title: str) -> str:
    """Return the ``bead_id — title`` gate headline, bounded to one line.

    Bead titles carry no length cap of their own, but ``presentation.title``
    does (single line, at most 120 characters), so this is the one place that
    boundary is enforced before it reaches gate validation.
    """
    full = f"{bead_id} — {title}".replace("\n", " ")
    if len(full) <= _MAX_GATE_TITLE_LENGTH:
        return full
    return full[: _MAX_GATE_TITLE_LENGTH - 1].rstrip() + "…"


def render_task_triage_preview(
    *,
    bead_id: str,
    title: str,
    description: str,
    notes: str,
    created_by: str = "",
    created_at: str = "",
    size: str | None = None,
    refs: Sequence[str] = (),
    plus_one_evidence: Sequence[TaskPlusOneEvidence] = (),
    close_history: Sequence[CloseRecord] = (),
) -> str:
    """Render the reviewed Markdown detail shown by ACE and mobile clients.

    The creation time is rendered absolute-only: this preview is persisted and
    later reconstructed byte for byte by gate validation, so a relative age
    would make the gate fail validation as it aged. The same rule governs the
    prior-close callout: every field it renders is a persisted absolute
    instant, never a recomputed age. The Notes section itself is conditional:
    it is omitted entirely when notes are blank rather than rendered with a
    placeholder.
    """
    description_text = description.strip() or "_No description._"
    notes_text = notes.strip()
    notes_section = f"\n\n## Notes\n\n{notes_text}" if notes_text else ""
    filer = f"**Filed by:** `@{created_by}`\n\n" if created_by else ""
    created = (
        f"**Created:** {bead_created_label(created_at, relative=False)}\n\n"
        if created_at
        else ""
    )
    metadata = ""
    if size:
        metadata += f"**Size:** `{_markdown_code(size)}`\n\n"
    if refs:
        rendered_refs = ", ".join(f"`{_markdown_code(ref)}`" for ref in refs)
        metadata += f"**References:** {rendered_refs}\n\n"
    close_history_section = _task_triage_close_history_preview(close_history)
    evidence_section = _task_triage_evidence_preview(plus_one_evidence, close_history)
    return (
        f"# {bead_id} — {title}\n\n"
        f"{filer}"
        f"{created}"
        f"{metadata}"
        f"{close_history_section}"
        f"## Description\n\n{description_text}"
        f"{notes_section}\n"
        f"{evidence_section}"
    )


def task_triage_presentation_note(
    bead_id: str,
    title: str,
    count: int,
    *,
    created_at: str = "",
    reopen_count: int = 0,
) -> str:
    """Return the stable notification summary for one task triage gate.

    The creation time rides along as an immutable calendar date rather than an
    age, because gate validation recomputes this note and compares it with the
    persisted one; a relative age would drift and fail that comparison. The
    same rule is why the reopen badge is derived from the persisted close
    history count rather than any live-computed value.
    """

    badges = [
        badge for badge in (plus_one_badge(count), reopen_badge(reopen_count)) if badge
    ]
    suffix = "".join(f" [{badge}]" for badge in badges)
    created = (
        bead_created_cli(created_at, use_color=False, relative=False)
        if created_at
        else ""
    )
    created_suffix = f" · {created}" if created else ""
    return f"{bead_id}{suffix} — {title}{created_suffix}"


def _task_triage_close_history_preview(
    close_history: Sequence[CloseRecord],
) -> str:
    """Render the prior-close warning callout shown above the description.

    This is the highest-value surface in the epic: Launch is the gate's
    primary branch, so a previously-closed task is exactly the case where
    skimming past the default would be wrong. Newest first, so the freshest
    decision is the one a triager sees when there is more than one record.
    """
    if not close_history:
        return ""
    blocks: list[str] = []
    for record in close_history_display_order(close_history):
        resolution = record.resolution.value if record.resolution else "(unrecorded)"
        reason = (record.close_reason or "").strip() or "(none)"
        header = (
            f"> [!WARNING] **{REOPEN_GLYPH} Previously closed {record.closed_at} "
            f"as {resolution}** {reason}"
        )
        blocks.append(
            "\n".join([header, ">", f"> {_close_record_reopened_markdown(record)}"])
        )
    return "\n\n".join(blocks) + "\n\n"


def _close_record_reopened_markdown(record: CloseRecord) -> str:
    """Return the cause-specific ``Reopened ...`` line for one close record."""
    if record.reopened_via == ReopenCause.PLUS_ONE:
        if record.reopened_by:
            return (
                f"Reopened {record.reopened_at} by a +1 from `@{record.reopened_by}`."
            )
        return f"Reopened {record.reopened_at} by a +1."
    if record.reopened_via == ReopenCause.OPEN:
        return f"Reopened {record.reopened_at} by `sase bead open`."
    if record.reopened_via == ReopenCause.UPDATE:
        return f"Reopened {record.reopened_at} by a status update."
    return f"Reopened {record.reopened_at} by an epic work preclaim."


def _task_triage_evidence_preview(
    evidence_rows: Sequence[TaskPlusOneEvidence],
    close_history: Sequence[CloseRecord] = (),
) -> str:
    if not evidence_rows:
        return ""
    lines = ["", f"## {PLUS_ONE_SECTION_LABEL.title()}", ""]
    for index, evidence in enumerate(evidence_rows):
        if index:
            lines.append("")
        label = plus_one_evidence_label(evidence).replace("`", "\\`")
        if evidence_reopened_bead(evidence, close_history):
            label = f"{label} {REOPEN_EVIDENCE_MARKER}"
        lines.append(f"> [!TIP] **{label}**")
        lines.extend(
            f"> {line}" if line else ">" for line in evidence.note.splitlines()
        )
        if evidence.refs:
            rendered_refs = ", ".join(
                f"`{_markdown_code(ref)}`" for ref in evidence.refs
            )
            lines.extend([">", f"> **References:** {rendered_refs}"])
    return "\n".join(lines) + "\n"


def _markdown_code(value: str) -> str:
    return value.replace("`", "\\`")
