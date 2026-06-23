"""Agent-specific COMMITS helpers for the prompt panel header."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.text import Text

from ...models.agent import Agent
from ..file_panel._linked_commits import (
    CommitInfo,
    get_cached_linked_commit_groups,
)
from ._agent_context_common import (
    COLOR_WORKSPACE_GLYPH,
    COLOR_WORKSPACE_NAME,
    WORKSPACE_GLYPH,
)

_COLOR_HEADER = "bold #87D7FF"
_COLOR_COMMIT_SHA = "dim #D7D7AF"
_COLOR_COMMIT_SUBJECT = "#D7D7FF"
_MAJOR_SECTION_RULE = "\u2500" * 50


def _append_major_section_divider(text: Text) -> None:
    text.append("\n")
    text.append(f"{_MAJOR_SECTION_RULE}\n", style="dim")
    text.append("\n")


def _display_text(value: object) -> str:
    return str(value).strip()


def _first_subject_line(message: str) -> str:
    for line in message.splitlines():
        subject = line.strip()
        if subject:
            return subject
    return ""


def _short_sha(value: str) -> str:
    return value.split()[0][:12] if value.split() else ""


def _primary_repo_name(agent: Agent, step_output: dict[str, Any] | None) -> str:
    meta_project = step_output.get("meta_project") if step_output is not None else None
    if meta_project:
        return _display_text(meta_project)
    if agent.project_file:
        stem = Path(agent.project_file).stem
        if stem:
            return stem
    return "primary"


def _primary_commit_infos(step_output: dict[str, Any] | None) -> tuple[CommitInfo, ...]:
    if step_output is None:
        return ()

    message = _display_text(step_output.get("meta_commit_message", ""))
    sha = _short_sha(_display_text(step_output.get("meta_new_commit", "")))
    subject = _first_subject_line(message)
    if not subject and not sha:
        return ()
    if not subject:
        subject = "(message unavailable)"
    return (CommitInfo(short_sha=sha, subject=subject),)


def _append_commit_group(
    text: Text,
    repo_name: str,
    commits: tuple[CommitInfo, ...],
) -> None:
    if not commits:
        return

    text.append("  ")
    text.append(WORKSPACE_GLYPH, style=COLOR_WORKSPACE_GLYPH)
    text.append(" ")
    text.append(repo_name, style=COLOR_WORKSPACE_NAME)
    text.append("\n")
    for commit in commits:
        text.append("    ")
        if commit.short_sha:
            text.append(commit.short_sha, style=_COLOR_COMMIT_SHA)
            text.append(" ")
        text.append(commit.subject, style=_COLOR_COMMIT_SUBJECT)
        text.append("\n")


def append_agent_commits_section(text: Text, agent: Agent) -> None:
    """Append persisted primary and cached linked commit messages, if any."""
    step_output = agent.step_output if isinstance(agent.step_output, dict) else None
    primary_commits = _primary_commit_infos(step_output)
    linked_groups = tuple(
        group for group in get_cached_linked_commit_groups(agent) if group.commits
    )
    if not primary_commits and not linked_groups:
        return

    _append_major_section_divider(text)
    text.append("COMMITS:\n", style=_COLOR_HEADER)
    if primary_commits:
        _append_commit_group(
            text,
            _primary_repo_name(agent, step_output),
            primary_commits,
        )
    for group in linked_groups:
        _append_commit_group(text, group.repo_name, group.commits)
