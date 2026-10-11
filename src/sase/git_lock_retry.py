"""Shared retry and stale-lock recovery executor for git commands.

Safety rules live in ``sase_core``. This module is the compatible callback
executor: it collects observations, waits, unlinks at most once, and returns
native result objects plus the existing attempt-count / lock-path /
lock-removed outcome attributes.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import logging
import os
from pathlib import Path
import time
from typing import Any, TypeVar

# Numeric defaults match ``sase.core.git_lock_wire``. Keep them here so TUI
# first-paint can import this module without pulling the git-lock policy
# packages; recovery functions load those on first use.
DEFAULT_GIT_LOCK_RETRY_DELAYS = (0.1, 0.2, 0.4, 0.8, 1.6, 3.2)
STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS = 15.0
DEFAULT_GIT_LOCK_RECOVERY_WAIT_CAP_SECONDS = 30.0
ENV_GIT_LOCK_RETRY_DELAYS = "SASE_GIT_LOCK_RETRY_DELAYS"

classify_git_lock_failure: Any
classify_git_lock_owner: Any
decide_eager_git_lock_cleanup: Any
decide_git_lock_recovery: Any
default_git_lock_retry_delays: Any
git_lock_wire_schema_version: Any
match_git_lock_path: Any
parse_git_lock_retry_delays: Any
validate_git_lock_retry_delays: Any
GIT_LOCK_ACTION_REMOVE_THEN_RETRY: str
GIT_LOCK_ACTION_RETRY: str
GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL: str
GIT_LOCK_ACTION_WAIT: str
GIT_LOCK_FAILURE_INDEX_LOCK: str
GIT_LOCK_FAILURE_OTHER_LOCK: str
GIT_LOCK_OWNER_UNKNOWN: str
GIT_LOCK_WIRE_SCHEMA_VERSION: int
canonicalize_lock_path: Any
probe_index_lock_owner: Any
resolve_index_lock_context: Any
snapshot_lock_path: Any
_GIT_LOCK_POLICY_LOADED = False


def _ensure_git_lock_policy() -> None:
    """Import policy modules on first recovery call, not at TUI first-paint."""
    global GIT_LOCK_ACTION_REMOVE_THEN_RETRY
    global GIT_LOCK_ACTION_RETRY
    global GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL
    global GIT_LOCK_ACTION_WAIT
    global GIT_LOCK_FAILURE_INDEX_LOCK
    global GIT_LOCK_FAILURE_OTHER_LOCK
    global GIT_LOCK_OWNER_UNKNOWN
    global GIT_LOCK_WIRE_SCHEMA_VERSION
    global _GIT_LOCK_POLICY_LOADED
    global canonicalize_lock_path
    global classify_git_lock_failure
    global classify_git_lock_owner
    global decide_eager_git_lock_cleanup
    global decide_git_lock_recovery
    global default_git_lock_retry_delays
    global git_lock_wire_schema_version
    global match_git_lock_path
    global parse_git_lock_retry_delays
    global probe_index_lock_owner
    global resolve_index_lock_context
    global snapshot_lock_path
    global validate_git_lock_retry_delays
    if _GIT_LOCK_POLICY_LOADED:
        return
    from sase.core.git_lock_facade import (
        classify_git_lock_failure as _classify_git_lock_failure,
        classify_git_lock_owner as _classify_git_lock_owner,
        decide_eager_git_lock_cleanup as _decide_eager_git_lock_cleanup,
        decide_git_lock_recovery as _decide_git_lock_recovery,
        default_git_lock_retry_delays as _default_git_lock_retry_delays,
        git_lock_wire_schema_version as _git_lock_wire_schema_version,
        match_git_lock_path as _match_git_lock_path,
        parse_git_lock_retry_delays as _parse_git_lock_retry_delays,
        validate_git_lock_retry_delays as _validate_git_lock_retry_delays,
    )
    from sase.core.git_lock_wire import (
        GIT_LOCK_ACTION_REMOVE_THEN_RETRY as _GIT_LOCK_ACTION_REMOVE_THEN_RETRY,
        GIT_LOCK_ACTION_RETRY as _GIT_LOCK_ACTION_RETRY,
        GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL as _GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL,
        GIT_LOCK_ACTION_WAIT as _GIT_LOCK_ACTION_WAIT,
        GIT_LOCK_FAILURE_INDEX_LOCK as _GIT_LOCK_FAILURE_INDEX_LOCK,
        GIT_LOCK_FAILURE_OTHER_LOCK as _GIT_LOCK_FAILURE_OTHER_LOCK,
        GIT_LOCK_OWNER_UNKNOWN as _GIT_LOCK_OWNER_UNKNOWN,
        GIT_LOCK_WIRE_SCHEMA_VERSION as _GIT_LOCK_WIRE_SCHEMA_VERSION,
    )
    from sase.git_lock_observe import (
        canonicalize_lock_path as _canonicalize_lock_path,
        probe_index_lock_owner as _probe_index_lock_owner,
        resolve_index_lock_context as _resolve_index_lock_context,
        snapshot_lock_path as _snapshot_lock_path,
    )

    classify_git_lock_failure = _classify_git_lock_failure
    classify_git_lock_owner = _classify_git_lock_owner
    decide_eager_git_lock_cleanup = _decide_eager_git_lock_cleanup
    decide_git_lock_recovery = _decide_git_lock_recovery
    default_git_lock_retry_delays = _default_git_lock_retry_delays
    git_lock_wire_schema_version = _git_lock_wire_schema_version
    match_git_lock_path = _match_git_lock_path
    parse_git_lock_retry_delays = _parse_git_lock_retry_delays
    validate_git_lock_retry_delays = _validate_git_lock_retry_delays
    GIT_LOCK_ACTION_REMOVE_THEN_RETRY = _GIT_LOCK_ACTION_REMOVE_THEN_RETRY
    GIT_LOCK_ACTION_RETRY = _GIT_LOCK_ACTION_RETRY
    GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL = _GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL
    GIT_LOCK_ACTION_WAIT = _GIT_LOCK_ACTION_WAIT
    GIT_LOCK_FAILURE_INDEX_LOCK = _GIT_LOCK_FAILURE_INDEX_LOCK
    GIT_LOCK_FAILURE_OTHER_LOCK = _GIT_LOCK_FAILURE_OTHER_LOCK
    GIT_LOCK_OWNER_UNKNOWN = _GIT_LOCK_OWNER_UNKNOWN
    GIT_LOCK_WIRE_SCHEMA_VERSION = _GIT_LOCK_WIRE_SCHEMA_VERSION
    canonicalize_lock_path = _canonicalize_lock_path
    probe_index_lock_owner = _probe_index_lock_owner
    resolve_index_lock_context = _resolve_index_lock_context
    snapshot_lock_path = _snapshot_lock_path
    _GIT_LOCK_POLICY_LOADED = True


_logger = logging.getLogger(__name__)

ResultT = TypeVar("ResultT")
UnixClock = Callable[[], float]
MonotonicClock = Callable[[], float]
Sleeper = Callable[[float], None]
CancelCheck = Callable[[], bool]
RecoveryHook = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class _GitLockRetryOutcome:
    """Details about the attempts made by :func:`run_with_git_lock_retry`."""

    attempts: int
    lock_removed: bool = False
    lock_path: Path | None = None

    @property
    def attempts_made(self) -> int:
        """Return the attempt count using the plan's descriptive name."""
        return self.attempts


