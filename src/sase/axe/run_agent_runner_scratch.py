"""Best-effort cleanup for one runner's launch-assigned scratch."""

from __future__ import annotations

import os
import shutil
import stat
from collections.abc import Iterable
from pathlib import Path

from sase.core.dismissed_agent_completion import SHELL_HANDOFF_OUTCOMES
from sase.core.paths import managed_tmpdir_root
from sase.env_contracts import SASE_LAUNCH_SCRATCH_KEY_ENV

_CANDIDATE_BUCKETS: tuple[tuple[str, str], ...] = (
    ("cargo-targets", "CARGO_TARGET_DIR"),
    ("agent-tmp", "TMPDIR"),
)
_LIVE_PATH_ENV_VARS = frozenset(
    {
        "TMPDIR",
        "TMP",
        "TEMP",
        "CARGO_TARGET_DIR",
        "CARGO_BUILD_BUILD_DIR",
    }
)


def cleanup_launch_scratch(
    *,
    exec_outcome: str,
    proc_root: Path | None = None,
) -> None:
    """Remove this runner's managed scratch when no live process still owns it."""
    try:
        _cleanup_launch_scratch(exec_outcome=exec_outcome, proc_root=proc_root)
    except Exception:
        return


def _cleanup_launch_scratch(
    *,
    exec_outcome: str,
    proc_root: Path | None,
) -> None:
    if exec_outcome in SHELL_HANDOFF_OUTCOMES:
        return
    scratch_key = os.environ.get(SASE_LAUNCH_SCRATCH_KEY_ENV)
    if not scratch_key:
        return

    observed_proc_root = Path("/proc") if proc_root is None else proc_root
    if not _has_usable_proc_root(observed_proc_root):
        return
    if not hasattr(os, "getuid"):
        return

    candidates = tuple(_launch_scratch_candidates(scratch_key=scratch_key))
    if not candidates:
        return
    if _any_candidate_is_live(candidates, proc_root=observed_proc_root):
        return

    for candidate in candidates:
        try:
            shutil.rmtree(candidate)
        except Exception:
            continue


def _launch_scratch_candidates(*, scratch_key: str) -> Iterable[Path]:
    root = managed_tmpdir_root()
    for bucket, env_var in _CANDIDATE_BUCKETS:
        bucket_dir = root / bucket
        candidate = bucket_dir / scratch_key
        if candidate.parent != bucket_dir:
            continue
        expected = _normalized_absolute_path(candidate)
        if _normalized_absolute_path(os.environ.get(env_var, "")) != expected:
            continue
        try:
            mode = os.lstat(candidate).st_mode
        except OSError:
            continue
        if not stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
            continue
        yield candidate


def _has_usable_proc_root(proc_root: Path) -> bool:
    return proc_root.is_dir() and os.access(proc_root, os.R_OK | os.X_OK)


def _any_candidate_is_live(candidates: tuple[Path, ...], *, proc_root: Path) -> bool:
    current_pid = os.getpid()
    current_uid = os.getuid()
    for pid_dir in _iter_pid_dirs(proc_root):
        try:
            if int(pid_dir.name) == current_pid:
                continue
            if pid_dir.stat().st_uid != current_uid:
                continue
        except (OSError, ValueError):
            continue

        if _pid_environ_references_candidate(pid_dir, candidates):
            return True
        if _pid_cwd_references_candidate(pid_dir, candidates):
            return True
    return False


def _iter_pid_dirs(proc_root: Path) -> Iterable[Path]:
    try:
        yield from proc_root.iterdir()
    except (FileNotFoundError, NotADirectoryError, PermissionError, ProcessLookupError):
        return


def _pid_environ_references_candidate(
    pid_dir: Path,
    candidates: tuple[Path, ...],
) -> bool:
    try:
        environ = (pid_dir / "environ").read_bytes()
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return False
    for item in environ.split(b"\0"):
        key, separator, value = item.partition(b"=")
        if not separator:
            continue
        try:
            key_text = key.decode()
            value_text = value.decode()
        except UnicodeDecodeError:
            continue
        if key_text not in _LIVE_PATH_ENV_VARS:
            continue
        value_path = _normalized_absolute_path(value_text)
        if value_path is not None and any(
            _is_path_at_or_under(value_path, candidate) for candidate in candidates
        ):
            return True
    return False


def _pid_cwd_references_candidate(pid_dir: Path, candidates: tuple[Path, ...]) -> bool:
    try:
        cwd = (pid_dir / "cwd").resolve(strict=True)
    except (FileNotFoundError, PermissionError, ProcessLookupError, OSError):
        return False
    return any(_is_path_at_or_under(cwd, candidate) for candidate in candidates)


def _normalized_absolute_path(value: str | Path) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        return path.resolve(strict=False)
    except OSError:
        return path.absolute()


def _is_path_at_or_under(path: Path, parent: Path) -> bool:
    normalized_parent = _normalized_absolute_path(parent)
    if normalized_parent is None:
        return False
    return path == normalized_parent or normalized_parent in path.parents
