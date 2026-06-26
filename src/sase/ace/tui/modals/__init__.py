"""Modal dialogs for the ace TUI."""

from .add_property_modal import AddableProperty, AddPropertyModal
from .agent_name_modal import AgentNameModal
from .agent_sibling_modal import AgentSiblingChoice, AgentSiblingModal
from .agent_workspace_tmux_modal import (
    AgentWorkspaceTmuxChoice,
    AgentWorkspaceTmuxModal,
    build_agent_workspace_tmux_choices,
)
from .agent_artifacts_modal import (
    AgentArtifactSelectionModal,
    AgentArtifactSelectionResult,
)
from .agent_cleanup_modal import (
    AgentCleanupAction,
    AgentCleanupCustomModal,
    AgentCleanupCustomResult,
    AgentCleanupModal,
    AgentCleanupPanelState,
    AgentCleanupResult,
    AgentCleanupTagModal,
    AgentCleanupTagResult,
)
from .command_history_modal import CommandHistoryModal
from .command_input_modal import CommandInputModal
from .command_palette_modal import CommandPaletteModal
from .confirm_action_modal import ConfirmActionModal
from .confirm_delete_modal import ConfirmDeleteModal
from .confirm_kill_modal import (
    ConfirmDismissAllModal,
    ConfirmKillAllModal,
    ConfirmKillModal,
)
from .confirm_rerun_modal import ConfirmRerunModal
from .confirm_revert_agent_modal import ConfirmRevertAgentModal
from .help_modal import HelpModal, TabName
from .hook_history_modal import HookHistoryAction, HookHistoryModal, HookHistoryResult
from .input_item_modal import InputItemModal
from .jump_all_modal import JumpAllModal, JumpAllResult
from .notification_modal import NotificationModal
from .parent_select_modal import ParentSelectModal
from .process_select_modal import ProcessSelection, ProcessSelectModal
from .project_management_modal import ProjectManagementModal
from .project_alias_editor_modal import ProjectAliasEditorModal
from .project_select_modal import ProjectSelectModal, ProjectSelectResult, SelectionItem
from .prompt_history_modal import (
    PromptHistoryAction,
    PromptHistoryModal,
    PromptHistoryResult,
)
from .prompt_submit_choice_modal import PromptSubmitChoice, PromptSubmitChoiceModal
from .query_edit_modal import QueryEditModal
from .quit_confirm_modal import QuitConfirmModal
from .stashed_prompts_modal import StashRestoreResult, StashedPromptsModal
from .update_pinned_stash_modal import UpdatePinnedStashModal
from .recursive_finder_modal import RecursiveFileFinderModal
from .rename_cl_modal import RenameCLModal
from .save_agent_group_modal import SaveAgentGroupModal, SaveAgentGroupResult
from .wait_modal import WaitAgentCandidate, WaitModal, WaitModalResult
from .revive_agent_modal import DismissedAgentSelectModal
from .saved_agent_group_revival_modal import (
    SavedAgentGroupRevivalModal,
    SavedAgentGroupRevivalResult,
)
from .snooze_duration_modal import SnoozeDurationModal
from .runners_modal import (
    BackgroundTaskEntry,
    RunnerJumpTarget,
    RunnersModal,
    get_runner_count,
)
from .status_modal import StatusModal
from .agent_tag_modal import AgentTagModal, AgentTagModalResult
from .tag_input_modal import TagInputModal
from .approve_options_modal import (
    ApproveOptionsEditPrompt,
    ApproveOptionsModal,
    ApproveOptionsResult,
    CustomApprovalEditPrompt,
    CustomApprovalModal,
    CustomApprovalResult,
)
from .auto_approve_modal import AutoApproveChoice, AutoApproveModal
from .custom_model_input_modal import CustomModelInputModal
from .model_picker_modal import ModelPickerModal
from .plan_approval_modal import PlanApprovalModal, PlanApprovalResult
from .user_question_modal import UserQuestionModal, UserQuestionResult
from .workflow_hitl_modal import WorkflowHITLInput, WorkflowHITLModal
from .workflow_select_modal import WorkflowSelectModal
from .workspace_input_modal import WorkspaceInputModal
from .activity_modal import ActivityModal
from .task_queue_modal import TaskQueueModal
from .zoom_panel_modal import ZoomPanelModal, ZoomPanelSeed, ZoomPanelTarget
from .temporary_llm_override_modal import (
    TemporaryLLMOverrideModal,
    TemporaryOverrideResult,
)
from .mentor_profile_select_modal import MentorProfileSelectModal
from .mentor_review_models import (
    MentorApplyResult,
    MentorInfo,
    MentorKillResult,
    MentorReviewData,
    MentorRunResult,
    build_mentor_review_data,
)
from .mentor_review_modal import MentorReviewModal
from .add_xprompt_modal import AddXPromptModal
from .agent_run_log_modal import AgentRunLogModal
from .log_modal import LogModal
from .input_collection_modal import InputCollectionModal
from .config_center_modal import ConfigCenterModal
from .plugin_action_confirm_modal import (
    PluginActionConfirmModal,
    PluginActionConfirmResult,
    PluginActionVariant,
)
from .plugins_browser_pane import PluginsBrowserPane
from .xprompt_item_modal import XPromptItemModal
from .xprompt_config_modal import XPromptConfigEntry, XPromptConfigEntryModal
from .xprompt_filename_modal import XPromptFilenameModal
from .xprompt_location_modal import XPromptLocation, XPromptLocationModal
from .xprompt_name_modal import XPromptNameModal
from .xprompt_save_target_modal import XPromptSaveTarget, XPromptSaveTargetModal
from .xprompt_select_modal import XPromptSelection, XPromptSelectModal

