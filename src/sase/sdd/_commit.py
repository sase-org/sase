"""SDD git commit helpers."""

import logging
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

from sase.sdd._init_files import ensure_sdd_initialized

_logger = logging.getLogger(__name__)


def commit_sdd_files(
    sdd_dir: Path,
    message: str,
    *,
    auto_commit_type: str = "sdd",
    paths: Iterable[str | Path] | None = None,
) -> None:
    """Auto-commit SDD files in a local `.sase/sdd/` git repo.

    No-op if `sdd_dir` is not a git repo or there are no staged changes.
    """
    if not (sdd_dir / ".git").is_dir():
        return

    pathspecs = normalize_sdd_commit_pathspecs(sdd_dir, paths)
    changed_files = changed_sdd_files(sdd_dir, pathspecs)
    if not changed_files:
        return

    subprocess.run(
        ["git", "add", "--"] + changed_files,
        cwd=sdd_dir,
        check=True,
        capture_output=True,
    )

    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--"] + changed_files,
        cwd=sdd_dir,
        capture_output=True,
    )
    if result.returncode != 0:
        from sase.workflows.commit.runtime_tags import (
            apply_auto_commit_tags_with_runtime,
        )

        message = apply_auto_commit_tags_with_runtime(message, auto_commit_type)
        subprocess.run(
            ["git", "commit", "-m", message, "--"] + changed_files,
            cwd=sdd_dir,
            check=True,
            capture_output=True,
        )


def ensure_bare_git_sdd_initialized(
    workspace_dir: str | Path,
    *,
    commit: bool = True,
    push: bool = False,
    raise_on_error: bool = False,
    initializer: Callable[[str | Path | None], tuple[Path, ...]]
    | None = ensure_sdd_initialized,
) -> tuple[Path, ...]:
    """Ensure generated SDD init files exist for a local bare-git checkout.

    Non-bare-git workspaces are a no-op. When *commit* is true, only generated
    SDD init paths are staged and committed. *push* is reserved for repository
    setup/materialization flows that already own synchronization with the bare
    remote.
    """
    workspace = Path(workspace_dir).expanduser()
    if not is_local_bare_git_workspace(workspace):
        return ()

    git_root = git_toplevel(workspace)
    if git_root is None:
        return ()

    init = ensure_sdd_initialized if initializer is None else initializer
    refreshed = init(git_root)
    if not refreshed or not commit:
        return refreshed

    try:
        commit_bare_git_sdd_init_paths(git_root, refreshed, push=push)
    except Exception as exc:
        message = f"Failed to commit generated SDD init files in {git_root}: {exc}"
        if raise_on_error:
            raise RuntimeError(message) from exc
        _logger.warning(message)

    return refreshed


def is_local_bare_git_workspace(workspace: Path) -> bool:
    """Return true for SASE's built-in bare-git local-remote workspaces."""
    try:
        from sase.vcs_provider import detect_vcs

        if detect_vcs(str(workspace)) != "bare_git":
            return False
    except Exception:
        return False

    result = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    url = result.stdout.strip()
    if not url:
        return False
    return not url.startswith(("http://", "https://", "git@", "ssh://"))


def git_toplevel(workspace: Path) -> Path | None:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    root = result.stdout.strip()
    if not root:
        return None
    return Path(root).resolve()


def commit_bare_git_sdd_init_paths(
    git_root: Path,
    paths: Iterable[Path],
    *,
    push: bool,
) -> None:
    rel_paths = relative_git_pathspecs(git_root, paths)
    if not rel_paths:
        return

    subprocess.run(
        ["git", "add", "--", *rel_paths],
        cwd=git_root,
        check=True,
        capture_output=True,
        text=True,
    )

    diff = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--", *rel_paths],
        cwd=git_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if diff.returncode == 0:
        return
    if diff.returncode != 1:
        raise RuntimeError((diff.stderr or "git diff --cached failed").strip())

    from sase.workflows.commit.runtime_tags import apply_auto_commit_tags_with_runtime

    message = apply_auto_commit_tags_with_runtime("Initialize SDD", "init")
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=sase@localhost",
            "-c",
            "user.name=sase",
            "commit",
            "-m",
            message,
            "--",
            *rel_paths,
        ],
        cwd=git_root,
        check=True,
        capture_output=True,
        text=True,
    )

    if push:
        subprocess.run(
            ["git", "push", "origin", "HEAD"],
            cwd=git_root,
            check=True,
            capture_output=True,
            text=True,
        )


def relative_git_pathspecs(git_root: Path, paths: Iterable[Path]) -> list[str]:
    root = git_root.resolve()
    rel_paths: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path)
        try:
            rel_paths.add(path.resolve().relative_to(root).as_posix())
        except ValueError:
            continue
    return sorted(path for path in rel_paths if path)


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
    result = subprocess.run(
        [
            "git",
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
    )
    stdout = result.stdout or b""
    if isinstance(stdout, str):
        return [path for path in stdout.split("\0") if path]
    return [path.decode("utf-8") for path in stdout.split(b"\0") if path]
