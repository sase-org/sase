"""Git command and origin-URL helpers for workspace materialization.

Split out of :mod:`sase.workspace_provider.utils`. Import the public
names from that module rather than depending on this one directly.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from sase.git_lock_retry import run_with_git_lock_retry


def non_interactive_git_env(base: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return an environment that prevents git/SSH credential prompts."""
    env = dict(os.environ if base is None else base)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"
    env["SSH_ASKPASS"] = "/bin/false"
    env["SSH_ASKPASS_REQUIRE"] = "force"
    return env


def git_result_adapter(result: Any) -> tuple[int, str]:
    """Adapt subprocess-shaped test doubles as well as CompletedProcess."""
    output = "\n".join(
        value
        for value in (getattr(result, "stderr", None), getattr(result, "stdout", None))
        if isinstance(value, str) and value
    )
    return int(result.returncode), output


def run_git_remote_get_url(cwd: str) -> subprocess.CompletedProcess[str]:
    result, _outcome = run_with_git_lock_retry(
        lambda: subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
        ),
        cwd=cwd,
        result_adapter=git_result_adapter,
    )
    return result


def command_output(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout or "").strip()


def git_remote_get_origin_push_urls(
    cwd: str,
) -> subprocess.CompletedProcess[str]:
    result, _outcome = run_with_git_lock_retry(
        lambda: subprocess.run(
            ["git", "remote", "get-url", "--push", "--all", "origin"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
        ),
        cwd=cwd,
        result_adapter=git_result_adapter,
    )
    return result


def git_config_get_all_origin_push_urls(
    cwd: str,
) -> subprocess.CompletedProcess[str]:
    result, _outcome = run_with_git_lock_retry(
        lambda: subprocess.run(
            ["git", "config", "--get-all", "remote.origin.pushurl"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
        ),
        cwd=cwd,
        result_adapter=git_result_adapter,
    )
    return result


def origin_read_error(cwd: str, result: subprocess.CompletedProcess[str]) -> str:
    detail = command_output(result)
    suffix = f": {detail}" if detail else ""
    return (
        "Could not read primary workspace origin URL; "
        f"could not read origin URL for git checkout {cwd}{suffix}"
    )


def git_command_error(
    action: str,
    cwd: str,
    result: subprocess.CompletedProcess[str],
) -> str:
    detail = command_output(result) or "unknown error"
    return f"{action} in git checkout {cwd}: {detail}"


def read_required_origin_url(primary_workspace_dir: str) -> str:
    result = run_git_remote_get_url(primary_workspace_dir)
    real_url = result.stdout.strip() if result.returncode == 0 else ""
    if real_url:
        return real_url
    raise RuntimeError(origin_read_error(primary_workspace_dir, result))


def _local_remote_path(origin_url: str, cwd: str) -> Path | None:
    if origin_url.startswith(("http://", "https://", "git@", "ssh://")):
        return None
    if origin_url.startswith("file://"):
        parsed = urlparse(origin_url)
        path = unquote(parsed.path)
        return Path(path).expanduser() if path else None
    if ":" in origin_url and not origin_url.startswith(("/", "~", ".")):
        return None
    origin_path = Path(origin_url).expanduser()
    if not origin_path.is_absolute():
        origin_path = Path(cwd).expanduser() / origin_path
    return origin_path


def same_path(left: Path, right: Path) -> bool:
    try:
        return left.resolve(strict=False) == right.resolve(strict=False)
    except OSError:
        left_norm = os.path.normcase(os.path.normpath(os.fspath(left)))
        right_norm = os.path.normcase(os.path.normpath(os.fspath(right)))
        return left_norm == right_norm


def remote_points_at_path(origin_url: str, expected_path: str, *, cwd: str) -> bool:
    origin_path = _local_remote_path(origin_url, cwd)
    if origin_path is None:
        return False
    return same_path(origin_path, Path(expected_path).expanduser())


def remote_urls_match(actual: str, expected: str, *, cwd: str) -> bool:
    if actual == expected:
        return True
    actual_path = _local_remote_path(actual, cwd)
    expected_path = _local_remote_path(expected, cwd)
    if actual_path is not None and expected_path is not None:
        return same_path(actual_path, expected_path)
    return actual.rstrip("/") == expected.rstrip("/")


def set_origin_url(cwd: str, origin_url: str) -> subprocess.CompletedProcess[str]:
    result, _outcome = run_with_git_lock_retry(
        lambda: subprocess.run(
            ["git", "remote", "set-url", "origin", origin_url],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
        ),
        cwd=cwd,
        result_adapter=git_result_adapter,
    )
    return result


def set_origin_push_url(
    cwd: str,
    new_url: str,
    old_url: str,
) -> subprocess.CompletedProcess[str]:
    result, _outcome = run_with_git_lock_retry(
        lambda: subprocess.run(
            ["git", "remote", "set-url", "--push", "origin", new_url, old_url],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            env=non_interactive_git_env(),
            stdin=subprocess.DEVNULL,
        ),
        cwd=cwd,
        result_adapter=git_result_adapter,
    )
    return result


def output_lines(result: subprocess.CompletedProcess[str]) -> list[str]:
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def get_default_branch(workspace_dir: str) -> str:
    """Detect the default branch for the origin remote.

    Returns a string like ``"origin/main"`` or ``"origin/master"``.
    Falls back to ``"origin/main"`` on any failure.
    """
    # These symbolic-ref/show-ref probes are read-only and never write the index.
    try:
        result = subprocess.run(
            ["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=workspace_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            ref = result.stdout.strip()
            if ref:
                branch = ref.rsplit("/", 1)[-1]
                return f"origin/{branch}"
    except Exception:
        pass
    # Probe for common default branch names
    for candidate in ("master", "main"):
        try:
            probe = subprocess.run(
                [
                    "git",
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/remotes/origin/{candidate}",
                ],
                cwd=workspace_dir,
                capture_output=True,
                check=False,
            )
            if probe.returncode == 0:
                return f"origin/{candidate}"
        except Exception:
            pass
    return "origin/main"


#: Git-dir-relative paths that mark an in-progress git operation, with labels.
#: ``rebase-apply`` is shared by ``git am`` and the ``--apply`` rebase backend;
#: it is labeled ``am`` and its abort sequence covers both commands.
GIT_IN_PROGRESS_OPERATION_PATHS: tuple[tuple[str, str], ...] = (
    ("rebase-merge", "rebase"),
    ("rebase-apply", "am"),
    ("MERGE_HEAD", "merge"),
    ("CHERRY_PICK_HEAD", "cherry-pick"),
    ("REVERT_HEAD", "revert"),
    ("BISECT_LOG", "bisect"),
    ("BISECT_EXPECTED_REV", "bisect"),
    ("BISECT_START", "bisect"),
    ("sequencer", "sequencer"),
)

#: Abort/quit command sequences per marker path. Each entry lists argv lists
#: (without the leading ``git``) tried in order until one succeeds; failures
#: are tolerated because the marker cleanup and hard reset below finish the
#: job. ``git merge`` has no ``--quit`` variant, so a failed merge abort falls
#: through to marker removal.
_OPERATION_ABORT_SEQUENCE: tuple[tuple[str, tuple[list[str], ...]], ...] = (
    ("rebase-merge", (["rebase", "--abort"], ["rebase", "--quit"])),
    (
        "rebase-apply",
        (
            ["rebase", "--abort"],
            ["am", "--abort"],
            ["rebase", "--quit"],
            ["am", "--quit"],
        ),
    ),
    ("MERGE_HEAD", (["merge", "--abort"],)),
    (
        "CHERRY_PICK_HEAD",
        (["cherry-pick", "--abort"], ["cherry-pick", "--quit"]),
    ),
    ("REVERT_HEAD", (["revert", "--abort"], ["revert", "--quit"])),
    ("BISECT_LOG", (["bisect", "reset"],)),
    ("BISECT_EXPECTED_REV", (["bisect", "reset"],)),
    ("BISECT_START", (["bisect", "reset"],)),
    ("sequencer", (["cherry-pick", "--quit"], ["revert", "--quit"])),
)


def in_progress_git_operations(git_dir: Path) -> list[str]:
    """Return the labels of in-progress git operations marked in *git_dir*.

    Labels follow :data:`GIT_IN_PROGRESS_OPERATION_PATHS`, deduplicated with
    the table order preserved. Never raises: an unreadable git dir reports no
    operations.
    """
    try:
        present = [
            label
            for relative, label in GIT_IN_PROGRESS_OPERATION_PATHS
            if (git_dir / relative).exists()
        ]
    except OSError:
        return []
    return list(dict.fromkeys(present))


def abort_in_progress_git_operations(
    repo_root: Path,
    git_dir: Path,
    run: Callable[[list[str]], tuple[int, str]],
) -> str | None:
    """Abort every in-progress git operation in *repo_root*.

    Runs each present marker's abort sequence (falling back to the ``--quit``
    variant), removes leftover known marker paths, and finishes with
    ``git reset --hard HEAD``. Returns ``None`` when no operation was in
    progress or every marker is gone, else a short error summary. Never
    raises: a failing *run* callback counts as a failed command.
    """
    present = [
        relative
        for relative, _ in GIT_IN_PROGRESS_OPERATION_PATHS
        if _exists(git_dir / relative)
    ]
    if not present:
        return None
    for relative in dict.fromkeys(present):
        for argv in dict(_OPERATION_ABORT_SEQUENCE).get(relative, ()):
            code, _ = _safe_run(run, ["git", *argv])
            if code == 0:
                break
    for relative, _ in GIT_IN_PROGRESS_OPERATION_PATHS:
        target = git_dir / relative
        try:
            if target.is_dir() and not target.is_symlink():
                shutil.rmtree(target)
            elif target.exists() or os.path.lexists(target):
                target.unlink()
        except OSError:
            pass
    code, detail = _safe_run(run, ["git", "reset", "--hard", "HEAD"])
    if code != 0:
        return f"git reset --hard HEAD failed: {detail or 'unknown error'}"
    remaining = in_progress_git_operations(git_dir)
    if remaining:
        return "in-progress git operations remain after abort: " + ", ".join(remaining)
    return None


def _exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def _safe_run(
    run: Callable[[list[str]], tuple[int, str]], argv: list[str]
) -> tuple[int, str]:
    try:
        return run(argv)
    except Exception as exc:  # noqa: BLE001 - abort must never raise.
        return 1, str(exc)