def git_lock_retry_delays() -> tuple[float, ...]:
    """Return the configured bounded backoff schedule for git lock failures."""
    _ensure_git_lock_policy()
    installed = git_lock_wire_schema_version()
    if installed != GIT_LOCK_WIRE_SCHEMA_VERSION:
        raise RuntimeError(
            "sase_core_rs git-lock wire is stale: expected "
            f"{GIT_LOCK_WIRE_SCHEMA_VERSION}, got {installed}"
        )
    raw = os.environ.get(ENV_GIT_LOCK_RETRY_DELAYS)
    if raw is None:
        return default_git_lock_retry_delays()
    return parse_git_lock_retry_delays(raw)


def git_index_lock_path(
    workspace_dir: str | Path,
    *,
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
) -> Path | None:
    """Resolve the index-lock path for *workspace_dir*'s git dir, if any."""
    _ensure_git_lock_policy()
    context = resolve_index_lock_context(workspace_dir, argv=argv, env=env)
    resolved = context.get("resolved_index_lock_path")
    if not isinstance(resolved, str) or not resolved:
        return None
    return Path(resolved)


def run_with_git_lock_retry(  # noqa: UP047
    attempt: Callable[[], ResultT],
    *,
    cwd: str | Path,
    result_adapter: Callable[[ResultT], tuple[int, str | bytes | None]] | None = None,
    delays: Iterable[float] | None = None,
    allow_lock_removal: bool = True,
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    unix_clock: UnixClock | None = None,
    monotonic_clock: MonotonicClock | None = None,
    sleeper: Sleeper | None = None,
    cancel_check: CancelCheck | None = None,
    on_recovery: RecoveryHook | None = None,
    remaining_timeout: Callable[[], float | None] | None = None,
    owner_probe: Callable[..., dict[str, Any]] | None = None,
    recovery_wait_cap: float = DEFAULT_GIT_LOCK_RECOVERY_WAIT_CAP_SECONDS,
    allow_age_wait: bool = True,
) -> tuple[ResultT, _GitLockRetryOutcome]:
    """Run *attempt* with bounded retry and safe stale-lock recovery.

    The native result object is returned unchanged. ``result_adapter`` converts
    that object to ``(returncode, error_output)`` for classification; objects
    with ``returncode``, ``stderr``, and ``stdout`` attributes use the default
    adapter automatically. ``allow_age_wait=False`` preserves a young owner-free
    lock instead of waiting for it to reach the stale-age threshold.
    """
    _ensure_git_lock_policy()
    retry_delays = (
        git_lock_retry_delays() if delays is None else _validated_retry_delays(delays)
    )
    adapter = result_adapter or _default_result_adapter
    repo_path = Path(cwd).expanduser()
    now = unix_clock or time.time
    monotonic = monotonic_clock or time.monotonic
    sleep = sleeper or time.sleep
    started = monotonic()
    budget = recovery_wait_cap
    probe = owner_probe or probe_index_lock_owner
    last_result: ResultT | None = None
    first_snapshot: dict[str, Any] | None = None
    identity_disqualified = False
    removal_attempted = False
    age_wait_used = False
    lock_removed = False
    latest_lock_path: Path | None = None
    attempts = 0

    def remaining_budget() -> float:
        elapsed = max(0.0, monotonic() - started)
        leftover = budget - elapsed
        deadline = remaining_timeout() if remaining_timeout is not None else None
        if deadline is None:
            return leftover
        return min(leftover, max(0.0, deadline))

    def cancelled() -> bool:
        return bool(cancel_check and cancel_check())

    def emit(message: str) -> None:
        _logger.warning("%s", message)
        if on_recovery is not None:
            on_recovery(message)

    def deadline_ns() -> int | None:
        if remaining_timeout is None:
            return None
        remaining = remaining_timeout()
        if remaining is None:
            return None
        return max(0, int(remaining * 1_000_000_000))

    while True:
        if cancelled():
            if last_result is None:
                raise RuntimeError(
                    "git lock recovery cancelled before the first attempt"
                )
            return last_result, _GitLockRetryOutcome(
                attempts=attempts,
                lock_removed=lock_removed,
                lock_path=latest_lock_path,
            )
        if last_result is None:
            last_result = attempt()
            attempts += 1
        returncode, output = adapter(last_result)
        classification = classify_git_lock_failure(
            {
                "exit_status": returncode,
                "stdout": _adapter_stdout(last_result),
                "stderr": _stream_text(output),
                "timed_out": False,
                "signal_terminated": returncode < 0,
            }
        )
        if classification.get("kind") not in {
            GIT_LOCK_FAILURE_INDEX_LOCK,
            GIT_LOCK_FAILURE_OTHER_LOCK,
        }:
            return last_result, _GitLockRetryOutcome(
                attempts=attempts,
                lock_removed=lock_removed,
                lock_path=latest_lock_path,
            )
        context = resolve_index_lock_context(repo_path, argv=argv, env=env)
        resolved_lock = context.get("resolved_index_lock_path")
        classification = classify_git_lock_failure(
            {
                "exit_status": returncode,
                "stdout": _adapter_stdout(last_result),
                "stderr": _stream_text(output),
                "timed_out": False,
                "signal_terminated": returncode < 0,
                "resolved_index_lock_path": resolved_lock,
            }
        )
        if classification.get("kind") not in {
            GIT_LOCK_FAILURE_INDEX_LOCK,
            GIT_LOCK_FAILURE_OTHER_LOCK,
        }:
            return last_result, _GitLockRetryOutcome(
                attempts=attempts,
                lock_removed=lock_removed,
                lock_path=latest_lock_path,
            )

        parsed = classification.get("parsed_lock_path")
        path_match = match_git_lock_path(
            {
                "parsed_error_path": _canonical_error_path(parsed, repo_path),
                "resolved_index_lock_path": resolved_lock,
                "git_context_supported": bool(context.get("supported")),
                "git_context_contradictory": bool(context.get("contradictory")),
            }
        )
        matched = path_match.get("matched_path")
        lock_path = Path(matched) if isinstance(matched, str) and matched else None
        if lock_path is not None:
            latest_lock_path = lock_path
        current_snapshot = snapshot_lock_path(lock_path)
        if first_snapshot is None and current_snapshot is not None:
            first_snapshot = current_snapshot
        if attempts <= len(retry_delays):
            owner = {
                "schema_version": GIT_LOCK_WIRE_SCHEMA_VERSION,
                "status": GIT_LOCK_OWNER_UNKNOWN,
                "reason": "owner probe deferred until retries exhaust",
            }
        else:
            owner = _owner_observation(
                probe,
                lock_path=lock_path,
                resolved_git_dir=(
                    str(context["resolved_git_dir"])
                    if context.get("resolved_git_dir")
                    else None
                ),
                resolved_worktree=(
                    str(context["resolved_worktree"])
                    if context.get("resolved_worktree")
                    else None
                ),
                remaining=remaining_budget(),
            )
        decision = decide_git_lock_recovery(
            {
                "schema_version": GIT_LOCK_WIRE_SCHEMA_VERSION,
                "failure": classification,
                "delays": list(retry_delays),
                "allow_lock_removal": allow_lock_removal,
                "attempts": attempts,
                "now_unix_ns": _observed_now_ns(
                    now, age_wait_used=age_wait_used, first_snapshot=first_snapshot
                ),
                "remaining_command_deadline_ns": deadline_ns(),
                "remaining_recovery_budget_ns": max(
                    0, int(remaining_budget() * 1_000_000_000)
                ),
                "cancelled": cancelled(),
                "removal_already_attempted": removal_attempted,
                "identity_disqualified": identity_disqualified,
                "first_snapshot": first_snapshot,
                "current_snapshot": current_snapshot,
                "path_match": path_match,
                "owner": owner,
            }
        )
        identity_disqualified = bool(decision.get("identity_disqualified"))
        action = str(decision.get("action"))
        reason = str(decision.get("reason"))
        if action == GIT_LOCK_ACTION_RETRY:
            delay = _delay_seconds(decision.get("delay_ns"))
            emit(
                "Git lock contention in "
                f"{repo_path}; retrying attempt {attempts + 1}/"
                f"{len(retry_delays) + 1} after {delay:.3f}s "
                f"(lock={latest_lock_path or 'unknown'}, reason={reason})"
            )
            if not _sleep_or_cancel(sleep, delay, cancelled):
                return last_result, _GitLockRetryOutcome(
                    attempts=attempts,
                    lock_removed=lock_removed,
                    lock_path=latest_lock_path,
                )
            last_result = None
            continue
        if action == GIT_LOCK_ACTION_WAIT:
            if age_wait_used or not allow_age_wait:
                emit(
                    "Preserving git index lock in "
                    f"{repo_path} after attempt {attempts} "
                    f"(lock={latest_lock_path}, reason={reason})"
                )
                return last_result, _GitLockRetryOutcome(
                    attempts=attempts,
                    lock_removed=lock_removed,
                    lock_path=latest_lock_path,
                )
            delay = _delay_seconds(decision.get("delay_ns"))
            if delay > 0:
                # Cover ns-to-float and chunked-sleep truncation so the lock
                # actually reaches the 15s stale-age threshold.
                delay += 0.001
            emit(
                "Waiting "
                f"{delay:.3f}s for owner-free git index lock in {repo_path} "
                f"to reach stale age (lock={latest_lock_path})"
            )
            age_wait_used = True
            if not _sleep_or_cancel(sleep, delay, cancelled):
                return last_result, _GitLockRetryOutcome(
                    attempts=attempts,
                    lock_removed=lock_removed,
                    lock_path=latest_lock_path,
                )
            continue
        if action == GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL:
            emit(
                "Git index lock in "
                f"{repo_path} disappeared before cleanup "
                f"(lock={latest_lock_path}); retrying once"
            )
            removal_attempted = True
            last_result = None
            continue
        if action == GIT_LOCK_ACTION_REMOVE_THEN_RETRY:
            removed, claimed = _remove_if_still_eligible(
                lock_path=lock_path,
                first_snapshot=first_snapshot,
                probe=probe,
                context=context,
                now_unix_ns=_observed_now_ns(
                    now, age_wait_used=age_wait_used, first_snapshot=first_snapshot
                ),
                remaining_budget=remaining_budget,
                deadline_ns=deadline_ns,
                cancelled=cancelled,
                classification=classification,
                path_match=path_match,
                retry_delays=retry_delays,
                allow_lock_removal=allow_lock_removal,
                identity_disqualified=identity_disqualified,
            )
            removal_attempted = True
            if cancelled():
                return last_result, _GitLockRetryOutcome(
                    attempts=attempts,
                    lock_removed=False,
                    lock_path=latest_lock_path,
                )
            if not removed:
                emit(
                    "Failed to remove stale git index lock in "
                    f"{repo_path} after attempt {attempts} "
                    f"(lock={latest_lock_path}, reason={reason})"
                )
                return last_result, _GitLockRetryOutcome(
                    attempts=attempts,
                    lock_removed=False,
                    lock_path=latest_lock_path,
                )
            lock_removed = claimed
            if claimed:
                emit(
                    "Removed stale git index lock in "
                    f"{repo_path} after attempt {attempts} "
                    f"(lock={latest_lock_path}); retrying once"
                )
            else:
                emit(
                    "Git index lock in "
                    f"{repo_path} was already gone "
                    f"(lock={latest_lock_path}); retrying once"
                )
            last_result = None
            continue
        emit(
            "Preserving git index lock in "
            f"{repo_path} after attempt {attempts} "
            f"(lock={latest_lock_path}, reason={reason})"
        )
        return last_result, _GitLockRetryOutcome(
            attempts=attempts,
            lock_removed=lock_removed,
            lock_path=latest_lock_path,
        )


