"""Action mixins for the ace TUI app."""

from .agent_workflow import AgentWorkflowMixin
from .agents import AgentMarkingMixin, AgentsMixin
from .agents_sync import AgentsSyncActionsMixin
from .axe import AxeMixin
from .artifacts import ArtifactsMixin
from .artifact_bugs import ArtifactBugsMixin
from .base import BaseActionsMixin
from .patch import PatchMixin
from .clipboard import ClipboardMixin
from .custom_modes import CustomModeMixin
from .event_handlers import EventHandlersMixin
from .hints import HintActionsMixin
from .lifecycle import LifecycleMixin
from .marking import MarkingMixin
from .navigation import NavigationMixin
from .post_update_toast import PostUpdateToastMixin
from .proposal_rebase import ProposalRebaseMixin
from .rename import RenameMixin
from .repro import ReproActionsMixin
from .startup import StartupMixin
from .status import StatusActionsMixin
from .sync import SyncMixin
from .task_actions import TaskActionsMixin
from .update_toast import UpdateToastMixin
from .workspace import WorkspaceActionsMixin

__all__ = [
    "AgentMarkingMixin",
    "AgentsMixin",
    "AgentsSyncActionsMixin",
    "AgentWorkflowMixin",
    "AxeMixin",
    "ArtifactsMixin",
    "ArtifactBugsMixin",
    "BaseActionsMixin",
    "PatchMixin",
    "ClipboardMixin",
    "CustomModeMixin",
    "EventHandlersMixin",
    "HintActionsMixin",
    "LifecycleMixin",
    "MarkingMixin",
    "NavigationMixin",
    "PostUpdateToastMixin",
    "ProposalRebaseMixin",
    "RenameMixin",
    "ReproActionsMixin",
    "StartupMixin",
    "StatusActionsMixin",
    "SyncMixin",
    "TaskActionsMixin",
    "UpdateToastMixin",
    "WorkspaceActionsMixin",
]
