"""Agent-specific COMMITS helpers for the prompt panel header."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rich.text import Text

from sase.project_display_names import project_display_name_for

from ...models.agent import Agent
from ._agent_context_common import (
    COLOR_WORKSPACE_GLYPH,
    COLOR_WORKSPACE_NAME,
    WORKSPACE_GLYPH,
)
from ._helpers import append_major_section_divider

_COLOR_HEADER = "bold #87D7FF"
_COLOR_COMMIT_SHA = "dim #D7D7AF"
_COLOR_COMMIT_SUBJECT = "#D7D7FF"


@dataclass(frozen=True)
class _CommitInfo:
    """Compact display data for one commit."""

    short_sha: str
    subject: str


@dataclass(frozen=True)
class CommitDiffInfo:
    """Per-commit diff metadata used by TUI diff/delta surfaces."""

    repo_name: str
    short_sha: str
    subject: str
    diff_path: str
    is_primary: bool


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
        return project_display_name_for(_display_text(meta_project))
    if agent.project_display_name:
        return agent.project_display_name
    if agent.project_file:
        key = Path(agent.project_file).stem
        if key:
            return project_display_name_for(key)
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


def _commit_info_from_record(record: dict[str, Any]) -> _CommitInfo | None:
    message = _display_text(record.get("message", ""))
    sha_value = record.get("sha", record.get("result", ""))
    sha = _short_sha(_display_text(sha_value))
    subject = _first_subject_line(message)
    if not subject and not sha:
        return None
    if not subject:
        subject = "(message unavailable)"
    return _CommitInfo(short_sha=sha, subject=subject)


def _commit_diff_path_from_record(record: dict[str, Any]) -> str | None:
    raw_path = record.get("diff_path") or record.get("commit_diff_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    return os.path.expanduser(raw_path.strip())


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
    return project_display_name_for(repo_name) if repo_name else "repository"


def _repo_name_for_commit_cwd(
    agent: Agent,
    step_output: dict[str, Any] | None,
    cwd_raw: object,
) -> str:
    cwd = _norm_path(cwd_raw)
    if cwd is None:
        return _primary_repo_name(agent, step_output)

    if _path_is_same_or_inside(cwd, _norm_path(agent.workspace_dir)):
        return _primary_repo_name(agent, step_output)

    for repo in agent.linked_repos:
        if _path_is_same_or_inside(cwd, _norm_path(repo.workspace_dir)):
            return repo.name

    return _repo_name_from_cwd(str(cwd_raw))


def _repo_name_for_commit_record(
    agent: Agent,
    step_output: dict[str, Any] | None,
    record: dict[str, Any],
) -> str:
    explicit_repo_name = _explicit_repo_name_from_record(record)
    if explicit_repo_name is not None:
        return explicit_repo_name
    return _repo_name_for_commit_cwd(agent, step_output, record.get("cwd"))


def _explicit_repo_name_from_record(record: dict[str, Any]) -> str | None:
    repo_name = record.get("repo_name")
    return (
        repo_name.strip() if isinstance(repo_name, str) and repo_name.strip() else None
    )


def _commit_cwd_is_primary(agent: Agent, cwd_raw: object) -> bool:
    cwd = _norm_path(cwd_raw)
    if cwd is None:
        return True
    return _path_is_same_or_inside(cwd, _norm_path(agent.workspace_dir))


def _persisted_commit_repo_name(
    agent: Agent,
    step_output: dict[str, Any] | None,
) -> str:
    cwd_raw = step_output.get("meta_commit_cwd") if step_output is not None else None
    return _repo_name_for_commit_cwd(agent, step_output, cwd_raw)


def _persisted_commit_groups(
    agent: Agent,
    step_output: dict[str, Any] | None,
) -> tuple[tuple[str, tuple[_CommitInfo, ...]], ...]:
    if step_output is None:
        return ()

    raw_commits = step_output.get("meta_commits")
    if isinstance(raw_commits, list) and raw_commits:
        grouped: dict[str, list[_CommitInfo]] = {}
        group_order: list[str] = []
        for raw_record in raw_commits:
            if not isinstance(raw_record, dict):
                continue
            commit = _commit_info_from_record(raw_record)
            if commit is None:
                continue
            repo_name = _repo_name_for_commit_record(agent, step_output, raw_record)
            if repo_name not in grouped:
                grouped[repo_name] = []
                group_order.append(repo_name)
            grouped[repo_name].append(commit)

        if grouped:
            primary_name = _primary_repo_name(agent, step_output)
            ordered_groups: list[tuple[str, tuple[_CommitInfo, ...]]] = []
            if primary_name in grouped:
                ordered_groups.append((primary_name, tuple(grouped[primary_name])))
            for repo_name in group_order:
                if repo_name == primary_name:
                    continue
                ordered_groups.append((repo_name, tuple(grouped[repo_name])))
            return tuple(ordered_groups)

    persisted_commits = _persisted_commit_infos(step_output)
    if not persisted_commits:
        return ()
    return ((_persisted_commit_repo_name(agent, step_output), persisted_commits),)


def agent_commit_diffs(agent: Agent) -> list[CommitDiffInfo]:
    """Return ordered persisted per-commit diff descriptors for ``agent``.

    This accessor only parses in-memory metadata. It deliberately avoids
    checking file existence so render paths can call it without disk I/O.
    """
    step_output = agent.step_output if isinstance(agent.step_output, dict) else None
    if step_output is None:
        return []

    raw_commits = step_output.get("meta_commits")
    if not isinstance(raw_commits, list) or not raw_commits:
        return []

    primary_name = _primary_repo_name(agent, step_output)
    grouped: dict[str, list[CommitDiffInfo]] = {}
    group_order: list[str] = []
    seen_paths: set[str] = set()
    for raw_record in raw_commits:
        if not isinstance(raw_record, dict):
            continue

        diff_path = _commit_diff_path_from_record(raw_record)
        path_key = _norm_path(diff_path)
        if diff_path is None or path_key is None or path_key in seen_paths:
            continue

        commit = _commit_info_from_record(raw_record)
        if commit is None:
            continue
        seen_paths.add(path_key)

        repo_name = _repo_name_for_commit_record(agent, step_output, raw_record)
        if repo_name not in grouped:
            grouped[repo_name] = []
            group_order.append(repo_name)
        explicit_repo_name = _explicit_repo_name_from_record(raw_record)
        grouped[repo_name].append(
            CommitDiffInfo(
                repo_name=repo_name,
                short_sha=commit.short_sha,
                subject=commit.subject,
                diff_path=diff_path,
                is_primary=repo_name == primary_name
                or (
                    explicit_repo_name is None
                    and _commit_cwd_is_primary(agent, raw_record.get("cwd"))
                ),
            )
        )

    ordered: list[CommitDiffInfo] = []
    if primary_name in grouped:
        ordered.extend(grouped[primary_name])
    for repo_name in group_order:
        if repo_name == primary_name:
            continue
        ordered.extend(grouped[repo_name])
    return ordered


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
    commit_groups = _persisted_commit_groups(agent, step_output)
    if not commit_groups:
        return

    append_major_section_divider(text)
    text.append("COMMITS:\n", style=_COLOR_HEADER)
    for repo_name, commits in commit_groups:
        _append_commit_group(text, repo_name, commits)
