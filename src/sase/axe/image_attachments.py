"""Attachment discovery for completed agent runs."""

from __future__ import annotations

import os
import socket
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from sase.media_types import SUPPORTED_VIDEO_EXTENSIONS, is_supported_video_path

SUPPORTED_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif"})
SUPPORTED_MARKDOWN_EXTENSIONS = frozenset({".md", ".markdown"})
MAX_COMPLETION_IMAGE_ATTACHMENTS = 10
_ATTACHMENT_STATUS_LETTERS = frozenset({"A", "C", "M", "R", "T"})


@dataclass(frozen=True)
class ExtraRepoScan:
    """Additional git repository to scan for agent-created attachments."""

    repo_dir: str
    base_sha: str | None = None
    agent_name: str | None = None
    include_working_tree: bool = False
    exclude: Callable[[str], bool] | None = None


@dataclass(frozen=True)
class DiffScan:
    """Saved diff whose paths are relative to a particular repository."""

    diff_path: str
    base_dir: str | None = None


def _is_supported_image_path(path: str | os.PathLike[str]) -> bool:
    """Return whether *path* has an image extension SASE should attach."""
    return Path(path).suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS


def _is_supported_video_path(path: str | os.PathLike[str]) -> bool:
    """Return whether *path* has a video extension SASE should attach."""
    return is_supported_video_path(Path(path))


def _is_supported_markdown_path(path: str | os.PathLike[str]) -> bool:
    return Path(path).suffix.lower() in SUPPORTED_MARKDOWN_EXTENSIONS


def append_unique_paths(
    paths: Iterable[str], existing: Iterable[str] = ()
) -> list[str]:
    """Return *paths* without duplicates, preserving order after *existing*."""
    seen = {os.path.abspath(os.path.expanduser(path)) for path in existing if path}
    result: list[str] = []
    for path in paths:
        if not path:
            continue
        key = os.path.abspath(os.path.expanduser(path))
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result


def collect_agent_image_paths(
    workspace_dir: str,
    *,
    diff_path: str | None = None,
    diff_scans: Iterable[DiffScan] = (),
    include_head_commit: bool = False,
    existing_files: Iterable[str] = (),
    extra_repo_scans: Iterable[ExtraRepoScan] = (),
) -> list[str]:
    """Collect image files added or modified by an agent.

    Sources are checked in stable order: local tracked changes, local
    untracked files, a saved commit/proposal diff, and optionally the most
    recent commit. Returned paths are absolute so notification senders can
    attach files outside the agent workspace.
    """
    return _collect_agent_attachment_paths(
        workspace_dir,
        is_supported_path=_is_supported_image_path,
        diff_path=diff_path,
        diff_scans=diff_scans,
        include_head_commit=include_head_commit,
        existing_files=existing_files,
        extra_repo_scans=extra_repo_scans,
    )


def collect_agent_video_paths(
    workspace_dir: str,
    *,
    diff_path: str | None = None,
    diff_scans: Iterable[DiffScan] = (),
    include_head_commit: bool = False,
    existing_files: Iterable[str] = (),
    extra_repo_scans: Iterable[ExtraRepoScan] = (),
) -> list[str]:
    """Collect video files added or modified by an agent.

    Sources and ordering match generated-image discovery. Returned paths are
    absolute so notification senders can attach files outside the workspace.
    """
    return _collect_agent_attachment_paths(
        workspace_dir,
        is_supported_path=_is_supported_video_path,
        diff_path=diff_path,
        diff_scans=diff_scans,
        include_head_commit=include_head_commit,
        existing_files=existing_files,
        extra_repo_scans=extra_repo_scans,
    )


def collect_agent_markdown_paths(
    workspace_dir: str,
    *,
    diff_path: str | None = None,
    diff_scans: Iterable[DiffScan] = (),
    include_head_commit: bool = False,
    existing_files: Iterable[str] = (),
    artifacts_dir: str | None = None,
    extra_repo_scans: Iterable[ExtraRepoScan] = (),
) -> list[str]:
    """Collect Markdown files added or modified by an agent.

    Sources are checked in the same stable order as image discovery: local
    tracked changes, local untracked files, a saved commit/proposal diff, and
    optionally the most recent commit. Returned paths are absolute source files
    suitable for later conversion steps. Files under ``artifacts_dir`` are
    excluded so generated run artifacts do not feed back into discovery.
    """
    return _collect_agent_attachment_paths(
        workspace_dir,
        is_supported_path=_is_supported_markdown_path,
        diff_path=diff_path,
        diff_scans=diff_scans,
        include_head_commit=include_head_commit,
        existing_files=existing_files,
        artifacts_dir=artifacts_dir,
        extra_repo_scans=extra_repo_scans,
    )


