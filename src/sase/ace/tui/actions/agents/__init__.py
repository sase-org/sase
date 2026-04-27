"""Agent display mixin for the ace TUI app."""

from ._core import DISMISSABLE_STATUSES, AgentsMixinCore
from ._marking import AgentMarkingMixin
from ._snapshot_cache import AgentSnapshotCache, get_global_snapshot_cache

# AgentsMixin is the public API - it's just an alias for AgentsMixinCore
# (which already inherits from AgentKillingMixin and AgentRevivalMixin)
AgentsMixin = AgentsMixinCore

__all__ = [
    "AgentMarkingMixin",
    "AgentSnapshotCache",
    "AgentsMixin",
    "DISMISSABLE_STATUSES",
    "get_global_snapshot_cache",
]
