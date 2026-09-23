"""Fold-aware error/variable/text sections for clan detail rows."""

from __future__ import annotations

from collections import defaultdict

from rich.text import Text

from sase.core.output_variable_display import var_value_preview

from ...models._agent_clan_sections import (
    ClanErrorEntry,
    ClanTextEntry,
    ClanVariableEntry,
)
from ...models.fold_state import FoldLevel
from ._agent_display_clan_sections_common import (
    ClanMemberHintWorkspace,
    append_fold_heading,
    append_full_body,
    append_member_subheading,
    append_more_tail,
    append_traceback,
    append_triage_line,
    humanize_prompt_body,
    text_with_member_hints,
    _TRIAGE_ENTRY_LIMIT,
)
from ._agent_display_state import HeaderHintState
from ._hint_caps import HintContentBudget
from ._output_variable_rich import append_var_value_lines, var_value_style

# Member prompt bodies render tagified and accent-colored like every other
# AGENT XPROMPT surface (D5/D6). Replies stay plain prose.
_PROMPT_ENTRY_KINDS = frozenset({"AGENT XPROMPT", "AGENT PROMPT"})


def append_errors_section(
    text: Text,
    entries: tuple[ClanErrorEntry, ...],
    *,
    level: FoldLevel,
    hint_state: HeaderHintState | None = None,
    hint_budget: HintContentBudget | None = None,
    member_hint_workspace: ClanMemberHintWorkspace | None = None,
) -> None:
    """Render ERRORS as count-only, triage previews, or full diagnostics."""
    append_fold_heading(
        text,
        title="ERRORS",
        section_id="errors",
        level=level,
        count=len(entries),
    )
    if level == FoldLevel.COLLAPSED:
        return
    if level == FoldLevel.EXPANDED:
        for entry in entries[:_TRIAGE_ENTRY_LIMIT]:
            append_triage_line(
                text,
                entry.member_label,
                entry.preview,
                member_identity=entry.member_identity,
                hint_state=hint_state,
                hint_budget=hint_budget,
                member_hint_workspace=member_hint_workspace,
            )
        append_more_tail(text, len(entries), _TRIAGE_ENTRY_LIMIT)
        return
    for entry in entries:
        append_member_subheading(text, entry.member_label)
        append_full_body(
            text,
            entry.message,
            style="#FF8787",
            member_identity=entry.member_identity,
            hint_state=hint_state,
            hint_budget=hint_budget,
            member_hint_workspace=member_hint_workspace,
        )
        if entry.traceback:
            text.append("  traceback\n", style="bold #FF5F5F")
            append_traceback(
                text,
                entry.traceback,
                member_identity=entry.member_identity,
                hint_state=hint_state,
                hint_budget=hint_budget,
                member_hint_workspace=member_hint_workspace,
            )


def append_variables_section(
    text: Text,
    entries: tuple[ClanVariableEntry, ...],
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
    hint_state: HeaderHintState | None = None,
    hint_budget: HintContentBudget | None = None,
    member_hint_workspace: ClanMemberHintWorkspace | None = None,
) -> None:
    """Render variables as count-only, one-line assignments, or full values."""
    append_fold_heading(
        text,
        title=title,
        section_id=section_id,
        level=level,
        count=len(entries),
    )
    if level == FoldLevel.COLLAPSED:
        return
    if level == FoldLevel.EXPANDED:
        for entry in entries[:_TRIAGE_ENTRY_LIMIT]:
            value = var_value_preview(entry.value, max_chars=96) or "—"
            append_triage_line(
                text,
                f"{entry.member_label}.{entry.name}",
                value,
                separator=" = ",
                body_style=var_value_style(entry.value),
                member_identity=entry.member_identity,
                hint_state=hint_state,
                hint_budget=hint_budget,
                member_hint_workspace=member_hint_workspace,
            )
        append_more_tail(text, len(entries), _TRIAGE_ENTRY_LIMIT)
        return
    grouped: dict[str, list[ClanVariableEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.member_label].append(entry)
    for member_label, member_entries in grouped.items():
        append_member_subheading(text, member_label)
        for entry in member_entries:
            text.append(f"  {entry.name}\n", style="bold #87D7FF")
            value_text = Text()
            append_var_value_lines(
                value_text,
                entry.value,
                first_prefix=Text("    ", style="dim"),
                continuation_prefix="    ",
            )
            text.append_text(
                text_with_member_hints(
                    value_text,
                    member_identity=entry.member_identity,
                    hint_state=hint_state,
                    hint_budget=hint_budget,
                    member_hint_workspace=member_hint_workspace,
                )
            )


def append_text_section(
    text: Text,
    entries: tuple[ClanTextEntry, ...],
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
    hint_state: HeaderHintState | None = None,
    hint_budget: HintContentBudget | None = None,
    member_hint_workspace: ClanMemberHintWorkspace | None = None,
) -> None:
    """Render reply/prompt bodies as headings, previews, or full member bodies."""
    append_fold_heading(
        text,
        title=title,
        section_id=section_id,
        level=level,
        count=len(entries),
    )
    if level == FoldLevel.COLLAPSED:
        return
    if level == FoldLevel.EXPANDED:
        for entry in entries[:_TRIAGE_ENTRY_LIMIT]:
            label = entry.member_label
            if entry.kind == "AGENT XPROMPT":
                label += " [XPROMPT]"
            preview = entry.preview or "—"
            if entry.kind in _PROMPT_ENTRY_KINDS:
                preview = humanize_prompt_body(preview)
            append_triage_line(
                text,
                label,
                preview,
                kind=entry.kind,
                member_identity=entry.member_identity,
                hint_state=hint_state,
                hint_budget=hint_budget,
                member_hint_workspace=member_hint_workspace,
                highlight_project_tags=entry.kind in _PROMPT_ENTRY_KINDS,
            )
        append_more_tail(text, len(entries), _TRIAGE_ENTRY_LIMIT)
        return
    grouped: dict[str, list[ClanTextEntry]] = defaultdict(list)
    for entry in entries:
        grouped[entry.member_label].append(entry)
    for member_label, member_entries in grouped.items():
        append_member_subheading(text, member_label)
        for entry in member_entries:
            kind_style = (
                "bold #AF87FF" if entry.kind == "AGENT XPROMPT" else "bold #87D7FF"
            )
            text.append(f"  {entry.kind}\n", style=kind_style)
            append_full_body(
                text,
                entry.body,
                indent="    ",
                member_identity=entry.member_identity,
                hint_state=hint_state,
                hint_budget=hint_budget,
                member_hint_workspace=member_hint_workspace,
                highlight_project_tags=entry.kind in _PROMPT_ENTRY_KINDS,
            )
