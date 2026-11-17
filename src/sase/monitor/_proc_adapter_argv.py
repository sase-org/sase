"""Build the explicit argv used to launch monitor procs."""

from __future__ import annotations

from collections.abc import Sequence


MONITOR_ARGV_PREFIX: tuple[str, ...] = ("/bin/sh", "-c")


MONITOR_FOLLOWUP_KIND = "monitor"


def _compile_monitor_argv(command: str) -> list[str]:
    """Compile a monitor command string to explicit argv."""
    return [*MONITOR_ARGV_PREFIX, command]


def monitor_proc_argv(
    command: str,
    *,
    execution_argv: Sequence[str] | None = None,
) -> list[str]:
    """Return the argv the proc supervisor should exec for a monitor.

    Host-owned epic launches pass an explicit execution argv (the
    code-swap bootstrap). Other monitors keep the historical ``/bin/sh -c``
    form of *command*.
    """
    if execution_argv:
        return [str(part) for part in execution_argv]
    return _compile_monitor_argv(command)
