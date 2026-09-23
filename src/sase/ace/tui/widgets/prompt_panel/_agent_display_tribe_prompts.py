"""Fold-aware PROMPTS section for tribe detail documents.

The tribe's intent map: one headline per distinct prompt at a glance, with
deeper fold levels revealing labels, sizes, previews, and full prompt bodies.
All strings and style spans arrive precomputed from the worker-side digest, so
this renderer only appends text and replays spans.
"""

from __future__ import annotations

from collections.abc import Mapping

from rich.text import Text

from sase.project_tag_style import project_column_style

from ...models._agent_clan_sections import ClanAgentIdentity
from ...models.fold_state import FoldLevel
from ._agent_display_tribe_common import (
    BODY_STYLE,
    FIELD_LABEL_STYLE,
    SECTIONS,
    TRIAGE_LIMIT,
    TRIBE_IDENTITY_COLOR,
    append_fold_heading,
    effective_level,
)
from ._agent_tribe_aggregation import TribeSectionSnapshot
from ._agent_tribe_prompts import PromptDigest, TribePromptGroup, TribePromptMember
from ._helpers import append_fold_anchor

PROMPT_GLANCE_LIMIT = TRIAGE_LIMIT
PROMPT_LIST_LIMIT = 24
PROMPT_PREVIEW_LINES = 10
PROMPT_BODY_SAFETY_LINES = 500
PROMPT_ENTRY_ANCHOR_PREFIX = "tribe:prompt:"

_MEMBER_LABEL_STYLE = "bold #D75FFF"
_UNIT_LABEL_STYLE = f"bold {TRIBE_IDENTITY_COLOR}"
_SHARED_COUNT_STYLE = "bold #5FD7FF"
_XPROMPT_CHIP_STYLE = "bold #87D787"
_GUTTER_STYLE = "dim #8787AF"
_SIZE_STYLE = "dim"


def append_prompts(
    text: Text,
    section_snapshot: TribeSectionSnapshot | None,
    *,
    level: FoldLevel,
    overrides: Mapping[str, FoldLevel],
    unit_numbers: Mapping[ClanAgentIdentity, str],
) -> None:
    """Append the PROMPTS section after the TRIBE MEMBERS roster."""
    disk = section_snapshot.disk if section_snapshot is not None else None
    loaded = disk is not None and "prompts" in disk.loaded_sections
    snapshot = disk.prompts if loaded and disk is not None else None
    groups = snapshot.groups if snapshot is not None else ()
    if not loaded or not groups:
        return
    distinct = len(groups)
    agent_count = snapshot.agent_count if snapshot is not None else 0
    append_fold_heading(
        text,
        title="PROMPTS",
        section_id=SECTIONS.prompts,
        level=level,
        count=agent_count,
        summary=f"{distinct} distinct" if distinct < agent_count else None,
    )
    if level is FoldLevel.EXHAUSTIVE:
        shown = groups
        tail: str | None = None
        dim_tail = False
    else:
        limit = (
            PROMPT_GLANCE_LIMIT if level is FoldLevel.COLLAPSED else PROMPT_LIST_LIMIT
        )
        shown = groups[:limit]
        hidden = len(groups) - len(shown)
        tail = f"  +{hidden} more" if hidden > 0 else None
        dim_tail = level is FoldLevel.COLLAPSED
    multi_project = snapshot.multi_project if snapshot is not None else False
    for index, group in enumerate(shown):
        entry_level = effective_level(
            f"{PROMPT_ENTRY_ANCHOR_PREFIX}{group.digest.group_key}",
            level,
            overrides,
        )
        _append_prompt_entry(
            text,
            group,
            level=entry_level,
            unit_numbers=unit_numbers,
            multi_project=multi_project,
        )
        if entry_level in (FoldLevel.FULLY_EXPANDED, FoldLevel.EXHAUSTIVE):
            if index < len(shown) - 1:
                text.append("\n")
    if tail is not None:
        text.append(tail + "\n", style="dim" if dim_tail else "")


