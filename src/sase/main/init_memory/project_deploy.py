"""Git deployment for project-level memory initialization."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
import subprocess
import sys

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from sase.main._init_chezmoi_deploy import skip_pull_push_without_upstream
from sase.memory.paths import CANONICAL_MEMORY_RELATIVE_ROOT, memory_write_root

from .commit_message import build_fold_commit_message
from .constants import COMMAND_LABEL, MEMORY_FOLD_DEFAULT_PREFIX, PROJECT_COMMIT_MESSAGE
from .git_state import (
    DirtyPath,
    PreInitGitState,
    classify,
    dirty_path_label,
    parse_status_z,
    partition_source_paths,
)
from .models import MemoryRootResult


def capture_pre_init_git_state(project_root: Path) -> PreInitGitState | None:
    """Capture dirty project paths before memory initialization writes occur."""
    try:
        repo_check = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return None

    if repo_check.returncode != 0 or not repo_check.stdout.strip():
        return None

    git_root = Path(repo_check.stdout.strip())
    try:
        status = subprocess.run(
            [
                "git",
                "-C",
                str(git_root),
                "status",
                "--porcelain=v1",
                "--untracked-files=all",
                "-z",
            ],
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None

    if status.returncode != 0:
        return None

    entries = parse_status_z(status.stdout)
    memory_dirty, other_dirty = classify(
        entries,
        (CANONICAL_MEMORY_RELATIVE_ROOT, Path("memory")),
    )
    return PreInitGitState(
        git_root=git_root,
        memory_dirty=memory_dirty,
        other_dirty=other_dirty,
    )


def _display_dirty_path(dirty_path: DirtyPath) -> str:
    return f"{dirty_path.path} ({dirty_path_label(dirty_path.status)})"


def _print_foreign_dirty_refusal(other_dirty: Iterable[DirtyPath]) -> None:
    """Explain why unrelated dirty paths prevent an automatic commit."""
    print(
        f"{COMMAND_LABEL}: refusing to commit - uncommitted changes unrelated "
        "to the generated memory work would be left behind:",
        file=sys.stderr,
    )
    for dirty_path in other_dirty:
        print(f"  - {_display_dirty_path(dirty_path)}", file=sys.stderr)
    print(
        "Commit or stash these unrelated changes and re-run `sase memory init`, or pass "
        "--no-commit to skip the git commit/push step. The regenerated memory "
        "files have been written but not committed.",
        file=sys.stderr,
    )


def _print_fold_prompt(fold_dirty: Iterable[DirtyPath]) -> None:
    """Prompt for a subject when pre-existing source edits are folded."""
    body = Text()
    body.append(
        "These source or memory edits will be committed together with the\n"
        "generated memory files and provider shims:\n\n"
    )
    for dirty_path in fold_dirty:
        body.append(f"  - {_display_dirty_path(dirty_path)}\n")
    Console(stderr=True).print(
        Panel(body, title="Uncommitted source changes", border_style="cyan")
    )
    default_tag = MEMORY_FOLD_DEFAULT_PREFIX.strip()
    print(
        f"A `{default_tag}` tag is added automatically if you omit one.",
        file=sys.stderr,
    )


def _resolve_fold_commit_message(
    fold_dirty: tuple[DirtyPath, ...],
    message: str | None,
    *,
    stdin_is_tty: Callable[[], bool],
    input_func: Callable[[str], str] | None = None,
) -> str | None:
    """Resolve and normalize the message used to fold existing source edits."""
    raw_subject = message
    if raw_subject is None:
        if not stdin_is_tty():
            print(
                f"{COMMAND_LABEL}: source or memory files have uncommitted changes "
                "to fold into the commit, but no commit message was provided and stdin is "
                'not a TTY. Re-run with --message "<subject>", or --no-commit '
                "to skip committing.",
                file=sys.stderr,
            )
            return None
        _print_fold_prompt(fold_dirty)
        try:
            if input_func is None:
                print("Commit message > ", end="", flush=True, file=sys.stderr)
                raw_subject = input()
            else:
                raw_subject = input_func("Commit message > ")
        except EOFError:
            print(
                f"{COMMAND_LABEL}: commit message entry reached EOF; aborting.",
                file=sys.stderr,
            )
            return None
        except KeyboardInterrupt:
            print("", file=sys.stderr)
            print(
                f"{COMMAND_LABEL}: commit message entry cancelled; aborting.",
                file=sys.stderr,
            )
            return None

    if raw_subject.strip() == "":
        print(f"{COMMAND_LABEL}: empty commit message; aborting.", file=sys.stderr)
        return None

    commit_message = build_fold_commit_message(raw_subject)
    subject = commit_message.splitlines()[0]
    print(f"{COMMAND_LABEL}: committing as: {subject}")
    return commit_message


def _unique_paths(paths: Iterable[Path]) -> tuple[Path, ...]:
    unique: list[Path] = []
    seen: set[Path] = set()
    for path in paths:
        key = path.resolve(strict=False)
        if key in seen:
            continue
        unique.append(path)
        seen.add(key)
    return tuple(unique)


def _repo_relative_source_paths(
    git_root: Path,
    source_paths: Iterable[Path],
) -> tuple[str, ...]:
    root = git_root.resolve(strict=False)
    relative: list[str] = []
    for source_path in source_paths:
        try:
            rel = source_path.resolve(strict=False).relative_to(root)
        except ValueError:
            continue
        relative.append(rel.as_posix())
    return tuple(relative)


def deploy_to_project_repo(
    project_result: MemoryRootResult,
    *,
    no_commit: bool,
    run_before_commit_hook: Callable[[str], bool],
    stdin_is_tty: Callable[[], bool],
    input_func: Callable[[str], str] | None = None,
    manage_memory: bool = True,
    git_state: PreInitGitState | None = None,
    message: str | None = None,
    owned_paths: Iterable[Path] = (),
) -> int:
    """Commit and push generated project memory files."""
    owned_paths = tuple(owned_paths)
    if no_commit:
        return 0

    if git_state is None:
        try:
            repo_check = subprocess.run(
                ["git", "-C", str(project_result.root), "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            print(f"{COMMAND_LABEL}: git not found on PATH", file=sys.stderr)
            return 1

        if repo_check.returncode != 0 or not repo_check.stdout.strip():
            detail = repo_check.stderr.strip()
            suffix = f": {detail}" if detail else ""
            print(
                f"{COMMAND_LABEL}: {project_result.root} is not a git repo{suffix}",
                file=sys.stderr,
            )
            return 1

        git_root = Path(repo_check.stdout.strip())
        memory_dirty: tuple[DirtyPath, ...] = ()
        other_dirty: tuple[DirtyPath, ...] = ()
    else:
        git_root = git_state.git_root
        memory_dirty = git_state.memory_dirty
        other_dirty = git_state.other_dirty

    source_dirty, other_dirty = partition_source_paths(
        other_dirty,
        _repo_relative_source_paths(
            git_root,
            (*project_result.fold_source_paths, *owned_paths),
        ),
    )
    fold_dirty = (*memory_dirty, *source_dirty)

    init_changed = bool(
        project_result.written_paths or project_result.deleted_paths or owned_paths
    )
    if other_dirty:
        if init_changed or fold_dirty:
            _print_foreign_dirty_refusal(other_dirty)
            return 1
        print(f"{COMMAND_LABEL}: nothing to commit in {git_root}")
        return 0

    if not init_changed and not fold_dirty:
        print(f"{COMMAND_LABEL}: nothing to commit in {git_root}")
        return 0

    fold_commit_message: str | None = None
    if fold_dirty:
        fold_commit_message = _resolve_fold_commit_message(
            fold_dirty,
            message,
            stdin_is_tty=stdin_is_tty,
            input_func=input_func,
        )
        if fold_commit_message is None:
            return 1

    if not run_before_commit_hook(str(git_root)):
        return 1

    stage_paths = _unique_paths(
        (
            *project_result.written_paths,
            *project_result.deleted_paths,
            *owned_paths,
            *(
                (memory_write_root(project_result.root) / "sase.md",)
                if manage_memory
                else ()
            ),
            *(git_root / dirty_path.path for dirty_path in fold_dirty),
        )
    )
    for path in stage_paths:
        add = subprocess.run(
            ["git", "-C", str(git_root), "add", "--", str(path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if add.returncode != 0:
            print(
                f"{COMMAND_LABEL}: git add failed for {path}: {add.stderr.strip()}",
                file=sys.stderr,
            )
            return 1

    staged = subprocess.run(
        ["git", "-C", str(git_root), "diff", "--cached", "--quiet"],
        capture_output=True,
        text=True,
        check=False,
    )
    if staged.returncode == 0:
        print(f"{COMMAND_LABEL}: nothing to commit in {git_root}")
        return 0
    if staged.returncode != 1:
        print(
            f"{COMMAND_LABEL}: staged diff check failed: {staged.stderr.strip()}",
            file=sys.stderr,
        )
        return 1

    print(f"Committing in {git_root}...")
    from sase.workflows.commit.runtime_tags import apply_auto_commit_type_tag

    commit_message = (
        apply_auto_commit_type_tag(PROJECT_COMMIT_MESSAGE, "memory")
        if fold_commit_message is None
        else fold_commit_message
    )
    commit = subprocess.run(
        ["git", "-C", str(git_root), "commit", "-m", commit_message],
        capture_output=True,
        text=True,
        check=False,
    )
    if commit.returncode != 0:
        print(
            f"{COMMAND_LABEL}: commit failed: {commit.stderr.strip()}", file=sys.stderr
        )
        return 1
    first_line = commit.stdout.strip().splitlines()[0] if commit.stdout.strip() else ""
    if first_line:
        print(f"  {first_line}")

    if skip_pull_push_without_upstream(git_root, COMMAND_LABEL):
        return 0

    print("Pulling...")
    pull = subprocess.run(
        ["git", "-C", str(git_root), "pull", "--rebase"],
        capture_output=True,
        text=True,
        check=False,
    )
    if pull.returncode != 0:
        print(f"{COMMAND_LABEL}: pull failed: {pull.stderr.strip()}", file=sys.stderr)
        return 1
    if pull.stdout.strip():
        print(f"  {pull.stdout.strip().splitlines()[0]}")

    print("Pushing...")
    push = subprocess.run(
        ["git", "-C", str(git_root), "push"],
        capture_output=True,
        text=True,
        check=False,
    )
    if push.returncode != 0:
        print(f"{COMMAND_LABEL}: push failed: {push.stderr.strip()}", file=sys.stderr)
        return 1
    tail = push.stderr.strip() or push.stdout.strip()
    if tail:
        print(f"  {tail.splitlines()[-1]}")

    return 0
