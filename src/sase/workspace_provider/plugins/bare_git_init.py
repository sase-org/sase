"""Bare-git project initialization.

Creates new bare-repo-backed git projects, optionally from an existing bare
repository.
"""

import os
import shlex
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import unquote, urlparse

from sase.core.paths import sase_projects_dir, sase_subdir, validate_sase_project_name
from sase.git_lock_retry import run_with_git_lock_retry
from sase.workspace_provider.plugins.bare_git_ref import set_bare_repo_dir
from sase.workspace_provider.utils import set_workspace_dir


class _BareRepoState(Enum):
    MISSING = "missing"
    EMPTY = "empty"
    HAS_REFS = "has_refs"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class _BareRepoAssessment:
    state: _BareRepoState
    detail: str = ""


class _CloneState(Enum):
    MISSING_OR_EMPTY = "missing_or_empty"
    MATCHING_ORIGIN = "matching_origin"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class _CloneAssessment:
    state: _CloneState
    detail: str = ""


def init_bare_git_project(
    project_name: str,
    *,
    bare_dir: str | None = None,
    clone_dir: str | None = None,
    existing_bare: str | None = None,
) -> str:
    """Initialize a new bare-repo-backed git project.

    Args:
        project_name: Name of the project.
        bare_dir: Path for the bare repo. Defaults to
            ``~/.sase/repos/<name>.git``.
        clone_dir: Path for the working clone. Defaults to
            ``~/projects/git/<name>/``.
        existing_bare: Path to an existing bare repo to clone from
            instead of creating a new one.

    Returns:
        The path to the created ``.gp`` project file.

    Raises:
        RuntimeError: If git commands fail or existing_bare is not a bare repo.
    """
    validate_sase_project_name(project_name)

    target_bare = existing_bare or bare_dir
    if target_bare is None:
        target_bare = str(sase_subdir("repos") / f"{project_name}.git")
    if clone_dir is None:
        clone_dir = str(Path.home() / "projects" / "git" / project_name) + "/"

    bare_path = Path(target_bare).expanduser()
    clone_path = Path(clone_dir).expanduser()
    bare_state = _assess_bare_repo(bare_path)
    clone_state = _assess_clone_dir(clone_path, bare_path)

    if bare_state.state is _BareRepoState.CONFLICT:
        _raise_init_conflict(project_name, bare_state.detail)
    if clone_state.state is _CloneState.CONFLICT:
        _raise_init_conflict(project_name, clone_state.detail)

    if clone_state.state is _CloneState.MISSING_OR_EMPTY:
        if bare_state.state is _BareRepoState.HAS_REFS:
            _clone_existing_bare_and_init_sdd(bare_path, clone_path)
        elif existing_bare and bare_state.state is _BareRepoState.MISSING:
            _raise_init_conflict(
                project_name,
                f"existing bare repository path does not exist: {bare_path}. "
                "Create it first, or pass a path to a valid bare git repository.",
            )
        else:
            _fresh_init_empty_bare_project(bare_path, clone_path)
    elif bare_state.state in {_BareRepoState.MISSING, _BareRepoState.EMPTY}:
        _rebuild_bare_from_matching_clone(bare_path, clone_path)

    # Create project spec file (canonical .sase extension).
    from sase.ace.patch.project_spec_path import active_project_spec_filename

    projects_base = sase_projects_dir()
    project_file = str(
        projects_base / project_name / active_project_spec_filename(project_name)
    )

    set_bare_repo_dir(project_file, str(bare_path))
    set_workspace_dir(project_file, _workspace_dir_value(clone_path))

    return project_file


