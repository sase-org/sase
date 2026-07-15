"""Commit helpers for SDD storage repositories."""

import logging
import os
import subprocess
from collections.abc import Iterable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from sase.sdd._git import SddGitCommandTimeout, run_sdd_git
from sase.sdd._git_contention import (
    SddGitCommandError,
    run_sdd_git_write,
    store_git_write_lock,
)
from sase.sdd._store_types import (
    SDD_STORAGE_SIDECAR_REPOS,
    SDD_STORAGE_SEPARATE_REPO,
)

if TYPE_CHECKING:
    from sase.sdd.store import SddStore

_logger = logging.getLogger(__name__)


def commit_sdd_files(
    sdd_dir: Path,
    message: str,
    *,
    auto_commit_type: str = "sdd",
    paths: Iterable[str | Path] | None = None,
    artifacts_dir: str | Path | None = None,
    repo_name: str | None = None,
    record_commit_marker: bool = True,
) -> bool:
    """Auto-commit SDD files in a local `.sase/sdd/` git repo.

    Returns true only when a new commit is created. No-ops if `sdd_dir` is not
    a git repo or there are no staged changes.
    """
    if not (sdd_dir / ".git").is_dir():
        return False

    pathspecs = normalize_sdd_commit_pathspecs(sdd_dir, paths)
    try:
        changed_files = changed_sdd_files(sdd_dir, pathspecs)
    except subprocess.CalledProcessError as exc:
        raise SddGitCommandError.from_error(exc) from exc
    if not changed_files:
        return False

    with store_git_write_lock(sdd_dir):
        run_sdd_git_write(
            ["add", "--"] + changed_files,
            cwd=sdd_dir,
            check=True,
            capture_output=True,
            op="sdd.add",
        )

        result = run_sdd_git(
            ["diff", "--cached", "--quiet", "--"] + changed_files,
            cwd=sdd_dir,
            capture_output=True,
            check=False,
            op="sdd.diff_cached",
        )
        if result.returncode == 0:
            return False
        diff_path = _capture_staged_sdd_diff(
            sdd_dir,
            changed_files,
            artifacts_dir=artifacts_dir,
        )
        from sase.workflows.commit.runtime_tags import (
            apply_auto_commit_tags_with_runtime,
        )

        message = apply_auto_commit_tags_with_runtime(message, auto_commit_type)
        run_sdd_git_write(
            ["commit", "-m", message, "--"] + changed_files,
            cwd=sdd_dir,
            check=True,
            capture_output=True,
            op="sdd.commit",
        )
    if record_commit_marker:
        _record_sdd_commit_marker(
            sdd_dir,
            message=message,
            artifacts_dir=artifacts_dir,
            repo_name=repo_name,
            diff_path=diff_path,
        )
    return True


def sdd_commit_targets(
    store: "SddStore", paths: Iterable[str | Path] | None
) -> list[tuple["SddStore", list[str | Path] | None]]:
    """Partition split-store paths between the plans and research repos."""

    if not store.is_sidecar_storage or store.research_dir is None:
        return [(store, list(paths) if paths is not None else None)]

    plans_store = replace(store, research_dir=None, research_remote_url=None)
    research_store = replace(
        store,
        sdd_dir=store.research_dir,
        repo_root=store.research_dir,
        remote_url=store.research_remote_url,
        research_dir=None,
        research_remote_url=None,
    )
    if paths is None:
        return [(plans_store, None), (research_store, None)]

    plans_paths: list[str | Path] = []
    research_paths: list[str | Path] = []
    research_root = store.research_dir.expanduser().resolve(strict=False)
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_absolute() and _path_is_within(path, research_root):
            research_paths.append(raw_path)
        else:
            # Relative paths retain the historical interpretation: they are
            # rooted at the store's primary (plans) repository.
            plans_paths.append(raw_path)

    targets: list[tuple[SddStore, list[str | Path] | None]] = []
    if plans_paths:
        targets.append((plans_store, plans_paths))
    if research_paths:
        targets.append((research_store, research_paths))
    return targets


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.expanduser().resolve(strict=False).relative_to(root)
    except ValueError:
        return False
    return True


def _record_sdd_commit_marker(
    sdd_dir: Path,
    *,
    message: str,
    artifacts_dir: str | Path | None,
    repo_name: str | None,
    diff_path: str | None,
) -> None:
    try:
        sha = _git_head_sha(sdd_dir)
        if not sha:
            return
        from sase.workflows.commit.commit_tracking import (
            record_sdd_commit_result_marker,
        )

        record_sdd_commit_result_marker(
            cwd=sdd_dir.expanduser().resolve(),
            result=sha,
            message=message,
            repo_name=repo_name,
            artifacts_dir=artifacts_dir,
            diff_path=diff_path,
        )
    except Exception:
        _logger.debug("failed to record SDD commit marker", exc_info=True)


