"""Widgets for the ace TUI."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS = {
    "ActiveXPromptArgHint": (".xprompt_arg_assist", "ActiveXPromptArgHint"),
    "AgentDetail": (".agent_detail", "AgentDetail"),
    "AgentInfoPanel": (".agent_info_panel", "AgentInfoPanel"),
    "AgentList": (".agent_list", "AgentList"),
    "AgentOnboarding": (".agent_onboarding", "AgentOnboarding"),
    "AgentToolsPanel": (".tools_panel", "AgentToolsPanel"),
    "AgentsSyncIndicator": (".agents_sync_indicator", "AgentsSyncIndicator"),
    "AliasOverridesIndicator": (
        ".alias_overrides_indicator",
        "AliasOverridesIndicator",
    ),
    "AncestorsChildrenPanel": (
        ".ancestors_children_panel",
        "AncestorsChildrenPanel",
    ),
    "ARTIFACTS_SUBTAB_ORDER": (".artifacts.types", "ARTIFACTS_SUBTAB_ORDER"),
    "ArtifactPlaceholderPane": (".artifacts.panes", "ArtifactPlaceholderPane"),
    "ArtifactsBeadsPane": (".artifacts.beads_pane", "ArtifactsBeadsPane"),
    "ArtifactsDocumentsPane": (".artifacts.plans_pane", "ArtifactsDocumentsPane"),
    "ArtifactsFilesPane": (".artifacts.files_pane", "ArtifactsFilesPane"),
    "ArtifactsPlansPane": (".artifacts.plans_pane", "ArtifactsPlansPane"),
    "ArtifactsPatchesPane": (".artifacts.panes", "ArtifactsPatchesPane"),
    "ArtifactsSubTab": (".artifacts.types", "ArtifactsSubTab"),
    "ArtifactsView": (".artifacts.view", "ArtifactsView"),
    "AxeDashboard": (".axe_dashboard", "AxeDashboard"),
    "AxeDescriptionBanner": (".axe_description_banner", "AxeDescriptionBanner"),
    "AxeInfoPanel": (".axe_info_panel", "AxeInfoPanel"),
    "AxeOnboarding": (".axe_onboarding", "AxeOnboarding"),
    "BgCmdList": (".bgcmd_list", "BgCmdList"),
    "ChangeSpecDetail": (  # legacy compatibility alias
        ".changespec_detail",
        # legacy compatibility alias
        "ChangeSpecDetail",
    ),
    "ChangeSpecInfoPanel": (  # legacy compatibility alias
        ".changespec_info_panel",
        # legacy compatibility alias
        "ChangeSpecInfoPanel",
    ),
    "ChangeSpecList": (  # legacy compatibility alias
        ".changespec_list",
        # legacy compatibility alias
        "ChangeSpecList",
    ),
    "ChangeSpecOnboarding": (  # legacy compatibility alias
        ".changespec_onboarding",
        # legacy compatibility alias
        "ChangeSpecOnboarding",
    ),
    "CommitsPane": (".artifacts.commits", "CommitsPane"),
    "CommitsTimeline": (".artifacts.commits", "CommitsTimeline"),
    "FileLineCountChanged": (".file_panel", "FileLineCountChanged"),
    "FilesSubTab": (".artifacts.types", "FilesSubTab"),
    "HintInputBar": (".hint_input_bar", "HintInputBar"),
    "KeybindingFooter": (".keybinding_footer", "KeybindingFooter"),
    "LLMOverrideIndicator": (".llm_override_indicator", "LLMOverrideIndicator"),
    "NotificationIndicator": (".notification_indicator", "NotificationIndicator"),
    "PatchDetail": (".patch_detail", "PatchDetail"),
    "PatchInfoPanel": (".patch_info_panel", "PatchInfoPanel"),
    "PatchList": (".patch_list", "PatchList"),
    "PatchOnboarding": (".patch_onboarding", "PatchOnboarding"),
    "ProviderDisablesIndicator": (
        ".provider_disables_indicator",
        "ProviderDisablesIndicator",
    ),
    "PromptInputBar": (".prompt_input_bar", "PromptInputBar"),
    "SearchQueryPanel": (".patch_detail", "SearchQueryPanel"),
    "StashedPromptsIndicator": (
        ".stashed_prompts_indicator",
        "StashedPromptsIndicator",
    ),
    "TabBar": (".tab_bar", "TabBar"),
    "TabQuickStart": (".tab_quickstart", "TabQuickStart"),
    "ProcIndicator": (".proc_indicator", "ProcIndicator"),
    "ToolDetailLevel": (".tools_panel", "ToolDetailLevel"),
    "ToolsVisibilityChanged": (".tools_panel", "ToolsVisibilityChanged"),
    "UpdatesAvailableIndicator": (
        ".updates_indicator",
        "UpdatesAvailableIndicator",
    ),
    "XPromptAssistEntry": (".xprompt_arg_assist", "XPromptAssistEntry"),
    "XPromptInputHint": (".xprompt_arg_assist", "XPromptInputHint"),
    "append_input_hints": (".xprompt_arg_assist", "append_input_hints"),
    "build_xprompt_assist_entries": (
        ".xprompt_arg_assist",
        "build_xprompt_assist_entries",
    ),
    "colon_args_skeleton": (".xprompt_arg_assist", "colon_args_skeleton"),
    "input_hint_from_input_arg": (".xprompt_arg_assist", "input_hint_from_input_arg"),
    "input_label": (".xprompt_arg_assist", "input_label"),
    "named_args_skeleton": (".xprompt_arg_assist", "named_args_skeleton"),
    "required_inputs": (".xprompt_arg_assist", "required_inputs"),
    "visible_inputs": (".xprompt_arg_assist", "visible_inputs"),
    "xprompt_completion_skeleton": (
        ".xprompt_arg_assist",
        "xprompt_completion_skeleton",
    ),
}

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
    "ArtifactsDocumentsPane",
    "ArtifactsFilesPane",
    "ArtifactsPlansPane",
    "ArtifactsPatchesPane",
    "ArtifactsSubTab",
    "FilesSubTab",
    "ArtifactsView",
    "CommitsPane",
    "CommitsTimeline",
    "BgCmdList",
    "PatchDetail",
    "PatchInfoPanel",
    "PatchList",
    "PatchOnboarding",
    "ProviderDisablesIndicator",
    "ChangeSpecDetail",  # legacy compatibility alias
    "ChangeSpecInfoPanel",  # legacy compatibility alias
    "ChangeSpecList",  # legacy compatibility alias
    "ChangeSpecOnboarding",  # legacy compatibility alias
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
    "ProcIndicator",
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


def __getattr__(name: str) -> Any:
    try:
        module_name, attr = _LAZY_EXPORTS[name]
    except KeyError as error:
        raise AttributeError(
            f"module {__name__!r} has no attribute {name!r}"
        ) from error
    module = import_module(module_name, __name__)
    value = getattr(module, attr)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted({*globals(), *__all__})


# PEP 562 entry points are called by Python, not by normal in-file code.
_PEP562_HOOKS = (__getattr__, __dir__)
