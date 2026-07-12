"""SDD git commit helpers."""

import logging
import os
import subprocess
import time
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from sase.sdd._init_files import ensure_sdd_initialized
from sase.sdd._store_types import (
    SDD_STORAGE_COMPANION_REPOS,
    SDD_STORAGE_SEPARATE_REPO,
)

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
        if record_commit_marker:
            _record_sdd_commit_marker(
                sdd_dir,
                message=message,
                artifacts_dir=artifacts_dir,
                repo_name=repo_name,
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
    artifacts_dir: str | Path | None = None,
) -> bool:
    """Commit SDD files in their owning repository and push per config.

    Push failure never changes the commit result; the local commit is
    preserved and failures are logged.
    """

    committed_any = False
    for target_store, target_paths in _sdd_commit_targets(store, paths):
        committed = commit_sdd_files(
            target_store.repo_root,
            message,
            auto_commit_type=auto_commit_type,
            paths=target_paths,
            artifacts_dir=artifacts_dir,
            repo_name=_sdd_store_label(target_store),
            record_commit_marker=target_store.storage
            in {SDD_STORAGE_SEPARATE_REPO, SDD_STORAGE_COMPANION_REPOS},
        )
        if committed:
            _push_sdd_store_after_commit(
                target_store, push_after_commit=push_after_commit
            )
            committed_any = True
    return committed_any


def _sdd_commit_targets(
    store: "SddStore", paths: Iterable[str | Path] | None
) -> list[tuple["SddStore", list[str | Path] | None]]:
    """Partition split-store paths between the plans and research repos."""

    if not store.is_companion_storage or store.research_dir is None:
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
        )
    except Exception:
        _logger.debug("failed to record SDD commit marker", exc_info=True)


def _git_head_sha(repo_dir: Path) -> str | None:
    try:
        result = _run_git(
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


def _sdd_store_label(store: "SddStore") -> str | None:
    if store.storage not in {
        SDD_STORAGE_SEPARATE_REPO,
        SDD_STORAGE_COMPANION_REPOS,
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


def _push_sdd_store_after_commit(
    store: "SddStore",
    *,
    push_after_commit: bool | Literal["async"] | None,
) -> None:
    from sase.sdd.store import (
        SDD_STORAGE_COMPANION_REPOS,
        SDD_STORAGE_SEPARATE_REPO,
    )

    if store.storage not in {
        SDD_STORAGE_SEPARATE_REPO,
        SDD_STORAGE_COMPANION_REPOS,
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
