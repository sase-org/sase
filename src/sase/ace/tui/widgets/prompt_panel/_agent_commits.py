"""Agent-specific COMMITS helpers for the prompt panel header."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.text import Text

from ...models.agent import Agent
from ._agent_context_common import (
    COLOR_WORKSPACE_GLYPH,
    COLOR_WORKSPACE_NAME,
    WORKSPACE_GLYPH,
)

_COLOR_HEADER = "bold #87D7FF"
_COLOR_COMMIT_SHA = "dim #D7D7AF"
_COLOR_COMMIT_SUBJECT = "#D7D7FF"
_MAJOR_SECTION_RULE = "\u2500" * 50


@dataclass(frozen=True)
class _CommitInfo:
    """Compact display data for one commit."""

    short_sha: str
    subject: str


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


def _persisted_commit_infos(
    step_output: dict[str, Any] | None,
) -> tuple[_CommitInfo, ...]:
    if step_output is None:
        return ()

    message = _display_text(step_output.get("meta_commit_message", ""))
    sha = _short_sha(_display_text(step_output.get("meta_new_commit", "")))
    subject = _first_subject_line(message)
    if not subject and not sha:
        return ()
    if not subject:
        subject = "(message unavailable)"
    return (_CommitInfo(short_sha=sha, subject=subject),)


def _norm_path(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return os.path.normcase(
        os.path.normpath(os.path.abspath(os.path.expanduser(value)))
    )


def _path_is_same_or_inside(child: str | None, parent: str | None) -> bool:
    if child is None or parent is None:
        return False
    try:
        return os.path.commonpath([child, parent]) == parent
    except ValueError:
        return False


def _repo_name_from_cwd(cwd: str) -> str:
    basename = os.path.basename(os.path.normpath(os.path.expanduser(cwd)))
    repo_name = re.sub(r"_\d+$", "", basename).strip()
    return repo_name or "repository"


def _persisted_commit_repo_name(
    agent: Agent,
    step_output: dict[str, Any] | None,
) -> str:
    cwd_raw = step_output.get("meta_commit_cwd") if step_output is not None else None
    cwd = _norm_path(cwd_raw)
    if cwd is None:
        return _primary_repo_name(agent, step_output)

    if _path_is_same_or_inside(cwd, _norm_path(agent.workspace_dir)):
        return _primary_repo_name(agent, step_output)

    for repo in agent.linked_repos:
        if _path_is_same_or_inside(cwd, _norm_path(repo.workspace_dir)):
            return repo.name

    return _repo_name_from_cwd(str(cwd_raw))


def _append_commit_group(
    text: Text,
    repo_name: str,
    commits: tuple[_CommitInfo, ...],
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
    """Append the persisted commit message, attributed to its source repo."""
    step_output = agent.step_output if isinstance(agent.step_output, dict) else None
    persisted_commits = _persisted_commit_infos(step_output)
    if not persisted_commits:
        return

    _append_major_section_divider(text)
    text.append("COMMITS:\n", style=_COLOR_HEADER)
    _append_commit_group(
        text,
        _persisted_commit_repo_name(agent, step_output),
        persisted_commits,
    )
