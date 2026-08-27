"""Action mixins for the ace TUI app."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS = {
    "AgentMarkingMixin": (".agents", "AgentMarkingMixin"),
    "AgentsMixin": (".agents", "AgentsMixin"),
    "AgentsSyncActionsMixin": (".agents_sync", "AgentsSyncActionsMixin"),
    "AgentWorkflowMixin": (".agent_workflow", "AgentWorkflowMixin"),
    "ArtifactsMixin": (".artifacts", "ArtifactsMixin"),
    "AxeMixin": (".axe", "AxeMixin"),
    "BaseActionsMixin": (".base", "BaseActionsMixin"),
    "ClipboardMixin": (".clipboard", "ClipboardMixin"),
    "CustomModeMixin": (".custom_modes", "CustomModeMixin"),
    "EventHandlersMixin": (".event_handlers", "EventHandlersMixin"),
    "HintActionsMixin": (".hints", "HintActionsMixin"),
    "LifecycleMixin": (".lifecycle", "LifecycleMixin"),
    "LinkFollowMixin": (".link_follow", "LinkFollowMixin"),
    "LinkSubjectMixin": (".link_subject", "LinkSubjectMixin"),
    "MarkingMixin": (".marking", "MarkingMixin"),
    "NavigationMixin": (".navigation", "NavigationMixin"),
    "PatchMixin": (".patch", "PatchMixin"),
    "PostUpdateToastMixin": (".post_update_toast", "PostUpdateToastMixin"),
    "ProposalRebaseMixin": (".proposal_rebase", "ProposalRebaseMixin"),
    "RenameMixin": (".rename", "RenameMixin"),
    "ReproActionsMixin": (".repro", "ReproActionsMixin"),
    "StartupMixin": (".startup", "StartupMixin"),
    "StatusActionsMixin": (".status", "StatusActionsMixin"),
    "SyncMixin": (".sync", "SyncMixin"),
    "ProcActionsMixin": (".proc_actions", "ProcActionsMixin"),
    "UpdateRunActionsMixin": (".update_run", "UpdateRunActionsMixin"),
    "UpdateToastMixin": (".update_toast", "UpdateToastMixin"),
    "WorkspaceActionsMixin": (".workspace", "WorkspaceActionsMixin"),
}

__all__ = [
    "AgentMarkingMixin",
    "AgentsMixin",
    "AgentsSyncActionsMixin",
    "AgentWorkflowMixin",
    "AxeMixin",
    "ArtifactsMixin",
    "BaseActionsMixin",
    "PatchMixin",
    "ClipboardMixin",
    "CustomModeMixin",
    "EventHandlersMixin",
    "HintActionsMixin",
    "LifecycleMixin",
    "LinkFollowMixin",
    "LinkSubjectMixin",
    "MarkingMixin",
    "NavigationMixin",
    "PostUpdateToastMixin",
    "ProposalRebaseMixin",
    "RenameMixin",
    "ReproActionsMixin",
    "StartupMixin",
    "StatusActionsMixin",
    "SyncMixin",
    "ProcActionsMixin",
    "UpdateRunActionsMixin",
    "UpdateToastMixin",
    "WorkspaceActionsMixin",
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
