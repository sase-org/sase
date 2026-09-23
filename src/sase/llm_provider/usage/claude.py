"""Claude Code subscription-usage collection.

Thin facade over the ``_claude_*`` modules: active ``/usage`` probing lives in
:mod:`sase.llm_provider.usage._claude_collect`, preflight checks in
:mod:`sase.llm_provider.usage._claude_preflight`, passive stream events in
:mod:`sase.llm_provider.usage._claude_passive`, and shared constants in
:mod:`sase.llm_provider.usage._claude_constants`.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from sase.llm_provider.usage._capability_cache import note_probe_capability_outcome
from sase.llm_provider.usage._claude_collect import run_claude_probe
from sase.llm_provider.usage._claude_constants import (
    CLAUDE_PROVIDER_NAME,
    CLAUDE_USAGE_MIN_VERSION,
)
from sase.llm_provider.usage._claude_passive import (
    capture_passive_context,
    claude_rate_limit_event_observation,
    flush_claude_passive_usage_events,
    submit_claude_passive_usage_event,
)
from sase.llm_provider.usage._claude_support import (
    ClaudeCommandRunner,
    run_claude_command,
)
from sase.llm_provider.usage.types import UsageProbeContext

_run_claude_command: ClaudeCommandRunner = run_claude_command

_claude_rate_limit_event_observation = claude_rate_limit_event_observation


def collect_claude_usage(
    context: UsageProbeContext,
    *,
    runner: ClaudeCommandRunner | None = None,
    clock: Callable[[], float] = time.time,
) -> dict[str, Any]:
    """Collect one zero-inference Claude ``/usage`` observation."""
    observation = run_claude_probe(
        context, run=runner or _run_claude_command, clock=clock
    )
    note_probe_capability_outcome(context.provider, observation)
    return observation


def capture_claude_passive_usage_context(
    *,
    executable: str | None = None,
    runner: ClaudeCommandRunner | None = None,
    clock: Callable[[], float] = time.time,
) -> UsageProbeContext | None:
    """Prepare a generation-fenced context for Claude stream usage events."""
    return capture_passive_context(
        executable=executable, run=runner or _run_claude_command, clock=clock
    )


__all__ = [
    "CLAUDE_PROVIDER_NAME",
    "CLAUDE_USAGE_MIN_VERSION",
    "capture_claude_passive_usage_context",
    "collect_claude_usage",
    "flush_claude_passive_usage_events",
    "submit_claude_passive_usage_event",
]
