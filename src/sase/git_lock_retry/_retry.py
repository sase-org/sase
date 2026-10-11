"""Bounded retry executor for git lock contention and stale-lock recovery."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
import logging
from pathlib import Path
import time
from typing import Any, TypeVar

from ._policy import (
    DEFAULT_GIT_LOCK_RECOVERY_WAIT_CAP_SECONDS,
    STALE_GIT_INDEX_LOCK_MIN_AGE_SECONDS,
    UnixClock,
    git_lock_policy,
    owner_observation,
    unix_ns,
)
from ._stale import remove_if_still_eligible

_logger = logging.getLogger("sase.git_lock_retry")

ResultT = TypeVar("ResultT")
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
    policy = git_lock_policy()
    if delays is None:
        from sase.git_lock_retry import git_lock_retry_delays as configured_delays

        retry_delays = configured_delays()
    else:
        retry_delays = _validated_retry_delays(delays)
    adapter = result_adapter or _default_result_adapter
    repo_path = Path(cwd).expanduser()
    now = unix_clock or time.time
    monotonic = monotonic_clock or time.monotonic
    sleep = sleeper or time.sleep
    started = monotonic()
    budget = recovery_wait_cap
    probe = owner_probe or policy.probe_index_lock_owner
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
        classification = policy.classify_git_lock_failure(
            {
                "exit_status": returncode,
                "stdout": _adapter_stdout(last_result),
                "stderr": _stream_text(output),
                "timed_out": False,
                "signal_terminated": returncode < 0,
            }
        )
        if classification.get("kind") not in {
            policy.GIT_LOCK_FAILURE_INDEX_LOCK,
            policy.GIT_LOCK_FAILURE_OTHER_LOCK,
        }:
            return last_result, _GitLockRetryOutcome(
                attempts=attempts,
                lock_removed=lock_removed,
                lock_path=latest_lock_path,
            )
        context = policy.resolve_index_lock_context(repo_path, argv=argv, env=env)
        resolved_lock = context.get("resolved_index_lock_path")
        classification = policy.classify_git_lock_failure(
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
            policy.GIT_LOCK_FAILURE_INDEX_LOCK,
            policy.GIT_LOCK_FAILURE_OTHER_LOCK,
        }:
            return last_result, _GitLockRetryOutcome(
                attempts=attempts,
                lock_removed=lock_removed,
                lock_path=latest_lock_path,
            )

        parsed = classification.get("parsed_lock_path")
        path_match = policy.match_git_lock_path(
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
        current_snapshot = policy.snapshot_lock_path(lock_path)
        if first_snapshot is None and current_snapshot is not None:
            first_snapshot = current_snapshot
        if attempts <= len(retry_delays):
            owner = {
                "schema_version": policy.GIT_LOCK_WIRE_SCHEMA_VERSION,
                "status": policy.GIT_LOCK_OWNER_UNKNOWN,
                "reason": "owner probe deferred until retries exhaust",
            }
        else:
            owner = owner_observation(
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
        decision = policy.decide_git_lock_recovery(
            {
                "schema_version": policy.GIT_LOCK_WIRE_SCHEMA_VERSION,
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
        if action == policy.GIT_LOCK_ACTION_RETRY:
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
        if action == policy.GIT_LOCK_ACTION_WAIT:
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
        if action == policy.GIT_LOCK_ACTION_RETRY_WITHOUT_REMOVAL:
            emit(
                "Git index lock in "
                f"{repo_path} disappeared before cleanup "
                f"(lock={latest_lock_path}); retrying once"
            )
            removal_attempted = True
            last_result = None
            continue
        if action == policy.GIT_LOCK_ACTION_REMOVE_THEN_RETRY:
            removed, claimed = remove_if_still_eligible(
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


def _canonical_error_path(parsed: object, repo_path: Path) -> str | None:
    if not isinstance(parsed, str) or not parsed:
        return None
    path = Path(parsed)
    if not path.is_absolute():
        path = repo_path / path
    return str(git_lock_policy().canonicalize_lock_path(path))


def _validated_retry_delays(delays: Iterable[float]) -> tuple[float, ...]:
    return git_lock_policy().validate_git_lock_retry_delays(
        tuple(float(delay) for delay in delays)
    )


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
    now_ns = unix_ns(clock)
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
