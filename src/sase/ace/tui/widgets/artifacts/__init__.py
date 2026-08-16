"""Artifacts tab widgets."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_LAZY_EXPORTS = {
    "ARTIFACTS_ACCENTS": (".types", "ARTIFACTS_ACCENTS"),
    "ARTIFACTS_PANE_IDS": (".types", "ARTIFACTS_PANE_IDS"),
    "ARTIFACTS_SUBTAB_ORDER": (".types", "ARTIFACTS_SUBTAB_ORDER"),
    "FIXED_ARTIFACTS_SUBTAB_ORDER": (".types", "FIXED_ARTIFACTS_SUBTAB_ORDER"),
    "ArtifactsTabDescriptor": (".types", "ArtifactsTabDescriptor"),
    "ArtifactEntryNavigator": (".entry_navigation", "ArtifactEntryNavigator"),
    "ArtifactEntryTarget": (".entry_navigation", "ArtifactEntryTarget"),
    "ArtifactPlaceholderPane": (".panes", "ArtifactPlaceholderPane"),
    "ArtifactsDegradedPane": (".panes", "ArtifactsDegradedPane"),
    "ArtifactsBeadsPane": (".beads_pane", "ArtifactsBeadsPane"),
    "ArtifactsDocumentsPane": (".plans_pane", "ArtifactsDocumentsPane"),
    "ArtifactsFilesPane": (".files_pane", "ArtifactsFilesPane"),
    "ArtifactsPaneKey": (".types", "ArtifactsPaneKey"),
    "ArtifactsPaneLifecycle": (".lifecycle", "ArtifactsPaneLifecycle"),
    "ArtifactsSnapshotPane": (".snapshot_pane", "ArtifactsSnapshotPane"),
    "ArtifactsPlansPane": (".plans_pane", "ArtifactsPlansPane"),
    "ArtifactsPatchesPane": (".panes", "ArtifactsPatchesPane"),
    "ArtifactsSubTab": (".types", "ArtifactsSubTab"),
    "ArtifactsView": (".view", "ArtifactsView"),
    "BeadRow": (".beads_pane", "BeadRow"),
    "CommitsPane": (".commits", "CommitsPane"),
    "CommitsTimeline": (".commits", "CommitsTimeline"),
    "DEFAULT_ARTIFACTS_SUBTAB": (".types", "DEFAULT_ARTIFACTS_SUBTAB"),
    "DEFAULT_FILES_SUBTAB": (".types", "DEFAULT_FILES_SUBTAB"),
    "FILES_PANE_IDS": (".types", "FILES_PANE_IDS"),
    "FILES_SUBTAB_ORDER": (".types", "FILES_SUBTAB_ORDER"),
    "FilesSubTab": (".types", "FilesSubTab"),
    "PlanRow": (".plans_pane", "PlanRow"),
    "PatchFilterBar": (".patch_filter_bar", "PatchFilterBar"),
    "RelationEntryFact": (".relation_panel", "RelationEntryFact"),
    "RelationKeymap": (".relation_panel", "RelationKeymap"),
    "RelationPanel": (".relation_panel", "RelationPanel"),
    "RelationPanelHostMixin": (".relation_panel", "RelationPanelHostMixin"),
    "artifacts_pane_key": (".types", "artifacts_pane_key"),
    "artifacts_subtab_order": (".types", "artifacts_subtab_order"),
    "descriptor_for_artifacts_subtab": (".types", "descriptor_for_artifacts_subtab"),
    "document_provider_roots": (".types", "document_provider_roots"),
    "normalize_artifacts_subtab": (".types", "normalize_artifacts_subtab"),
    "reset_artifacts_subtabs_cache": (".types", "reset_artifacts_subtabs_cache"),
    "resolve_artifacts_subtabs": (".types", "resolve_artifacts_subtabs"),
}

__all__ = [
    "ARTIFACTS_ACCENTS",
    "ARTIFACTS_PANE_IDS",
    "ARTIFACTS_SUBTAB_ORDER",
    "FILES_PANE_IDS",
    "FILES_SUBTAB_ORDER",
    "FIXED_ARTIFACTS_SUBTAB_ORDER",
    "ArtifactPlaceholderPane",
    "ArtifactsDegradedPane",
    "ArtifactEntryNavigator",
    "ArtifactEntryTarget",
    "ArtifactsBeadsPane",
    "ArtifactsDocumentsPane",
    "ArtifactsFilesPane",
    "ArtifactsPaneKey",
    "ArtifactsPaneLifecycle",
    "ArtifactsSnapshotPane",
    "ArtifactsPlansPane",
    "ArtifactsPatchesPane",
    "ArtifactsSubTab",
    "ArtifactsTabDescriptor",
    "ArtifactsView",
    "CommitsPane",
    "CommitsTimeline",
    "BeadRow",
    "DEFAULT_ARTIFACTS_SUBTAB",
    "DEFAULT_FILES_SUBTAB",
    "FilesSubTab",
    "PlanRow",
    "PatchFilterBar",
    "RelationEntryFact",
    "RelationKeymap",
    "RelationPanel",
    "RelationPanelHostMixin",
    "artifacts_pane_key",
    "artifacts_subtab_order",
    "descriptor_for_artifacts_subtab",
    "document_provider_roots",
    "normalize_artifacts_subtab",
    "reset_artifacts_subtabs_cache",
    "resolve_artifacts_subtabs",
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
