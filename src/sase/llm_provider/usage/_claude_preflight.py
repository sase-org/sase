"""Zero-cost preflight checks for the Claude usage probe."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sase.llm_provider.usage._capability_cache import (
    decode_command_result,
    encode_command_result,
    read_probe_capability,
    write_probe_capability,
)
from sase.llm_provider.usage._claude_constants import CLAUDE_USAGE_MIN_VERSION
from sase.llm_provider.usage._claude_support import (
    ClaudeCommandResult,
    ClaudeCommandRunner,
    extract_version,
    print_help_supports_zero_cost_probe,
    safe_run,
    status_observation,
)
from sase.llm_provider.usage.types import UsageProbeContext


def preflight_usage_probe(
    context: UsageProbeContext,
    executable: str,
    run: ClaudeCommandRunner,
    clock: Callable[[], float],
    *,
    fingerprint: str | None = None,
) -> dict[str, Any] | None:
    """Check the Claude CLI can serve a zero-cost probe, using the cache."""
    if fingerprint is not None:
        cached = read_probe_capability(context.provider, fingerprint, now=clock())
        if cached is not None:
            decoded = _decode_cached_preflight(cached)
            if decoded is not None:
                return _preflight_status_from_results(
                    context, decoded[0], decoded[1], decoded[2], clock=clock
                )
    version_result = safe_run(
        run,
        (executable, "--version"),
        cwd=None,
        deadline_at=context.deadline_at,
    )
    if version_result == "timeout":
        return status_observation(
            context, now=clock(), outcome="error", reason_code="timeout"
        )
    if version_result == "not_installed":
        return status_observation(
            context,
            now=clock(),
            outcome="unsupported",
            reason_code="not_installed",
        )
    if (
        not isinstance(version_result, ClaudeCommandResult)
        or version_result.returncode != 0
    ):
        return status_observation(
            context,
            now=clock(),
            outcome="unsupported",
            reason_code="unsupported_cli_version",
        )
    version = extract_version(f"{version_result.stdout} {version_result.stderr}")
    if version is None or version < CLAUDE_USAGE_MIN_VERSION:
        return status_observation(
            context,
            now=clock(),
            outcome="unsupported",
            reason_code="unsupported_cli_version",
        )

    print_help = safe_run(
        run,
        (executable, "-p", "--help"),
        cwd=None,
        deadline_at=context.deadline_at,
    )
    auth_help = safe_run(
        run,
        (executable, "auth", "status", "--help"),
        cwd=None,
        deadline_at=context.deadline_at,
    )
    if print_help == "timeout" or auth_help == "timeout":
        return status_observation(
            context, now=clock(), outcome="error", reason_code="timeout"
        )
    if print_help == "not_installed" or auth_help == "not_installed":
        return status_observation(
            context,
            now=clock(),
            outcome="unsupported",
            reason_code="not_installed",
        )
    status = _preflight_status_from_results(
        context, version_result, print_help, auth_help, clock=clock
    )
    if status is None and fingerprint is not None:
        version_entry = (
            encode_command_result(
                version_result.returncode,
                version_result.stdout,
                version_result.stderr,
            )
            if isinstance(version_result, ClaudeCommandResult)
            else None
        )
        print_entry = (
            encode_command_result(
                print_help.returncode, print_help.stdout, print_help.stderr
            )
            if isinstance(print_help, ClaudeCommandResult)
            else None
        )
        auth_entry = (
            encode_command_result(
                auth_help.returncode, auth_help.stdout, auth_help.stderr
            )
            if isinstance(auth_help, ClaudeCommandResult)
            else None
        )
        if (
            version_entry is not None
            and print_entry is not None
            and auth_entry is not None
        ):
            write_probe_capability(
                context.provider,
                fingerprint,
                {
                    "version": version_entry,
                    "print_help": print_entry,
                    "auth_help": auth_entry,
                },
                now=clock(),
            )
    return status


def _decode_cached_preflight(
    cached: dict[str, Any],
) -> tuple[ClaudeCommandResult, ClaudeCommandResult, ClaudeCommandResult] | None:
    """Decode cached preflight outputs, or ``None`` when they are not usable."""
    version = decode_command_result(cached.get("version"))
    print_help = decode_command_result(cached.get("print_help"))
    auth_help = decode_command_result(cached.get("auth_help"))
    if version is None or print_help is None or auth_help is None:
        return None
    return (
        ClaudeCommandResult(*version),
        ClaudeCommandResult(*print_help),
        ClaudeCommandResult(*auth_help),
    )


def _preflight_status_from_results(
    context: UsageProbeContext,
    version_result: ClaudeCommandResult | str,
    print_help: ClaudeCommandResult | str,
    auth_help: ClaudeCommandResult | str,
    *,
    clock: Callable[[], float],
) -> dict[str, Any] | None:
    """Validate preflight command results; ``None`` means the probe may run."""
    if isinstance(version_result, ClaudeCommandResult):
        version = extract_version(f"{version_result.stdout} {version_result.stderr}")
    else:
        version = None
    if version is None or version < CLAUDE_USAGE_MIN_VERSION:
        return status_observation(
            context,
            now=clock(),
            outcome="unsupported",
            reason_code="unsupported_cli_version",
        )
    if not (
        isinstance(print_help, ClaudeCommandResult)
        and isinstance(auth_help, ClaudeCommandResult)
        and print_help.returncode == 0
        and auth_help.returncode == 0
        and print_help_supports_zero_cost_probe(print_help.stdout)
        and "--json" in auth_help.stdout
    ):
        return status_observation(
            context,
            now=clock(),
            outcome="unsupported",
            reason_code="unsupported_cli_version",
        )
    return None


__all__ = [
    "preflight_usage_probe",
]
