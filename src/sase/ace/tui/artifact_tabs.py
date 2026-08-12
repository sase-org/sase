"""Provider-aware Artifacts tab registry.

This module intentionally has no Textual widget dependencies.  It is used by
rendering, keybindings, action availability, tests, and a few widget-free
callers that need to switch Artifacts panes without importing the widget tree.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import effective_project_name
from sase.sidecar_ref_config import SidecarRefPolicy, effective_sidecar_ref_policies


ArtifactsSubTab = str
FilesSubTab = str
ArtifactsPaneKey = str

DEFAULT_ARTIFACTS_SUBTAB: ArtifactsSubTab = "stitches"
FIXED_ARTIFACTS_SUBTAB_ORDER: tuple[ArtifactsSubTab, ...] = (
    "stitches",
    "patches",
    "beads",
    "files",
)
FIXED_ARTIFACTS_DIGITS: dict[ArtifactsSubTab, str] = {
    "stitches": "1",
    "patches": "2",
    "beads": "3",
    "files": "4",
}
FIXED_ARTIFACTS_PANE_IDS: dict[ArtifactsSubTab, str] = {
    "patches": "artifacts-patches-pane",
    "stitches": "artifacts-stitches-pane",
    "beads": "artifacts-beads-pane",
    "files": "artifacts-files-pane",
}

LEGACY_ARTIFACTS_SUBTABS: dict[str, ArtifactsSubTab] = {
    "prs": "patches",
    "bugs": "beads",
    "plans": "ref:plan",
    "other": "files",
    # The standalone Chats pane has been retired. Transcript access remains
    # available from agent detail and artifact flows.
    "chats": DEFAULT_ARTIFACTS_SUBTAB,
}

EXTERNAL_ACCENT = "#FF5F5F"
ARTIFACTS_ACCENTS: dict[str, str] = {
    "patches": "#00D7AF",
    "stitches": "#FFD700",
    "beads": "#D787FF",
    "files": "#FFAF5F",
    "ref:plan": "#AF87FF",
    # Compatibility aliases for older modules/tests while the provider pane
    # keeps the old plans action surface.
    "plans": "#AF87FF",
    "other": "#FFAF5F",
}

_PROVIDER_ACCENTS: tuple[str, ...] = (
    "#AF87FF",
    "#5FAFFF",
    "#5FD7AF",
    "#FF87D7",
    "#87D7FF",
    "#D7AF5F",
)


@dataclass(frozen=True, slots=True)
class ArtifactsTabDescriptor:
    """Immutable runtime descriptor for one top-level Artifacts pane."""

    id: ArtifactsSubTab
    label: str
    accent: str
    pane_id: str
    provider_kind: str | None = None
    provider_spec_digest: str | None = None
    provider_spec: Mapping[str, Any] | None = None
    digit_shortcut: str | None = None

    @property
    def is_provider(self) -> bool:
        return self.provider_kind is not None


@dataclass(frozen=True, slots=True)
class DocumentProviderProjectRoot:
    """One project/root contributing rows to a document-provider pane."""

    project: str
    display_name: str
    workspace_dir: str | None
    role: str
    root: Path
    policy: SidecarRefPolicy


@dataclass(frozen=True, slots=True)
class _ProjectProviderRecord:
    project: str
    display_name: str
    workspace_dir: str | None
    role: str
    root: Path
    policy: SidecarRefPolicy


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
    token = _provider_source_token()
    if _ARTIFACTS_TAB_CACHE is not None and _ARTIFACTS_TAB_CACHE[0] == token:
        return _ARTIFACTS_TAB_CACHE[1]

    provider_records = _load_project_provider_records(project=None)
    providers = _provider_descriptors(provider_records)
    descriptors = (
        _fixed_descriptor("stitches"),
        _fixed_descriptor("patches"),
        _fixed_descriptor("beads"),
        *providers,
        _fixed_descriptor("files"),
    )
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
        for record in _load_project_provider_records(project=project)
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


def _fixed_descriptor(subtab: ArtifactsSubTab) -> ArtifactsTabDescriptor:
    labels = {
        "patches": "Patches",
        "stitches": "Stitches",
        "beads": "Beads",
        "files": "Files",
    }
    return ArtifactsTabDescriptor(
        id=subtab,
        label=labels[subtab],
        accent=ARTIFACTS_ACCENTS[subtab],
        pane_id=FIXED_ARTIFACTS_PANE_IDS[subtab],
        digit_shortcut=FIXED_ARTIFACTS_DIGITS[subtab],
    )


def _provider_descriptors(
    provider_records: Iterable[_ProjectProviderRecord],
) -> tuple[ArtifactsTabDescriptor, ...]:
    by_kind: dict[str, list[_ProjectProviderRecord]] = {}
    for record in provider_records:
        by_kind.setdefault(record.policy.ref_kind, []).append(record)

    descriptors: list[ArtifactsTabDescriptor] = []
    for offset, kind in enumerate(sorted(by_kind, key=_natural_label_key), start=5):
        records = by_kind[kind]
        policy = records[0].policy
        spec = policy.spec or {}
        tab_id = f"ref:{kind}"
        accent = (
            ARTIFACTS_ACCENTS.get(tab_id)
            or _PROVIDER_ACCENTS[(offset - 5) % len(_PROVIDER_ACCENTS)]
        )
        digest = "|".join(
            sorted(
                {
                    value
                    for record in records
                    if (value := record.policy.digest) is not None
                }
            )
        )
        descriptors.append(
            ArtifactsTabDescriptor(
                id=tab_id,
                label=_provider_label(kind, spec),
                accent=accent,
                pane_id=(
                    "artifacts-plans-pane"
                    if kind == "plan"
                    else f"artifacts-ref-{_slug(kind)}-pane"
                ),
                provider_kind=kind,
                provider_spec_digest=digest or policy.digest,
                provider_spec=spec,
                digit_shortcut=str(offset) if offset <= 9 else None,
            )
        )
        ARTIFACTS_ACCENTS.setdefault(tab_id, accent)
    return tuple(descriptors)


def _load_project_provider_records(
    *,
    project: str | None,
) -> tuple[_ProjectProviderRecord, ...]:
    try:
        records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    except Exception:
        records = []
    project_records = tuple(
        record
        for record in records
        if bool(getattr(record, "is_project", False))
        and not bool(getattr(record, "system_managed", False))
    )
    selected = _select_project_records(project_records, project)
    loaded: list[_ProjectProviderRecord] = []
    for record in selected:
        workspace_dir = getattr(record, "workspace_dir", None)
        if not workspace_dir:
            continue
        workspace = Path(str(workspace_dir)).expanduser().resolve(strict=False)
        try:
            from sase._linked_repo_config import resolution_config
            from sase.content_layout import resolve_project_config_read_path
            from sase.sdd.store import document_sidecar_roles, resolve_sdd_store

            store = resolve_sdd_store(workspace, 1)
            roles = document_sidecar_roles(
                store.split_sidecar_roles(),
                include_plans=True,
            )
            try:
                source_path = resolve_project_config_read_path(workspace)
            except Exception:
                source_path = None
            policies = effective_sidecar_ref_policies(
                resolution_config(str(workspace), None),
                primary_workspace_dir=workspace,
                roles=roles,
                source_path=source_path,
            )
        except Exception:
            continue
        for role in roles:
            policy = policies.get(role)
            if policy is None or not policy.is_document:
                continue
            try:
                root = store.kind_root(role)
            except (KeyError, OSError, ValueError):
                continue
            loaded.append(
                _ProjectProviderRecord(
                    project=str(record.project_name),
                    display_name=effective_project_name(record),
                    workspace_dir=str(workspace_dir),
                    role=role,
                    root=root,
                    policy=policy,
                )
            )
    return tuple(
        sorted(
            loaded,
            key=lambda item: (
                item.policy.ref_kind.casefold(),
                item.display_name.casefold(),
                item.project,
                item.role,
                str(item.root),
            ),
        )
    )


def _select_project_records(
    records: tuple[Any, ...], project: str | None
) -> tuple[Any, ...]:
    if project is None:
        return tuple(
            record
            for record in records
            if getattr(record, "state", "enabled") == "enabled"
        )
    folded = project.casefold()
    return tuple(
        record
        for record in records
        if folded
        in {
            str(getattr(record, "project_name", "")).casefold(),
            effective_project_name(record).casefold(),
            *(
                str(alias).casefold()
                for alias in getattr(record, "aliases", ())
                if alias
            ),
        }
    )


def _provider_source_token() -> tuple[object, ...]:
    try:
        records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    except Exception:
        return ("unavailable",)
    token: list[object] = []
    for record in records:
        if not bool(getattr(record, "is_project", False)) or bool(
            getattr(record, "system_managed", False)
        ):
            continue
        project_file = Path(str(getattr(record, "project_file", "")))
        try:
            stat = project_file.stat()
            project_file_token: object = (
                str(project_file),
                stat.st_mtime_ns,
                stat.st_size,
            )
        except OSError:
            project_file_token = (str(project_file), None, None)
        workspace_dir = getattr(record, "workspace_dir", None)
        config_token: object = None
        if workspace_dir:
            try:
                from sase.content_layout import resolve_project_config_read_path

                config_path = resolve_project_config_read_path(Path(str(workspace_dir)))
                if config_path is not None:
                    config_stat = Path(config_path).stat()
                    config_token = (
                        str(config_path),
                        config_stat.st_mtime_ns,
                        config_stat.st_size,
                    )
            except Exception:
                config_token = None
        token.append(
            (
                getattr(record, "project_name", ""),
                getattr(record, "state", "enabled"),
                effective_project_name(record),
                tuple(getattr(record, "aliases", ())),
                workspace_dir,
                project_file_token,
                config_token,
            )
        )
    return tuple(token)


def _provider_label(kind: str, spec: Mapping[str, Any]) -> str:
    for candidate in (
        spec.get("label"),
        (spec.get("ref") or {}).get("label")
        if isinstance(spec.get("ref"), Mapping)
        else None,
    ):
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    label = kind.replace("_", " ").replace("-", " ").strip().title()
    if not label:
        return "Documents"
    if label.casefold().endswith("s"):
        return label
    return f"{label}s"


def _natural_label_key(value: str) -> tuple[object, ...]:
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", value)
    )


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", value.casefold()).strip("-_")
    return slug or "document"


# Compatibility constants for existing imports. Call the functions above when a
# refresh-sensitive value is needed.
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
    "ARTIFACTS_PANE_IDS",
    "ARTIFACTS_SUBTAB_ORDER",
    "DEFAULT_ARTIFACTS_SUBTAB",
    "DEFAULT_FILES_SUBTAB",
    "EXTERNAL_ACCENT",
    "FILES_PANE_IDS",
    "FILES_SUBTAB_ORDER",
    "FIXED_ARTIFACTS_DIGITS",
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
