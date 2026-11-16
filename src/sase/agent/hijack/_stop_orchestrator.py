"""The ordered stop protocol for Agent Hijack (phase ``stop``)."""

from __future__ import annotations

from sase.agent.hijack._stop_orchestrator_common import (
    HijackStopResult,
    STOP_INTENT_SOURCE,
)
from sase.agent.hijack._stop_orchestrator_main import stop_agent_for_hijack

__all__ = [
    "HijackStopResult",
    "STOP_INTENT_SOURCE",
    "stop_agent_for_hijack",
]
