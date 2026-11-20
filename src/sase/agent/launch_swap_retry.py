"""Defer and retry launches that overlap a code swap.

A launch process (``sase run``, ``sase bead work``, an agent runner start)
imports SASE lazily as it goes. If a code swap lands before or during that
work, the process can fail with a missing ``sase_core_rs`` or a swap-skew
``ImportError``. It can also silently mix module versions. Retrying such a
failure in the same process cannot help, because the stale modules stay in
``sys.modules``. The retry is therefore always a fresh process: wait until no
code-swap writer is live, then ``exec`` the same command.

Rules:

* Only an *armed* process re-execs. :func:`arm_code_swap_retry` arms it, and
  only real entry points call it, so a library caller (a test, the TUI) never
  has its process replaced.
* A process retries at most once. The marker that says "this run is the
  retry" is consumed when the retry arms, so child processes never inherit
  it.
* A failure is retried only when it looks like swap skew *and* a swap is in
  play: a writer is live, a swap completed since this process booted, or the
  last swap completed within the post-swap grace. The text alone is not
  enough.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Sequence

from sase.axe.runner_failure_facts import capture_failure_facts
from sase.core.code_swap_epoch import (
    code_swap_in_play,
    code_swap_since_boot,
    code_swap_writer_live,
    snapshot_boot_swap_generation,
    wait_for_code_swap_writer,
)
from sase.core.state_write_guard import pytest_context_detected

#: Set on the retry's environment so it never retries again. Consumed (popped)
#: by :func:`arm_code_swap_retry`, so it never leaks into child processes.
ENV_CODE_SWAP_RETRY = "SASE_CODE_SWAP_RETRY"

#: How long a launch waits for one live swap before giving up and failing as
#: it would have without the retry. A ``sase dev update`` that rebuilds the
#: Rust extension from source can take over ten minutes.
CODE_SWAP_RETRY_WAIT_SECONDS = 1800.0

#: ``os.execv``'s shape; tests substitute a recorder.
_ExecFn = Callable[[str, list[str]], object]

_armed = False
_retry_spent = False


def arm_code_swap_retry() -> None:
    """Let this process re-exec itself once across a code swap.

    Records the boot swap generation, which is why entry points should call
    it before they import launch code. It also consumes the retry marker, so
    a process that is already the retry stays unable to retry again. A pytest
    process never arms: an in-process entry-point test must not be able to
    replace the test runner.
    """
    global _armed, _retry_spent  # noqa: PLW0603 - process-wide entry state
    if pytest_context_detected():
        return
    snapshot_boot_swap_generation()
    if os.environ.pop(ENV_CODE_SWAP_RETRY, None) == "1":
        _retry_spent = True
    _armed = True


def sase_cli_argv() -> list[str]:
    """Return the argv that reruns this ``sase`` CLI invocation verbatim."""
    return [sys.executable, "-m", "sase", *sys.argv[1:]]


def defer_launch_for_code_swap(
    argv: Sequence[str],
    *,
    execv: _ExecFn = os.execv,
) -> None:
    """Before a launch does anything: wait out a swap and start fresh.

    Re-execs when a writer is live now, or when a swap completed after this
    process booted (its already-imported modules may predate the swap).
    Returns when neither holds, or when the retry is unavailable.
    """
    if code_swap_writer_live():
        reason = "a code swap is in progress"
    elif code_swap_since_boot():
        reason = "a code swap completed after this command started"
    else:
        return
    reexec_after_code_swap(argv, reason=reason, execv=execv)


def retry_launch_after_code_swap(
    exc: BaseException,
    argv: Sequence[str],
    *,
    execv: _ExecFn = os.execv,
) -> None:
    """After a failed launch: retry it once in a fresh process if it was swap fallout.

    Returns (so the caller reports the original failure) unless the failure
    looks like swap skew while a swap is in play. Callers must only call this
    when the failed attempt left nothing behind that a rerun would duplicate,
    such as spawned agents.
    """
    if not _looks_like_swap_skew(exc):
        return
    reason = code_swap_in_play()
    if reason is None:
        return
    reexec_after_code_swap(
        argv,
        reason=f"{reason}, and the launch failed with {type(exc).__name__}: {exc}",
        execv=execv,
    )


def reexec_after_code_swap(
    argv: Sequence[str],
    *,
    reason: str,
    wait_seconds: float = CODE_SWAP_RETRY_WAIT_SECONDS,
    execv: _ExecFn = os.execv,
) -> None:
    """Wait for any live writer to finish, then replace this process with *argv*.

    Returns without exec'ing when this process is not armed, already used its
    retry, the wait timed out, or the exec itself failed. The caller then
    fails exactly as it would have without the retry.
    """
    global _retry_spent  # noqa: PLW0603 - the retry is spent once per process
    if not _armed or _retry_spent or not argv:
        return
    _retry_spent = True
    if not wait_for_code_swap_writer(
        timeout_seconds=wait_seconds,
        on_wait=lambda: _say(
            f"sase: waiting for the code swap to finish before retrying ({reason})"
        ),
    ):
        _say(
            "sase: the code swap did not finish within "
            f"{int(wait_seconds)}s; not retrying"
        )
        return
    _say(f"sase: retrying in a fresh process after a code swap ({reason})")
    os.environ[ENV_CODE_SWAP_RETRY] = "1"
    try:
        execv(argv[0], list(argv))
    except OSError as exc:
        os.environ.pop(ENV_CODE_SWAP_RETRY, None)
        _say(f"sase: could not restart after the code swap: {exc}")


def _looks_like_swap_skew(exc: BaseException) -> bool:
    """Whether *exc* matches the shared swap-skew failure patterns."""
    try:
        return bool(capture_failure_facts(exc, phase="launch").get("skew_suspect"))
    except Exception:  # noqa: BLE001 - classification must never break a launch
        return False


def _say(message: str) -> None:
    try:
        sys.stdout.flush()
        print(message, file=sys.stderr, flush=True)
    except (OSError, ValueError):
        pass


__all__ = [
    "CODE_SWAP_RETRY_WAIT_SECONDS",
    "ENV_CODE_SWAP_RETRY",
    "arm_code_swap_retry",
    "defer_launch_for_code_swap",
    "reexec_after_code_swap",
    "retry_launch_after_code_swap",
    "sase_cli_argv",
]
