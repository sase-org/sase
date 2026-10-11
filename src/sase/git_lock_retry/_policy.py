"""Lazy git-lock policy loading, delay schedule, and shared observation helpers.

Numeric defaults match ``sase.core.git_lock_wire``. Keep them here so TUI
first-paint can import ``sase.git_lock_retry`` without pulling the git-lock
policy packages; recovery functions load those on first use.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any

# Numeric defaults match ``sase.core.git_lock_wire``.
DEFAULT_GIT_LOCK_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6, 3.2)
STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS = 15.0
DEFAULT_GIT_LOCK_RECOVERY_WAIT_CAP_SECONDS = 30.0
ENV_GIT_LOCK_RETRY_DELAYS = "SASE_GIT_LOCK_RETRY_DELAYS"

UnixClock = Callable[[], float]


@dataclass(frozen=True, slots=True)
class _GitLockPolicy:
    """Loaded git-lock policy callbacks and wire constants."""

    classify_git_lock_failure: Any
    classify_git_lock_owner: Any
    decide_eager_git_lock_cleanup: Any
    decide_git_lock_recovery: Any
    default_git_lock_retry_delays: Any
    git_lock_wire_schema_version: Any
    match_git_lock_path: Any
    parse_git_lock_retry_delays: Any
    validate_git_lock_retry_delays: Any
    canonicalize_lock_path: Any
    probe_index_lock_owner: Any
    resolve_index_lock_context: Any
    snapshot_lock_path: Any
    GIT_LOCK_ACTION_REMOVE_THEN_RETRY: str
    GIT_LOCK_ACTION_RETRY: str
    GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL: str
    GIT_LOCK_ACTION_WAIT: str
    GIT_LOCK_FAILURE_INDEX_LOCK: str
    GIT_LOCK_FAILURE_OTHER_LOCK: str
    GIT_LOCK_OWNER_UNKNOWN: str
    GIT_LOCK_WIRE_SCHEMA_VERSION: int


_policy: _GitLockPolicy | None = None


def git_lock_policy() -> _GitLockPolicy:
    """Import policy modules on first recovery call, not at TUI first-paint."""
    global _policy
    if _policy is not None:
        return _policy
    from sase.core.git_lock_facade import (
        classify_git_lock_failure as classify_failure,
        classify_git_lock_owner as classify_owner,
        decide_eager_git_lock_cleanup as decide_eager_cleanup,
        decide_git_lock_recovery as decide_recovery,
        default_git_lock_retry_delays as default_delays,
        git_lock_wire_schema_version as wire_schema_version,
        match_git_lock_path as match_lock_path,
        parse_git_lock_retry_delays as parse_delays,
        validate_git_lock_retry_delays as validate_delays,
    )
    from sase.core.git_lock_wire import (
        GIT_LOCK_ACTION_REMOVE_THEN_RETRY,
        GIT_LOCK_ACTION_RETRY,
        GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL,
        GIT_LOCK_ACTION_WAIT,
        GIT_LOCK_FAILURE_INDEX_LOCK,
        GIT_LOCK_FAILURE_OTHER_LOCK,
        GIT_LOCK_OWNER_UNKNOWN,
        GIT_LOCK_WIRE_SCHEMA_VERSION,
    )
    from sase.git_lock_observe import (
        canonicalize_lock_path,
        probe_index_lock_owner,
        resolve_index_lock_context,
        snapshot_lock_path,
    )

    _policy = _GitLockPolicy(
        classify_git_lock_failure=classify_failure,
        classify_git_lock_owner=classify_owner,
        decide_eager_git_lock_cleanup=decide_eager_cleanup,
        decide_git_lock_recovery=decide_recovery,
        default_git_lock_retry_delays=default_delays,
        git_lock_wire_schema_version=wire_schema_version,
        match_git_lock_path=match_lock_path,
        parse_git_lock_retry_delays=parse_delays,
        validate_git_lock_retry_delays=validate_delays,
        canonicalize_lock_path=canonicalize_lock_path,
        probe_index_lock_owner=probe_index_lock_owner,
        resolve_index_lock_context=resolve_index_lock_context,
        snapshot_lock_path=snapshot_lock_path,
        GIT_LOCK_ACTION_REMOVE_THEN_RETRY=GIT_LOCK_ACTION_REMOVE_THEN_RETRY,
        GIT_LOCK_ACTION_RETRY=GIT_LOCK_ACTION_RETRY,
        GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL=GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL,
        GIT_LOCK_ACTION_WAIT=GIT_LOCK_ACTION_WAIT,
        GIT_LOCK_FAILURE_INDEX_LOCK=GIT_LOCK_FAILURE_INDEX_LOCK,
        GIT_LOCK_FAILURE_OTHER_LOCK=GIT_LOCK_FAILURE_OTHER_LOCK,
        GIT_LOCK_OWNER_UNKNOWN=GIT_LOCK_OWNER_UNKNOWN,
        GIT_LOCK_WIRE_SCHEMA_VERSION=GIT_LOCK_WIRE_SCHEMA_VERSION,
    )
    return _policy


def git_lock_retry_delays() -> tuple[float, ...]:
    """Return the configured bounded backoff schedule for git lock failures."""
    policy = git_lock_policy()
    installed = policy.git_lock_wire_schema_version()
    if installed != policy.GIT_LOCK_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs git-lock wire is stale: expected "
            f"{policy.GIT_LOCK_WIRE_SCHEMA_VERSION}, got {installed}"
        )
    raw = os.environ.get(ENV_GIT_LOCK_RETRY_DELAYS)
    if raw is None:
        return policy.default_git_lock_retry_delays()
    return policy.parse_git_lock_retry_delays(raw)


def git_index_lock_path(
    workspace_dir: str | Path,
    *,
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    """Resolve the index-lock path for *workspace_dir*'s git dir, if any."""
    context = git_lock_policy().resolve_index_lock_context(
        workspace_dir, argv=argv, env=env
    )
    resolved = context.get("resolved_index_lock_path")
    if not isinstance(resolved, str) or not resolved:
        return None
    return Path(resolved)


def owner_observation(
    probe: Callable[..., dict[str, Any]],
    *,
    lock_path: Path | None,
    resolved_git_dir: str | None,
    resolved_worktree: str | None,
    remaining: float,
) -> dict[str, Any]:
    """Classify process facts for the lock at *lock_path*."""
    timeout = max(0.05, min(2.0, remaining if remaining > 0 else 0.05))
    facts = probe(
        lock_path=lock_path,
        resolved_git_dir=resolved_git_dir,
        resolved_worktree=resolved_worktree,
        timeout=timeout,
    )
    return git_lock_policy().classify_git_lock_owner(facts)


def unix_ns(clock: UnixClock) -> int:
    """Return *clock*'s unix time as an integer nanosecond stamp."""
    return int(clock() * 1_000_000_000)