def _append_prompt_entry(
    text: Text,
    group: TribePromptGroup,
    *,
    level: FoldLevel,
    unit_numbers: Mapping[ClanAgentIdentity, str],
    multi_project: bool,
) -> None:
    """Append one independently foldable prompt entry line and its body."""
    digest: PromptDigest = group.digest
    members: tuple[TribePromptMember, ...] = group.members
    line = Text()
    units: list[ClanAgentIdentity] = []
    for member in members:
        if member.unit_identity not in units:
            units.append(member.unit_identity)
    for unit_identity in units[:3]:
        number = unit_numbers.get(unit_identity)
        if number is None:
            line.append("•", style="dim")
        else:
            line.append(f" {number} ", style=f"bold black on {TRIBE_IDENTITY_COLOR}")
    if len(units) > 3:
        line.append(f"+{len(units) - 3}", style="dim")
    line.append(" ")
    detail = ""
    if len(members) == 1 and not members[0].is_unit_root:
        line.append("› ", style="dim")
        line.append(members[0].member_label, style=_MEMBER_LABEL_STYLE)
        detail = f"› {members[0].member_label}"
    elif len(members) > 1:
        line.append(f"×{len(members)}", style=_SHARED_COUNT_STYLE)
        detail = f"×{len(members)}"
    elif level is not FoldLevel.COLLAPSED:
        line.append(members[0].unit_label, style=_UNIT_LABEL_STYLE)
        detail = members[0].unit_label
    if level in (FoldLevel.COLLAPSED, FoldLevel.EXPANDED):
        if detail:
            line.append("  ")
        line.append_text(_styled_text(digest.headline, digest.headline_spans))
    _append_entry_tags(line, digest, multi_project=multi_project)
    append_fold_anchor(
        text, line, section_id=f"{PROMPT_ENTRY_ANCHOR_PREFIX}{digest.group_key}"
    )
    if level in (FoldLevel.FULLY_EXPANDED, FoldLevel.EXHAUSTIVE):
        _append_prompt_body(text, digest, members, full=level is FoldLevel.EXHAUSTIVE)


def _append_entry_tags(
    line: Text,
    digest: PromptDigest,
    *,
    multi_project: bool,
) -> None:
    """Append dim ``·``-separated xprompt, size, and project tags to *line*."""
    tags: list[Text] = []
    for chip in digest.xprompts:
        tags.append(Text(chip, style=_XPROMPT_CHIP_STYLE))
    if digest.body_line_count > 1:
        tags.append(Text(f"{digest.body_line_count} lines", style=_SIZE_STYLE))
    if multi_project and digest.project is not None:
        tags.append(
            Text(f"+{digest.project}", style=project_column_style(digest.project))
        )
    if not tags:
        return
    line.append(" · ", style="dim")
    for index, tag in enumerate(tags):
        if index:
            line.append(" · ", style="dim")
        line.append_text(tag)


def _append_prompt_body(
    text: Text,
    digest: PromptDigest,
    members: tuple[TribePromptMember, ...],
    *,
    full: bool,
) -> None:
    """Append one entry's gutter-quoted body preview or full body."""
    if full and len(members) == 1 and digest.launch:
        text.append("    launch  ", style=FIELD_LABEL_STYLE)
        text.append_text(_styled_text(digest.launch, digest.launch_spans))
        text.append("\n")
    if not digest.body:
        return
    max_lines = PROMPT_BODY_SAFETY_LINES if full else PROMPT_PREVIEW_LINES
    cut, hidden = _slice_body_lines(digest.body, max_lines)
    # The slice is a prefix of the tokenized body, so replaying the precomputed
    # spans over it clips them to the slice without re-tokenizing.
    sliced = _styled_text(cut, digest.body_spans)
    for line in sliced.split("\n", allow_blank=True):
        text.append("   │ ", style=_GUTTER_STYLE)
        text.append_text(line)
        text.append("\n")
    if hidden > 0:
        text.append(f"    │ … +{hidden} more lines\n", style="dim italic")
        if full:
            text.append(
                "    │ open the agent (press its number) for the rest\n",
                style="dim italic",
            )
    if not full and len(members) > 1:
        labels = [
            _prompt_member_label(member.unit_label, member.member_label)
            for member in members
        ]
        shared = ", ".join(labels[:8])
        if len(labels) > 8:
            shared += f" +{len(labels) - 8}"
        text.append(f"    ↳ shared by {shared}\n", style="dim")


def _slice_body_lines(body: str, max_lines: int) -> tuple[str, int]:
    """Return the first *max_lines* lines of *body* plus the hidden count."""
    lines = body.split("\n")
    if len(lines) <= max_lines:
        return body, 0
    return "\n".join(lines[:max_lines]), len(lines) - max_lines


def _styled_text(content: str, spans: tuple[tuple[str, int, int], ...]) -> Text:
    """Return *content* with precomputed spans replayed over the base style."""
    styled = Text(content, style=BODY_STYLE)
    for span_style, start, end in spans:
        if 0 <= start < len(content):
            styled.stylize(span_style, start, min(end, len(content)))
    return styled


def _prompt_member_label(unit_label: str, member_label: str) -> str:
    if member_label == unit_label:
        return unit_label
    return f"{unit_label} › {member_label}"


__all__ = [
    "PROMPT_BODY_SAFETY_LINES",
    "PROMPT_ENTRY_ANCHOR_PREFIX",
    "PROMPT_GLANCE_LIMIT",
    "PROMPT_LIST_LIMIT",
    "PROMPT_PREVIEW_LINES",
    "append_prompts",
]