__all__ = [
    "ActivityModal",
    "AddableProperty",
    "AddPropertyModal",
    "InputItemModal",
    "MentorApplyResult",
    "MentorInfo",
    "MentorKillResult",
    "MentorProfileSelectModal",
    "MentorReviewData",
    "MentorReviewModal",
    "MentorRunResult",
    "build_mentor_review_data",
    "AddXPromptModal",
    "ApproveOptionsEditPrompt",
    "ApproveOptionsModal",
    "ApproveOptionsResult",
    "AutoApproveChoice",
    "AutoApproveModal",
    "CustomApprovalEditPrompt",
    "CustomApprovalModal",
    "CustomApprovalResult",
    "AgentNameModal",
    "AgentSiblingChoice",
    "AgentSiblingModal",
    "AgentWorkspaceTmuxChoice",
    "AgentWorkspaceTmuxModal",
    "build_agent_workspace_tmux_choices",
    "AgentArtifactSelectionModal",
    "AgentArtifactSelectionResult",
    "AgentCleanupAction",
    "AgentCleanupCustomModal",
    "AgentCleanupCustomResult",
    "AgentCleanupModal",
    "AgentCleanupPanelState",
    "AgentCleanupResult",
    "AgentCleanupTagModal",
    "AgentCleanupTagResult",
    "AgentRunLogModal",
    "LogModal",
    "AgentTagModal",
    "AgentTagModalResult",
    "CommandHistoryModal",
    "ConfirmActionModal",
    "CommandInputModal",
    "CommandPaletteModal",
    "CustomModelInputModal",
    "ConfirmDeleteModal",
    "ConfirmDismissAllModal",
    "ConfirmKillAllModal",
    "ConfirmKillModal",
    "ConfirmRerunModal",
    "ConfirmRevertAgentModal",
    "DismissedAgentSelectModal",
    "HelpModal",
    "HookHistoryAction",
    "HookHistoryModal",
    "HookHistoryResult",
    "JumpAllModal",
    "JumpAllResult",
    "RecursiveFileFinderModal",
    "ModelPickerModal",
    "NotificationModal",
    "ParentSelectModal",
    "PlanApprovalModal",
    "PlanApprovalResult",
    "ProcessSelectModal",
    "ProcessSelection",
    "ProjectAliasEditorModal",
    "ProjectManagementModal",
    "ProjectSelectModal",
    "ProjectSelectResult",
    "PromptHistoryAction",
    "PromptHistoryModal",
    "PromptHistoryResult",
    "PromptSubmitChoice",
    "PromptSubmitChoiceModal",
    "QueryEditModal",
    "QuitConfirmModal",
    "RenameCLModal",
    "StashRestoreResult",
    "StashedPromptsModal",
    "SavedAgentGroupRevivalModal",
    "SavedAgentGroupRevivalResult",
    "SaveAgentGroupModal",
    "SaveAgentGroupResult",
    "BackgroundTaskEntry",
    "RunnerJumpTarget",
    "RunnersModal",
    "SnoozeDurationModal",
    "get_runner_count",
    "SelectionItem",
    "StatusModal",
    "TabName",
    "TagInputModal",
    "TaskQueueModal",
    "TemporaryLLMOverrideModal",
    "TemporaryOverrideResult",
    "UpdatePinnedStashModal",
    "WaitModal",
    "WaitAgentCandidate",
    "WaitModalResult",
    "UserQuestionModal",
    "UserQuestionResult",
    "InputCollectionModal",
    "ConfigCenterModal",
    "PluginActionConfirmModal",
    "PluginActionConfirmResult",
    "PluginActionVariant",
    "PluginsBrowserPane",
    "XPromptItemModal",
    "XPromptConfigEntry",
    "XPromptConfigEntryModal",
    "XPromptFilenameModal",
    "XPromptLocation",
    "XPromptLocationModal",
    "XPromptNameModal",
    "XPromptSaveTarget",
    "XPromptSaveTargetModal",
    "XPromptSelection",
    "XPromptSelectModal",
    "WorkflowHITLInput",
    "WorkflowHITLModal",
    "WorkflowSelectModal",
    "WorkspaceInputModal",
    "ZoomPanelModal",
    "ZoomPanelSeed",
    "ZoomPanelTarget",
]
