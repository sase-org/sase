"""Shared Markdown sections for persisted prompt renderings."""

from __future__ import annotations

from collections.abc import Mapping
import re

from sase.prompt.render import format_size

XPROMPT_SECTION_START = "<!-- sase:section:xprompt -->"
XPROMPT_SECTION_END = "<!-- /sase:section:xprompt -->"
RENDERED_SECTION_START = "<!-- sase:section:rendered -->"
RENDERED_SECTION_END = "<!-- /sase:section:rendered -->"

_SECTION_SENTINELS = (
    XPROMPT_SECTION_START,
    XPROMPT_SECTION_END,
    RENDERED_SECTION_START,
    RENDERED_SECTION_END,
)
_BACKTICK_RUN_RE = re.compile(r"`+")


def render_prompt_sections(
    xprompt_prompt: str | None,
    rendered_prompt: str | None,
    *,
    xprompt_links: Mapping[str, str] | None = None,
) -> str:
    """Render the optional XPrompt and rendered-prompt storage sections.

    ``xprompt_links`` is accepted for the chat writer's linkification boundary.
    Callers that use the Rust rewriter pass already-linked XPrompt text and leave
    it unset; accepting the mapping here keeps the shared format independent of
    a specific provenance-record type.
    """

    del xprompt_links
    sections: list[str] = []
    if xprompt_prompt is not None:
        escaped = _escape_section_sentinels(xprompt_prompt)
        sections.append(
            "\n".join(
                (
                    XPROMPT_SECTION_START,
                    "",
                    "## Agent XPrompt",
                    "",
                    escaped,
                    "",
                    XPROMPT_SECTION_END,
                )
            )
        )
    if rendered_prompt is not None:
        sections.append(_render_rendered_prompt(rendered_prompt))
    return "\n".join(sections) + ("\n" if sections else "")


def strip_prompt_sections(content: str) -> str:
    """Remove complete sentinel-delimited prompt sections from ``content``."""

    stripped = content
    for start, end in (
        (XPROMPT_SECTION_START, XPROMPT_SECTION_END),
        (RENDERED_SECTION_START, RENDERED_SECTION_END),
    ):
        while True:
            start_at = stripped.find(start)
            if start_at < 0:
                break
            end_at = stripped.find(end, start_at + len(start))
            if end_at < 0:
                break
            stripped = stripped[:start_at] + stripped[end_at + len(end) :]
    return stripped


def _render_rendered_prompt(prompt: str) -> str:
    escaped = _escape_section_sentinels(prompt)
    longest = max(
        (len(match.group(0)) for match in _BACKTICK_RUN_RE.finditer(escaped)),
        default=0,
    )
    fence = "`" * max(3, longest + 1)
    size = format_size(len(prompt.encode("utf-8")))
    separator = "" if escaped.endswith("\n") else "\n"
    fenced = f"{fence}markdown\n{escaped}{separator}{fence}"
    return "\n".join(
        (
            RENDERED_SECTION_START,
            "",
            "<details>",
            f"<summary><b>Agent Prompt</b> — rendered, {size}</summary>",
            "",
            fenced,
            "",
            "</details>",
            "",
            RENDERED_SECTION_END,
        )
    )


def _escape_section_sentinels(content: str) -> str:
    escaped = content
    for sentinel in _SECTION_SENTINELS:
        escaped = escaped.replace(
            sentinel,
            sentinel.replace("<!--", "&lt;!--").replace("-->", "--&gt;"),
        )
    return escaped


__all__ = [
    "RENDERED_SECTION_END",
    "RENDERED_SECTION_START",
    "XPROMPT_SECTION_END",
    "XPROMPT_SECTION_START",
    "render_prompt_sections",
    "strip_prompt_sections",
]
