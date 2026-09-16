"""Low-level Git helpers for workspace object sharing."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from sase.git_lock_retry import run_with_git_lock_retry
from sase.workspace_provider._git_objects_model import (
    _BORROWER_CONFIG_KEYS,
    _CONFIG_ENABLED,
    _CONFIG_PRIMARY_CHECKOUT,
    _CONFIG_PRIMARY_OBJECTS,
    _CONFIG_SOURCE,
    GitObjectSharingError,
)
from sase.workspace_provider._utils_git import (
    command_output,
    git_result_adapter,
    non_interactive_git_env,
)


def run_git(
    cwd: str,
    args: list[str],
    *,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    try:
        result, _outcome = run_with_git_lock_retry(
            lambda: subprocess.run(
                ["git", *args],
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
    except OSError as exc:
        raise GitObjectSharingError(
            f"could not run git {' '.join(args)} in {cwd}: {exc}"
        ) from exc
    if check and result.returncode != 0:
        detail = command_output(result) or "unknown error"
        raise GitObjectSharingError(f"git {' '.join(args)} failed in {cwd}: {detail}")
    return result


def _git_output(cwd: str, args: list[str]) -> str:
    result = run_git(cwd, args, check=True)
    return result.stdout.strip()


def _canonical_existing_or_future_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def git_object_dir(checkout_dir: str) -> Path:
    """Return the resolved Git object directory for *checkout_dir*."""

    raw = _git_output(checkout_dir, ["rev-parse", "--git-path", "objects"])
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path(checkout_dir) / path
    return _canonical_existing_or_future_path(path)


def alternates_file(checkout_dir: str) -> Path:
    return git_object_dir(checkout_dir) / "info" / "alternates"


def _config_get(checkout_dir: str, key: str) -> str:
    value = config_get_optional(checkout_dir, key)
    return value or ""


def config_get_optional(checkout_dir: str, key: str) -> str | None:
    result = run_git(checkout_dir, ["config", "--local", "--get", key])
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def config_bool(checkout_dir: str, key: str) -> bool:
    value = _config_get(checkout_dir, key).strip().lower()
    return value in {"1", "true", "yes", "on"}


def set_config(checkout_dir: str, key: str, value: str) -> None:
    run_git(checkout_dir, ["config", "--local", key, value], check=True)


def unset_config(checkout_dir: str, key: str) -> None:
    result = run_git(checkout_dir, ["config", "--local", "--unset-all", key])
    if result.returncode not in {0, 5}:
        detail = command_output(result) or "unknown error"
        raise GitObjectSharingError(
            f"could not unset {key} in {checkout_dir}: {detail}"
        )


def configure_primary_for_sharing(primary_checkout_dir: str) -> None:
    """Protect a primary checkout whose objects are borrowed by workspaces."""

    set_config(primary_checkout_dir, "gc.pruneExpire", "never")
    set_config(primary_checkout_dir, _CONFIG_SOURCE, "true")


def configure_borrower_for_sharing(
    checkout_dir: str,
    *,
    primary_checkout_dir: str,
    primary_object_dir: Path,
) -> None:
    """Mark a managed checkout as a SASE-owned Git object borrower."""

    set_config(checkout_dir, _CONFIG_ENABLED, "true")
    set_config(checkout_dir, _CONFIG_PRIMARY_OBJECTS, str(primary_object_dir))
    set_config(
        checkout_dir,
        _CONFIG_PRIMARY_CHECKOUT,
        str(Path(primary_checkout_dir).expanduser().resolve(strict=False)),
    )
    set_config(checkout_dir, "gc.auto", "0")
    set_config(checkout_dir, "maintenance.auto", "false")


def clear_borrower_config(checkout_dir: str) -> None:
    for key in _BORROWER_CONFIG_KEYS:
        unset_config(checkout_dir, key)


def _object_dir_bytes(object_dir: str | Path) -> int:
    """Measure local object storage without following symlinks."""

    root = Path(object_dir)
    if not root.exists():
        return 0

    total = 0
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        stat = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(Path(entry.path))
                    else:
                        total += stat.st_size
        except OSError:
            continue
    return total


def checkout_object_bytes(checkout_dir: str) -> int:
    return _object_dir_bytes(git_object_dir(checkout_dir.rstrip("/")))


def is_git_checkout(checkout_dir: str) -> bool:
    result = run_git(checkout_dir.rstrip("/"), ["rev-parse", "--is-inside-work-tree"])
    return result.returncode == 0 and result.stdout.strip() == "true"


def status_porcelain(checkout_dir: str) -> subprocess.CompletedProcess[str]:
    return run_git(checkout_dir.rstrip("/"), ["status", "--porcelain"])


def fsck_connectivity(checkout_dir: str) -> None:
    run_git(checkout_dir.rstrip("/"), ["fsck", "--connectivity-only"], check=True)
