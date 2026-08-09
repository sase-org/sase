"""Artifacts tab widgets."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .bugs import BugIssueList as BugIssueList

_LAZY_EXPORTS = {
    "ARTIFACTS_ACCENTS": (".types", "ARTIFACTS_ACCENTS"),
    "ARTIFACTS_PANE_IDS": (".types", "ARTIFACTS_PANE_IDS"),
    "ARTIFACTS_SUBTAB_ORDER": (".types", "ARTIFACTS_SUBTAB_ORDER"),
    "ArtifactEntryNavigator": (".entry_navigation", "ArtifactEntryNavigator"),
    "ArtifactEntryTarget": (".entry_navigation", "ArtifactEntryTarget"),
    "ArtifactPlaceholderPane": (".panes", "ArtifactPlaceholderPane"),
    "ArtifactsBeadsPane": (".beads_pane", "ArtifactsBeadsPane"),
    "ArtifactsBugsPane": (".bugs", "ArtifactsBugsPane"),
    "ArtifactsChatsPane": (".chats_pane", "ArtifactsChatsPane"),
    "ArtifactsFilesPane": (".files_pane", "ArtifactsFilesPane"),
    "ArtifactsFilesView": (".files_view", "ArtifactsFilesView"),
    "ArtifactsPaneKey": (".types", "ArtifactsPaneKey"),
    "ArtifactsPaneLifecycle": (".lifecycle", "ArtifactsPaneLifecycle"),
    "ArtifactsPlansPane": (".plans_pane", "ArtifactsPlansPane"),
    "ArtifactsPrsPane": (".panes", "ArtifactsPrsPane"),
    "ArtifactsSubTab": (".types", "ArtifactsSubTab"),
    "ArtifactsView": (".view", "ArtifactsView"),
    "BeadRow": (".beads_pane", "BeadRow"),
    "BugIssueList": (".bugs", "BugIssueList"),
    "BugLinkList": (".bugs", "BugLinkList"),
    "CommitsPane": (".commits", "CommitsPane"),
    "CommitsTimeline": (".commits", "CommitsTimeline"),
    "DEFAULT_ARTIFACTS_SUBTAB": (".types", "DEFAULT_ARTIFACTS_SUBTAB"),
    "DEFAULT_FILES_SUBTAB": (".types", "DEFAULT_FILES_SUBTAB"),
    "FILES_PANE_IDS": (".types", "FILES_PANE_IDS"),
    "FILES_SUBTAB_ORDER": (".types", "FILES_SUBTAB_ORDER"),
    "FilesSubTab": (".types", "FilesSubTab"),
    "PlanRow": (".plans_pane", "PlanRow"),
    "artifacts_pane_key": (".types", "artifacts_pane_key"),
}

__all__ = [
    "ARTIFACTS_ACCENTS",
    "ARTIFACTS_PANE_IDS",
    "ARTIFACTS_SUBTAB_ORDER",
    "FILES_PANE_IDS",
    "FILES_SUBTAB_ORDER",
    "ArtifactPlaceholderPane",
    "ArtifactEntryNavigator",
    "ArtifactEntryTarget",
    "ArtifactsBugsPane",
    "ArtifactsBeadsPane",
    "ArtifactsChatsPane",
    "ArtifactsFilesPane",
    "ArtifactsFilesView",
    "ArtifactsPaneKey",
    "ArtifactsPaneLifecycle",
    "ArtifactsPlansPane",
    "ArtifactsPrsPane",
    "ArtifactsSubTab",
    "ArtifactsView",
    "CommitsPane",
    "CommitsTimeline",
    "BugIssueList",
    "BugLinkList",
    "BeadRow",
    "DEFAULT_ARTIFACTS_SUBTAB",
    "DEFAULT_FILES_SUBTAB",
    "FilesSubTab",
    "PlanRow",
    "artifacts_pane_key",
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
