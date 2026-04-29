"""Widgets for the ace TUI."""

from .agent_detail import AgentDetail
from .agent_info_panel import AgentInfoPanel
from .agent_list import AgentList
from .file_panel import FileTrimChanged
from .ancestors_children_panel import AncestorsChildrenPanel
from .axe_dashboard import AxeDashboard
from .axe_info_panel import AxeInfoPanel
from .backend_indicator import BackendIndicator
from .bgcmd_list import BgCmdList
from .changespec_detail import ChangeSpecDetail, SearchQueryPanel
from .changespec_info_panel import ChangeSpecInfoPanel
from .changespec_list import ChangeSpecList
from .hint_input_bar import HintInputBar
from .keybinding_footer import KeybindingFooter
from .thinking_panel import AgentThinkingPanel, ThinkingVisibilityChanged
from .inactive_indicator import InactiveIndicator
from .llm_override_indicator import LLMOverrideIndicator
from .notification_indicator import NotificationIndicator
from .prompt_input_bar import PromptInputBar
from .tab_bar import TabBar
from .task_indicator import TaskIndicator

__all__ = [
    "AgentDetail",
    "AgentInfoPanel",
    "AgentThinkingPanel",
    "AgentList",
    "AncestorsChildrenPanel",
    "AxeDashboard",
    "AxeInfoPanel",
    "BackendIndicator",
    "BgCmdList",
    "ChangeSpecDetail",
    "ChangeSpecInfoPanel",
    "ChangeSpecList",
    "FileTrimChanged",
    "HintInputBar",
    "InactiveIndicator",
    "KeybindingFooter",
    "LLMOverrideIndicator",
    "NotificationIndicator",
    "PromptInputBar",
    "SearchQueryPanel",
    "TabBar",
    "TaskIndicator",
    "ThinkingVisibilityChanged",
]
