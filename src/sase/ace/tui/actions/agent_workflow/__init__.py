"""Custom agent workflow mixin for the ace TUI app."""

from ._agent_launch import AgentLaunchMixin
from ._editor import EditorMixin
from ._entry_points import EntryPointsMixin
from ._leader_mode import LeaderModeMixin
from ._mentor_review import MentorReviewMixin
from ._prompt_bar import PromptBarMixin


class AgentWorkflowMixin(
    EntryPointsMixin,
    LeaderModeMixin,
    MentorReviewMixin,
    PromptBarMixin,
    EditorMixin,
    AgentLaunchMixin,
):
    """Mixin providing custom agent workflow actions."""

    pass
