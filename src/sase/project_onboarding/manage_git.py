"""Git plumbing for journaled SASE management setup."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
from pathlib import Path
import subprocess
from typing import Any

from sase.noninteractive_subprocess import run_noninteractive
from sase.workspace_provider.utils import non_interactive_git_env

CONFIG_RELATIVE = Path("sase") / "sase.yml"
GIT_TIMEOUT_SECONDS = 30.0
PUSH_TIMEOUT_SECONDS = 60.0


class ManagementError(RuntimeError):
    """The management effect could not safely reach its postcondition."""


def run_git(
    checkout: Path,
    *args: str,
    timeout: float = GIT_TIMEOUT_SECONDS,
) -> subprocess.CompletedProcess[str]:
    """Run git in *checkout* without prompting for credentials."""

    env = non_interactive_git_env()
    env["GH_PROMPT_DISABLED"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return run_noninteractive(
            ["git", *args],
            cwd=checkout,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise ManagementError(
            f"git {' '.join(args)} timed out after {timeout:g}s"
        ) from exc
    except OSError as exc:
        raise ManagementError(f"could not run git {' '.join(args)}: {exc}") from exc


def failure_message(action: str, result: subprocess.CompletedProcess[str]) -> str:
    """Return a one-line description of a failed git command."""

    detail = (result.stderr or result.stdout or "").strip()
    suffix = f": {detail}" if detail else ""
    return f"failed to {action} (exit {result.returncode}){suffix}"


def read_config(path: Path) -> bytes:
    """Return *path* bytes, treating a missing file as empty."""

    try:
        return path.read_bytes()
    except FileNotFoundError:
        return b""
    except OSError as exc:
        raise ManagementError(f"could not read {path}: {exc}") from exc


def sha256(content: bytes) -> str:
    """Return the hex SHA-256 digest of *content*."""

    return hashlib.sha256(content).hexdigest()


def normalize_branch(branch: str) -> str:
    """Return a usable branch name, or empty when the ref is invalid."""

    normalized = branch.strip()
    if normalized.startswith("refs/heads/"):
        normalized = normalized.removeprefix("refs/heads/")
    elif normalized.startswith("origin/"):
        normalized = normalized.removeprefix("origin/")
    if not normalized:
        return ""
    checked = run_git(Path.cwd(), "check-ref-format", f"refs/heads/{normalized}")
    return normalized if checked.returncode == 0 else ""


def remote_oid(checkout: Path, branch: str) -> str:
    """Return origin's unique OID for *branch*."""

    result = run_git(
        checkout,
        "ls-remote",
        "--heads",
        "origin",
        f"refs/heads/{branch}",
        timeout=PUSH_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise ManagementError(failure_message("verify origin default branch", result))
    rows = [line.split() for line in result.stdout.splitlines() if line.strip()]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != f"refs/heads/{branch}":
        raise ManagementError(f"origin has no unique refs/heads/{branch} branch")
    return rows[0][0]


def remote_heads(checkout: Path) -> dict[str, str]:
    """Return origin's heads as ``{ref: oid}``."""

    result = run_git(
        checkout,
        "ls-remote",
        "--heads",
        "origin",
        timeout=PUSH_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise ManagementError(failure_message("list origin heads", result))
    heads: dict[str, str] = {}
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        oid, ref = parts
        if ref.startswith("refs/heads/"):
            heads[ref] = oid
    return heads


def born_head(checkout: Path) -> str:
    """Return HEAD's commit, or empty when the branch is still unborn."""

    result = run_git(
        checkout,
        "rev-parse",
        "--verify",
        "-q",
        "HEAD",
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _current_branch(checkout: Path) -> str:
    """Return HEAD's short branch name, or empty when it is detached."""

    result = run_git(
        checkout,
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return ""
    return normalize_branch(result.stdout.strip())


def should_manage_empty_origin(
    checkout: Path, remote: Mapping[str, Any], state: Mapping[str, Any]
) -> bool:
    """Return whether origin is unborn or already holds this root marker."""

    recorded_branch = normalize_branch(str(state.get("commit_branch") or ""))
    recorded_commit = str(state.get("commit_id") or "")
    if state.get("root_commit") is True and recorded_branch and recorded_commit:
        heads = remote_heads(checkout)
        if heads.get(f"refs/heads/{recorded_branch}") == recorded_commit:
            return True
    provider_branch = normalize_branch(str(remote.get("default_branch") or ""))
    if remote.get("is_empty") is True or not provider_branch:
        return not remote_heads(checkout)
    return False


def choose_empty_origin_branch(
    checkout: Path, remote: Mapping[str, Any], state: Mapping[str, Any]
) -> str:
    """Choose the branch that will receive the empty-origin root commit."""

    recorded = normalize_branch(str(state.get("commit_branch") or ""))
    if recorded:
        return recorded
    provider = normalize_branch(str(remote.get("default_branch") or ""))
    if provider:
        return provider
    local = _current_branch(checkout)
    if local:
        return local
    raise ManagementError("could not determine a branch for the first commit")


def align_unborn_head(checkout: Path, branch: str) -> None:
    """Point unborn HEAD at *branch*, or require an already-matching born HEAD."""

    current = _current_branch(checkout)
    if current == branch:
        return
    if born_head(checkout):
        raise ManagementError(
            f"checkout is on {current or 'detached HEAD'}, expected default branch {branch}"
        )
    result = run_git(
        checkout,
        "symbolic-ref",
        "HEAD",
        f"refs/heads/{branch}",
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise ManagementError(failure_message("retarget unborn HEAD", result))


def ensure_upstream(checkout: Path, branch: str) -> None:
    """Set ``branch.<branch>.{remote,merge}`` when either value is missing."""

    remote = run_git(
        checkout,
        "config",
        "--get",
        f"branch.{branch}.remote",
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if remote.returncode != 0 or not remote.stdout.strip():
        result = run_git(
            checkout,
            "config",
            f"branch.{branch}.remote",
            "origin",
            timeout=GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise ManagementError(failure_message("set upstream remote", result))
    merge = run_git(
        checkout,
        "config",
        "--get",
        f"branch.{branch}.merge",
        timeout=GIT_TIMEOUT_SECONDS,
    )
    if merge.returncode != 0 or not merge.stdout.strip():
        result = run_git(
            checkout,
            "config",
            f"branch.{branch}.merge",
            f"refs/heads/{branch}",
            timeout=GIT_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            raise ManagementError(failure_message("set upstream merge", result))


__all__ = [
    "CONFIG_RELATIVE",
    "GIT_TIMEOUT_SECONDS",
    "ManagementError",
    "PUSH_TIMEOUT_SECONDS",
    "align_unborn_head",
    "born_head",
    "choose_empty_origin_branch",
    "ensure_upstream",
    "failure_message",
    "normalize_branch",
    "read_config",
    "remote_heads",
    "remote_oid",
    "run_git",
    "sha256",
    "should_manage_empty_origin",
]