def _collect_agent_attachment_paths(
    workspace_dir: str,
    *,
    is_supported_path: Callable[[str | os.PathLike[str]], bool],
    diff_path: str | None = None,
    diff_scans: Iterable[DiffScan] = (),
    include_head_commit: bool = False,
    existing_files: Iterable[str] = (),
    artifacts_dir: str | None = None,
    extra_repo_scans: Iterable[ExtraRepoScan] = (),
) -> list[str]:
    candidates: list[tuple[str, str]] = []
    candidates.extend(
        (path, workspace_dir) for path in _local_changed_paths(workspace_dir)
    )
    candidates.extend((path, workspace_dir) for path in _untracked_paths(workspace_dir))
    candidates.extend(
        (path, workspace_dir) for path in _paths_from_diff_file(diff_path)
    )
    for diff_scan in diff_scans:
        base_dir = diff_scan.base_dir or workspace_dir
        candidates.extend(
            (path, base_dir) for path in _paths_from_diff_file(diff_scan.diff_path)
        )
    if include_head_commit:
        candidates.extend(
            (path, workspace_dir) for path in _head_commit_paths(workspace_dir)
        )

    attachment_paths = [
        resolved
        for candidate, base_dir in candidates
        if (
            resolved := _resolve_existing_attachment_path(
                candidate,
                base_dir,
                is_supported_path=is_supported_path,
                artifacts_dir=artifacts_dir,
            )
        )
    ]
    for extra_scan in extra_repo_scans:
        repo_dir = _scan_repo_dir(extra_scan)
        if repo_dir is None:
            continue
        attachment_paths.extend(
            resolved
            for candidate in _extra_repo_changed_paths(repo_dir, extra_scan)
            if (
                resolved := _resolve_existing_attachment_path(
                    candidate,
                    repo_dir,
                    is_supported_path=is_supported_path,
                    artifacts_dir=artifacts_dir,
                )
            )
        )
    return append_unique_paths(attachment_paths, existing_files)


def _local_changed_paths(workspace_dir: str) -> list[str]:
    return _paths_from_name_status(
        _run_git(workspace_dir, "diff", "--name-status", "-z", "HEAD", "--")
    )


def _head_commit_paths(workspace_dir: str) -> list[str]:
    return _paths_from_name_status(
        _run_git(workspace_dir, "diff", "--name-status", "-z", "HEAD~1..HEAD", "--")
    )


def _extra_repo_changed_paths(repo_dir: str, scan: ExtraRepoScan) -> list[str]:
    paths: list[str] = []
    base = (scan.base_sha or "").strip()
    agent_name = (scan.agent_name or "").strip()
    if base and agent_name:
        head = _git_head_sha(repo_dir)
        if head and head != base:
            paths.extend(_attributed_commit_paths(repo_dir, base, agent_name))
    if scan.include_working_tree:
        paths.extend(_local_changed_paths(repo_dir))
        paths.extend(_untracked_paths(repo_dir))
    if scan.exclude is None:
        return paths
    return [path for path in paths if not scan.exclude(path)]


def _attributed_commit_paths(
    repo_dir: str,
    base_sha: str,
    agent_name: str,
) -> list[str]:
    from sase.workflows.commit.runtime_tags import parse_trailing_commit_tags

    output = _run_git(
        repo_dir,
        "log",
        "--reverse",
        "-z",
        "--format=%H%x1f%B",
        f"{base_sha}..HEAD",
    )
    current_hostname = _current_hostname()
    paths: list[str] = []
    for record in output.split("\0"):
        if "\x1f" not in record:
            continue
        commit_sha, message = record.split("\x1f", 1)
        commit_sha = commit_sha.strip()
        if not commit_sha:
            continue
        tags = parse_trailing_commit_tags(message)
        if not _agent_tag_matches(tags.get("AGENT"), agent_name):
            continue
        tagged_machine = tags.get("MACHINE")
        if tagged_machine and tagged_machine != current_hostname:
            continue
        paths.extend(
            _paths_from_name_status(
                _run_git(
                    repo_dir,
                    "diff-tree",
                    "--no-commit-id",
                    "--name-status",
                    "-z",
                    "-r",
                    commit_sha,
                )
            )
        )
    return paths


def _agent_tag_matches(tagged_agent: str | None, agent_name: str) -> bool:
    return bool(
        tagged_agent
        and (
            tagged_agent == agent_name
            or tagged_agent.startswith(f"{agent_name}.")
            or tagged_agent.startswith(f"{agent_name}--")
        )
    )


