"""Support functions for Claude Code subscription usage collection."""

from __future__ import annotations

from ._claude_support_auth import (
    ClaudeAuthInfo,
    auth_info_from_result,
    extract_plan,
    hashed_context_id,
    status_from_auth_text,
)
from ._claude_support_command import (
    ClaudeCommandResult,
    ClaudeCommandRunner,
    extract_version,
    print_help_supports_zero_cost_probe,
    resolve_claude_executable,
    run_claude_command,
    safe_run,
    usage_probe_argv,
)
from ._claude_support_reset_time import parse_claude_reset_timestamp
from ._claude_support_windows import (
    event_window,
    has_zero_cost_markers,
    is_finite_number,
    optional_epoch_seconds,
    parse_usage_windows,
    status_observation,
    vendor_state_from_rate_limit_info,
)

__all__ = [
    "ClaudeAuthInfo",
    "ClaudeCommandResult",
    "ClaudeCommandRunner",
    "auth_info_from_result",
    "event_window",
    "extract_plan",
    "extract_version",
    "has_zero_cost_markers",
    "hashed_context_id",
    "is_finite_number",
    "optional_epoch_seconds",
    "parse_claude_reset_timestamp",
    "parse_usage_windows",
    "print_help_supports_zero_cost_probe",
    "resolve_claude_executable",
    "run_claude_command",
    "safe_run",
    "status_from_auth_text",
    "status_observation",
    "usage_probe_argv",
    "vendor_state_from_rate_limit_info",
]
