"""Host observation adapters for Git index-lock recovery.

Python collects filesystem and process facts. The Rust core classifies them.
Unavailable tools, permission errors on relevant Git processes, and incomplete
inspection yield ``unknown``, never an empty ``absent`` result.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
from typing import Any

from sase.core.git_lock_wire import (
    GIT_LOCK_FILE_DIRECTORY,
    GIT_LOCK_FILE_OTHER,
    GIT_LOCK_FILE_REGULAR,
    GIT_LOCK_FILE_SYMLINK,
    GIT_LOCK_PROBE_COMPLETE,
    GIT_LOCK_PROBE_INCOMPLETE,
    GIT_LOCK_WIRE_SCHEMA_VERSION,
)

_PROC_ROOT = Path("/proc")
_LSOF_TIMEOUT_SECONDS = 2.0
_PS_TIMEOUT_SECONDS = 2.0
_PLUMBING_TIMEOUT_SECONDS = 2.0


def snapshot_lock_path(lock_path: Path | None) -> dict[str, Any] | None:
    """Return an ``lstat`` snapshot of *lock_path*, refusing to follow a leaf symlink."""
    if lock_path is None:
        return None
    try:
        info = os.lstat(lock_path)
    except FileNotFoundError:
        return None
    except OSError:
        return None
    if stat.S_ISLNK(info.st_mode):
        file_type = GIT_LOCK_FILE_SYMLINK
    elif stat.S_ISREG(info.st_mode):
        file_type = GIT_LOCK_FILE_REGULAR
    elif stat.S_ISDIR(info.st_mode):
        file_type = GIT_LOCK_FILE_DIRECTORY
    else:
        file_type = GIT_LOCK_FILE_OTHER
    return {
        "path": str(canonicalize_lock_path(lock_path)),
        "file_type": file_type,
        "device": int(info.st_dev),
        "inode": int(info.st_ino),
        "size": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
    }


def canonicalize_lock_path(lock_path: Path) -> Path:
    """Canonicalize the parent of *lock_path* without resolving a symlink leaf."""
    parent = lock_path.parent.expanduser()
    try:
        parent = parent.resolve(strict=False)
    except OSError:
        parent = parent
    return parent / lock_path.name


def _canonicalize_dir_path(path: str | Path | None) -> str | None:
    """Canonicalize a directory path, returning ``None`` when *path* is empty."""
    if path is None:
        return None
    text = str(path).strip()
    if not text:
        return None
    try:
        return str(Path(text).expanduser().resolve(strict=False))
    except OSError:
        return str(Path(text))


def resolve_index_lock_context(
    cwd: str | Path,
    *,
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = _PLUMBING_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Resolve the index lock from Git plumbing in the effective command context."""
    effective_cwd = _effective_git_cwd(cwd, argv)
    command_env = dict(os.environ if env is None else env)
    git_dir_env = command_env.get("GIT_DIR")
    git_index_env = command_env.get("GIT_INDEX_FILE")
    git_work_tree_env = command_env.get("GIT_WORK_TREE")
    plumbing = _run_git_plumbing(
        ["rev-parse", "--git-path", "index"],
        cwd=effective_cwd,
        env=command_env,
        timeout=timeout,
    )
    git_dir = _run_git_plumbing(
        ["rev-parse", "--absolute-git-dir"],
        cwd=effective_cwd,
        env=command_env,
        timeout=timeout,
    )
    worktree = _run_git_plumbing(
        ["rev-parse", "--show-toplevel"],
        cwd=effective_cwd,
        env=command_env,
        timeout=timeout,
    )
    if plumbing is None:
        if git_dir_env or git_index_env:
            return {
                "supported": False,
                "contradictory": False,
                "resolved_index_lock_path": None,
                "resolved_git_dir": _canonicalize_dir_path(git_dir_env),
                "resolved_worktree": _canonicalize_dir_path(
                    git_work_tree_env or effective_cwd
                ),
            }
        fallback = _fallback_index_lock_path(effective_cwd)
        return {
            "supported": fallback is not None,
            "contradictory": False,
            "resolved_index_lock_path": (
                str(canonicalize_lock_path(fallback)) if fallback is not None else None
            ),
            "resolved_git_dir": _canonicalize_dir_path(effective_cwd / ".git"),
            "resolved_worktree": _canonicalize_dir_path(effective_cwd),
        }

    index_path = Path(plumbing)
    if not index_path.is_absolute():
        index_path = effective_cwd / index_path
    lock_path = canonicalize_lock_path(Path(f"{index_path}.lock"))
    contradictory = False
    if git_index_env:
        expected = canonicalize_lock_path(Path(f"{git_index_env}.lock"))
        if not expected.is_absolute():
            expected = canonicalize_lock_path(effective_cwd / expected)
        contradictory = expected != lock_path
    return {
        "supported": not contradictory,
        "contradictory": contradictory,
        "resolved_index_lock_path": str(lock_path),
        "resolved_git_dir": _canonicalize_dir_path(git_dir)
        or _canonicalize_dir_path(git_dir_env),
        "resolved_worktree": _canonicalize_dir_path(worktree)
        or _canonicalize_dir_path(git_work_tree_env)
        or _canonicalize_dir_path(effective_cwd),
    }


