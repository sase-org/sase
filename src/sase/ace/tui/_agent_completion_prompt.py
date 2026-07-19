"""Prompt and VCS metadata extraction for agent completion candidates."""

from __future__ import annotations

import re

from sase.ace.tui._agent_completion_models import AgentVcsWorkflow

_WORKFLOW_STYLES = (
    "#5FD7FF",
    "#00D7AF",
    "#D7AF87",
    "#AF87FF",
    "#FFD75F",
    "#FF87AF",
)
_FRONTMATTER_RE = re.compile(r"\A---[^\n]*\n.*?\n---\s*", re.DOTALL)
_DIRECTIVE_NAME_RE = re.compile(r"%[a-zA-Z_][a-zA-Z0-9_]*")


def vcs_workflow_from_prompt(raw_prompt: str) -> AgentVcsWorkflow | None:
    if not raw_prompt:
        return None

    from sase.xprompt import extract_project_from_vcs_tag, extract_vcs_workflow_tag
    from sase.project_display_names import (
        humanize_vcs_refs_in_text,
        project_display_name_for,
    )

    body = _strip_leading_prompt_directives(_strip_frontmatter(raw_prompt))
    tag = extract_vcs_workflow_tag(body)
    if not tag:
        return None

    raw_tag = tag.strip()
    display_tag = humanize_vcs_refs_in_text(raw_tag)
    workflow_type = _workflow_type_from_vcs_tag(display_tag)
    provider_display = _provider_display(workflow_type)
    project = extract_project_from_vcs_tag(raw_tag)
    return AgentVcsWorkflow(
        tag=display_tag,
        workflow_type=workflow_type,
        project=project_display_name_for(project) if project else None,
        provider_display=provider_display,
        style=_workflow_style(workflow_type),
    )


def raw_vcs_tag_for_prompt(raw_prompt: str) -> str:
    if not raw_prompt:
        return ""
    from sase.xprompt import extract_vcs_workflow_tag, find_vcs_workflow_tag

    body = _strip_leading_prompt_directives(_strip_frontmatter(raw_prompt))
    tag = extract_vcs_workflow_tag(body) or find_vcs_workflow_tag(body)
    return tag.strip() if tag else ""


def _workflow_type_from_vcs_tag(tag: str) -> str | None:
    if not tag.startswith("#"):
        return None
    body = tag[1:]
    for suffix in ("!!", "??"):
        body = body.replace(suffix, "", 1)
    separators = [
        idx for idx in (body.find(":"), body.find("_"), body.find("(")) if idx >= 0
    ]
    if separators:
        body = body[: min(separators)]
    if body.endswith("+"):
        body = body[:-1]
    return body or None


def _provider_display(workflow_type: str | None) -> str | None:
    if not workflow_type:
        return None
    try:
        from sase.workspace_provider import get_display_name

        return get_display_name(workflow_type) or workflow_type
    except Exception:
        return workflow_type


def _workflow_style(workflow_type: str | None) -> str:
    if not workflow_type:
        return "dim"
    index = sum(ord(char) for char in workflow_type) % len(_WORKFLOW_STYLES)
    return f"bold {_WORKFLOW_STYLES[index]}"


def prompt_snippet(raw_prompt: str, *, max_len: int = 96, humanize: bool = True) -> str:
    cleaned = _strip_frontmatter(raw_prompt)
    cleaned = _strip_leading_prompt_directives(cleaned)
    cleaned = _strip_leading_vcs_tag(cleaned)
    cleaned = _strip_leading_prompt_directives(cleaned)
    snippet = " ".join(cleaned.split())
    if humanize:
        from sase.project_display_names import humanize_vcs_refs_in_text

        snippet = humanize_vcs_refs_in_text(snippet)
    if len(snippet) <= max_len:
        return snippet
    if max_len <= 3:
        return snippet[:max_len]
    return snippet[: max_len - 3].rstrip() + "..."


def _strip_frontmatter(text: str) -> str:
    return _FRONTMATTER_RE.sub("", text, count=1).lstrip()


def _strip_leading_prompt_directives(text: str) -> str:
    from sase.xprompt._parsing import find_matching_paren_for_args

    current = text.lstrip()
    while current.startswith("%"):
        match = _DIRECTIVE_NAME_RE.match(current)
        if match is None:
            return current
        end = match.end()
        marker = current[end : end + 1]
        if marker == "(":
            close = find_matching_paren_for_args(current, end)
            if close is None:
                return current
            end = close + 1
        elif marker == ":":
            end += 1
            while end < len(current) and not current[end].isspace():
                end += 1
        elif marker == "+":
            end += 1

        next_text = current[end:].lstrip()
        if next_text == current:
            return current
        current = next_text
    return current


def _strip_leading_vcs_tag(text: str) -> str:
    stripped = text.lstrip()
    if not stripped.startswith("#"):
        return stripped
    try:
        from sase.xprompt import strip_vcs_workflow_tag

        return strip_vcs_workflow_tag(stripped).lstrip()
    except Exception:
        return stripped


__all__ = ["prompt_snippet", "raw_vcs_tag_for_prompt", "vcs_workflow_from_prompt"]
