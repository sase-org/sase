"""Source-integrity checks for generated skill deployments."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.version._git import run_git
from sase.workspace_provider.utils import get_default_branch
from sase.xprompt.loader import get_sase_package_skills_dir

_LAND_FIRST_INSTRUCTION = (
    "Land the skill source change on the canonical branch first, then rerun. "
    "Use --allow-dirty only as a deliberate escape hatch; it can revert other "
    "agents' skill deployments."
)


def skill_source_integrity_error() -> str | None:
    """Return why the packaged skill sources are unsafe to deploy, if any."""
    skills_dir = get_sase_package_skills_dir().resolve()
    try:
        repo_root = Path(run_git(skills_dir, "rev-parse", "--show-toplevel")).resolve()
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        return _verification_error(
            f"could not resolve the git repository backing {skills_dir}", exc
        )

    try:
        skills_pathspec = skills_dir.relative_to(repo_root).as_posix()
    except ValueError:
        return _verification_error(
            f"resolved packaged skills directory {skills_dir} is outside git root "
            f"{repo_root}"
        )

    try:
        dirty = run_git(
            repo_root,
            "status",
            "--porcelain=v1",
            "--",
            skills_pathspec,
        )
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        return _verification_error("could not inspect skill source changes", exc)

    if dirty:
        details = "\n".join(f"  {line}" for line in dirty.splitlines())
        return (
            "refusing chezmoi skill deploy because packaged skill sources have "
            f"uncommitted changes:\n{details}\n{_LAND_FIRST_INSTRUCTION}"
        )

    canonical_ref = get_default_branch(str(repo_root))
    try:
        run_git(
            repo_root,
            "merge-base",
            "--is-ancestor",
            "HEAD",
            canonical_ref,
        )
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        commits = _unmerged_commits(repo_root, canonical_ref)
        details = (
            "\n".join(f"  {line}" for line in commits.splitlines())
            if commits
            else f"  (unable to list commits: {_git_error_detail(exc)})"
        )
        return (
            "refusing chezmoi skill deploy because HEAD is not an ancestor of "
            f"{canonical_ref}; these commits are not on the canonical branch:\n"
            f"{details}\n{_LAND_FIRST_INSTRUCTION}"
        )

    return None


def _unmerged_commits(repo_root: Path, canonical_ref: str) -> str:
    try:
        return run_git(
            repo_root,
            "log",
            "--format=%h %s",
            f"{canonical_ref}..HEAD",
        )
    except (
        FileNotFoundError,
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return ""


def _verification_error(message: str, exc: BaseException | None = None) -> str:
    detail = f": {_git_error_detail(exc)}" if exc is not None else ""
    return (
        f"refusing chezmoi skill deploy because source integrity {message}{detail}.\n"
        f"{_LAND_FIRST_INSTRUCTION}"
    )


def _git_error_detail(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        stderr = exc.stderr
        if isinstance(stderr, str) and stderr.strip():
            return stderr.strip()
    return str(exc)
