"""Actor detection for project onboarding and creation flows."""

from __future__ import annotations

from collections.abc import Mapping
import os
import sys
from typing import Literal, TextIO

from sase.agent.identity import discover_agent_identity

_Actor = Literal["human", "agent"]

_GATE_COMMAND_VALUE = "1"
_emitted_bypass_reasons: set[str] = set()

HUMAN_ONLY_CREATE_MESSAGE = (
    "sase project create refuses to apply inside agents and monitors. "
    "Propose the exact command through /sase_gate for human approval."
)


def detect_actor(
    env: Mapping[str, str] | None = None,
    *,
    stderr: TextIO | None = None,
) -> _Actor:
    """Return ``"human"`` or ``"agent"`` from the process environment.

    An agent is recognized from ``SASE_AGENT``, ``SASE_AGENT_NAME``, an
    identity discovered by :func:`discover_agent_identity`, or
    ``SASE_MONITOR_ID``. An approved gate (``SASE_GATE_COMMAND=1``) or a
    nonempty ``SASE_PROJECT_CREATE_BYPASS`` reason permits human behavior;
    the bypass prints its reason to stderr once per process.
    """

    current = env if env is not None else os.environ
    actor: _Actor = "agent" if _agent_present(current) else "human"
    if actor == "human":
        return actor
    if _clean(current.get("SASE_GATE_COMMAND")) == _GATE_COMMAND_VALUE:
        return "human"
    bypass = _clean(current.get("SASE_PROJECT_CREATE_BYPASS"))
    if bypass:
        _emit_bypass_reason(bypass, sys.stderr if stderr is None else stderr)
        return "human"
    return "agent"


def _agent_present(env: Mapping[str, str]) -> bool:
    if _clean(env.get("SASE_AGENT")):
        return True
    if _clean(env.get("SASE_AGENT_NAME")):
        return True
    if _clean(env.get("SASE_MONITOR_ID")):
        return True
    return discover_agent_identity(env) is not None


def _clean(value: str | None) -> str:
    return value.strip() if isinstance(value, str) else ""


def _emit_bypass_reason(reason: str, stream: TextIO) -> None:
    if reason in _emitted_bypass_reasons:
        return
    _emitted_bypass_reasons.add(reason)
    print(f"SASE_PROJECT_CREATE_BYPASS: {reason}", file=stream)


__all__ = ["HUMAN_ONLY_CREATE_MESSAGE", "detect_actor"]
