"""Human-facing text rendered by the FlagTriage gate.

Every renderer here is reconstructed byte for byte by gate validation, so all
of it is a pure function of persisted fields: the removal countdown is derived
from the *pinned* ``due_as_of``/``release`` values carried in the payload,
never from a live clock or the installed release. The Notes section is
conditional: it is omitted entirely when a bead's notes are blank, rather than
rendered with a placeholder.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date

from sase.bead.model import FlagRecord, Issue, IssueType, Status
from sase.bead_flag_presentation import flag_due_presentation
from sase.bead_time_presentation import bead_created_label
from sase.task_type_gate_presentation import (
    TaskTypeGateDisplay,
    task_type_gate_markdown_fact,
)
from sase.task_types import TASK_TYPE_BODY_SEPARATOR, render_task_type_display_block

_UNREGISTERED_DEFINITION_CALLOUT = (
    "> [!WARNING] **No registry definition names this key.** "
    "`tools/check_feature_flags` treats a live flag bead with no matching "
    "definition as an error.\n\n"
)
_FLAG_TRIAGE_ANSWERS = (
    "## Answers\n\n"
    "- **Remove** deletes the Off branch and makes the On branch unconditional.\n"
    "- **Extend** pushes both thresholds out.\n"
    "- **Keep** means the behavior is permanent and belongs in a config field.\n"
    "- **Close** abandons the removal.\n"
)


def render_flag_triage_preview(
    *,
    bead_id: str,
    title: str,
    description: str,
    notes: str,
    flag: FlagRecord,
    due_as_of: str,
    release: str,
    definition: Mapping[str, str] | None = None,
    kind: str = "",
    created_by: str = "",
    created_at: str = "",
    size: str | None = None,
    task_type: str = "",
    task_type_fields: Mapping[str, str] | None = None,
    task_type_display: TaskTypeGateDisplay | None = None,
) -> str:
    """Render the reviewed Markdown detail shown by ACE and mobile clients.

    Every payload-derived field is rendered before ``## Description``, and the
    ``## Notes`` section is conditional, mirroring
    :func:`sase.bead._task_gate_preview.render_task_triage_preview` so gate
    validation's marker-slicing recovery works the same way here. The typed
    body block and the four-answer vocabulary sit after Notes so they stay
    outside the marker-delimited region.
    """
    stored_fields = dict(task_type_fields or {})
    description_text = description.strip() or "_No description._"
    notes_text = notes.strip()
    notes_section = f"\n\n## Notes\n\n{notes_text}" if notes_text else ""
    type_body = _flag_task_type_body(task_type, stored_fields)
    type_section = f"\n\n{TASK_TYPE_BODY_SEPARATOR}\n\n{type_body}" if type_body else ""
    filer = f"**Filed by:** `@{created_by}`\n\n" if created_by else ""
    created = (
        f"**Created:** {bead_created_label(created_at, relative=False)}\n\n"
        if created_at
        else ""
    )
    shown_kind = kind or (definition["kind"] if definition is not None else "")
    metadata = ""
    if size:
        metadata += f"**Size:** `{_markdown_code(size)}`\n\n"
    if shown_kind:
        metadata += f"**Kind:** `{_markdown_code(shown_kind)}`\n\n"
    if task_type_display is not None:
        metadata += f"{task_type_gate_markdown_fact(task_type_display, task_type)}\n\n"
    return (
        f"# {bead_id} — {title}\n\n"
        f"{_flag_triage_warning_block(flag, due_as_of=due_as_of, release=release)}"
        f"{filer}"
        f"{created}"
        f"{metadata}"
        f"{_flag_triage_definition_section(definition)}"
        f"## Description\n\n{description_text}"
        f"{notes_section}\n"
        f"{type_section}"
        f"\n{_FLAG_TRIAGE_ANSWERS}"
    )


def _flag_task_type_body(task_type: str, task_type_fields: Mapping[str, str]) -> str:
    if not task_type:
        return ""
    preview_issue = Issue(
        "preview",
        "",
        status=Status.OPEN,
        issue_type=IssueType.TASK,
        task_type=task_type,
        task_type_fields=dict(task_type_fields),
    )
    return render_task_type_display_block(preview_issue)


def flag_triage_presentation_note(
    bead_id: str,
    title: str,
    flag: FlagRecord,
    *,
    due_as_of: str,
    release: str,
) -> str:
    """Return the stable notification summary for one flag triage gate.

    The removal countdown rides along as computed from the *pinned*
    ``due_as_of``/``release`` values rather than the live clock or installed
    release, because gate validation recomputes this note and compares it
    with the persisted one; a live value would drift and fail that
    comparison.
    """
    presentation = flag_due_presentation(
        flag.remove_by_date,
        flag.remove_by_release,
        today=date.fromisoformat(due_as_of),
        release=release,
    )
    return f"{bead_id} [⚑ {flag.key}] — {title} · {presentation.label}"


def _flag_triage_warning_block(
    flag: FlagRecord, *, due_as_of: str, release: str
) -> str:
    """Render the callout naming the flag, its thresholds, and its status."""
    presentation = flag_due_presentation(
        flag.remove_by_date,
        flag.remove_by_release,
        today=date.fromisoformat(due_as_of),
        release=release,
    )
    return (
        f"> [!WARNING] **⚑ `{_markdown_code(flag.key)}` is due for removal**\n"
        ">\n"
        f"> **Remove by:** {flag.remove_by_date} · v{flag.remove_by_release}\n"
        f"> **Status:** {presentation.label} (as of {due_as_of}, release "
        f"v{release})\n\n"
    )


def _flag_triage_definition_section(definition: Mapping[str, str] | None) -> str:
    if definition is None:
        return _UNREGISTERED_DEFINITION_CALLOUT
    return f"## What this flag does\n\n{definition['description']}\n\n"


def _markdown_code(value: str) -> str:
    return value.replace("`", "\\`")


__all__ = [
    "flag_triage_presentation_note",
    "render_flag_triage_preview",
]
