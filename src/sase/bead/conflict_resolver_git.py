"""Git plumbing primitives shared by the bead-store conflict resolver."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.git_lock_retry import run_with_git_lock_retry
from sase.sdd._git import sdd_git_command


class GitProbeFailure(RuntimeError):
    """A resolver probe could not answer, which is not the same as "clean"."""


def _run_git(cwd: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one resolver git command under the shared git-lock retry policy.

    The resolver's probes are not lock-free: ``git diff`` refreshes the index
    and therefore takes ``index.lock``, so a concurrent bead-store writer can
    fail a probe that has nothing to do with the conflict being resolved.
    """
    result, _outcome = run_with_git_lock_retry(
        lambda: subprocess.run(
            sdd_git_command(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        ),
        cwd=cwd,
    )
    return result


def _probe_failure(message: str, result: subprocess.CompletedProcess[str]) -> str:
    detail = (result.stderr or result.stdout or "").strip()
    return f"{message}: {detail}" if detail else f"{message} (exit {result.returncode})"


def git_repo_root(cwd: Path) -> Path | None:
    result = _run_git(cwd, ["rev-parse", "--show-toplevel"])
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip())


def conflicted_files(repo_root: Path) -> list[str]:
    result = _run_git(repo_root, ["diff", "--name-only", "--diff-filter=U"])
    if result.returncode != 0:
        raise GitProbeFailure(
            _probe_failure("could not list conflicted bead files", result)
        )
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def unmerged_stages(repo_root: Path, path: str) -> frozenset[int]:
    """Return which conflict stages *path* actually has in the index.

    Knowing this up front is what lets :func:`read_git_show` treat a
    ``git show`` failure as an error instead of silently substituting an empty
    stream, which would drop one side of the merge.
    """
    result = _run_git(repo_root, ["ls-files", "--unmerged", "-z", "--", path])
    if result.returncode != 0:
        raise GitProbeFailure(
            _probe_failure(f"could not read conflict stages for {path}", result)
        )
    stages: set[int] = set()
    for entry in result.stdout.split("\0"):
        head, _, _ = entry.partition("\t")
        fields = head.split()
        if len(fields) == 3 and fields[2].isdigit():
            stages.add(int(fields[2]))
    return frozenset(stages)


def upstream_and_local_stages(repo_root: Path) -> tuple[int, int]:
    git_dir = _git_dir(repo_root)
    if (git_dir / "rebase-merge").is_dir() or (git_dir / "rebase-apply").is_dir():
        return (2, 3)
    return (3, 2)


def _git_dir(repo_root: Path) -> Path:
    # A failure here must not fall back to the merge stage order: during a
    # rebase that silently swaps "ours" and "theirs" in the semantic merge.
    result = _run_git(repo_root, ["rev-parse", "--git-dir"])
    if result.returncode != 0:
        raise GitProbeFailure(_probe_failure("could not locate the git dir", result))
    path = Path(result.stdout.strip())
    if path.is_absolute():
        return path
    return repo_root / path


def read_git_show(repo_root: Path, stage: int, path: str) -> str:
    """Read one conflict stage of *path* via ``git show``, or raise on failure."""
    result = _run_git(repo_root, ["show", f":{stage}:{path}"])
    if result.returncode != 0:
        raise GitProbeFailure(
            _probe_failure(f"could not read stage {stage} of {path}", result)
        )
    return result.stdout


def git_add(repo_root: Path, paths: list[str]) -> None:
    if paths:
        result = _run_git(repo_root, ["add", "--", *paths])
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(detail or f"git add failed with {result.returncode}")


def git_rm(repo_root: Path, path: str) -> None:
    result = _run_git(repo_root, ["rm", "-r", "-f", "--", path])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(detail or f"git rm failed with {result.returncode}")
