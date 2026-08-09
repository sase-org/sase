"""Widgets for the ace TUI."""

from .agent_detail import AgentDetail
from .agent_info_panel import AgentInfoPanel
from .agent_list import AgentList
from .agent_onboarding import AgentOnboarding
from .agents_sync_indicator import AgentsSyncIndicator
from .alias_overrides_indicator import AliasOverridesIndicator
from .file_panel import FileLineCountChanged
from .ancestors_children_panel import AncestorsChildrenPanel
from .axe_dashboard import AxeDashboard
from .axe_description_banner import AxeDescriptionBanner
from .axe_info_panel import AxeInfoPanel
from .axe_onboarding import AxeOnboarding
from .artifacts import (
    ARTIFACTS_SUBTAB_ORDER,
    ArtifactPlaceholderPane,
    ArtifactsBeadsPane,
    ArtifactsChatsPane,
    ArtifactsFilesPane,
    ArtifactsFilesView,
    ArtifactsPlansPane,
    ArtifactsBugsPane,
    ArtifactsPrsPane,
    ArtifactsSubTab,
    FilesSubTab,
    ArtifactsView,
    CommitsPane,
    CommitsTimeline,
)
from .bgcmd_list import BgCmdList
from .changespec_detail import ChangeSpecDetail
from .patch_detail import PatchDetail, SearchQueryPanel
from .patch_info_panel import PatchInfoPanel
from .patch_list import PatchList
from .patch_onboarding import PatchOnboarding
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

ChangeSpecInfoPanel = PatchInfoPanel
ChangeSpecList = PatchList
ChangeSpecOnboarding = PatchOnboarding

__all__ = [
    "AgentDetail",
    "AgentInfoPanel",
    "AgentToolsPanel",
    "ToolDetailLevel",
    "AgentList",
    "AgentOnboarding",
    "AgentsSyncIndicator",
    "AliasOverridesIndicator",
    "AncestorsChildrenPanel",
    "ActiveXPromptArgHint",
    "AxeDashboard",
    "AxeDescriptionBanner",
    "AxeInfoPanel",
    "AxeOnboarding",
    "ARTIFACTS_SUBTAB_ORDER",
    "ArtifactPlaceholderPane",
    "ArtifactsBeadsPane",
    "ArtifactsChatsPane",
    "ArtifactsFilesPane",
    "ArtifactsFilesView",
    "ArtifactsPlansPane",
    "ArtifactsBugsPane",
    "ArtifactsPrsPane",
    "ArtifactsSubTab",
    "FilesSubTab",
    "ArtifactsView",
    "CommitsPane",
    "CommitsTimeline",
    "BgCmdList",
    "ChangeSpecDetail",
    "ChangeSpecInfoPanel",
    "ChangeSpecList",
    "ChangeSpecOnboarding",
    "PatchDetail",
    "PatchInfoPanel",
    "PatchList",
    "PatchOnboarding",
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