def try_remove_stale_index_lock(
    workspace_dir: str | Path,
    *,
    min_age_seconds: float = STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS,
    unix_clock: UnixClock | None = None,
    owner_probe: Callable[..., dict[str, Any]] | None = None,
) -> bool:
    """Remove an aged owner-free index lock using the shared recovery policy."""
    _ensure_git_lock_policy()
    now = unix_clock or time.time
    context = resolve_index_lock_context(workspace_dir)
    resolved = context.get("resolved_index_lock_path")
    if not isinstance(resolved, str) or not resolved:
        return False
    lock_path = Path(resolved)
    snapshot = snapshot_lock_path(lock_path)
    owner = _owner_observation(
        owner_probe or probe_index_lock_owner,
        lock_path=lock_path,
        resolved_git_dir=(
            str(context["resolved_git_dir"])
            if context.get("resolved_git_dir")
            else None
        ),
        resolved_worktree=(
            str(context["resolved_worktree"])
            if context.get("resolved_worktree")
            else None
        ),
        remaining=DEFAULT_GIT_LOCK_RECOVERY_WAIT_CAP_SECONDS,
    )
    decision = decide_eager_git_lock_cleanup(
        {
            "now_unix_ns": _unix_ns(now),
            "min_age_ns": max(0, int(min_age_seconds * 1_000_000_000)),
            "snapshot": snapshot,
            "owner": owner,
        }
    )
    if str(decision.get("action")) != GIT_LOCK_ACTION_REMOVE_THEN_RETRY:
        return False
    recheck = snapshot_lock_path(lock_path)
    if recheck is None or snapshot is None or recheck != snapshot:
        return False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return True