def _current_hostname() -> str | None:
    try:
        hostname = socket.gethostname().strip()
    except OSError:
        hostname = ""
    return hostname or (os.environ.get("HOSTNAME") or "").strip() or None


def _scan_repo_dir(scan: ExtraRepoScan) -> str | None:
    if not scan.repo_dir:
        return None
    repo_dir = Path(os.path.expanduser(scan.repo_dir))
    if not (repo_dir / ".git").exists():
        return None
    return str(repo_dir)


def _git_head_sha(workspace_dir: str) -> str:
    return _run_git(workspace_dir, "rev-parse", "HEAD").strip()


def same_git_repo(left_dir: str, right_dir: str) -> bool:
    """Return whether two directories belong to the same Git worktree."""
    left_root = _run_git(left_dir, "rev-parse", "--show-toplevel").strip()
    right_root = _run_git(right_dir, "rev-parse", "--show-toplevel").strip()
    if not left_root or not right_root:
        return False
    try:
        return Path(left_root).resolve() == Path(right_root).resolve()
    except OSError:
        return False


def _untracked_paths(workspace_dir: str) -> list[str]:
    output = _run_git(workspace_dir, "ls-files", "--others", "--exclude-standard", "-z")
    return [part for part in output.split("\0") if part]


def _run_git(workspace_dir: str, *args: str) -> str:
    # Attachment discovery uses only diff/log/rev-parse/ls-files probes; no
    # call in this module writes the index, so lock retries would add no value.
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=workspace_dir,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout


def _paths_from_name_status(output: str) -> list[str]:
    if not output:
        return []
    parts = output.split("\0")
    if parts and parts[-1] == "":
        parts.pop()

    paths: list[str] = []
    i = 0
    while i < len(parts):
        status = parts[i]
        i += 1
        if not status:
            continue
        letter = status[0]
        if letter in {"R", "C"}:
            if i + 1 >= len(parts):
                break
            _old_path = parts[i]
            new_path = parts[i + 1]
            i += 2
            if letter in _ATTACHMENT_STATUS_LETTERS:
                paths.append(new_path)
            continue
        if i >= len(parts):
            break
        path = parts[i]
        i += 1
        if letter in _ATTACHMENT_STATUS_LETTERS:
            paths.append(path)
    return paths


def _paths_from_diff_file(diff_path: str | None) -> list[str]:
    if not diff_path:
        return []
    path = Path(os.path.expanduser(diff_path))
    try:
        diff_text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return _paths_from_diff_text(diff_text)


def _paths_from_diff_text(diff_text: str) -> list[str]:
    paths: list[str] = []
    deleted_paths: set[str] = set()
    current_path: str | None = None

    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            parts = line.split()
            current_path = _normalize_diff_path(parts[3]) if len(parts) >= 4 else None
            if current_path:
                paths.append(current_path)
            continue
        if line.startswith("rename to "):
            current_path = _normalize_diff_path(line.removeprefix("rename to "))
            if current_path:
                paths.append(current_path)
            continue
        if line.startswith("+++ "):
            current_path = _normalize_diff_path(line.removeprefix("+++ "))
            if current_path:
                paths.append(current_path)
            continue
        if line.startswith("deleted file mode") and current_path:
            deleted_paths.add(current_path)

    return [path for path in paths if path not in deleted_paths]


def _normalize_diff_path(path: str) -> str | None:
    value = path.strip()
    if not value or value == "/dev/null":
        return None
    if value.startswith("a/") or value.startswith("b/"):
        value = value[2:]
    return value or None


def _resolve_existing_attachment_path(
    path: str,
    workspace_dir: str,
    *,
    is_supported_path: Callable[[str | os.PathLike[str]], bool],
    artifacts_dir: str | None = None,
) -> str | None:
    if not is_supported_path(path):
        return None
    candidate = Path(os.path.expanduser(path))
    if not candidate.is_absolute():
        candidate = Path(workspace_dir) / candidate
    try:
        resolved = candidate.resolve(strict=True)
    except OSError:
        return None
    if artifacts_dir and _is_relative_to_directory(resolved, artifacts_dir):
        return None
    if not resolved.is_file():
        return None
    return str(resolved)


def _is_relative_to_directory(path: Path, directory: str) -> bool:
    try:
        root = Path(os.path.expanduser(directory)).resolve(strict=False)
        path.relative_to(root)
    except (OSError, ValueError):
        return False
    return True
