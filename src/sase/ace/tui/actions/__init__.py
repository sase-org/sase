"""Action mixins for the ace TUI app."""

from .agent_workflow import AgentWorkflowMixin
from .agents import AgentMarkingMixin, AgentsMixin
from .artifacts import ArtifactsMixin
from .axe import AxeMixin
from .base import BaseActionsMixin
from .changespec import ChangeSpecMixin
from .clipboard import ClipboardMixin
from .custom_modes import CustomModeMixin
from .event_handlers import EventHandlersMixin
from .hints import HintActionsMixin
from .lifecycle import LifecycleMixin
from .marking import MarkingMixin
from .navigation import NavigationMixin
from .proposal_rebase import ProposalRebaseMixin
from .rename import RenameMixin
from .startup import StartupMixin
from .status import StatusActionsMixin
from .sync import SyncMixin
from .task_actions import TaskActionsMixin
from .workspace import WorkspaceActionsMixin

__all__ = [
    "AgentMarkingMixin",
    "AgentsMixin",
    "AgentWorkflowMixin",
    "ArtifactsMixin",
    "AxeMixin",
    "BaseActionsMixin",
    "ChangeSpecMixin",
    "ClipboardMixin",
    "CustomModeMixin",
    "EventHandlersMixin",
    "HintActionsMixin",
    "LifecycleMixin",
    "MarkingMixin",
    "NavigationMixin",
    "ProposalRebaseMixin",
    "RenameMixin",
    "StartupMixin",
    "StatusActionsMixin",
    "SyncMixin",
    "TaskActionsMixin",
    "WorkspaceActionsMixin",
]
