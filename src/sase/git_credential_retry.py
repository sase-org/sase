"""Bounded retries for SSH publickey denials from git.

``SASE_GIT_CREDENTIAL_RETRY_MAX_SECONDS`` caps total credential-retry sleep
for every budget; setting it to ``0`` disables these retries.
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from sase.core.retryability_wire import RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED
from sase.service.ssh_agent import local_ssh_credential_state

_LOG = logging.getLogger(__name__)
_RETRY_MAX_SECONDS_ENV = "SASE_GIT_CREDENTIAL_RETRY_MAX_SECONDS"
_EXHAUSTION_MEMO_SECONDS = 10 * 60
_EXHAUSTED_HOSTS: dict[str, tuple[float, str]] = {}
_SSH_HOST_DENIAL = re.compile(
    r"(?im)(?:^|\s)(?:[^@\s/:]+@)?(?P<host>[A-Za-z0-9.-]+):\s*"
    r"Permission denied \(publickey"
)


@dataclass(frozen=True)
class CredentialRetryBudget:
    """A named sequence of delays, each allowing one confirmation retry."""

    label: str
    delays: tuple[float, ...]


LAUNCH_CREDENTIAL_RETRY_BUDGET = CredentialRetryBudget("launch", (5, 10, 20, 30, 45))
BACKGROUND_CREDENTIAL_RETRY_BUDGET = CredentialRetryBudget("background", (10,))


def _ssh_host(detail: str) -> str | None:
    match = _SSH_HOST_DENIAL.search(detail)
    if match is None:
        return None
    return match.group("host").casefold().rstrip(".") or None


def _sleep_cap(env: Mapping[str, str]) -> tuple[float | None, str | None]:
    raw = env.get(_RETRY_MAX_SECONDS_ENV)
    if raw is None:
        return None, None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return 0, f"invalid {_RETRY_MAX_SECONDS_ENV} disables retries"
    if not math.isfinite(value):
        return 0, f"invalid {_RETRY_MAX_SECONDS_ENV} disables retries"
    if value < 0:
        return 0, f"negative {_RETRY_MAX_SECONDS_ENV} disables retries"
    return value, None


class CredentialRetry:
    """Track credential-confirmation attempts for one logical git operation."""

    def __init__(
        self,
        budget: CredentialRetryBudget,
        *,
        deadline: float | None,
        env: Mapping[str, str],
        sleep: Callable[[float], None] | None = None,
        monotonic: Callable[[], float] | None = None,
        credential_probe: Callable[[Mapping[str, str], str | None], str] | None = None,
    ) -> None:
        self.budget = budget
        self.deadline = deadline
        self.env = env
        self._sleep = sleep or time.sleep
        self._monotonic = monotonic or time.monotonic
        self._credential_probe = credential_probe or local_ssh_credential_state
        self._sleep_cap_seconds, cap_error = _sleep_cap(env)
        self._stop_reason = cap_error
        self._attempts = 0
        self._slept_seconds = 0.0
        self._first_detail: str | None = None
        self._host: str | None = None
        self._credential_checked = False

    @property
    def attempts(self) -> int:
        """Number of credential-denial retries already slept for."""
        return self._attempts

    @property
    def first_detail(self) -> str | None:
        """Original stderr from the first ambiguous publickey denial."""
        return self._first_detail

    def retry_after(self, verdict: str, detail: str) -> bool:
        """Sleep for the next allowed retry and return whether to retry."""
        if verdict != RETRYABILITY_VERDICT_CREDENTIAL_UNCONFIRMED:
            return False

        if self._first_detail is None:
            self._first_detail = detail
            self._host = _ssh_host(detail)

        now = self._monotonic()
        if self._host is not None and self._is_recently_exhausted(self._host, now):
            self._stop_reason = "credential retry was recently exhausted for this host"
            return False

        if not self._credential_checked:
            self._credential_checked = True
            try:
                credential_state = self._credential_probe(self.env, self._host)
            except Exception:
                credential_state = "unknown"
            if credential_state == "absent":
                self._stop_reason = "no local SSH credential"
                self._memoize_exhaustion(now, self._stop_reason)
                return False

        if self._attempts >= len(self.budget.delays):
            self._stop_reason = "credential retry budget exhausted"
            self._memoize_exhaustion(now, self._stop_reason)
            return False

        delay = self.budget.delays[self._attempts]
        if self._sleep_cap_seconds is not None:
            remaining_cap = self._sleep_cap_seconds - self._slept_seconds
            if delay > remaining_cap:
                self._stop_reason = (
                    self._stop_reason or "credential retry sleep cap exhausted"
                )
                return False

        if self.deadline is not None and delay > self.deadline - now:
            self._stop_reason = (
                "next credential retry would exceed the operation deadline"
            )
            return False

        _LOG.warning(
            "GitHub denied SSH publickey authentication; credential retry %s for %s "
            "after %gs; original stderr:\n%s",
            self._attempts + 1,
            self.budget.label,
            delay,
            detail,
        )
        self._sleep(delay)
        self._attempts += 1
        self._slept_seconds += delay
        return True

    def note_success(self) -> None:
        """Record recovery and clear this host's recent-exhaustion memo."""
        if self._host is not None:
            _EXHAUSTED_HOSTS.pop(self._host, None)
        if self._attempts:
            _LOG.warning(
                "transient SSH publickey denial cleared after %s retries",
                self._attempts,
            )

    def failure_suffix(self) -> str:
        """Return a one-line explanation to append after git's original stderr."""
        if self._first_detail is None:
            return ""
        operation_attempts = self._attempts + 1
        attempt_word = "attempt" if operation_attempts == 1 else "attempts"
        elapsed = f"{self._slept_seconds:g}s"
        suffix = (
            "GitHub refused SSH publickey authentication on "
            f"{operation_attempts} {attempt_word} over {elapsed}"
        )
        if self._stop_reason:
            suffix += f"; {self._stop_reason}"
        return suffix + "; see docs/reference/agents/service-host.md"

    def _is_recently_exhausted(self, host: str, now: float) -> bool:
        entry = _EXHAUSTED_HOSTS.get(host)
        if entry is None:
            return False
        exhausted_at, _reason = entry
        age = now - exhausted_at
        if 0 <= age < _EXHAUSTION_MEMO_SECONDS:
            return True
        _EXHAUSTED_HOSTS.pop(host, None)
        return False

    def _memoize_exhaustion(self, now: float, reason: str) -> None:
        if self._host is not None:
            _EXHAUSTED_HOSTS[self._host] = (now, reason)


__all__ = [
    "BACKGROUND_CREDENTIAL_RETRY_BUDGET",
    "CredentialRetry",
    "CredentialRetryBudget",
    "LAUNCH_CREDENTIAL_RETRY_BUDGET",
]
