"""Git preparation helpers for operational workspace leases."""

from __future__ import annotations

import subprocess
from pathlib import Path

from sase.workspace_provider._lease_model import OperationalLeaseError
from sase.workspace_provider.utils import get_default_branch, non_interactive_git_env


def prepare_from_primary_remote(checkout: Path) -> None:
    if not (checkout / ".git").exists() and not (checkout / ".git").is_file():
        raise OperationalLeaseError(
            "preparation",
            f"{checkout} is not a git checkout",
        )
    remotes = _git_remotes(checkout)
    if "origin" in remotes:
        fetch = _run_git(["fetch", "--quiet", "origin"], checkout)
        if fetch.returncode != 0:
            detail = fetch.stderr.strip() or fetch.stdout.strip() or "git fetch failed"
            raise OperationalLeaseError("preparation", detail)
    upstream = _configured_upstream(checkout)
    if upstream is None:
        return
    local_branch = upstream.rsplit("/", 1)[-1]
    checkout_result = _run_git(
        ["checkout", "--force", "-B", local_branch, upstream],
        checkout,
    )
    if checkout_result.returncode != 0:
        detail = (
            checkout_result.stderr.strip()
            or checkout_result.stdout.strip()
            or f"git checkout {upstream} failed"
        )
        raise OperationalLeaseError("preparation", detail)


def _configured_upstream(checkout: Path) -> str | None:
    tracking = _run_git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        checkout,
    )
    if tracking.returncode == 0:
        ref = tracking.stdout.strip()
        if ref:
            return ref
    origin_head = _run_git(
        ["symbolic-ref", "--quiet", "refs/remotes/origin/HEAD"],
        checkout,
    )
    if origin_head.returncode == 0:
        ref = origin_head.stdout.strip()
        if ref.startswith("refs/remotes/"):
            return ref.removeprefix("refs/remotes/")
        if ref:
            return ref
    default_branch = get_default_branch(str(checkout))
    if _ref_exists(checkout, f"refs/remotes/{default_branch}"):
        return default_branch
    return None


def _git_remotes(checkout: Path) -> set[str]:
    result = _run_git(["remote"], checkout)
    if result.returncode != 0:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _ref_exists(checkout: Path, ref: str) -> bool:
    result = _run_git(["show-ref", "--verify", "--quiet", ref], checkout)
    return result.returncode == 0


def _run_git(args: list[str], checkout: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
        env=non_interactive_git_env(),
        stdin=subprocess.DEVNULL,
    )


__all__ = [
    "_configured_upstream",
    "_git_remotes",
    "prepare_from_primary_remote",
    "_ref_exists",
    "_run_git",
]
