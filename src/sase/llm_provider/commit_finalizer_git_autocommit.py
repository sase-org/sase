"""Narrow, provably-safe auto-commits performed during commit finalization.

Each auto-commit here must first *prove* the working tree holds nothing but
the one mechanical edit it is willing to own — an SDD plan's ``wip -> done``
status flip, a bead-store ``issues.jsonl`` reprojection, or a Q&A block
appended to an archived prompt. Anything broader is left for the agent to
commit itself.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from pathlib import Path
import shutil
import tempfile
from typing import TYPE_CHECKING

from .commit_finalizer_git_paths import (
    is_prompt_archive_path,
    normalize_path,
    normalize_status_path,
)
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
_ISSUES_JSONL = "issues.jsonl"
_NESTED_BEADS_ISSUES_JSONL = f"beads/{_ISSUES_JSONL}"

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _DoneStatusAutoCommitCandidate:
    repo_dir: str
    path: str
    stage_path: bool


@dataclass(frozen=True)
class _SddPromptQaAutoCommitCandidate:
    repo_dir: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class _SddBeadReprojectionAutoCommitCandidate:
    repo_name: str
    repo_dir: str
    path: str
    beads_dir: str
    stage_path: bool


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


def sdd_bead_reprojection_auto_commit_candidates(
    dirty_state: DirtyState,
) -> tuple[_SddBeadReprojectionAutoCommitCandidate, ...]:
    """Return SDD repos proven to contain only a bead ``issues.jsonl`` reprojection."""
    candidates: list[_SddBeadReprojectionAutoCommitCandidate] = []
    for repo in dirty_state.repos:
        if repo.kind != "sdd":
            continue
        candidate = _sdd_bead_reprojection_auto_commit_candidate(
            repo.name,
            normalize_path(repo.path),
            repo.changed_files,
        )
        if candidate is not None:
            candidates.append(candidate)
    return tuple(candidates)


def auto_commit_sdd_bead_reprojection_candidate(
    candidate: _SddBeadReprojectionAutoCommitCandidate,
    *,
    artifacts_dir: Path | None = None,
) -> bool:
    """Commit one proven bead ``issues.jsonl`` reprojection under the store lock."""

    from sase.bead._sync_git import bead_store_write_lock
    from sase.sdd._git import run_sdd_git
    from sase.sdd._git_contention import run_sdd_git_write
    from sase.workflows.commit.runtime_tags import apply_auto_commit_tags_with_runtime

    repo_dir = Path(candidate.repo_dir)
    beads_dir = Path(candidate.beads_dir)
    with bead_store_write_lock(beads_dir):
        current = _sdd_bead_reprojection_auto_commit_candidate(
            candidate.repo_name,
            candidate.repo_dir,
            (candidate.path,),
        )
        if current is None or current.beads_dir != candidate.beads_dir:
            return False

        if current.stage_path:
            added = run_sdd_git_write(
                ["add", "--", current.path],
                cwd=repo_dir,
                capture_output=True,
                check=False,
                op="bead.reprojection.add",
            )
            if added.returncode != 0:
                return False

        diff_result = run_sdd_git(
            ["diff", "--cached", "--quiet", "--", current.path],
            cwd=repo_dir,
            capture_output=True,
            check=False,
            op="bead.reprojection.diff_cached",
        )
        if diff_result.returncode == 0:
            return False
        if diff_result.returncode != 1:
            if current.stage_path:
                run_sdd_git_write(
                    ["reset", "-q", "--", current.path],
                    cwd=repo_dir,
                    capture_output=True,
                    check=False,
                    op="bead.reprojection.reset",
                )
            return False

        diff_path = _capture_cached_sdd_diff(
            repo_dir,
            current.path,
            artifacts_dir=artifacts_dir,
        )
        message = apply_auto_commit_tags_with_runtime(
            "chore(beads): reproject issues.jsonl",
            "beads",
        )
        committed = run_sdd_git_write(
            ["commit", "-m", message, "--", current.path],
            cwd=repo_dir,
            capture_output=True,
            check=False,
            op="bead.reprojection.commit",
        )
        if committed.returncode != 0:
            if current.stage_path:
                run_sdd_git_write(
                    ["reset", "-q", "--", current.path],
                    cwd=repo_dir,
                    capture_output=True,
                    check=False,
                    op="bead.reprojection.reset",
                )
            return False
    _record_sdd_commit_marker(
        repo_dir,
        repo_name=candidate.repo_name,
        message=message,
        artifacts_dir=artifacts_dir,
        diff_path=diff_path,
    )
    return True


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


def _sdd_bead_reprojection_auto_commit_candidate(
    repo_name: str,
    repo_dir: str,
    changed_files: tuple[str, ...],
) -> _SddBeadReprojectionAutoCommitCandidate | None:
    status_records = git_status_records(repo_dir)
    if len(status_records) != 1:
        return None

    record = status_records[0]
    record_path = normalize_status_path(record.path)
    if {normalize_status_path(path) for path in changed_files} != {record_path}:
        return None

    stage_path = _should_stage_modified_tracked_record(record)
    if stage_path is None:
        return None

    beads_dir = _bead_store_dir_for_issues_path(repo_dir, record_path)
    if beads_dir is None:
        return None
    if not _has_only_bead_issues_reprojection_diff(beads_dir):
        return None
    return _SddBeadReprojectionAutoCommitCandidate(
        repo_name=repo_name,
        repo_dir=repo_dir,
        path=record_path,
        beads_dir=str(beads_dir),
        stage_path=stage_path,
    )


def _bead_store_dir_for_issues_path(repo_dir: str, path: str) -> Path | None:
    relative = Path(path)
    if relative.is_absolute():
        return None
    if relative.as_posix() == _ISSUES_JSONL:
        beads_dir = Path(repo_dir)
    elif relative.as_posix() == _NESTED_BEADS_ISSUES_JSONL:
        beads_dir = Path(repo_dir) / "beads"
    else:
        return None

    if not (beads_dir / "config.json").is_file():
        return None
    return beads_dir


def _has_only_bead_issues_reprojection_diff(beads_dir: Path) -> bool:
    issues_path = beads_dir / _ISSUES_JSONL
    try:
        real_issues = issues_path.read_bytes()
    except OSError:
        return False

    temp_parent = _temporary_directory_parent()
    try:
        with tempfile.TemporaryDirectory(
            prefix="sase-bead-reprojection-",
            dir=temp_parent,
        ) as temp_root:
            copied = Path(temp_root) / "beads"
            shutil.copytree(
                beads_dir,
                copied,
                ignore=shutil.ignore_patterns(".git"),
            )
            from sase.core import bead_mutation_facade as rust_beads

            rust_beads.export_jsonl(copied)
            return (copied / _ISSUES_JSONL).read_bytes() == real_issues
    except Exception:
        _logger.debug(
            "Failed to prove bead issues.jsonl reprojection for %s",
            beads_dir,
            exc_info=True,
        )
        return False


def _temporary_directory_parent() -> str | None:
    sandbox = os.environ.get("SASE_PYTEST_SANDBOX_DIR", "").strip()
    if not sandbox:
        return None
    sandbox_path = Path(sandbox).expanduser()
    return str(sandbox_path) if sandbox_path.is_dir() else None


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


def _capture_cached_sdd_diff(
    repo_dir: Path,
    path: str,
    *,
    artifacts_dir: Path | None,
) -> str | None:
    resolved_artifacts_dir = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not resolved_artifacts_dir:
        return None

    from sase.sdd._git import run_sdd_git
    from sase.workflows.commit.commit_tracking import write_commit_diff_artifact

    try:
        diff_result = run_sdd_git(
            ["diff", "--cached", "--", path],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=False,
            op="bead.reprojection.capture_cached_diff",
        )
        if diff_result.returncode != 0 or not isinstance(diff_result.stdout, str):
            return None
        if not diff_result.stdout:
            return None
        return write_commit_diff_artifact(
            diff_result.stdout,
            artifacts_dir=resolved_artifacts_dir,
        )
    except Exception:
        _logger.debug("failed to capture bead reprojection diff", exc_info=True)
        return None


def _record_sdd_commit_marker(
    repo_dir: Path,
    *,
    repo_name: str,
    message: str,
    artifacts_dir: Path | None,
    diff_path: str | None,
) -> None:
    try:
        head = run_git(str(repo_dir), ["rev-parse", "HEAD"])
        if head is None or head.returncode != 0:
            return
        commit_sha = head.stdout.strip()
        if not commit_sha:
            return
        from sase.workflows.commit.commit_tracking import (
            record_sdd_commit_result_marker,
        )

        record_sdd_commit_result_marker(
            cwd=repo_dir,
            result=commit_sha,
            message=message,
            repo_name=repo_name,
            artifacts_dir=artifacts_dir,
            diff_path=diff_path,
        )
    except Exception:
        _logger.debug("failed to record bead reprojection commit marker", exc_info=True)


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