def _run_git(
    args: list[str],
    *,
    cwd: str | Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run git and raise errors that include the command and git stderr."""
    cmd = ["git", *args]
    cwd_value = str(cwd) if cwd is not None else None
    try:
        result, _ = run_with_git_lock_retry(
            lambda: subprocess.run(
                cmd,
                cwd=cwd_value,
                capture_output=True,
                text=True,
                check=False,
            ),
            cwd=cwd_value or Path.cwd(),
        )
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            _format_git_error(
                cmd,
                cwd=cwd_value,
                returncode=exc.returncode,
                stdout=exc.stdout,
                stderr=exc.stderr,
            )
        ) from exc
    except FileNotFoundError as exc:
        raise RuntimeError("git executable not found on PATH") from exc
    if check and result.returncode != 0:
        raise RuntimeError(
            _format_git_error(
                cmd,
                cwd=cwd_value,
                returncode=result.returncode,
                stdout=result.stdout,
                stderr=result.stderr,
            )
        )
    return result


def _format_git_error(
    cmd: list[str],
    *,
    cwd: str | None,
    returncode: int,
    stdout: str | None,
    stderr: str | None,
) -> str:
    detail = (stderr or "").strip() or (stdout or "").strip()
    if not detail:
        detail = f"git exited with status {returncode}"
    cwd_text = f" in {cwd}" if cwd else ""
    return f"git command failed{cwd_text}: {shlex.join(cmd)}\n{detail}"


def _assess_bare_repo(bare_path: Path) -> _BareRepoAssessment:
    if not bare_path.exists():
        return _BareRepoAssessment(_BareRepoState.MISSING)

    result = _run_git(
        ["--git-dir", str(bare_path), "rev-parse", "--is-bare-repository"],
        check=False,
    )
    if result.returncode != 0 or result.stdout.strip() != "true":
        return _BareRepoAssessment(
            _BareRepoState.CONFLICT,
            f"bare repository path exists but is not a valid bare git repository: "
            f"{bare_path}. Move it aside, or pass an explicit bare_dir/existing_bare "
            "path.",
        )

    refs = _run_git(
        ["--git-dir", str(bare_path), "show-ref", "--quiet"],
        check=False,
    )
    if refs.returncode == 0:
        return _BareRepoAssessment(_BareRepoState.HAS_REFS)
    if refs.returncode == 1:
        return _BareRepoAssessment(_BareRepoState.EMPTY)
    return _BareRepoAssessment(
        _BareRepoState.CONFLICT,
        f"could not inspect refs in bare repository {bare_path}: "
        f"{refs.stderr.strip() or refs.stdout.strip() or f'exit {refs.returncode}'}",
    )


def _assess_clone_dir(clone_path: Path, bare_path: Path) -> _CloneAssessment:
    if not clone_path.exists():
        return _CloneAssessment(_CloneState.MISSING_OR_EMPTY)
    if not clone_path.is_dir():
        return _CloneAssessment(
            _CloneState.CONFLICT,
            f"working clone path exists and is not a directory: {clone_path}. "
            "Move it aside or pass an explicit clone_dir.",
        )
    if not any(clone_path.iterdir()):
        return _CloneAssessment(_CloneState.MISSING_OR_EMPTY)

    root = _run_git(["rev-parse", "--show-toplevel"], cwd=clone_path, check=False)
    if root.returncode != 0:
        return _CloneAssessment(
            _CloneState.CONFLICT,
            f"working clone directory already exists and is not a git checkout: "
            f"{clone_path}. Move it aside or pass an explicit clone_dir.",
        )

    repo_root = Path(root.stdout.strip()).expanduser()
    if _resolve_path(repo_root) != _resolve_path(clone_path):
        return _CloneAssessment(
            _CloneState.CONFLICT,
            f"working clone directory {clone_path} is inside git repository "
            f"{repo_root}, but SASE expected the clone root itself. Pass an "
            "explicit clone_dir or move the directory aside.",
        )

    origin = _run_git(["remote", "get-url", "origin"], cwd=clone_path, check=False)
    origin_url = origin.stdout.strip() if origin.returncode == 0 else ""
    if not origin_url:
        return _CloneAssessment(
            _CloneState.CONFLICT,
            f"working clone at {clone_path} has no origin remote. Set origin to "
            f"{bare_path}, move the directory aside, or pass an explicit clone_dir.",
        )
    if not _remote_matches_path(origin_url, bare_path, clone_path):
        return _CloneAssessment(
            _CloneState.CONFLICT,
            f"working clone at {clone_path} has origin {origin_url!r}, expected "
            f"{bare_path}. Set origin to the expected bare repository, move the "
            "directory aside, or pass an explicit clone_dir.",
        )

    return _CloneAssessment(_CloneState.MATCHING_ORIGIN)


def _remote_matches_path(origin_url: str, bare_path: Path, clone_path: Path) -> bool:
    origin_path = _local_remote_path(origin_url, clone_path)
    if origin_path is None:
        return False
    return _resolve_path(origin_path) == _resolve_path(bare_path)


def _local_remote_path(origin_url: str, clone_path: Path) -> Path | None:
    if origin_url.startswith(("http://", "https://", "git@", "ssh://")):
        return None
    if origin_url.startswith("file://"):
        parsed = urlparse(origin_url)
        return Path(unquote(parsed.path)).expanduser()
    if ":" in origin_url and not origin_url.startswith(("/", "~")):
        return None

    path = Path(origin_url).expanduser()
    if path.is_absolute():
        return path
    return clone_path / path


def _fresh_init_empty_bare_project(bare_path: Path, clone_path: Path) -> None:
    bare_path.parent.mkdir(parents=True, exist_ok=True)
    clone_path.parent.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "--bare", str(bare_path)])
    _run_git(["clone", str(bare_path), str(clone_path)])

    _run_git(["config", "user.email", "sase@localhost"], cwd=clone_path)
    _run_git(["config", "user.name", "sase"], cwd=clone_path)

    from sase.sdd.files import ensure_sdd_initialized

    generated_paths = ensure_sdd_initialized(clone_path)
    _stage_generated_paths(clone_path, generated_paths)

    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    commit_message = apply_auto_commit_type_tag("Initial commit", "init")
    _run_git(["commit", "--allow-empty", "-m", commit_message], cwd=clone_path)
    _run_git(["push", "origin", "HEAD"], cwd=clone_path)


def _clone_existing_bare_and_init_sdd(bare_path: Path, clone_path: Path) -> None:
    clone_path.parent.mkdir(parents=True, exist_ok=True)
    _run_git(["clone", str(bare_path), str(clone_path)])

    from sase.sdd.files import ensure_bare_git_sdd_initialized

    ensure_bare_git_sdd_initialized(
        _workspace_dir_value(clone_path),
        commit=True,
        push=True,
        raise_on_error=True,
    )


def _rebuild_bare_from_matching_clone(bare_path: Path, clone_path: Path) -> None:
    current_branch = _current_branch(clone_path)
    if not _clone_has_local_branches(clone_path):
        raise RuntimeError(
            f"Cannot rebuild bare repository {bare_path} from {clone_path}: "
            "the clone has no local branches to push. Create a commit, move the "
            "directory aside, or pass an explicit clone_dir."
        )

    if not bare_path.exists():
        bare_path.parent.mkdir(parents=True, exist_ok=True)
        _run_git(["init", "--bare", str(bare_path)])

    _run_git(["push", "origin", "--all"], cwd=clone_path)
    _run_git(["push", "origin", "--tags"], cwd=clone_path)
    _run_git(
        [
            "--git-dir",
            str(bare_path),
            "symbolic-ref",
            "HEAD",
            f"refs/heads/{current_branch}",
        ]
    )


def _current_branch(clone_path: Path) -> str:
    result = _run_git(
        ["symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=clone_path,
        check=False,
    )
    branch = result.stdout.strip()
    if result.returncode == 0 and branch:
        return branch
    raise RuntimeError(
        f"Cannot rebuild bare repository from {clone_path}: the clone is detached. "
        "Check out a branch before initializing the SASE project."
    )


def _clone_has_local_branches(clone_path: Path) -> bool:
    result = _run_git(["show-ref", "--heads", "--quiet"], cwd=clone_path, check=False)
    return result.returncode == 0


def _resolve_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _workspace_dir_value(clone_path: Path) -> str:
    value = str(clone_path)
    if not value.endswith(os.sep):
        value += os.sep
    return value


def _raise_init_conflict(project_name: str, detail: str) -> None:
    raise RuntimeError(f"Cannot initialize bare-git project '{project_name}': {detail}")


def _stage_generated_paths(repo_root: Path, paths: Iterable[Path]) -> None:
    """Stage generated SDD init paths for the initial bare-git commit."""
    rel_paths = _relative_paths(repo_root, paths)
    if not rel_paths:
        return
    _run_git(["add", "--", *rel_paths], cwd=repo_root)


def _relative_paths(repo_root: Path, paths: Iterable[Path]) -> list[str]:
    root = repo_root.resolve()
    rel_paths: set[str] = set()
    for path in paths:
        try:
            rel_paths.add(Path(path).resolve().relative_to(root).as_posix())
        except ValueError:
            continue
    return sorted(rel_paths)