def probe_index_lock_owner(
    *,
    lock_path: Path | None,
    resolved_git_dir: str | None,
    resolved_worktree: str | None,
    timeout: float = _LSOF_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Collect process facts for the resolved lock and classify completeness."""
    if lock_path is None:
        return {
            "schema_version": GIT_LOCK_WIRE_SCHEMA_VERSION,
            "probe_status": GIT_LOCK_PROBE_COMPLETE,
            "probe_reason": "no lock path",
            "processes": [],
            "resolved_git_dir": resolved_git_dir,
            "resolved_index_lock_path": None,
            "resolved_worktree": resolved_worktree,
        }
    canonical = canonicalize_lock_path(lock_path)
    if _PROC_ROOT.is_dir():
        return _probe_linux(
            canonical,
            resolved_git_dir=resolved_git_dir,
            resolved_worktree=resolved_worktree,
        )
    if sys.platform == "darwin":
        return _probe_macos(
            canonical,
            resolved_git_dir=resolved_git_dir,
            resolved_worktree=resolved_worktree,
            timeout=timeout,
        )
    return {
        "schema_version": GIT_LOCK_WIRE_SCHEMA_VERSION,
        "probe_status": GIT_LOCK_PROBE_INCOMPLETE,
        "probe_reason": "no process-observation adapter for this platform",
        "processes": [],
        "resolved_git_dir": resolved_git_dir,
        "resolved_index_lock_path": str(canonical),
        "resolved_worktree": resolved_worktree,
    }


def _effective_git_cwd(cwd: str | Path, argv: Sequence[str] | None) -> Path:
    base = Path(cwd).expanduser()
    if argv is None:
        return base
    try:
        index = list(argv).index("-C")
        configured = Path(argv[index + 1])
    except (ValueError, IndexError):
        return base
    if configured.is_absolute():
        return configured
    return base / configured


def _run_git_plumbing(
    args: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    timeout: float,
) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=dict(env),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    text = result.stdout.strip()
    if result.returncode != 0 or not text:
        return None
    return text


def _fallback_index_lock_path(workspace: Path) -> Path | None:
    git_path = workspace / ".git"
    if git_path.is_dir():
        return git_path / "index.lock"
    if not git_path.exists():
        return None
    git_dir = _run_git_plumbing(
        ["rev-parse", "--git-dir"],
        cwd=workspace,
        env=os.environ,
        timeout=_PLUMBING_TIMEOUT_SECONDS,
    )
    if git_dir is None:
        return None
    git_dir_path = Path(git_dir)
    if not git_dir_path.is_absolute():
        git_dir_path = workspace / git_dir_path
    return git_dir_path / "index.lock"


def _probe_linux(
    lock_path: Path,
    *,
    resolved_git_dir: str | None,
    resolved_worktree: str | None,
) -> dict[str, Any]:
    try:
        lock_stat = os.lstat(lock_path)
    except OSError:
        lock_stat = None
    processes: list[dict[str, Any]] = []
    incomplete_reason: str | None = None
    try:
        pid_entries = list(_PROC_ROOT.iterdir())
    except OSError as error:
        return _incomplete(
            f"could not list /proc: {error}",
            lock_path,
            resolved_git_dir,
            resolved_worktree,
        )
    for entry in pid_entries:
        if not entry.name.isdigit():
            continue
        pid = int(entry.name)
        fact, relevant_error = _linux_process_fact(
            pid, lock_path=lock_path, lock_stat=lock_stat
        )
        if fact is not None:
            processes.append(fact)
        elif relevant_error is not None:
            incomplete_reason = relevant_error
    if incomplete_reason is not None:
        return {
            "schema_version": GIT_LOCK_WIRE_SCHEMA_VERSION,
            "probe_status": GIT_LOCK_PROBE_INCOMPLETE,
            "probe_reason": incomplete_reason,
            "processes": processes,
            "resolved_git_dir": resolved_git_dir,
            "resolved_index_lock_path": str(lock_path),
            "resolved_worktree": resolved_worktree,
        }
    return {
        "schema_version": GIT_LOCK_WIRE_SCHEMA_VERSION,
        "probe_status": GIT_LOCK_PROBE_COMPLETE,
        "probe_reason": "linux /proc scan",
        "processes": processes,
        "resolved_git_dir": resolved_git_dir,
        "resolved_index_lock_path": str(lock_path),
        "resolved_worktree": resolved_worktree,
    }


def _linux_process_fact(
    pid: int,
    *,
    lock_path: Path,
    lock_stat: os.stat_result | None,
) -> tuple[dict[str, Any] | None, str | None]:
    proc = _PROC_ROOT / str(pid)
    argv = _read_cmdline(proc / "cmdline")
    executable = _readlink(proc / "exe")
    cwd = _readlink(proc / "cwd")
    environ = _read_environ(proc / "environ")
    ppid = _read_ppid(proc / "status")
    holds, fd_error = _linux_holds_lock(proc, lock_path, lock_stat)
    looks_like_git = _looks_like_git(executable, argv)
    if fd_error is not None and looks_like_git:
        return None, fd_error
    if argv is None and looks_like_git:
        return None, f"could not read git argv for pid {pid}"
    if not looks_like_git and not holds:
        return None, None
    return (
        {
            "pid": pid,
            "ppid": ppid,
            "executable": _canonicalize_dir_path(executable) or executable,
            "argv": _canonicalize_git_path_argv(
                argv or [], _canonicalize_dir_path(cwd)
            ),
            "cwd": _canonicalize_dir_path(cwd),
            "git_dir_env": _canonicalize_dir_path(
                environ.get("GIT_DIR") if environ else None
            ),
            "git_index_file_env": _canonicalize_dir_path(
                environ.get("GIT_INDEX_FILE") if environ else None
            ),
            "git_work_tree_env": _canonicalize_dir_path(
                environ.get("GIT_WORK_TREE") if environ else None
            ),
            "holds_lock_descriptor": holds,
            "association_ambiguous": looks_like_git and argv is None and cwd is None,
        },
        None,
    )


def _linux_holds_lock(
    proc: Path,
    lock_path: Path,
    lock_stat: os.stat_result | None,
) -> tuple[bool, str | None]:
    fd_dir = proc / "fd"
    try:
        descriptors = list(fd_dir.iterdir())
    except PermissionError:
        return False, f"permission denied reading {fd_dir}"
    except OSError:
        return False, None
    lock_text = str(lock_path)
    for descriptor in descriptors:
        try:
            target = os.readlink(descriptor)
        except OSError:
            continue
        if target == lock_text:
            return True, None
        if lock_stat is None:
            continue
        try:
            info = os.stat(descriptor)
        except OSError:
            continue
        if info.st_dev == lock_stat.st_dev and info.st_ino == lock_stat.st_ino:
            return True, None
    return False, None


def _probe_macos(
    lock_path: Path,
    *,
    resolved_git_dir: str | None,
    resolved_worktree: str | None,
    timeout: float,
) -> dict[str, Any]:
    lsof = shutil.which("lsof")
    ps_bin = shutil.which("ps")
    if lsof is None or ps_bin is None:
        return _incomplete(
            "macOS owner probe requires lsof and ps",
            lock_path,
            resolved_git_dir,
            resolved_worktree,
        )
    holders, lsof_error = _macos_lock_holders(lsof, lock_path, timeout)
    if lsof_error is not None:
        return _incomplete(lsof_error, lock_path, resolved_git_dir, resolved_worktree)
    processes, ps_error = _macos_git_processes(ps_bin, timeout, holders)
    if ps_error is not None:
        return _incomplete(ps_error, lock_path, resolved_git_dir, resolved_worktree)
    cwds = _macos_cwds(lsof, [int(process["pid"]) for process in processes], timeout)
    for process in processes:
        cwd = cwds.get(int(process["pid"]))
        if cwd:
            canonical_cwd = _canonicalize_dir_path(cwd)
            process["cwd"] = canonical_cwd
            process["argv"] = _canonicalize_git_path_argv(
                list(process.get("argv") or []), canonical_cwd
            )
    return {
        "schema_version": GIT_LOCK_WIRE_SCHEMA_VERSION,
        "probe_status": GIT_LOCK_PROBE_COMPLETE,
        "probe_reason": "macos lsof/ps scan",
        "processes": processes,
        "resolved_git_dir": resolved_git_dir,
        "resolved_index_lock_path": str(lock_path),
        "resolved_worktree": resolved_worktree,
    }


def _macos_lock_holders(
    lsof: str, lock_path: Path, timeout: float
) -> tuple[set[int], str | None]:
    try:
        result = subprocess.run(
            [lsof, "-F", "p", "--", str(lock_path)],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return set(), "lsof timed out"
    except OSError as error:
        return set(), f"lsof failed: {error}"
    if result.returncode not in {0, 1}:
        return set(), f"lsof exited {result.returncode}"
    holders: set[int] = set()
    for line in result.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            holders.add(int(line[1:]))
    return holders, None


def _macos_cwds(lsof: str, pids: Sequence[int], timeout: float) -> dict[int, str]:
    if not pids:
        return {}
    try:
        result = subprocess.run(
            [
                lsof,
                "-a",
                "-d",
                "cwd",
                "-F",
                "pn",
                "-p",
                ",".join(str(pid) for pid in pids),
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    cwds: dict[int, str] = {}
    current: int | None = None
    for line in result.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            current = int(line[1:])
            continue
        if current is not None and line.startswith("n") and line[1:]:
            cwds[current] = line[1:]
    return cwds


def _macos_git_processes(
    ps_bin: str, timeout: float, holders: set[int]
) -> tuple[list[dict[str, Any]], str | None]:
    try:
        result = subprocess.run(
            [ps_bin, "-axo", "pid=,ppid=,command="],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return [], "ps timed out"
    except OSError as error:
        return [], f"ps failed: {error}"
    if result.returncode != 0:
        return [], f"ps exited {result.returncode}"
    processes: list[dict[str, Any]] = []
    seen: set[int] = set()
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split(None, 2)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        command = parts[2] if len(parts) > 2 else ""
        argv = command.split()
        looks_like_git = _looks_like_git(argv[0] if argv else None, argv)
        holds = pid in holders
        if not looks_like_git and not holds:
            continue
        seen.add(pid)
        processes.append(
            {
                "pid": pid,
                "ppid": ppid,
                "executable": argv[0] if argv else None,
                "argv": _canonicalize_git_path_argv(argv, None),
                "cwd": None,
                "git_dir_env": None,
                "git_index_file_env": None,
                "git_work_tree_env": None,
                "holds_lock_descriptor": holds,
                "association_ambiguous": False,
            }
        )
    for pid in holders - seen:
        processes.append(
            {
                "pid": pid,
                "ppid": None,
                "executable": None,
                "argv": [],
                "cwd": None,
                "git_dir_env": None,
                "git_index_file_env": None,
                "git_work_tree_env": None,
                "holds_lock_descriptor": True,
                "association_ambiguous": False,
            }
        )
    return processes, None


def _canonicalize_git_path_argv(argv: Sequence[str], cwd: str | None) -> list[str]:
    canonical: list[str] = []
    path_options = {"-C", "--git-dir", "--work-tree"}
    index = 0
    while index < len(argv):
        item = argv[index]
        if item in path_options and index + 1 < len(argv):
            canonical.append(item)
            canonical.append(_resolve_maybe_relative(argv[index + 1], cwd))
            index += 2
            continue
        matched = False
        for option in path_options:
            prefix = f"{option}="
            if item.startswith(prefix):
                canonical.append(
                    prefix + _resolve_maybe_relative(item[len(prefix) :], cwd)
                )
                matched = True
                break
        if not matched:
            canonical.append(item)
        index += 1
    return canonical


def _resolve_maybe_relative(path: str, cwd: str | None) -> str:
    candidate = Path(path)
    if not candidate.is_absolute() and cwd:
        candidate = Path(cwd) / candidate
    resolved = _canonicalize_dir_path(candidate)
    return resolved or path


def _looks_like_git(executable: str | None, argv: Sequence[str] | None) -> bool:
    names = []
    if executable:
        names.append(Path(executable).name)
    if argv:
        names.append(Path(argv[0]).name)
    return any(name in {"git", "git.exe"} for name in names)


def _read_cmdline(path: Path) -> list[str] | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    return [part.decode("utf-8", "replace") for part in data.split(b"\0") if part]


def _readlink(path: Path) -> str | None:
    try:
        return os.readlink(path)
    except OSError:
        return None


def _read_environ(path: Path) -> dict[str, str] | None:
    try:
        data = path.read_bytes()
    except OSError:
        return None
    values: dict[str, str] = {}
    for part in data.split(b"\0"):
        if not part or b"=" not in part:
            continue
        key, value = part.split(b"=", 1)
        values[key.decode("utf-8", "replace")] = value.decode("utf-8", "replace")
    return values


def _read_ppid(path: Path) -> int | None:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("PPid:"):
            try:
                return int(line.split(":", 1)[1].strip())
            except ValueError:
                return None
    return None


def _incomplete(
    reason: str,
    lock_path: Path,
    resolved_git_dir: str | None,
    resolved_worktree: str | None,
) -> dict[str, Any]:
    return {
        "schema_version": GIT_LOCK_WIRE_SCHEMA_VERSION,
        "probe_status": GIT_LOCK_PROBE_INCOMPLETE,
        "probe_reason": reason,
        "processes": [],
        "resolved_git_dir": resolved_git_dir,
        "resolved_index_lock_path": str(lock_path),
        "resolved_worktree": resolved_worktree,
    }


__all__ = [
    "canonicalize_lock_path",
    "probe_index_lock_owner",
    "resolve_index_lock_context",
    "snapshot_lock_path",
]
