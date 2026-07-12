"""Widgets for the ace TUI."""

from .agent_detail import AgentDetail
from .agent_info_panel import AgentInfoPanel
from .agent_list import AgentList
from .agent_onboarding import AgentOnboarding
from .alias_overrides_indicator import AliasOverridesIndicator
from .file_panel import FileLineCountChanged
from .ancestors_children_panel import AncestorsChildrenPanel
from .axe_dashboard import AxeDashboard
from .axe_info_panel import AxeInfoPanel
from .axe_onboarding import AxeOnboarding
from .bgcmd_list import BgCmdList
from .changespec_detail import ChangeSpecDetail, SearchQueryPanel
from .changespec_info_panel import ChangeSpecInfoPanel
from .changespec_list import ChangeSpecList
from .changespec_onboarding import ChangeSpecOnboarding
from .hint_input_bar import HintInputBar
from .keybinding_footer import KeybindingFooter
from .tools_panel import AgentToolsPanel, ToolDetailLevel, ToolsVisibilityChanged
from .llm_override_indicator import LLMOverrideIndicator
from .notification_indicator import NotificationIndicator
from .prompt_input_bar import PromptInputBar
from .stashed_prompts_indicator import StashedPromptsIndicator
from .tab_bar import TabBar
from .tab_quickstart import TabQuickStart
from .task_indicator import TaskIndicator
from .updates_indicator import UpdatesAvailableIndicator
from .xprompt_arg_assist import (
    ActiveXPromptArgHint,
    XPromptAssistEntry,
    XPromptInputHint,
    append_input_hints,
    build_xprompt_assist_entries,
    colon_args_skeleton,
    input_hint_from_input_arg,
    input_label,
    named_args_skeleton,
    required_inputs,
    visible_inputs,
    xprompt_completion_skeleton,
)

__all__ = [
    "AgentDetail",
    "AgentInfoPanel",
    "AgentToolsPanel",
    "ToolDetailLevel",
    "AgentList",
    "AgentOnboarding",
    "AliasOverridesIndicator",
    "AncestorsChildrenPanel",
    "ActiveXPromptArgHint",
    "AxeDashboard",
    "AxeInfoPanel",
    "AxeOnboarding",
    "BgCmdList",
    "ChangeSpecDetail",
    "ChangeSpecInfoPanel",
    "ChangeSpecList",
    "ChangeSpecOnboarding",
    "FileLineCountChanged",
    "HintInputBar",
    "KeybindingFooter",
    "LLMOverrideIndicator",
    "NotificationIndicator",
    "PromptInputBar",
    "SearchQueryPanel",
    "StashedPromptsIndicator",
    "TabBar",
    "TabQuickStart",
    "TaskIndicator",
    "ToolsVisibilityChanged",
    "UpdatesAvailableIndicator",
    "XPromptAssistEntry",
    "XPromptInputHint",
    "append_input_hints",
    "build_xprompt_assist_entries",
    "colon_args_skeleton",
    "input_hint_from_input_arg",
    "input_label",
    "named_args_skeleton",
    "required_inputs",
    "visible_inputs",
    "xprompt_completion_skeleton",
]
