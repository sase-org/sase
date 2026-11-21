"""Keep SASE agents from starting service hosts that outlive them.

A detached service host escapes the agent's ``sase-agent-*`` scope, so the
runner's sweep never stops it, and a throwaway ``HOME`` or ``SASE_HOME`` hides
it from ``sase service status``. Inside an agent environment the TUI's
auto-start is skipped, and ``sase service start``, the TUI start key, and
the detached start path refuse unless :data:`SERVICE_AGENT_BYPASS_ENV`
holds a non-empty reason. This mirrors ``SASE_GLOBAL_INSTALL_BYPASS``.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

#: Escape hatch: a non-empty reason that lets an agent start a service host.
SERVICE_AGENT_BYPASS_ENV = "SASE_SERVICE_AGENT_BYPASS"

#: Environment variables whose non-empty value marks an agent or monitor run.
#: Matches ``agent_marker_present`` in :mod:`sase.agent.identity`.
_AGENT_ENV_VARS = ("SASE_AGENT", "SASE_AGENT_NAME", "SASE_MONITOR_ID")


@dataclass(frozen=True)
class _ServiceAgentGuard:
    """Outcome of the agent check for one service-host start."""

    refused: bool
    marker: str | None = None
    bypass_reason: str | None = None


def service_agent_guard(environ: Mapping[str, str] | None = None) -> _ServiceAgentGuard:
    """Return whether this process must not start a service host."""
    env = os.environ if environ is None else environ
    marker = next(
        (name for name in _AGENT_ENV_VARS if (env.get(name) or "").strip()),
        None,
    )
    if marker is None:
        return _ServiceAgentGuard(refused=False)
    reason = (env.get(SERVICE_AGENT_BYPASS_ENV) or "").strip()
    if reason:
        return _ServiceAgentGuard(refused=False, marker=marker, bypass_reason=reason)
    return _ServiceAgentGuard(refused=True, marker=marker)


def service_agent_refusal_message(action: str, guard: _ServiceAgentGuard) -> str:
    """Render the refusal for *action* (``start`` or ``restart``)."""
    return (
        f"refusing to {action} the service host inside a SASE agent "
        f"({guard.marker} is set): a host started here outlives the agent and "
        "nothing stops it. Leave the account's service host to its owner, or set "
        f"{SERVICE_AGENT_BYPASS_ENV}='<reason>' to {action} one deliberately; "
        "afterwards stop it with `sase service stop` from the same environment "
        "(same HOME and SASE_HOME), or with the `systemctl --user stop <unit>` "
        "command that `sase service status` prints for it."
    )


def service_auto_start_notice(environ: Mapping[str, str] | None = None) -> str | None:
    """Return the one-line notice when the TUI must skip host auto-start."""
    guard = service_agent_guard(environ)
    if not guard.refused:
        return None
    return (
        f"Service host auto-start skipped inside a SASE agent ({guard.marker}); "
        "behaving like --no-service."
    )


__all__ = [
    "SERVICE_AGENT_BYPASS_ENV",
    "service_agent_guard",
    "service_agent_refusal_message",
    "service_auto_start_notice",
]
