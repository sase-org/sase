"""Git and artifact path helpers for commit finalization."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .commit_finalizer_types import DirtyState

_AUTO_COMMIT_GIT_TIMEOUT_SECONDS = 5
_SDD_PLAN_DIR_PREFIXES = ("sdd/plans/",)


@dataclass(frozen=True)
class _GitStatusRecord:
    xy: str
    path: str


@dataclass(frozen=True)
class _DoneStatusAutoCommitCandidate:
    repo_dir: str
    path: str
    stage_path: bool


def git_changed_files(repo_dir: str) -> list[str]:
    repo_dir = _normalize_path(repo_dir)
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


def _done_sdd_plan_status_auto_commit_candidate(
    dirty_state: DirtyState,
) -> _DoneStatusAutoCommitCandidate | None:
    if len(dirty_state.repos) != 1:
        return None

    repo = dirty_state.repos[0]
    repo_dir = _normalize_path(repo.path)
    if repo.kind != "main" or repo_dir != _normalize_path(dirty_state.project_dir):
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
        return subprocess.run(
            ["git", "-C", repo_dir, *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except Exception:
        return None


def _changed_files_from_git_status(status_text: str) -> list[str]:
    changed: list[str] = []
    for raw_line in status_text.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        changed.append(line[3:] if len(line) > 3 else line)
    return changed


def _normalize_path(path: str) -> str:
    return str(Path(path).expanduser().resolve(strict=False))
