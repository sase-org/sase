"""Shared helpers for xprompt argument-completion tests."""

from __future__ import annotations

from typing import Any, Literal

from sase.ace.tui.agent_completion import (
    AgentCompletionCandidate,
    AgentVcsWorkflow,
)
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.xprompt_arg_assist import (
    XPromptAssistEntry,
    XPromptInputHint,
)


def style_at(text: Any, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    base_style = getattr(text, "style", None)
    return str(base_style) if base_style else None


def input_hint(
    name: str,
    type_: str,
    position: int,
    *,
    required: bool = True,
    default_display: str | None = None,
    repeatable: bool = False,
    description: str | None = None,
) -> XPromptInputHint:
    return XPromptInputHint(
        name=name,
        type=type_,
        required=required,
        default_display=default_display,
        position=position,
        repeatable=repeatable,
        description=description,
    )


def review_entry() -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name="review",
        insertion="#review",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(
            input_hint("path", "path", 0),
            input_hint("enabled", "bool", 1),
            input_hint("count", "int", 2),
        ),
        content_preview=None,
    )


def rich_review_entry() -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name="review",
        insertion="#review",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(
            input_hint("path", "path", 0, description="file to review"),
            input_hint(
                "enabled",
                "bool",
                1,
                required=False,
                default_display="true",
                description="turn on",
            ),
            input_hint(
                "count",
                "int",
                2,
                required=False,
                default_display="3",
            ),
            input_hint("label", "str", 3, description="a free-form label"),
        ),
        content_preview=None,
    )


def fork_entry() -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name="fork",
        insertion="#fork",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(input_hint("names", "agent", 0, repeatable=True),),
        content_preview=None,
    )


def gh_entry() -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name="gh",
        insertion="#gh",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(input_hint("project", "word", 0),),
        content_preview=None,
    )


def ask_entry() -> XPromptAssistEntry:
    return XPromptAssistEntry(
        name="ask",
        insertion="#ask",
        reference_prefix="#",
        kind="xprompt",
        input_signature=None,
        inputs=(input_hint("body", "text", 0),),
        content_preview=None,
    )


def agent_candidate(
    name: str,
    *,
    status: str = "RUNNING",
    vcs_tag: str = "#gh:sase",
    snippet: str = "Fix prompt completion",
    tribe: str | None = None,
    kind: Literal["agent", "family", "clan", "tribe"] = "agent",
    member_count: int | None = None,
    member_names: tuple[str, ...] = (),
) -> AgentCompletionCandidate:
    return AgentCompletionCandidate(
        name=name,
        label=name,
        status=status,
        kind=kind,
        member_count=member_count,
        aggregate_status=status if kind != "agent" else None,
        member_names=member_names,
        tribe=tribe,
        vcs_workflow=AgentVcsWorkflow(
            tag=vcs_tag,
            workflow_type="gh",
            project="sase",
            provider_display="GitHub",
            style="bold #5FD7FF",
        ),
        prompt_snippet=snippet,
    )


def seed_entries(
    ta: PromptTextArea,
    entries: list[XPromptAssistEntry],
    project: str | None = None,
) -> None:
    ta._xprompt_arg_assist_entries_by_project[project] = entries