def _remove_if_still_eligible(
    *,
    lock_path: Path | None,
    first_snapshot: dict[str, Any] | None,
    probe: Callable[..., dict[str, Any]],
    context: Mapping[str, Any],
    now_unix_ns: int,
    remaining_budget: Callable[[], float],
    deadline_ns: Callable[[], int | None],
    cancelled: Callable[[], bool],
    classification: dict[str, Any],
    path_match: dict[str, Any],
    retry_delays: tuple[float, ...],
    allow_lock_removal: bool,
    identity_disqualified: bool,
) -> tuple[bool, bool]:
    if cancelled() or lock_path is None:
        return False, False
    current = snapshot_lock_path(lock_path)
    if current is None:
        return True, False
    owner = _owner_observation(
        probe,
        lock_path=lock_path,
        resolved_git_dir=(
            str(context["resolved_git_dir"])
            if context.get("resolved_git_dir")
            else None
        ),
        resolved_worktree=(
            str(context["resolved_worktree"])
            if context.get("resolved_worktree")
            else None
        ),
        remaining=remaining_budget(),
    )
    decision = decide_git_lock_recovery(
        {
            "schema_version": GIT_LOCK_WIRE_SCHEMA_VERSION,
            "failure": classification,
            "delays": list(retry_delays),
            "allow_lock_removal": allow_lock_removal,
            "attempts": 10_000,
            "now_unix_ns": now_unix_ns,
            "remaining_command_deadline_ns": deadline_ns(),
            "remaining_recovery_budget_ns": max(
                0, int(remaining_budget() * 1_000_000_000)
            ),
            "cancelled": cancelled(),
            "removal_already_attempted": False,
            "identity_disqualified": identity_disqualified,
            "first_snapshot": first_snapshot,
            "current_snapshot": current,
            "path_match": path_match,
            "owner": owner,
        }
    )
    if str(decision.get("action")) == GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL:
        return True, False
    if str(decision.get("action")) != GIT_LOCK_ACTION_REMOVE_THEN_RETRY:
        return False, False
    recheck = snapshot_lock_path(lock_path)
    if recheck is None:
        return True, False
    if recheck != current:
        return False, False
    try:
        lock_path.unlink()
    except FileNotFoundError:
        return True, False
    except OSError:
        return False, False
    return True, True


