"""In-memory AgentEnterTarget resolver for context-aware Enter.

This compatibility module keeps the historical ``_agent_enter_targets``
import path while the implementation lives in smaller,
responsibility-focused sibling modules.
"""

from __future__ import annotations

from ._agent_enter_index import (
    GateNotificationIndex,
    build_gate_notification_index,
    empty_gate_notification_index,
)
from ._agent_enter_labels import gate_target_label
from ._agent_enter_models import (
    CLAN_EMPTY_MESSAGE,
    NO_TARGET_EMPTY_MESSAGE,
    AgentEnterResolution,
    AgentEnterTarget,
    PatchSummary,
)
from ._agent_enter_resolver import (
    enter_action_label_for_targets,
    resolve_agent_enter_targets,
)

__all__ = [
    "AgentEnterResolution",
    "AgentEnterTarget",
    "CLAN_EMPTY_MESSAGE",
    "GateNotificationIndex",
    "NO_TARGET_EMPTY_MESSAGE",
    "PatchSummary",
    "build_gate_notification_index",
    "empty_gate_notification_index",
    "enter_action_label_for_targets",
    "gate_target_label",
    "resolve_agent_enter_targets",
]
