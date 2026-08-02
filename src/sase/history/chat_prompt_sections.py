"""Shared Markdown sections for persisted prompt renderings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import re
from typing import Any, cast

from sase.config import get_chat_rendered_prompt_max_bytes
from sase.core.rust import require_rust_binding
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
_SECTION_RE = re.compile(
    r"<!-- sase:section:(?P<name>xprompt|rendered) -->.*?"
    r"<!-- /sase:section:(?P=name) -->",
    re.DOTALL,
)
_SECTION_CAPTURE_RE = re.compile(
    r"<!-- sase:section:(?P<name>xprompt|rendered) -->"
    r"(?P<body>.*?)"
    r"<!-- /sase:section:(?P=name) -->",
    re.DOTALL,
)
_BACKTICK_RUN_RE = re.compile(r"`+")
_RENDERED_FENCE_OPEN_RE = re.compile(r"^(`{3,})markdown\s*$")
_IDENTICAL_RENDERED_ROW = "- **RENDERED:** identical to the XPrompt"


@dataclass(frozen=True, slots=True)
class StoredPromptRenderings:
    """Prompt renderings extracted from persisted chat/archive Markdown."""

    xprompt_prompt: str | None = None
    rendered_prompt: str | None = None


def render_prompt_sections(
    xprompt_prompt: str | None,
    rendered_prompt: str | None,
    *,
    xprompt_links: Mapping[str, str] | None = None,
) -> str:
    """Return sentinel-delimited XPrompt and rendered-prompt sections.

    ``xprompt_links`` is primarily useful to focused callers and tests. Normal
    agent finalization resolves the same links from launch-captured provenance
    before passing the XPrompt prompt to chat storage.
    """

    if xprompt_prompt is None and rendered_prompt is None:
        return ""

    sections: list[str] = []
    if xprompt_prompt is not None:
        linked_xprompt = _rewrite_xprompt_links(xprompt_prompt, xprompt_links)
        sections.append(
            _sentinel_section(
                XPROMPT_SECTION_START,
                XPROMPT_SECTION_END,
                f"## Agent XPrompt\n\n{_escape_sentinels(linked_xprompt)}",
            )
        )

    if rendered_prompt is not None:
        if xprompt_prompt is not None and rendered_prompt == xprompt_prompt:
            rendered_body = "- **RENDERED:** identical to the XPrompt"
        else:
            truncated, omitted = _truncate_utf8(
                rendered_prompt,
                get_chat_rendered_prompt_max_bytes(),
            )
            if omitted:
                truncated += f"\n\n… truncated ({omitted} bytes omitted)"
            rendered_body = _render_details(
                _escape_sentinels(truncated),
                size_bytes=len(rendered_prompt.encode("utf-8")),
            )
        sections.append(
            _sentinel_section(
                RENDERED_SECTION_START,
                RENDERED_SECTION_END,
                rendered_body,
            )
        )

    return "\n".join(sections)


def strip_prompt_sections(content: str) -> str:
    """Replace stored prompt-rendering sections with same-length whitespace."""

    if "<!-- sase:section:" not in content:
        return content

    def blank(match: re.Match[str]) -> str:
        return "".join("\n" if char == "\n" else " " for char in match.group(0))

    return _SECTION_RE.sub(blank, content)


def remove_prompt_sections(content: str) -> str:
    """Remove persisted prompt-rendering sections from Markdown content."""

    if "<!-- sase:section:" not in content:
        return content
    return _SECTION_RE.sub("", content)


def extract_prompt_renderings(
    content: str,
    *,
    xprompt_fallback: str | None = None,
) -> StoredPromptRenderings:
    """Extract stored XPrompt and rendered prompt bodies from Markdown."""

    xprompt_prompt = xprompt_fallback
    rendered_body: str | None = None
    rendered_identical = False

    for match in _SECTION_CAPTURE_RE.finditer(content):
        name = match.group("name")
        body = _trim_section_padding(match.group("body"))
        if name == "xprompt" and xprompt_prompt is None:
            xprompt_prompt = _extract_xprompt_body(body)
        elif name == "rendered" and rendered_body is None:
            rendered_body, rendered_identical = _extract_rendered_body(body)

    if rendered_identical:
        rendered_body = xprompt_prompt
    return StoredPromptRenderings(
        xprompt_prompt=xprompt_prompt,
        rendered_prompt=rendered_body,
    )


def _sentinel_section(start: str, end: str, body: str) -> str:
    return f"{start}\n\n{body}\n\n{end}\n"


def _escape_sentinels(content: str) -> str:
    """Keep a prompt's literal sentinel comments from closing our regions."""

    escaped = content
    for sentinel in _SECTION_SENTINELS:
        escaped = escaped.replace(
            sentinel,
            sentinel.replace("<!--", "&lt;!--").replace("-->", "--&gt;"),
        )
    return escaped


