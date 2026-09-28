"""Shared helpers for explicit user-requested agent termination.

Termination has two stages. The *immediate* stage
(:func:`request_user_kill` with ``wait=False``) records the user's intent and
sends one SIGTERM; it is cheap enough for an interactive caller. The *durable*
stage (:func:`terminate_agent_processes`) finds the agent's whole process set,
escalates to SIGKILL, and verifies death; it must run somewhere that survives
the caller, such as the ``sase agent persist-cleanup`` proc.

This module is the seam callers import; the work lives in
``_user_kill_types`` (shared types and constants), ``_user_kill_intent``
(intent markers and recorded identity), ``_user_kill_tree`` (verified
tree termination), and ``_user_kill_request`` (interactive requests).
"""

from __future__ import annotations

from sase.agent._user_kill_intent import (
    ensure_user_kill_intent as ensure_user_kill_intent,
)
from sase.agent._user_kill_intent import (
    has_user_kill_intent as has_user_kill_intent,
)
from sase.agent._user_kill_intent import (
    live_verified_agent_pid as live_verified_agent_pid,
)
from sase.agent._user_kill_request import (
    escalate_user_kill_in_background as escalate_user_kill_in_background,
)
from sase.agent._user_kill_request import request_user_kill as request_user_kill
from sase.agent._user_kill_tree import (
    terminate_agent_processes as terminate_agent_processes,
)
from sase.agent._user_kill_types import (
    DEFAULT_TERMINATE_GRACE_SECONDS as DEFAULT_TERMINATE_GRACE_SECONDS,
)
from sase.agent._user_kill_types import (
    USER_KILL_INTENT_MARKER as USER_KILL_INTENT_MARKER,
)
from sase.agent._user_kill_types import AgentTerminationResult as AgentTerminationResult
from sase.agent._user_kill_types import Kill as Kill
from sase.agent._user_kill_types import Killpg as Killpg
from sase.agent._user_kill_types import RegistryFn as RegistryFn
from sase.agent._user_kill_types import SleepFn as SleepFn
from sase.agent._user_kill_types import TimeFn as TimeFn

__all__ = [
    "DEFAULT_TERMINATE_GRACE_SECONDS",
    "USER_KILL_INTENT_MARKER",
    "AgentTerminationResult",
    "ensure_user_kill_intent",
    "escalate_user_kill_in_background",
    "has_user_kill_intent",
    "live_verified_agent_pid",
    "request_user_kill",
    "terminate_agent_processes",
]
