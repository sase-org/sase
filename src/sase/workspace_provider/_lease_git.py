"""Git preparation helpers for operational workspace leases."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from sase.core.retryability_facade import classify_failure_retryability
from sase.core.retryability_wire import RETRY_OPERATION_GIT
from sase.git_lock_retry import run_with_git_lock_retry
from sase.workspace_provider._lease_model import (
    OperationalLeaseError,
    is_credential_verdict,
)
from sase.workspace_provider.utils import get_default_branch, non_interactive_git_env

_logger = logging.getLogger(__name__)

_FETCH_MAX_ATTEMPTS = 3
_FETCH_RETRY_DELAYS_SECONDS = (1.0, 5.0)
_CREDENTIAL_CONFIRMATION_DELAY_SECONDS = 10.0

_sleep = time.sleep


def prepare_from_primary_remote(checkout: Path) -> None:
    if not (checkout / ".git").exists() and not (checkout / ".git").is_file():
        raise OperationalLeaseError(
            "preparation",
            f"{checkout} is not a git checkout",
        )
    remotes = _git_remotes(checkout)
    if "origin" in remotes:
        _fetch_origin_with_retries(checkout)
    upstream = _configured_upstream(checkout)
    if upstream is None:
        return
    local_branch = upstream.rsplit("/", 1)[-1]
    checkout_result = _run_git_mutation(
        ["checkout", "--force", "-B", local_branch, upstream],
        checkout,
    )
    if checkout_result.returncode != 0:
        detail = (
            checkout_result.stderr.strip()
            or checkout_result.stdout.strip()
            or f"git checkout {upstream} failed"
        )
        raise _preparation_error(detail, checkout_result.returncode)


def _fetch_origin_with_retries(checkout: Path) -> None:
    """Fetch origin with bounded, classified retries.

    Transient transport failures retry up to ``_FETCH_MAX_ATTEMPTS`` total
    attempts. A credential refusal gets exactly one delayed confirmation
    retry. Anything else raises on the first attempt.
    """
    from sase.sdd._git import network_git_timeout

    timeout = network_git_timeout()
    credential_retry_used = False
    first_credential_stderr: str | None = None

    for attempt in range(1, _FETCH_MAX_ATTEMPTS + 1):
        try:
            fetch = _run_git(["fetch", "--quiet", "origin"], checkout, timeout=timeout)
        except subprocess.TimeoutExpired:
            if attempt >= _FETCH_MAX_ATTEMPTS:
                raise OperationalLeaseError(
                    "preparation",
                    f"git fetch timed out after {timeout:g}s",
                ) from None
            _sleep(_FETCH_RETRY_DELAYS_SECONDS[attempt - 1])
            continue
        if fetch.returncode == 0:
            if first_credential_stderr is not None:
                _logger.warning(
                    "transient remote credential refusal cleared on retry: %s",
                    first_credential_stderr,
                )
            return
        detail = fetch.stderr.strip() or fetch.stdout.strip() or "git fetch failed"
        verdict = classify_failure_retryability(
            RETRY_OPERATION_GIT,
            exit_status=fetch.returncode,
            stderr=detail,
        )
        if is_credential_verdict(verdict):
            if credential_retry_used or attempt >= _FETCH_MAX_ATTEMPTS:
                raise _preparation_error(detail, fetch.returncode)
            credential_retry_used = True
            first_credential_stderr = detail
            _sleep(_CREDENTIAL_CONFIRMATION_DELAY_SECONDS)
            continue
        if not verdict.retryable or attempt >= _FETCH_MAX_ATTEMPTS:
            raise _preparation_error(detail, fetch.returncode)
        if verdict.retry_after_seconds is not None:
            _sleep(max(0.0, float(verdict.retry_after_seconds)))
        else:
            _sleep(_FETCH_RETRY_DELAYS_SECONDS[attempt - 1])


def _preparation_error(detail: str, returncode: int) -> OperationalLeaseError:
    """Build the preparation failure for a git command that exited non-zero.

    The shared classifier decides whether the failure is a credential problem;
    that verdict rides on the error so callers can branch without re-parsing
    the message.
    """
    verdict = classify_failure_retryability(
        RETRY_OPERATION_GIT,
        exit_status=returncode,
        stderr=detail,
    )
    if is_credential_verdict(verdict):
        detail = _with_ssh_agent_hint(detail)
    return OperationalLeaseError("preparation", detail, retryability=verdict)


def _with_ssh_agent_hint(detail: str) -> str:
    """Append the remediation sentence for a git credential failure.

    The raw git text is preserved verbatim; the sentence only points at the
    usual culprit so nobody goes hunting for a revoked deploy key.
    """
    return (
        f"{detail}\n"
        "This is usually a missing or empty SSH agent in the calling process "
        "(check SSH_AUTH_SOCK); when the caller is the service host, give it an "
        "unattended credential (see docs/init.md). Re-running `sase service "
        "init` from a login shell only lasts until that shell's agent dies."
    )


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


def _run_git_mutation(
    args: list[str],
    checkout: Path,
) -> subprocess.CompletedProcess[str]:
    result, _outcome = run_with_git_lock_retry(
        lambda: _run_git(args, checkout),
        cwd=checkout,
    )
    return result


def _run_git(
    args: list[str],
    checkout: Path,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=False,
        env=non_interactive_git_env(),
        stdin=subprocess.DEVNULL,
        timeout=timeout,
    )


__all__ = [
    "_configured_upstream",
    "_git_remotes",
    "prepare_from_primary_remote",
    "_ref_exists",
    "_run_git",
]
