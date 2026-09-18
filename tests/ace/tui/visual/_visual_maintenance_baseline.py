"""Golden-tree inventory, dirty-path recording, and concurrent-edit checks."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import subprocess

from tests.ace.tui.visual._visual_capture_paths import (
    DEFAULT_ACE_ROOT,
    DEFAULT_PAGER_ROOT,
    hash_file_tree,
    sha256_bytes,
)
from tests.ace.tui.visual._visual_maintenance_types import (
    GoldenBaseline,
    GoldenFileState,
    MaintenanceError,
)


def default_ace_root(repo_root: Path) -> Path:
    return repo_root / DEFAULT_ACE_ROOT


def default_pager_root(repo_root: Path) -> Path:
    return repo_root / DEFAULT_PAGER_ROOT


def capture_golden_baseline(repo_root: Path) -> GoldenBaseline:
    """Record hashes of both PNG roots without mutating the tree."""
    ace_root = default_ace_root(repo_root)
    pager_root = default_pager_root(repo_root)
    files: dict[str, GoldenFileState] = {}
    files.update(_scan_root(ace_root, repo_root, "ace"))
    files.update(_scan_root(pager_root, repo_root, "pager"))
    return GoldenBaseline(
        ace_root=ace_root,
        pager_root=pager_root,
        ace_tree_hash=hash_file_tree(ace_root),
        pager_tree_hash=hash_file_tree(pager_root),
        files=files,
        dirty_paths=git_dirty_golden_paths(repo_root, (ace_root, pager_root)),
        git_index_fingerprint=git_index_fingerprint(repo_root, (ace_root, pager_root)),
    )


def _list_golden_pngs(root: Path) -> list[Path]:
    """Return regular, non-symlink PNG files under *root*."""
    if not root.exists():
        return []
    files = [
        path for path in root.rglob("*.png") if path.is_file() and not path.is_symlink()
    ]
    return sorted(files)


def git_dirty_golden_paths(repo_root: Path, roots: Sequence[Path]) -> tuple[str, ...]:
    """Return repo-relative dirty golden paths, or empty when git is unavailable."""
    rels = [_repo_relative(path, repo_root) for path in roots]
    proc = _git(repo_root, "status", "--porcelain=v1", "-uall", "--", *rels)
    if proc is None or proc.returncode != 0:
        return ()
    paths: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        payload = line[3:]
        if " -> " in payload:
            payload = payload.split(" -> ", 1)[1]
        paths.append(payload.strip())
    return tuple(sorted(set(paths)))


def git_index_fingerprint(repo_root: Path, roots: Sequence[Path]) -> str:
    """Return the staged index listing for *roots*, or empty when git is missing."""
    rels = [_repo_relative(path, repo_root) for path in roots]
    proc = _git(repo_root, "ls-files", "-s", "--", *rels)
    if proc is None or proc.returncode != 0:
        return ""
    return proc.stdout


def detect_concurrent_edits(
    baseline: GoldenBaseline, repo_root: Path
) -> tuple[str, ...]:
    """Return golden paths whose bytes changed after the run-start snapshot."""
    current = capture_golden_baseline(repo_root)
    conflicts: list[str] = []
    for path, state in sorted(baseline.files.items()):
        other = current.files.get(path)
        if other is None:
            conflicts.append(f"deleted:{path}")
            continue
        if other.sha256 != state.sha256:
            conflicts.append(f"modified:{path}")
    for path in sorted(set(current.files) - set(baseline.files)):
        conflicts.append(f"created:{path}")
    return tuple(conflicts)


def recheck_baseline_or_raise(baseline: GoldenBaseline, repo_root: Path) -> None:
    """Refuse apply when goldens changed under us."""
    conflicts = detect_concurrent_edits(baseline, repo_root)
    if not conflicts:
        return
    raise MaintenanceError(
        "golden files changed during the run; refusing to apply: "
        + ", ".join(conflicts)
    )


def _scan_root(
    root: Path, repo_root: Path, identity: str
) -> dict[str, GoldenFileState]:
    files: dict[str, GoldenFileState] = {}
    for path in _list_golden_pngs(root):
        relative = _repo_relative(path, repo_root)
        data = path.read_bytes()
        stat = path.stat()
        files[relative] = GoldenFileState(
            relative_path=relative,
            sha256=sha256_bytes(data),
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            root_identity=identity,
        )
    return files


def _repo_relative(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None