def _owner_observation(
    probe: Callable[..., dict[str, Any]],
    *,
    lock_path: Path | None,
    resolved_git_dir: str | None,
    resolved_worktree: str | None,
    remaining: float,
) -> dict[str, Any]:
    timeout = max(0.05, min(2.0, remaining if remaining > 0 else 0.05))
    facts = probe(
        lock_path=lock_path,
        resolved_git_dir=resolved_git_dir,
        resolved_worktree=resolved_worktree,
        timeout=timeout,
    )
    return classify_git_lock_owner(facts)


def _canonical_error_path(parsed: object, repo_path: Path) -> str | None:
    if not isinstance(parsed, str) or not parsed:
        return None
    path = Path(parsed)
    if not path.is_absolute():
        path = repo_path / path
    return str(canonicalize_lock_path(path))


def _validated_retry_delays(delays: Iterable[float]) -> tuple[float, ...]:
    return validate_git_lock_retry_delays(tuple(float(delay) for delay in delays))


def _default_result_adapter(result: Any) -> tuple[int, str | bytes | None]:
    try:
        returncode = int(result.returncode)
    except (AttributeError, TypeError, ValueError) as error:
        raise TypeError(
            "result_adapter is required for results without an integer returncode"
        ) from error
    stderr = getattr(result, "stderr", None)
    stdout = getattr(result, "stdout", None)
    output = "\n".join(
        detail for value in (stderr, stdout) if (detail := _stream_text(value))
    )
    return returncode, output


