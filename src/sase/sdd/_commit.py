"""SDD git commit helpers."""

import logging
import os
import subprocess
import time
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sase.sdd._init_files import ensure_sdd_initialized

if TYPE_CHECKING:
    from sase.sdd.store import SddStore

_logger = logging.getLogger(__name__)

ENV_LOCAL_TIMEOUT = "SASE_SDD_GIT_LOCAL_TIMEOUT"
ENV_NETWORK_TIMEOUT = "SASE_SDD_GIT_NETWORK_TIMEOUT"
ENV_SLOW_MS = "SASE_SDD_GIT_SLOW_MS"

DEFAULT_LOCAL_GIT_TIMEOUT_SECONDS = 30.0
DEFAULT_NETWORK_GIT_TIMEOUT_SECONDS = 120.0
DEFAULT_SLOW_GIT_MS = 1_000.0


class SddGitCommandTimeout(RuntimeError):
    """Raised when a bounded SDD git command exceeds its timeout."""


def _run_git(
    args: list[str],
    *,
    cwd: Path,
    op: str,
    timeout: float | None = None,
    check: bool,
    capture_output: bool,
    text: bool = False,
) -> subprocess.CompletedProcess[Any]:
    """Run git with a finite timeout and structured timing telemetry."""
    timeout_seconds = timeout if timeout is not None else _local_git_timeout()
    cmd = ["git", *args]
    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            check=check,
            capture_output=capture_output,
            text=text,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        duration_ms = (time.perf_counter() - start) * 1000.0
        _log_git_operation(
            op=op,
            cmd=cmd,
            cwd=cwd,
            status="timeout",
            duration_ms=duration_ms,
            timeout_seconds=timeout_seconds,
            returncode=None,
            stdout=exc.stdout,
            stderr=exc.stderr,
        )
        raise SddGitCommandTimeout(
            f"git operation {op!r} timed out after {timeout_seconds:.1f}s in {cwd}"
        ) from exc
    except subprocess.CalledProcessError as exc:
        duration_ms = (time.perf_counter() - start) * 1000.0
        _log_git_operation(
            op=op,
            cmd=cmd,
            cwd=cwd,
            status="error",
            duration_ms=duration_ms,
            timeout_seconds=timeout_seconds,
            returncode=exc.returncode,
            stdout=exc.stdout,
            stderr=exc.stderr,
        )
        raise

    duration_ms = (time.perf_counter() - start) * 1000.0
    if _should_log_git_operation(args, duration_ms, result.returncode):
        _log_git_operation(
            op=op,
            cmd=cmd,
            cwd=cwd,
            status="ok" if result.returncode == 0 else "nonzero",
            duration_ms=duration_ms,
            timeout_seconds=timeout_seconds,
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
    return result


def run_sdd_git(
    args: list[str],
    *,
    cwd: Path,
    op: str,
    timeout: float | None = None,
    check: bool,
    capture_output: bool,
    text: bool = False,
) -> subprocess.CompletedProcess[Any]:
    """Run a bounded git command with SDD telemetry."""

    return _run_git(
        args,
        cwd=cwd,
        op=op,
        timeout=timeout,
        check=check,
        capture_output=capture_output,
        text=text,
    )


def _should_log_git_operation(
    args: list[str],
    duration_ms: float,
    returncode: int,
) -> bool:
    if returncode != 0:
        return True
    if any(arg in {"push", "fetch"} for arg in args):
        return True
    return duration_ms >= _slow_git_ms()


def _log_git_operation(
    *,
    op: str,
    cmd: list[str],
    cwd: Path,
    status: str,
    duration_ms: float,
    timeout_seconds: float,
    returncode: int | None,
    stdout: str | bytes | None,
    stderr: str | bytes | None,
) -> None:
    try:
        from sase.logs import log_tui_git_operation

        log_tui_git_operation(
            {
                "ts": time.time(),
                "event": "sdd_git_operation",
                "operation": op,
                "status": status,
                "duration_ms": round(duration_ms, 3),
                "timeout_seconds": timeout_seconds,
                "returncode": returncode,
                "cwd": str(cwd),
                "cmd": cmd,
                "stdout_preview": _preview_stream(stdout),
                "stderr_preview": _preview_stream(stderr),
            }
        )
    except Exception:
        _logger.debug("failed to write SDD git operation telemetry", exc_info=True)


def _preview_stream(value: str | bytes | None, limit: int = 500) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = value
    text = text.strip()
    if not text:
        return None
    return text[:limit]


def _local_git_timeout() -> float:
    return _float_env(ENV_LOCAL_TIMEOUT, DEFAULT_LOCAL_GIT_TIMEOUT_SECONDS)


def _network_git_timeout() -> float:
    return _float_env(ENV_NETWORK_TIMEOUT, DEFAULT_NETWORK_GIT_TIMEOUT_SECONDS)


def network_git_timeout() -> float:
    """Return the configured timeout for SDD network git operations."""
    return _network_git_timeout()


def _slow_git_ms() -> float:
    return _float_env(ENV_SLOW_MS, DEFAULT_SLOW_GIT_MS)


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def commit_sdd_files(
    sdd_dir: Path,
    message: str,
    *,
    auto_commit_type: str = "sdd",
    paths: Iterable[str | Path] | None = None,
) -> bool:
    """Auto-commit SDD files in a local `.sase/sdd/` git repo.

    Returns true only when a new commit is created. No-ops if `sdd_dir` is not
    a git repo or there are no staged changes.
    """
    if not (sdd_dir / ".git").is_dir():
        return False

    pathspecs = normalize_sdd_commit_pathspecs(sdd_dir, paths)
    changed_files = changed_sdd_files(sdd_dir, pathspecs)
    if not changed_files:
        return False

    _run_git(
        ["add", "--"] + changed_files,
        cwd=sdd_dir,
        check=True,
        capture_output=True,
        op="sdd.add",
    )

    result = _run_git(
        ["diff", "--cached", "--quiet", "--"] + changed_files,
        cwd=sdd_dir,
        capture_output=True,
        check=False,
        op="sdd.diff_cached",
    )
    if result.returncode != 0:
        from sase.workflows.commit.runtime_tags import (
            apply_auto_commit_tags_with_runtime,
        )

        message = apply_auto_commit_tags_with_runtime(message, auto_commit_type)
        _run_git(
            ["commit", "-m", message, "--"] + changed_files,
            cwd=sdd_dir,
            check=True,
            capture_output=True,
            op="sdd.commit",
        )
        return True
    return False


def commit_sdd_store_files(
    store: "SddStore",
    message: str,
    *,
    auto_commit_type: str = "sdd",
    paths: Iterable[str | Path] | None = None,
    push_after_commit: bool | Literal["async"] | None = None,
) -> bool:
    """Commit SDD files and push separate-repo stores per config.

    Push failure never changes the commit result; the local commit is
    preserved and failures are logged.
    """

    committed = commit_sdd_files(
        store.repo_root,
        message,
        auto_commit_type=auto_commit_type,
        paths=paths,
    )
    if committed:
        _push_sdd_store_after_commit(store, push_after_commit=push_after_commit)
    return committed


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


def _push_sdd_store_after_commit(
    store: "SddStore",
    *,
    push_after_commit: bool | Literal["async"] | None,
) -> None:
    from sase.sdd.store import SDD_STORAGE_SEPARATE_REPO

    if store.storage != SDD_STORAGE_SEPARATE_REPO:
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
        result = _run_git(
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
        result = _run_git(
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

    _run_git(
        ["add", "--", *rel_paths],
        cwd=git_root,
        check=True,
        capture_output=True,
        text=True,
        op="bare_git_sdd_init.add",
    )

    diff = _run_git(
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
    _run_git(
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
            _run_git(
                ["push", "origin", "HEAD"],
                cwd=git_root,
                check=True,
                capture_output=True,
                text=True,
                timeout=_network_git_timeout(),
                op="bare_git_sdd_init.push",
            )
        except (subprocess.CalledProcessError, SddGitCommandTimeout) as exc:
            # Pushing the generated SDD init commit is a best-effort sync with
            # the bare remote. A rejection (e.g. the remote moved ahead, so the
            # push is non-fast-forward) or a network timeout must never abort
            # the caller: the local commit is preserved and can be pushed later.
            # This mirrors commit_sdd_store_files, where "push failure never
            # changes the commit result." Without this, an ordinary agent launch
            # (ws_get_workspace_directory -> ensure_bare_git_sdd_initialized with
            # push=True, raise_on_error=True) would fail whenever the bare-git
            # workspace is behind its remote.
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
    result = _run_git(
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
