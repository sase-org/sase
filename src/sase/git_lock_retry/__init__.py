"""Shared retry and stale-lock recovery executor for git commands.

Safety rules live in ``sase_core``. This package is the compatible callback
executor: it collects observations, waits, unlinks at most once, and returns
native result objects plus the existing attempt-count / lock-path /
lock-removed outcome attributes.

Public callables here are thin forwards so TUI first-paint can import this
package without loading the policy, retry, or stale-lock submodules.
Constants stay lazy (PEP 562) for the same reason.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, TypeVar

from sase._lazy_exports import lazy_dir, lazy_getattr

ResultT = TypeVar("ResultT")

_LAZY_EXPORTS = {
    "DEFAULT_GIT_LOCK_RECOVERY_WAIT_CAP_SECONDS": (
        "sase.git_lock_retry._policy",
        "DEFAULT_GIT_LOCK_RECOVERY_WAIT_CAP_SECONDS",
    ),
    "DEFAULT_GIT_LOCK_RETRY_DELAYS": (
        "sase.git_lock_retry._policy",
        "DEFAULT_GIT_LOCK_RETRY_DELAYS",
    ),
    "ENV_GIT_LOCK_RETRY_DELAYS": (
        "sase.git_lock_retry._policy",
        "ENV_GIT_LOCK_RETRY_DELAYS",
    ),
    "STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS": (
        "sase.git_lock_retry._policy",
        "STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS",
    ),
}


def git_lock_retry_delays() -> tuple[float, ...]:
    """Return the configured bounded backoff schedule for git lock failures."""
    from sase.git_lock_retry._policy import git_lock_retry_delays as impl

    return impl()


def git_index_lock_path(
    workspace_dir: str | Path,
    *,
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    """Resolve the index-lock path for *workspace_dir*'s git dir, if any."""
    from sase.git_lock_retry._policy import git_index_lock_path as impl

    return impl(workspace_dir, argv=argv, env=env)


def run_with_git_lock_retry(  # noqa: UP047
    attempt: Callable[[], ResultT],
    *,
    cwd: str | Path,
    result_adapter: Callable[[ResultT], tuple[int, str | bytes | None]] | None = None,
    delays: Iterable[float] | None = None,
    allow_lock_removal: bool = True,
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    unix_clock: Callable[[], float] | None = None,
    monotonic_clock: Callable[[], float] | None = None,
    sleeper: Callable[[float], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    on_recovery: Callable[[str], None] | None = None,
    remaining_timeout: Callable[[], float | None] | None = None,
    owner_probe: Callable[..., dict[str, Any]] | None = None,
    recovery_wait_cap: float | None = None,
    allow_age_wait: bool = True,
) -> tuple[ResultT, Any]:
    """Run *attempt* with bounded retry and safe stale-lock recovery.

    The native result object is returned unchanged. ``result_adapter`` converts
    that object to ``(returncode, error_output)`` for classification; objects
    with ``returncode``, ``stderr``, and ``stdout`` attributes use the default
    adapter automatically. ``allow_age_wait=False`` preserves a young owner-free
    lock instead of waiting for it to reach the stale-age threshold.
    """
    from sase.git_lock_retry._retry import run_with_git_lock_retry as impl

    extra: dict[str, Any] = {}
    if recovery_wait_cap is not None:
        extra["recovery_wait_cap"] = recovery_wait_cap
    return impl(
        attempt,
        cwd=cwd,
        result_adapter=result_adapter,
        delays=delays,
        allow_lock_removal=allow_lock_removal,
        argv=argv,
        env=env,
        unix_clock=unix_clock,
        monotonic_clock=monotonic_clock,
        sleeper=sleeper,
        cancel_check=cancel_check,
        on_recovery=on_recovery,
        remaining_timeout=remaining_timeout,
        owner_probe=owner_probe,
        allow_age_wait=allow_age_wait,
        **extra,
    )


def try_remove_stale_index_lock(
    workspace_dir: str | Path,
    *,
    min_age_seconds: float | None = None,
    unix_clock: Callable[[], float] | None = None,
    owner_probe: Callable[..., dict[str, Any]] | None = None,
) -> bool:
    """Remove an aged owner-free index lock using the shared recovery policy."""
    from sase.git_lock_retry._stale import try_remove_stale_index_lock as impl

    extra: dict[str, Any] = {}
    if min_age_seconds is not None:
        extra["min_age_seconds"] = min_age_seconds
    return impl(
        workspace_dir,
        unix_clock=unix_clock,
        owner_probe=owner_probe,
        **extra,
    )


def __getattr__(name: str) -> Any:
    return lazy_getattr(__name__, globals(), _LAZY_EXPORTS, name)


def __dir__() -> list[str]:
    return lazy_dir(globals(), _LAZY_EXPORTS)


# Symvision cannot see Python's package-level lazy hook lookup.
_PACKAGE_GETATTR = __getattr__
_PACKAGE_DIR = __dir__

__all__ = [
    "DEFAULT_GIT_LOCK_RETRY_DELAYS",
    "ENV_GIT_LOCK_RETRY_DELAYS",
    "STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS",
    "git_index_lock_path",
    "git_lock_retry_delays",
    "run_with_git_lock_retry",
    "try_remove_stale_index_lock",
]
