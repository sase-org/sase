"""Shared rendering primitives for clan detail sections."""

from __future__ import annotations

from collections.abc import Callable

from rich.syntax import Syntax
from rich.text import Text

from sase.project_display_names import humanize_vcs_refs_in_text

from ...models._agent_clan_sections import (
    ClanAgentIdentity,
    first_meaningful_line,
)
from ...models.fold_state import FoldLevel
from .._agent_list_styling import _AGENT_NAME_ANNOTATION_STYLE
from ._agent_display_state import HeaderHintState
from ._container_hint_text import container_text_with_file_hints
from ._fold_language import append_fold_glyph, fold_count_style
from ._helpers import append_major_section_divider, append_section_heading
from ._hint_caps import HintContentBudget

_TRIAGE_ENTRY_LIMIT = 8
_CLAN_SECTION_HEADING_STYLE = "bold #D7AF5F underline"
_CLAN_MEMBER_SUBHEADING_STYLE = "bold #D75FFF"
_CLAN_BODY_STYLE = "#D7D7FF"


def humanize_prompt_body(body: str) -> str:
    """Tagify project refs in a clan prompt body, failing open."""
    try:
        return humanize_vcs_refs_in_text(body)
    except Exception:
        return body


type ClanMemberHintWorkspace = Callable[[ClanAgentIdentity, str], str | None]


def append_fold_heading(
    text: Text,
    *,
    title: str,
    section_id: str,
    level: FoldLevel,
    count: int | None,
) -> None:
    append_major_section_divider(text)
    heading = Text()
    append_fold_glyph(heading, level)
    heading.append(title, style=_CLAN_SECTION_HEADING_STYLE)
    if count is not None:
        heading.append(f" · {count}", style=fold_count_style(title))
    append_section_heading(text, heading, section_id=section_id)


def append_triage_line(
    text: Text,
    label: str,
    body: str,
    *,
    separator: str = " · ",
    kind: str | None = None,
    body_style: str = _CLAN_BODY_STYLE,
    member_identity: ClanAgentIdentity | None = None,
    hint_state: HeaderHintState | None = None,
    hint_budget: HintContentBudget | None = None,
    member_hint_workspace: ClanMemberHintWorkspace | None = None,
    highlight_project_tags: bool = False,
) -> None:
    text.append("• ", style="dim #D75FFF")
    text.append(label, style=_AGENT_NAME_ANNOTATION_STYLE)
    if kind:
        text.append(f" · {kind}", style="italic #AF87FF")
    text.append(separator, style="dim")
    visible_body = first_meaningful_line(body, max_chars=120) or "—"
    body_text = Text(visible_body, style=body_style)
    if highlight_project_tags:
        try:
            from sase.ace.tui.util.xprompt_syntax import stylize_project_tags

            stylize_project_tags(body_text, visible_body)
        except Exception:
            pass
    text.append_text(
        text_with_member_hints(
            body_text,
            member_identity=member_identity,
            hint_state=hint_state,
            hint_budget=hint_budget,
            member_hint_workspace=member_hint_workspace,
        )
    )
    text.append("\n")


def append_member_subheading(text: Text, label: str) -> None:
    text.append(f"{label}\n", style=_CLAN_MEMBER_SUBHEADING_STYLE)


def append_full_body(
    text: Text,
    body: str,
    *,
    style: str = _CLAN_BODY_STYLE,
    indent: str = "  ",
    member_identity: ClanAgentIdentity | None = None,
    hint_state: HeaderHintState | None = None,
    hint_budget: HintContentBudget | None = None,
    member_hint_workspace: ClanMemberHintWorkspace | None = None,
    highlight_project_tags: bool = False,
) -> None:
    body_text = Text()
    if highlight_project_tags:
        _append_tag_highlighted_lines(body_text, body, style=style, indent=indent)
    else:
        lines = body.splitlines() or ["—"]
        for line in lines:
            body_text.append(indent, style="dim")
            body_text.append(line or " ", style=style)
            body_text.append("\n")
    text.append_text(
        text_with_member_hints(
            body_text,
            member_identity=member_identity,
            hint_state=hint_state,
            hint_budget=hint_budget,
            member_hint_workspace=member_hint_workspace,
        )
    )


def _append_tag_highlighted_lines(
    body_text: Text,
    body: str,
    *,
    style: str,
    indent: str,
) -> None:
    """Append tagified, accent-styled prompt lines (D5/D6).

    The whole humanized body is tokenized at once so multi-line literal
    zones stay inert, then split back into the same indented line
    structure as the plain path. Fails open to the plain rendering.
    """
    from sase.ace.tui.util.xprompt_syntax import stylize_project_tags

    humanized = humanize_prompt_body(body)
    display_lines = humanized.splitlines() or ["—"]
    try:
        source = "\n".join(line or " " for line in display_lines)
        flat = Text(source, style=style)
        stylize_project_tags(flat, source)
        split_lines: list[Text] = list(flat.split("\n", allow_blank=True))
    except Exception:
        split_lines = [Text(line or " ", style=style) for line in display_lines]
    for line in split_lines:
        body_text.append(indent, style="dim")
        body_text.append_text(line)
        body_text.append("\n")


def append_traceback(
    text: Text,
    traceback: str,
    *,
    member_identity: ClanAgentIdentity | None = None,
    hint_state: HeaderHintState | None = None,
    hint_budget: HintContentBudget | None = None,
    member_hint_workspace: ClanMemberHintWorkspace | None = None,
) -> None:
    """Append traceback text with the regular agent panel's pytb highlighting."""
    highlighted = Syntax(
        traceback,
        "pytb",
        theme="monokai",
        word_wrap=True,
    ).highlight(traceback)
    traceback_text = Text()
    for line in highlighted.split("\n", allow_blank=True):
        traceback_text.append("  ", style="dim")
        traceback_text.append_text(line)
        traceback_text.append("\n")
    text.append_text(
        text_with_member_hints(
            traceback_text,
            member_identity=member_identity,
            hint_state=hint_state,
            hint_budget=hint_budget,
            member_hint_workspace=member_hint_workspace,
        )
    )


def text_with_member_hints(
    content: Text,
    *,
    member_identity: ClanAgentIdentity | None,
    hint_state: HeaderHintState | None,
    hint_budget: HintContentBudget | None,
    member_hint_workspace: ClanMemberHintWorkspace | None,
) -> Text:
    """Annotate one visible body fragment against its owning member."""
    if member_identity is None or hint_state is None or member_hint_workspace is None:
        return content
    return container_text_with_file_hints(
        content,
        hint_state,
        workspace_dir=member_hint_workspace(member_identity, content.plain),
        budget=hint_budget,
    )


def append_more_tail(text: Text, total: int, shown: int) -> None:
    hidden = total - min(total, shown)
    if hidden > 0:
        text.append(f"  +{hidden} more\n", style="dim italic")
