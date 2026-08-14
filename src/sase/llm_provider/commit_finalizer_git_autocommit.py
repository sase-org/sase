"""Narrow, provably-safe auto-commits performed during commit finalization.

Each auto-commit here must first *prove* the working tree holds nothing but
the one mechanical edit it is willing to own — an SDD plan's ``wip -> done``
status flip, or a Q&A block appended to an archived prompt. Anything broader
is left for the agent to commit itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .commit_finalizer_git_paths import is_prompt_archive_path, normalize_path
from .commit_finalizer_git_status import (
    GitStatusRecord,
    git_show_head_file,
    git_status_records,
    run_git,
)

if TYPE_CHECKING:
    from .commit_finalizer_types import DirtyState

_SDD_PLAN_DIR_PREFIXES = ("sdd/plans/",)
_QA_HEADER = "### Questions and Answers"


@dataclass(frozen=True)
class _DoneStatusAutoCommitCandidate:
    repo_dir: str
    path: str
    stage_path: bool


@dataclass(frozen=True)
class _SddPromptQaAutoCommitCandidate:
    repo_dir: str
    paths: tuple[str, ...]


def auto_commit_done_sdd_plan_status(dirty_state: DirtyState) -> bool:
    """Commit a generated SDD plan status closeout change, when proven narrow."""
    candidate = _done_sdd_plan_status_auto_commit_candidate(dirty_state)
    if candidate is None:
        return False

    from sase.workflows.commit.runtime_tags import apply_auto_commit_tags_with_runtime

    message = apply_auto_commit_tags_with_runtime("chore: Mark SDD plan done", "sdd")
    return _git_add_and_commit_path(
        candidate.repo_dir,
        candidate.path,
        message,
        stage_path=candidate.stage_path,
    )


def sdd_prompt_qa_auto_commit_candidates(
    dirty_state: DirtyState,
) -> tuple[_SddPromptQaAutoCommitCandidate, ...]:
    """Return external SDD repos proven to contain only Q&A snapshot edits."""
    candidates: list[_SddPromptQaAutoCommitCandidate] = []
    for repo in dirty_state.repos:
        if repo.kind != "sdd":
            continue

        repo_dir = normalize_path(repo.path)
        status_records = git_status_records(repo_dir)
        if not status_records:
            continue
        if {record.path for record in status_records} != set(repo.changed_files):
            continue
        if any(record.xy != " M" for record in status_records):
            continue
        if any(not is_prompt_archive_path(record.path) for record in status_records):
            continue
        if any(
            not _has_only_sdd_prompt_qa_diff(repo_dir, record.path)
            for record in status_records
        ):
            continue

        candidates.append(
            _SddPromptQaAutoCommitCandidate(
                repo_dir=repo_dir,
                paths=tuple(record.path for record in status_records),
            )
        )
    return tuple(candidates)


def auto_commit_sdd_prompt_qa_candidate(
    candidate: _SddPromptQaAutoCommitCandidate,
) -> bool:
    """Commit one proven Q&A-only agents-sidecar prompt change set."""

    from sase.workflows.commit.runtime_tags import apply_auto_commit_tags_with_runtime

    if not candidate.paths:
        return False
    from sase.agents_sync import git_sync
    from sase.agents_sync.git import run_git as run_agents_git

    repo = Path(candidate.repo_dir)
    lock_path = git_sync.agents_git_dir(repo, run_agents_git) / "sase-agents-sync.lock"
    with git_sync.bounded_agents_lock(
        lock_path,
        git_sync.configured_agents_lock_timeout(),
    ) as acquired:
        if not acquired:
            return False
        for path in candidate.paths:
            added = run_git(candidate.repo_dir, ["add", "--", path])
            if added is None or added.returncode != 0:
                return False
        stem = Path(candidate.paths[0]).stem
        message = apply_auto_commit_tags_with_runtime(
            f"Add Q&A to {stem} prompt",
            "sdd",
        )
        committed = run_git(
            candidate.repo_dir,
            ["commit", "--no-verify", "-m", message, "--", *candidate.paths],
            timeout=10,
        )
        return committed is not None and committed.returncode == 0


def _done_sdd_plan_status_auto_commit_candidate(
    dirty_state: DirtyState,
) -> _DoneStatusAutoCommitCandidate | None:
    if len(dirty_state.repos) != 1:
        return None

    repo = dirty_state.repos[0]
    repo_dir = normalize_path(repo.path)
    if repo.kind != "main" or repo_dir != normalize_path(dirty_state.project_dir):
        return None
    if len(repo.changed_files) != 1 or not _is_sdd_plan_markdown_path(
        repo.changed_files[0]
    ):
        return None

    status_records = git_status_records(repo_dir)
    if len(status_records) != 1:
        return None

    record = status_records[0]
    stage_path = _should_stage_modified_tracked_record(record)
    if stage_path is None:
        return None
    if not _is_sdd_plan_markdown_path(record.path):
        return None
    if not _has_exact_done_status_transition(repo_dir, record.path):
        return None

    return _DoneStatusAutoCommitCandidate(
        repo_dir=repo_dir,
        path=record.path,
        stage_path=stage_path,
    )


def _should_stage_modified_tracked_record(record: GitStatusRecord) -> bool | None:
    if " -> " in record.path:
        return None
    if record.xy == " M":
        return True
    if record.xy == "M ":
        return False
    return None


def _is_sdd_plan_markdown_path(path: str) -> bool:
    return path.endswith(".md") and path.startswith(_SDD_PLAN_DIR_PREFIXES)


def _has_exact_done_status_transition(repo_dir: str, path: str) -> bool:
    head_text = git_show_head_file(repo_dir, path)
    if head_text is None:
        return False

    try:
        worktree_text = (Path(repo_dir) / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False

    head_lines = head_text.splitlines(keepends=True)
    worktree_lines = worktree_text.splitlines(keepends=True)
    if len(head_lines) != len(worktree_lines):
        return False

    changed_indices = [
        idx
        for idx, (head_line, worktree_line) in enumerate(
            zip(head_lines, worktree_lines, strict=True)
        )
        if head_line != worktree_line
    ]
    if len(changed_indices) != 1:
        return False

    changed_idx = changed_indices[0]
    frontmatter_bounds = _frontmatter_bounds(head_lines)
    if frontmatter_bounds is None:
        return False
    frontmatter_start, frontmatter_end = frontmatter_bounds
    if not frontmatter_start <= changed_idx < frontmatter_end:
        return False

    head_content, head_ending = _split_line_ending(head_lines[changed_idx])
    worktree_content, worktree_ending = _split_line_ending(worktree_lines[changed_idx])
    return (
        head_content == "status: wip"
        and worktree_content == "status: done"
        and head_ending == worktree_ending
    )


def _has_only_sdd_prompt_qa_diff(repo_dir: str, path: str) -> bool:
    head_text = git_show_head_file(repo_dir, path)
    if head_text is None:
        return False

    try:
        worktree_text = (Path(repo_dir) / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    if _QA_HEADER not in worktree_text:
        return False

    from sase.sdd._write import strip_qa_block

    return strip_qa_block(worktree_text).rstrip("\n") == strip_qa_block(
        head_text
    ).rstrip("\n")


def _frontmatter_bounds(lines: list[str]) -> tuple[int, int] | None:
    if not lines or _line_content(lines[0]) != "---":
        return None
    for idx, line in enumerate(lines[1:], start=1):
        if _line_content(line) == "---":
            return (1, idx)
    return None


def _line_content(line: str) -> str:
    return _split_line_ending(line)[0]


def _split_line_ending(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def _git_add_and_commit_path(
    repo_dir: str,
    path: str,
    message: str,
    *,
    stage_path: bool,
) -> bool:
    if stage_path:
        add_result = run_git(repo_dir, ["add", "--", path])
        if add_result is None or add_result.returncode != 0:
            return False

    commit_result = run_git(
        repo_dir,
        ["commit", "--no-verify", "-m", message, "--", path],
        timeout=10,
    )
    if commit_result is None or commit_result.returncode != 0:
        if stage_path:
            run_git(repo_dir, ["reset", "-q", "--", path])
        return False
    return True