def _capture_staged_sdd_diff(
    sdd_dir: Path,
    changed_files: list[str],
    *,
    artifacts_dir: str | Path | None,
) -> str | None:
    resolved_artifacts_dir = artifacts_dir or os.environ.get("SASE_ARTIFACTS_DIR")
    if not resolved_artifacts_dir:
        return None
    try:
        result = run_sdd_git(
            ["diff", "--cached", "--"] + changed_files,
            cwd=sdd_dir,
            capture_output=True,
            text=True,
            check=True,
            op="sdd.capture_cached_diff",
        )
        diff_text = result.stdout
        if not isinstance(diff_text, str) or not diff_text:
            return None
        from sase.workflows.commit.commit_tracking import (
            write_commit_diff_artifact,
        )

        return write_commit_diff_artifact(
            diff_text,
            artifacts_dir=resolved_artifacts_dir,
        )
    except Exception:
        _logger.debug("failed to capture staged SDD diff", exc_info=True)
        return None


def _git_head_sha(repo_dir: Path) -> str | None:
    try:
        result = run_sdd_git(
            ["rev-parse", "HEAD"],
            cwd=repo_dir,
            capture_output=True,
            text=True,
            check=True,
            op="sdd.rev_parse_head",
        )
    except (subprocess.CalledProcessError, SddGitCommandTimeout):
        return None
    sha = result.stdout.strip()
    return sha or None


def sdd_store_label(store: "SddStore") -> str | None:
    if store.storage not in {
        SDD_STORAGE_SEPARATE_REPO,
        SDD_STORAGE_SIDECAR_REPOS,
    }:
        return None

    if store.remote_url:
        label = _repo_label_from_remote_url(store.remote_url)
        if label:
            return label
    label = _sdd_store_record_label(store)
    if label:
        return label
    return "sdd"


def _sdd_store_record_label(store: "SddStore") -> str | None:
    try:
        from sase.sdd.store import read_sdd_store_record

        workspace_dir = store.sdd_dir.parent.parent
        record = read_sdd_store_record(workspace_dir)
    except Exception:
        return None
    if record is not None and record.repo:
        return record.repo
    return None


def _repo_label_from_remote_url(remote_url: str) -> str | None:
    raw = remote_url.strip().rstrip("/")
    if not raw:
        return None
    if raw.endswith(".git"):
        raw = raw[:-4]

    path_part = raw
    if "://" in path_part:
        _, _, without_scheme = path_part.partition("://")
        _, _, path_part = without_scheme.partition("/")
    elif ":" in path_part and not path_part.startswith(("/", ".")):
        path_part = path_part.rsplit(":", 1)[1]

    parts = [part for part in path_part.split("/") if part]
    if len(parts) >= 2:
        return "/".join(parts[-2:])
    if parts:
        return parts[-1]
    return None


def _sdd_push_after_commit_config() -> bool | Literal["async"]:
    """Return the configured SDD push mode."""

    try:
        from sase.config import load_merged_config

        raw = load_merged_config().get("sdd", {}).get("push_after_commit", "async")
    except Exception:
        return "async"
    if raw in (True, False, "async"):
        return raw  # type: ignore[return-value]
    return "async"


def push_sdd_store_after_commit(
    store: "SddStore",
    *,
    push_after_commit: bool | Literal["async"] | None,
) -> None:
    if store.storage not in {
        SDD_STORAGE_SEPARATE_REPO,
        SDD_STORAGE_SIDECAR_REPOS,
    }:
        return

    mode = (
        _sdd_push_after_commit_config()
        if push_after_commit is None
        else push_after_commit
    )
    if mode is False:
        return

    from sase.bead.sync import push_bead_work_launch, push_bead_work_launch_async

    if mode == "async":
        handle = push_bead_work_launch_async(store.repo_root)
        if handle is not None:
            _logger.info(
                "Started async SDD push pid=%s log=%s",
                handle.pid,
                handle.log_path,
            )
        return

    outcome = push_bead_work_launch(store.repo_root)
    if outcome.error:
        _logger.warning("SDD git push failed after local commit: %s", outcome.error)


def normalize_sdd_commit_pathspecs(
    sdd_dir: Path,
    paths: Iterable[str | Path] | None,
) -> list[str]:
    """Return git pathspecs rooted at ``sdd_dir`` for targeted SDD commits."""
    if paths is None:
        return ["."]

    sdd_root = sdd_dir.resolve()
    pathspecs: list[str] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_absolute():
            try:
                path = path.resolve().relative_to(sdd_root)
            except ValueError:
                path = Path(raw_path)
        pathspec = path.as_posix()
        if pathspec and pathspec != ".":
            pathspecs.append(pathspec)
    return pathspecs or ["."]


def changed_sdd_files(sdd_dir: Path, pathspecs: list[str]) -> list[str]:
    """Return concrete changed files under ``pathspecs`` in the SDD git repo."""
    result = run_sdd_git(
        [
            "ls-files",
            "--modified",
            "--others",
            "--deleted",
            "--exclude-standard",
            "-z",
            "--",
            *pathspecs,
        ],
        cwd=sdd_dir,
        check=True,
        capture_output=True,
        op="sdd.changed_files",
    )
    stdout = result.stdout or b""
    if isinstance(stdout, str):
        return [path for path in stdout.split("\0") if path]
    return [path.decode("utf-8") for path in stdout.split(b"\0") if path]
