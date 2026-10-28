"""Git plumbing helpers for verified checkout snapshots."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from collections.abc import Sequence
from pathlib import Path

from sase.workspace_provider._rescue_git_commands import RESCUE_GIT_TIMEOUT_SECONDS
from sase.workspace_provider._snapshot_model import (
    IndexEntry,
    PreservationError,
)
from sase.workspace_provider._utils_git import non_interactive_git_env


def run_git_bytes(
    cwd: Path,
    *args: str,
    env: dict[str, str] | None = None,
    input_bytes: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Run git capturing raw bytes so paths and blobs stay binary-safe."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            check=False,
            env=env if env is not None else non_interactive_git_env(),
            input=input_bytes,
            timeout=RESCUE_GIT_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return subprocess.CompletedProcess(
            ["git", *args],
            returncode=124,
            stdout=b"",
            stderr=str(exc).encode(),
        )


def snapshot_env(
    *,
    index_file: Path | None = None,
    object_dir: Path | None = None,
    alternate_dirs: Sequence[Path] = (),
) -> dict[str, str]:
    env = non_interactive_git_env()
    if index_file is not None:
        env["GIT_INDEX_FILE"] = str(index_file)
    if object_dir is not None:
        env["GIT_OBJECT_DIRECTORY"] = str(object_dir)
    if alternate_dirs:
        env["GIT_ALTERNATE_OBJECT_DIRECTORIES"] = os.pathsep.join(
            str(path) for path in alternate_dirs
        )
    return env


def git_output(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    result = run_git_bytes(cwd, *args, env=env)
    if result.returncode != 0:
        detail = _err_text(result)
        raise PreservationError(f"git {' '.join(args)} failed: {detail}")
    return result.stdout.decode("utf-8", "surrogateescape").strip()


def _err_text(result: subprocess.CompletedProcess[bytes]) -> str:
    raw = result.stderr or result.stdout or b""
    return raw.decode("utf-8", "replace").strip() or f"exit {result.returncode}"


def require_git(result: subprocess.CompletedProcess[bytes], what: str) -> bytes:
    if result.returncode != 0:
        raise PreservationError(f"{what} failed: {_err_text(result)}")
    return result.stdout


def parse_ls_files_stage(data: bytes) -> tuple[IndexEntry, ...]:
    entries: list[IndexEntry] = []
    for item in data.split(b"\0"):
        if not item:
            continue
        try:
            meta, path_b = item.split(b"\t", 1)
            mode_b, sha_b, stage_b = meta.split(b" ")
            entries.append(
                IndexEntry(
                    mode=mode_b.decode("ascii"),
                    sha=sha_b.decode("ascii"),
                    stage=int(stage_b),
                    path=os.fsdecode(path_b),
                )
            )
        except (ValueError, UnicodeDecodeError) as exc:
            raise PreservationError(
                f"could not parse ls-files stage row: {item!r}"
            ) from exc
    return tuple(entries)


def status_paths(status_z: bytes) -> tuple[str, ...]:
    paths: list[str] = []
    items = [item for item in status_z.split(b"\0") if item]
    index = 0
    while index < len(items):
        item = items[index]
        if len(item) < 3:
            index += 1
            continue
        code = item[:2]
        path = os.fsdecode(item[3:]) if item[2:3] == b" " else os.fsdecode(item[2:])
        paths.append(path)
        if code in {b"R ", b"R", b"C ", b"C"} or code[:1] in {b"R", b"C"}:
            if index + 1 < len(items) and not (
                len(items[index + 1]) >= 3 and items[index + 1][2:3] == b" "
            ):
                paths.append(os.fsdecode(items[index + 1]))
                index += 1
        index += 1
    return tuple(paths)


def special_index_paths(
    repo_root: Path, *, env: dict[str, str] | None = None
) -> set[str]:
    """Return paths Git marks assume-unchanged or skip-worktree."""
    output = require_git(
        run_git_bytes(repo_root, "ls-files", "-v", "-z", env=env),
        "git ls-files -v",
    )
    paths: set[str] = set()
    for item in output.split(b"\0"):
        if len(item) < 3 or item[1:2] != b" ":
            continue
        tag = item[:1]
        if tag.islower() or tag == b"S":
            paths.add(os.fsdecode(item[2:]))
    return paths


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_repo_path(repo: Path, rel: str) -> Path:
    if rel.startswith("/") or rel.startswith("\\") or not rel:
        raise PreservationError(f"refusing unsafe path {rel!r}")
    parts = Path(rel).parts
    if any(part in {os.pardir, ""} for part in parts):
        raise PreservationError(f"refusing unsafe path {rel!r}")
    dest = (repo / rel).resolve(strict=False)
    repo_res = repo.resolve(strict=False)
    if dest != repo_res and repo_res not in dest.parents:
        raise PreservationError(f"path escapes repository: {rel}")
    return repo / rel


def file_mode_for_path(path: Path) -> str:
    if path.is_symlink():
        return "120000"
    st = path.lstat()
    if stat.S_ISDIR(st.st_mode):
        raise PreservationError(f"refusing to hash directory as a blob: {path}")
    if st.st_mode & stat.S_IXUSR:
        return "100755"
    return "100644"


def read_worktree_bytes(path: Path) -> bytes:
    if path.is_symlink():
        return os.fsencode(os.readlink(path))
    return path.read_bytes()


def nested_git_root(repo: Path, rel: str) -> Path | None:
    repo_res = repo.resolve(strict=False)
    path = safe_repo_path(repo, rel)
    current = path if path.is_dir() else path.parent
    while True:
        current_res = current.resolve(strict=False)
        if current_res == repo_res:
            return None
        if repo_res not in current_res.parents:
            return None
        if (current / ".git").exists() or os.path.lexists(current / ".git"):
            return current
        current = current.parent
