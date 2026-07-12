"""SDD initialization commits for local bare-git workspaces."""

import logging
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

from sase.sdd._git import SddGitCommandTimeout, network_git_timeout, run_sdd_git
from sase.sdd._init_files import ensure_sdd_initialized

_logger = logging.getLogger(__name__)


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

    try:
        result = run_sdd_git(
            ["config", "--get", "remote.origin.url"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
            op="bare_git.remote_url",
        )
    except SddGitCommandTimeout:
        return False
    if result.returncode != 0:
        return False
    url = result.stdout.strip()
    if not url:
        return False
    return not url.startswith(("http://", "https://", "git@", "ssh://"))


def git_toplevel(workspace: Path) -> Path | None:
    try:
        result = run_sdd_git(
            ["rev-parse", "--show-toplevel"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
            op="bare_git.toplevel",
        )
    except SddGitCommandTimeout:
        return None
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

    run_sdd_git(
        ["add", "--", *rel_paths],
        cwd=git_root,
        check=True,
        capture_output=True,
        text=True,
        op="bare_git_sdd_init.add",
    )

    diff = run_sdd_git(
        ["diff", "--cached", "--quiet", "--", *rel_paths],
        cwd=git_root,
        capture_output=True,
        text=True,
        check=False,
        op="bare_git_sdd_init.diff_cached",
    )
    if diff.returncode == 0:
        return
    if diff.returncode != 1:
        raise RuntimeError((diff.stderr or "git diff --cached failed").strip())

    from sase.workflows.commit.runtime_tags import apply_auto_commit_tags_with_runtime

    message = apply_auto_commit_tags_with_runtime("Initialize SDD", "init")
    run_sdd_git(
        [
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
        op="bare_git_sdd_init.commit",
    )

    if push:
        try:
            run_sdd_git(
                ["push", "origin", "HEAD"],
                cwd=git_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=network_git_timeout(),
                op="bare_git_sdd_init.push",
            )
        except (subprocess.CalledProcessError, SddGitCommandTimeout) as exc:
            # Pushing the generated SDD init commit is a best-effort sync with
            # the bare remote. A rejection or timeout must never abort the
            # caller: the local commit is preserved and can be pushed later.
            detail = ""
            if isinstance(exc, subprocess.CalledProcessError):
                detail = (exc.stderr or exc.stdout or "").strip()
            _logger.warning(
                "Best-effort SDD init push failed in %s: %s",
                git_root,
                detail or exc,
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
