"""Git and artifact path helpers for commit finalization."""

from __future__ import annotations

import ast
from collections.abc import Iterable
import subprocess
from dataclasses import dataclass
from pathlib import Path
import re
from typing import TYPE_CHECKING

from sase.git_lock_retry import run_with_git_lock_retry
from sase.linked_repos import (
    EXTERNAL_REPO_CLONES_SUBDIR,
    LINKED_REPO_CLONES_SUBDIR,
    SIDECAR_REPO_CLONES_SUBDIR,
)

if TYPE_CHECKING:
    from .commit_finalizer_types import DirtyState

_AUTO_COMMIT_GIT_TIMEOUT_SECONDS = 5
_SDD_PLAN_DIR_PREFIXES = ("sdd/plans/",)
_EXTERNAL_SDD_PROMPT_PATTERN = re.compile(r"prompts/\d{6}/[^/]+\.md")
_QA_HEADER = "### Questions and Answers"
_SASE_RESERVED_PATH_PARTS = (
    (".sase",),
    SIDECAR_REPO_CLONES_SUBDIR,
    LINKED_REPO_CLONES_SUBDIR,
    EXTERNAL_REPO_CLONES_SUBDIR,
)


def is_prompt_archive_path(path: str) -> bool:
    """Return whether *path* names a canonical archived prompt."""

    return _EXTERNAL_SDD_PROMPT_PATTERN.fullmatch(path) is not None


@dataclass(frozen=True)
class _GitStatusRecord:
    xy: str
    path: str


@dataclass(frozen=True)
class _DoneStatusAutoCommitCandidate:
    repo_dir: str
    path: str
    stage_path: bool


@dataclass(frozen=True)
class _SddPromptQaAutoCommitCandidate:
    repo_dir: str
    paths: tuple[str, ...]


def git_changed_files(repo_dir: str) -> list[str]:
    # Status/show subprocesses in this module are read-only. Auto-commit add,
    # commit, and reset operations all funnel through the retrying _run_git.
    repo_dir = normalize_path(repo_dir)
    if not Path(repo_dir).is_dir():
        return []
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_dir,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    return _changed_files_from_git_status(result.stdout)


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
        status_records = _git_status_records(repo_dir)
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
    from sase.agents_sync.git import run_git

    repo = Path(candidate.repo_dir)
    lock_path = git_sync.agents_git_dir(repo, run_git) / "sase-agents-sync.lock"
    with git_sync.bounded_agents_lock(
        lock_path,
        git_sync.configured_agents_lock_timeout(),
    ) as acquired:
        if not acquired:
            return False
        for path in candidate.paths:
            added = _run_git(candidate.repo_dir, ["add", "--", path])
            if added is None or added.returncode != 0:
                return False
        stem = Path(candidate.paths[0]).stem
        message = apply_auto_commit_tags_with_runtime(
            f"Add Q&A to {stem} prompt",
            "sdd",
        )
        committed = _run_git(
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

    status_records = _git_status_records(repo_dir)
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


def _git_status_records(repo_dir: str) -> list[_GitStatusRecord]:
    try:
        result = subprocess.run(
            [
                "git",
                "-C",
                repo_dir,
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_AUTO_COMMIT_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []

    records: list[_GitStatusRecord] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.rstrip()
        if len(line) < 4:
            return []
        records.append(_GitStatusRecord(xy=line[:2], path=line[3:]))
    return records


def _should_stage_modified_tracked_record(record: _GitStatusRecord) -> bool | None:
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
    head_text = _git_show_head_file(repo_dir, path)
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
    head_text = _git_show_head_file(repo_dir, path)
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


def _git_show_head_file(repo_dir: str, path: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", repo_dir, "show", f"HEAD:{path}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_AUTO_COMMIT_GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    return result.stdout


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
        add_result = _run_git(repo_dir, ["add", "--", path])
        if add_result is None or add_result.returncode != 0:
            return False

    commit_result = _run_git(
        repo_dir,
        ["commit", "--no-verify", "-m", message, "--", path],
        timeout=10,
    )
    if commit_result is None or commit_result.returncode != 0:
        if stage_path:
            _run_git(repo_dir, ["reset", "-q", "--", path])
        return False
    return True


def _run_git(
    repo_dir: str,
    args: list[str],
    *,
    timeout: int = _AUTO_COMMIT_GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str] | None:
    try:
        result, _outcome = run_with_git_lock_retry(
            lambda: subprocess.run(
                ["git", "-C", repo_dir, *args],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            ),
            cwd=repo_dir,
        )
        return result
    except Exception:
        return None


def _changed_files_from_git_status(status_text: str) -> list[str]:
    changed: list[str] = []
    for raw_line in status_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        path = line[3:] if len(line) > 3 else line
        is_rename = len(line) >= 2 and bool({"R", "C"} & set(line[:2]))
        if _is_sase_reserved_status_path(path, is_rename=is_rename):
            continue
        changed.append(path)
    return changed


def filter_sase_reserved_paths(paths: Iterable[str]) -> list[str]:
    """Remove root-scoped SASE metadata paths from a changed-file list."""

    return [path for path in paths if not _is_sase_reserved_status_path(path)]


def _is_sase_reserved_status_path(path: str, *, is_rename: bool = False) -> bool:
    candidates = path.split(" -> ", 1) if is_rename or " -> " in path else [path]
    return any(_is_sase_reserved_path(_unquote_git_path(item)) for item in candidates)


def _unquote_git_path(path: str) -> str:
    normalized = path.strip()
    if len(normalized) >= 2 and normalized[0] == normalized[-1] == '"':
        try:
            value = ast.literal_eval(normalized)
        except (SyntaxError, ValueError):
            return normalized[1:-1]
        if isinstance(value, str):
            return value
    return normalized


def _is_sase_reserved_path(path: str) -> bool:
    normalized = path[2:] if path.startswith("./") else path
    parts = tuple(part for part in normalized.split("/") if part)
    return any(parts[: len(prefix)] == prefix for prefix in _SASE_RESERVED_PATH_PARTS)


def normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))
