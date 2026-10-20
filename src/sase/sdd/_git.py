"""Compatibility facade for bounded SDD git execution.

Implementations are split between shared configuration, local execution with
streaming transfers, and classifier-driven network retries. This module
retains the original import surface for callers and tests.
"""

from sase.sdd._git_config import (
    DEFAULT_LOCAL_GIT_TIMEOUT_SECONDS,
    DEFAULT_NETWORK_GIT_MAX_ATTEMPTS,
    DEFAULT_NETWORK_GIT_RETRY_DELAYS_SECONDS,
    DEFAULT_NETWORK_GIT_TIMEOUT_SECONDS,
    DEFAULT_NETWORK_GIT_TRANSFER_CEILING_SECONDS,
    DEFAULT_SLOW_GIT_MS,
    ENV_LOCAL_TIMEOUT,
    ENV_NETWORK_TIMEOUT,
    ENV_NETWORK_TRANSFER_CEILING,
    ENV_SLOW_MS,
    SddGitCommandTimeout,
    sdd_git_command,
)
from sase.sdd._git_network import (
    SddGitRunFn,
    network_git_timeout,
    run_sdd_network_git,
    run_sdd_network_git_with_retries,
)
from sase.sdd._git_runner import run_sdd_git

__all__ = [
    "DEFAULT_LOCAL_GIT_TIMEOUT_SECONDS",
    "DEFAULT_NETWORK_GIT_MAX_ATTEMPTS",
    "DEFAULT_NETWORK_GIT_RETRY_DELAYS_SECONDS",
    "DEFAULT_NETWORK_GIT_TIMEOUT_SECONDS",
    "DEFAULT_NETWORK_GIT_TRANSFER_CEILING_SECONDS",
    "DEFAULT_SLOW_GIT_MS",
    "ENV_LOCAL_TIMEOUT",
    "ENV_NETWORK_TIMEOUT",
    "ENV_NETWORK_TRANSFER_CEILING",
    "ENV_SLOW_MS",
    "SddGitCommandTimeout",
    "SddGitRunFn",
    "network_git_timeout",
    "run_sdd_git",
    "run_sdd_network_git",
    "run_sdd_network_git_with_retries",
    "sdd_git_command",
]
