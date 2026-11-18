"""Deadline-bounded git runner that types timeouts instead of misreading them."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import time

from sase.sdd._git import SddGitCommandTimeout
from sase.sdd._repository_types import GitRunner, SddGitTimeoutResult

SDD_ROLLBACK_GRACE_SECONDS = 20.0


class DeadlineGitRunner:
    """A :data:`GitRunner` that maps budget/timeout failures to typed results."""

    def __init__(self, deadline: float | None) -> None:
        self.deadline = deadline

    def __call__(
        self,
        repo_root: Path,
        args: list[str],
        *,
        op: str,
        network: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        from sase.sdd._git import network_git_timeout
        from sase.sdd._git_contention import (
            run_sdd_git_write,
            run_sdd_git_write_network,
        )

        deadline = self.deadline
        if deadline is not None and time.monotonic() >= deadline:
            return SddGitTimeoutResult(
                ["git", *args],
                returncode=124,
                stdout="",
                stderr="deadline expired before git operation",
                timeout_reason="deadline",
            )
        cap = network_git_timeout() if network else None
        if deadline is None:
            effective: float | None = cap
            clipped = False
        elif cap is None:
            effective = max(0.0, deadline - time.monotonic())
            clipped = True
        else:
            remaining = max(0.0, deadline - time.monotonic())
            effective = min(cap, remaining)
            clipped = remaining <= cap
        try:
            if network:
                return run_sdd_git_write_network(
                    args,
                    cwd=repo_root,
                    op=op,
                    timeout=effective,
                    deadline=deadline,
                    check=False,
                    capture_output=True,
                    text=True,
                    env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
                )
            return run_sdd_git_write(
                args,
                cwd=repo_root,
                op=op,
                timeout=effective,
                check=False,
                capture_output=True,
                text=True,
                env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
            )
        except SddGitCommandTimeout as exc:
            reason = "deadline" if (deadline is not None and clipped) else "wall_clock"
            return SddGitTimeoutResult(
                ["git", *args],
                returncode=124,
                stdout="",
                stderr=str(exc),
                timeout_reason=reason,  # type: ignore[arg-type]
            )

    def with_grace(self, seconds: float) -> DeadlineGitRunner:
        """Return a runner whose deadline covers *seconds* of rollback grace."""
        if self.deadline is None:
            return self
        return DeadlineGitRunner(max(self.deadline, time.monotonic() + seconds))


def rollback_runner(runner: GitRunner) -> GitRunner:
    """Swap in the rollback grace budget for deadline-bounded runners."""
    if isinstance(runner, DeadlineGitRunner):
        return runner.with_grace(SDD_ROLLBACK_GRACE_SECONDS)
    return runner
