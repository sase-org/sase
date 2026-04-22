"""Agent display mixin for the ace TUI app."""

from ._core import DISMISSABLE_STATUSES, AgentsMixinCore
from ._marking import AgentMarkingMixin

# AgentsMixin is the public API - it's just an alias for AgentsMixinCore
# (which already inherits from AgentKillingMixin and AgentRevivalMixin)
AgentsMixin = AgentsMixinCore

__all__ = ["AgentMarkingMixin", "AgentsMixin", "DISMISSABLE_STATUSES"]