def _unescape_sentinels(content: str) -> str:
    restored = content
    for sentinel in _SECTION_SENTINELS:
        escaped = sentinel.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
        restored = restored.replace(escaped, sentinel)
    return restored


def _trim_section_padding(body: str) -> str:
    if body.startswith("\n\n"):
        body = body[2:]
    elif body.startswith("\n"):
        body = body[1:]
    if body.endswith("\n\n"):
        body = body[:-2]
    elif body.endswith("\n"):
        body = body[:-1]
    return body


def _extract_xprompt_body(body: str) -> str:
    body = _unescape_sentinels(body)
    heading = "## Agent XPrompt"
    if not body.startswith(heading):
        return body
    prompt = body[len(heading) :]
    if prompt.startswith("\n\n"):
        return prompt[2:]
    if prompt.startswith("\n"):
        return prompt[1:]
    return prompt


def _extract_rendered_body(body: str) -> tuple[str | None, bool]:
    body = _unescape_sentinels(body)
    if body.strip() == _IDENTICAL_RENDERED_ROW:
        return None, True

    lines = body.splitlines(keepends=True)
    for start_index, line in enumerate(lines):
        match = _RENDERED_FENCE_OPEN_RE.match(line.rstrip("\n"))
        if match is None:
            continue
        fence = match.group(1)
        for end_index in range(start_index + 1, len(lines)):
            if lines[end_index].strip() == fence:
                return "".join(lines[start_index + 1 : end_index]), False
        return None, False
    return None, False


def _truncate_utf8(content: str, max_bytes: int) -> tuple[str, int]:
    encoded = content.encode("utf-8")
    if len(encoded) <= max_bytes:
        return content, 0
    prefix = encoded[:max_bytes].decode("utf-8", errors="ignore")
    retained = len(prefix.encode("utf-8"))
    return prefix, len(encoded) - retained


def _render_details(content: str, *, size_bytes: int) -> str:
    longest_run = max(
        (len(match.group(0)) for match in _BACKTICK_RUN_RE.finditer(content)),
        default=0,
    )
    fence = "`" * max(3, longest_run + 1)
    size = format_size(size_bytes)
    content_suffix = "" if not content or content.endswith("\n") else "\n"
    return (
        "<details>\n"
        f"<summary><b>Agent Prompt</b> — rendered, {size}</summary>\n\n"
        f"{fence}markdown\n"
        f"{content}{content_suffix}"
        f"{fence}\n\n"
        "</details>"
    )


def _rewrite_xprompt_links(
    prompt: str,
    links: Mapping[str, str] | None,
) -> str:
    if not links:
        return prompt
    records = [
        {
            "schema_version": 1,
            "raw_ref": raw_ref,
            "name": raw_ref.removeprefix("#"),
            "kind": "xprompt",
            "source_kind": None,
            "source_path": None,
            "definition_line": None,
            "repo": None,
            "repo_root": None,
            "repo_relpath": None,
            "chezmoi": False,
            "skipped_reason": None,
        }
        for raw_ref in links
    ]
    rewrite = require_rust_binding("prompt_xprompt_rewrite_links")
    payload = cast(
        Mapping[str, Any],
        rewrite(prompt, records, lambda record: links.get(record["raw_ref"])),
    )
    return str(payload.get("prompt") or "")


__all__ = [
    "RENDERED_SECTION_END",
    "RENDERED_SECTION_START",
    "StoredPromptRenderings",
    "XPROMPT_SECTION_END",
    "XPROMPT_SECTION_START",
    "extract_prompt_renderings",
    "remove_prompt_sections",
    "render_prompt_sections",
    "strip_prompt_sections",
]
