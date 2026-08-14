"""Provider-aware Artifacts tab registry.

This module intentionally has no Textual widget dependencies.  It is used by
rendering, keybindings, action availability, tests, and a few widget-free
callers that need to switch Artifacts panes without importing the widget tree.

It is the public face of three private siblings: ``_artifact_tab_model``
(identifiers, constants, records), ``_artifact_tab_discovery`` (walking projects
for document providers), and ``_artifact_tab_descriptors`` (turning that into
rendered panes).  Import from here, not from them.
"""

from __future__ import annotations

from typing import Any

from sase.sidecar_ref_config import DEFAULT_DOCUMENT_TAB_ICON

from ._artifact_tab_descriptors import (
    assign_artifacts_digit_shortcuts,
    fixed_descriptor,
    provider_descriptors,
)
from ._artifact_tab_discovery import (
    load_project_provider_records,
    provider_source_token,
)
from ._artifact_tab_model import (
    ARTIFACTS_ACCENTS,
    ARTIFACTS_ICONS,
    DEFAULT_ARTIFACTS_SUBTAB,
    EXTERNAL_ACCENT,
    FIXED_ARTIFACTS_PANE_IDS,
    FIXED_ARTIFACTS_SUBTAB_ORDER,
    LEGACY_ARTIFACTS_SUBTABS,
    ArtifactsPaneKey,
    ArtifactsSubTab,
    ArtifactsTabDescriptor,
    DocumentProviderProjectRoot,
    FilesSubTab,
)


_ARTIFACTS_TAB_CACHE: tuple[object, tuple[ArtifactsTabDescriptor, ...]] | None = None
_PROVIDER_ROOTS_CACHE: dict[
    tuple[str, str | None], tuple[DocumentProviderProjectRoot, ...]
] = {}


def reset_artifacts_subtabs_cache() -> None:
    """Clear cached provider descriptors and document roots."""

    global _ARTIFACTS_TAB_CACHE
    _ARTIFACTS_TAB_CACHE = None
    _PROVIDER_ROOTS_CACHE.clear()


def resolve_artifacts_subtabs() -> tuple[ArtifactsTabDescriptor, ...]:
    """Return fixed and configured provider tabs in visual order."""

    global _ARTIFACTS_TAB_CACHE
    token = provider_source_token()
    if (
        token is not None
        and _ARTIFACTS_TAB_CACHE is not None
        and _ARTIFACTS_TAB_CACHE[0] == token
    ):
        return _ARTIFACTS_TAB_CACHE[1]

    loaded = load_project_provider_records(project=None)
    providers = provider_descriptors(loaded.records, loaded.issues)
    descriptors = assign_artifacts_digit_shortcuts(
        (
            fixed_descriptor("stitches"),
            fixed_descriptor("patches"),
            fixed_descriptor("beads"),
            *providers,
            fixed_descriptor("files"),
        )
    )
    if token is not None:
        _ARTIFACTS_TAB_CACHE = (token, descriptors)
    return descriptors


def artifacts_subtab_order() -> tuple[ArtifactsSubTab, ...]:
    return tuple(descriptor.id for descriptor in resolve_artifacts_subtabs())


def descriptor_for_artifacts_subtab(
    subtab: str,
) -> ArtifactsTabDescriptor | None:
    normalized = normalize_artifacts_subtab(subtab)
    return next(
        (
            descriptor
            for descriptor in resolve_artifacts_subtabs()
            if descriptor.id == normalized
        ),
        None,
    )


def document_provider_roots(
    provider_kind: str,
    *,
    project: str | None,
) -> tuple[DocumentProviderProjectRoot, ...]:
    """Return roots for *provider_kind* in enabled/current project scope."""

    key = (provider_kind, project)
    cached = _PROVIDER_ROOTS_CACHE.get(key)
    if cached is not None:
        return cached
    roots = tuple(
        DocumentProviderProjectRoot(
            project=record.project,
            display_name=record.display_name,
            workspace_dir=record.workspace_dir,
            role=record.role,
            root=record.root,
            policy=record.policy,
        )
        for record in load_project_provider_records(project=project).records
        if record.policy.ref_kind == provider_kind
    )
    _PROVIDER_ROOTS_CACHE[key] = roots
    return roots


def normalize_artifacts_subtab(value: str) -> ArtifactsSubTab:
    """Map a persisted or legacy sub-tab identifier to a configured pane id."""

    canonical = LEGACY_ARTIFACTS_SUBTABS.get(value, value)
    configured = {descriptor.id for descriptor in resolve_artifacts_subtabs()}
    if canonical in configured:
        return canonical
    return DEFAULT_ARTIFACTS_SUBTAB


def artifacts_pane_key(
    subtab: ArtifactsSubTab,
    files_subtab: FilesSubTab | None = None,
) -> ArtifactsPaneKey:
    """Return the visible Artifacts pane id.

    ``files_subtab`` is accepted only for compatibility with older callers. The
    nested Files panes were flattened; old ``plans``/``other`` values are
    normalized through :func:`normalize_artifacts_subtab`.
    """

    if subtab == "files" and files_subtab:
        legacy = LEGACY_ARTIFACTS_SUBTABS.get(files_subtab)
        if legacy is not None:
            return normalize_artifacts_subtab(legacy)
    return normalize_artifacts_subtab(subtab)


def switch_to_artifacts_subtab(app: Any, subtab: ArtifactsSubTab) -> None:
    """Show the Artifacts tab with *subtab* as its active pane."""

    from .tab_order import ARTIFACTS_TAB

    app.current_artifacts_subtab = normalize_artifacts_subtab(subtab)
    app.current_tab = ARTIFACTS_TAB


# Compatibility constants for existing imports. These intentionally avoid
# provider discovery at import time; runtime-sensitive callers must use the
# resolver functions above.
ARTIFACTS_SUBTAB_ORDER: tuple[ArtifactsSubTab, ...] = FIXED_ARTIFACTS_SUBTAB_ORDER
ARTIFACTS_PANE_IDS: dict[ArtifactsSubTab, str] = dict(FIXED_ARTIFACTS_PANE_IDS)
FILES_SUBTAB_ORDER: tuple[FilesSubTab, ...] = ()
FILES_PANE_IDS: dict[FilesSubTab, str] = {}
DEFAULT_FILES_SUBTAB: FilesSubTab = "files"


__all__ = [
    "ARTIFACTS_ACCENTS",
    "ARTIFACTS_ICONS",
    "ARTIFACTS_PANE_IDS",
    "ARTIFACTS_SUBTAB_ORDER",
    "DEFAULT_ARTIFACTS_SUBTAB",
    "DEFAULT_DOCUMENT_TAB_ICON",
    "DEFAULT_FILES_SUBTAB",
    "EXTERNAL_ACCENT",
    "FILES_PANE_IDS",
    "FILES_SUBTAB_ORDER",
    "FIXED_ARTIFACTS_PANE_IDS",
    "FIXED_ARTIFACTS_SUBTAB_ORDER",
    "LEGACY_ARTIFACTS_SUBTABS",
    "ArtifactsPaneKey",
    "ArtifactsSubTab",
    "ArtifactsTabDescriptor",
    "DocumentProviderProjectRoot",
    "FilesSubTab",
    "artifacts_pane_key",
    "artifacts_subtab_order",
    "descriptor_for_artifacts_subtab",
    "document_provider_roots",
    "normalize_artifacts_subtab",
    "reset_artifacts_subtabs_cache",
    "resolve_artifacts_subtabs",
    "switch_to_artifacts_subtab",
]
