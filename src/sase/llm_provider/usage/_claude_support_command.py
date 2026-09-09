"""Bounded Claude CLI command execution and version/probe helpers."""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from packaging.version import InvalidVersion, Version

_COMMAND_TIMEOUT_FLOOR_SECONDS = 0.05
_VERSION_RE = re.compile(r"(\d+(?:\.\d+){1,3})")
CLAUDE_USAGE_PROBE_BUDGET_USD = "0.01"


@dataclass(frozen=True)
class ClaudeCommandResult:
    """One bounded Claude CLI command result."""

    returncode: int
    stdout: str
    stderr: str


ClaudeCommandRunner = Callable[[Sequence[str], str | None, float], ClaudeCommandResult]


def resolve_claude_executable(executable: str | None) -> str | None:
    """Resolve an explicit or PATH-provided Claude executable."""
    if executable:
        return executable
    return shutil.which("claude")


def extract_version(text: str) -> Version | None:
    """Extract a semantic-looking Claude CLI version from command output."""
    match = _VERSION_RE.search(text)
    if match is None:
        return None
    try:
        return Version(match.group(1))
    except InvalidVersion:
        return None


def print_help_supports_zero_cost_probe(help_text: str) -> bool:
    """Return whether Claude print mode supports the guarded usage probe."""
    required = (
        "--output-format",
        "json",
        "--max-budget-usd",
        "--safe-mode",
        "--no-session-persistence",
    )
    return all(item in help_text for item in required)


def usage_probe_argv(executable: str) -> tuple[str, ...]:
    """Build the guarded one-cent-capped Claude ``/usage`` argv."""
    return (
        executable,
        "-p",
        "--output-format",
        "json",
        "--safe-mode",
        "--no-session-persistence",
        "--permission-prompts",
        "none",
        "--max-budget-usd",
        CLAUDE_USAGE_PROBE_BUDGET_USD,
        "/usage",
    )


def run_claude_command(
    argv: Sequence[str],
    cwd: str | None,
    deadline_at: float,
) -> ClaudeCommandResult:
    """Run one bounded Claude CLI command without shell expansion."""
    timeout = deadline_at - time.time()
    if timeout <= 0.0:
        raise subprocess.TimeoutExpired(list(argv), 0.0)
    completed = subprocess.run(
        list(argv),
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=max(timeout, _COMMAND_TIMEOUT_FLOOR_SECONDS),
    )
    return ClaudeCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )


def safe_run(
    run: ClaudeCommandRunner,
    argv: Sequence[str],
    *,
    cwd: str | None,
    deadline_at: float,
) -> ClaudeCommandResult | str:
    """Convert expected Claude command failures into local sentinel values."""
    try:
        return run(argv, cwd, deadline_at)
    except FileNotFoundError:
        return "not_installed"
    except subprocess.TimeoutExpired:
        return "timeout"
    except OSError:
        return "failed"