def _adapter_stdout(result: Any) -> str:
    return _stream_text(getattr(result, "stdout", None))


def _unix_ns(clock: UnixClock) -> int:
    return int(clock() * 1_000_000_000)


def _observed_now_ns(
    clock: UnixClock,
    *,
    age_wait_used: bool,
    first_snapshot: dict[str, Any] | None,
) -> int:
    """Return the policy clock, treating a completed age-wait as stale.

    Chunked sleep and ``int(seconds * 1e9)`` truncation can leave the lock a
    few nanoseconds younger than the 15s threshold after the executor already
    waited the policy-requested delay. Once that wait has run against an
    unchanged first snapshot, count the lock as aged from that snapshot.
    """
    now_ns = _unix_ns(clock)
    if not age_wait_used or first_snapshot is None:
        return now_ns
    mtime_ns = first_snapshot.get("mtime_ns")
    if not isinstance(mtime_ns, int):
        return now_ns
    waited_until = mtime_ns + int(STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS * 1_000_000_000)
    return max(now_ns, waited_until)


def _delay_seconds(delay_ns: object) -> float:
    if not isinstance(delay_ns, int):
        return 0.0
    return max(0.0, delay_ns / 1_000_000_000)


def _sleep_or_cancel(
    sleep: Sleeper, delay: float, cancelled: Callable[[], bool]
) -> bool:
    if delay <= 0:
        return not cancelled()
    remaining = delay
    while remaining > 0:
        if cancelled():
            return False
        step = min(0.05, remaining)
        sleep(step)
        remaining -= step
    return not cancelled()


def _stream_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value if isinstance(value, str) else ""


__all__ = [
    "DEFAULT_GIT_LOCK_RETRY_DELAYS",
    "ENV_GIT_LOCK_RETRY_DELAYS",
    "STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS",
    "git_index_lock_path",
    "git_lock_retry_delays",
    "run_with_git_lock_retry",
    "try_remove_stale_index_lock",
]
