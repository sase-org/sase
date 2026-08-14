"""Provider-aware Artifacts tab registry.

This module intentionally has no Textual widget dependencies.  It is used by
rendering, keybindings, action availability, tests, and a few widget-free
callers that need to switch Artifacts panes without importing the widget tree.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
import hashlib
from pathlib import Path
import re
from typing import Any

from rich.cells import cell_len

from sase.content_layout import LayoutCollisionError
from sase.core.paths import sase_projects_dir
from sase.core.project_lifecycle_facade import list_project_records
from sase.core.project_lifecycle_wire import effective_project_name
from sase.notification_gates.model_validation import GateError, validate_icon
from sase.sidecar_ref_config import (
    DEFAULT_DOCUMENT_TAB_ICON,
    REF_ICON_CONFIG_KEY,
    SidecarRefPolicy,
    sidecar_ref_policy_report,
    sidecar_role_ref_kind,
)


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
ARTIFACTS_ICONS: dict[str, str] = {
    "stitches": "◉",
    "patches": "⎇",
    "beads": "◈",
    "files": "▤",
}

_PROVIDER_ACCENTS: tuple[str, ...] = (
    "#AF87FF",
    "#5FAFFF",
    "#5FD7AF",
    "#FF87D7",
    "#87D7FF",
    "#D7AF5F",
)

_ARTIFACTS_DIGIT_KEYS: tuple[str, ...] = tuple(str(digit) for digit in range(1, 10))

# Operational failures during provider discovery. Narrower than ``Exception``
# so programming errors (TypeError, NameError, AssertionError) still escape.
_PROVIDER_DISCOVERY_ERRORS: tuple[type[BaseException], ...] = (
    AttributeError,
    ImportError,
    KeyError,
    LayoutCollisionError,
    OSError,
    RuntimeError,
    ValueError,
)


@dataclass(frozen=True, slots=True)
class ArtifactsTabDescriptor:
    """Immutable runtime descriptor for one top-level Artifacts pane."""

    id: ArtifactsSubTab
    label: str
    accent: str
    pane_id: str
    icon: str = ""
    provider_kind: str | None = None
    provider_spec_digest: str | None = None
    provider_spec: Mapping[str, Any] | None = None
    digit_shortcut: str | None = None
    error: str | None = None
    error_code: str | None = None
    error_source: str | None = None

    @property
    def is_provider(self) -> bool:
        return self.provider_kind is not None

    @property
    def is_degraded(self) -> bool:
        return self.error is not None


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


@dataclass(frozen=True, slots=True)
class _ProviderDiscoveryIssue:
    """A provider-discovery failure that must stay visible on a tab."""

    message: str
    code: str
    kind: str | None = None
    role: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class _ProviderLoadResult:
    records: tuple[_ProjectProviderRecord, ...]
    issues: tuple[_ProviderDiscoveryIssue, ...]


_ARTIFACTS_TAB_CACHE: tuple[object, tuple[ArtifactsTabDescriptor, ...]] | None = None
_PROVIDER_ROOTS_CACHE: dict[
    tuple[str, str | None], tuple[DocumentProviderProjectRoot, ...]
] = {}


def reset_artifacts_subtabs_cache() -> None:
    """Clear cached provider descriptors and document roots."""

    global _ARTIFACTS_TAB_CACHE
    _ARTIFACTS_TAB_CACHE = None
    _PROVIDER_ROOTS_CACHE.clear()


def _provider_accent_for_kind(kind: str) -> str:
    """Return a stable provider accent derived from ``ref_kind``.

    Pinned built-in kinds (``plan``) keep their ``ARTIFACTS_ACCENTS`` colour.
    Every other kind hashes onto the provider palette after reserved built-in
    colours are removed, so installing an unrelated sidecar cannot repaint an
    existing tab and a provider can never draw a built-in's colour.
    """

    tab_id = f"ref:{kind}"
    pinned = ARTIFACTS_ACCENTS.get(tab_id)
    if pinned is not None:
        return pinned
    reserved = frozenset(ARTIFACTS_ACCENTS.values())
    palette = [color for color in _PROVIDER_ACCENTS if color not in reserved]
    if not palette:
        palette = list(_PROVIDER_ACCENTS)
    digest = hashlib.sha256(kind.encode("utf-8")).digest()
    return palette[int.from_bytes(digest[:8], "big") % len(palette)]


def _assign_artifacts_digit_shortcuts(
    descriptors: Sequence[ArtifactsTabDescriptor],
) -> tuple[ArtifactsTabDescriptor, ...]:
    """Number Artifacts panes by visual position, Files highest.

    ``descriptors`` must arrive in visual (left-to-right) order, with the
    Files pane last. The Files descriptor (``id == "files"``) always
    receives a digit shortcut, and it is always the highest digit assigned:
    its 1-based position clamped to the last available digit. Every other
    descriptor receives its own 1-based positional digit as long as that
    digit is strictly lower than the Files digit; any pane beyond that
    (only reachable with more than nine panes) receives
    ``digit_shortcut=None``. If no descriptor has ``id == "files"``
    (defensive; not reachable from :func:`resolve_artifacts_subtabs`), this
    falls back to plain positional numbering with ``None`` past the ninth
    pane.
    """

    files_index = next(
        (
            index
            for index, descriptor in enumerate(descriptors)
            if descriptor.id == "files"
        ),
        None,
    )
    if files_index is None:
        return tuple(
            replace(
                descriptor,
                digit_shortcut=(
                    _ARTIFACTS_DIGIT_KEYS[index]
                    if index < len(_ARTIFACTS_DIGIT_KEYS)
                    else None
                ),
            )
            for index, descriptor in enumerate(descriptors)
        )

    files_digit_index = min(len(descriptors), len(_ARTIFACTS_DIGIT_KEYS)) - 1
    result: list[ArtifactsTabDescriptor] = []
    for index, descriptor in enumerate(descriptors):
        if index == files_index:
            digit = _ARTIFACTS_DIGIT_KEYS[files_digit_index]
        elif index < files_digit_index:
            digit = _ARTIFACTS_DIGIT_KEYS[index]
        else:
            digit = None
        result.append(replace(descriptor, digit_shortcut=digit))
    return tuple(result)


def resolve_artifacts_subtabs() -> tuple[ArtifactsTabDescriptor, ...]:
    """Return fixed and configured provider tabs in visual order."""

    global _ARTIFACTS_TAB_CACHE
    token = _provider_source_token()
    if (
        token is not None
        and _ARTIFACTS_TAB_CACHE is not None
        and _ARTIFACTS_TAB_CACHE[0] == token
    ):
        return _ARTIFACTS_TAB_CACHE[1]

    loaded = _load_project_provider_records(project=None)
    providers = _provider_descriptors(loaded.records, loaded.issues)
    descriptors = _assign_artifacts_digit_shortcuts(
        (
            _fixed_descriptor("stitches"),
            _fixed_descriptor("patches"),
            _fixed_descriptor("beads"),
            *providers,
            _fixed_descriptor("files"),
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
        for record in _load_project_provider_records(project=project).records
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
        "patches": "Patch",
        "stitches": "Stitch",
        "beads": "Bead",
        "files": "File",
    }
    return ArtifactsTabDescriptor(
        id=subtab,
        label=labels[subtab],
        accent=ARTIFACTS_ACCENTS[subtab],
        pane_id=FIXED_ARTIFACTS_PANE_IDS[subtab],
        icon=ARTIFACTS_ICONS[subtab],
    )


def _provider_descriptors(
    provider_records: Iterable[_ProjectProviderRecord],
    issues: Iterable[_ProviderDiscoveryIssue] = (),
) -> tuple[ArtifactsTabDescriptor, ...]:
    by_kind: dict[str, list[_ProjectProviderRecord]] = {}
    for record in provider_records:
        by_kind.setdefault(record.policy.ref_kind, []).append(record)

    issues_by_kind: dict[str, list[_ProviderDiscoveryIssue]] = {}
    for issue in issues:
        kind = issue.kind or "plan"
        issues_by_kind.setdefault(kind, []).append(issue)

    kinds = set(by_kind) | set(issues_by_kind)
    descriptors: list[ArtifactsTabDescriptor] = []
    for kind in sorted(kinds, key=_natural_label_key):
        records = by_kind.get(kind, [])
        kind_issues = issues_by_kind.get(kind, [])
        descriptors.append(_descriptor_for_provider_kind(kind, records, kind_issues))
    return tuple(descriptors)


def _descriptor_for_provider_kind(
    kind: str,
    records: Sequence[_ProjectProviderRecord],
    issues: Sequence[_ProviderDiscoveryIssue],
) -> ArtifactsTabDescriptor:
    healthy = [record for record in records if record.policy.spec is not None]
    policy = (healthy[0].policy if healthy else None) or (
        records[0].policy if records else None
    )
    spec = dict(policy.spec) if policy is not None and policy.spec is not None else None
    if spec is None and kind == "plan":
        from sase.artifact_providers import builtin_plan_ref_provider_spec

        spec = builtin_plan_ref_provider_spec()
    ref = spec.get("ref") if isinstance(spec, Mapping) else None
    icon = (
        _sanitize_tab_icon(ref.get(REF_ICON_CONFIG_KEY))
        if isinstance(ref, Mapping)
        else ""
    ) or DEFAULT_DOCUMENT_TAB_ICON
    digest = "|".join(
        sorted(
            {value for record in records if (value := record.policy.digest) is not None}
        )
    )
    error: str | None = None
    error_code: str | None = None
    error_source: str | None = None
    if not healthy and issues:
        issue = issues[0]
        error = issue.message
        error_code = issue.code
        error_source = issue.source
    return ArtifactsTabDescriptor(
        id=f"ref:{kind}",
        label=_provider_label(kind, spec or {}),
        accent=_provider_accent_for_kind(kind),
        pane_id=(
            "artifacts-plans-pane"
            if kind == "plan"
            else f"artifacts-ref-{_slug(kind)}-pane"
        ),
        icon=icon,
        provider_kind=kind,
        provider_spec_digest=digest or (policy.digest if policy is not None else None),
        provider_spec=spec,
        error=error,
        error_code=error_code,
        error_source=error_source,
    )


def _load_project_provider_records(
    *,
    project: str | None,
) -> _ProviderLoadResult:
    try:
        records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    except _PROVIDER_DISCOVERY_ERRORS as exc:
        return _ProviderLoadResult(
            records=(),
            issues=(
                _ProviderDiscoveryIssue(
                    message=str(exc),
                    code="provider_discovery_failed",
                    kind="plan",
                    source="list_project_records",
                ),
            ),
        )
    project_records = tuple(
        record
        for record in records
        if bool(getattr(record, "is_project", False))
        and not bool(getattr(record, "system_managed", False))
    )
    selected = _select_project_records(project_records, project)
    loaded: list[_ProjectProviderRecord] = []
    issues: list[_ProviderDiscoveryIssue] = []
    for record in selected:
        workspace_dir = getattr(record, "workspace_dir", None)
        if not workspace_dir:
            continue
        workspace = Path(str(workspace_dir)).expanduser().resolve(strict=False)
        issues.extend(_load_workspace_provider_records(record, workspace, loaded))
    return _ProviderLoadResult(
        records=tuple(
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
        ),
        issues=tuple(issues),
    )


def _load_workspace_provider_records(
    record: Any,
    workspace: Path,
    loaded: list[_ProjectProviderRecord],
) -> tuple[_ProviderDiscoveryIssue, ...]:
    from sase._linked_repo_config import resolution_config
    from sase.content_layout import resolve_project_config_read_path
    from sase.sdd.store import document_sidecar_roles, resolve_sdd_store

    issues: list[_ProviderDiscoveryIssue] = []
    try:
        store = resolve_sdd_store(workspace, 1)
        roles = document_sidecar_roles(
            store.split_sidecar_roles(),
            include_plans=True,
        )
    except _PROVIDER_DISCOVERY_ERRORS as exc:
        return (
            _ProviderDiscoveryIssue(
                message=str(exc),
                code="provider_store_failed",
                kind="plan",
                source=str(workspace),
            ),
        )
    try:
        source_path = resolve_project_config_read_path(workspace)
    except _PROVIDER_DISCOVERY_ERRORS as exc:
        source_path = None
        issues.append(
            _ProviderDiscoveryIssue(
                message=str(exc),
                code="provider_config_unavailable",
                kind="plan",
                source=str(workspace),
            )
        )
    try:
        report = sidecar_ref_policy_report(
            resolution_config(str(workspace), None),
            primary_workspace_dir=workspace,
            roles=roles,
            source_path=source_path,
        )
    except _PROVIDER_DISCOVERY_ERRORS as exc:
        issues.append(
            _ProviderDiscoveryIssue(
                message=str(exc),
                code="provider_policy_failed",
                kind="plan",
                source=str(source_path or workspace),
            )
        )
        return tuple(issues)

    for diagnostic in report.diagnostics:
        role = diagnostic.role
        if role is None or role in report.policies:
            continue
        issues.append(
            _ProviderDiscoveryIssue(
                message=diagnostic.message,
                code=diagnostic.code,
                kind=sidecar_role_ref_kind(role),
                role=role,
                source=None if source_path is None else str(source_path),
            )
        )
    for role in roles:
        policy = report.policies.get(role)
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
                workspace_dir=str(getattr(record, "workspace_dir", workspace)),
                role=role,
                root=root,
                policy=policy,
            )
        )
    return tuple(issues)


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


def _provider_source_token() -> tuple[object, ...] | None:
    """Return a cache key for configured providers, or ``None`` if listing failed.

    A ``None`` token is uncacheable so a transient discovery failure cannot
    pin a degraded four-tab answer the way the old ``("unavailable",)``
    sentinel did.
    """

    try:
        records = list_project_records(
            sase_projects_dir(),
            "all",
            include_home=False,
            projects_only=True,
        )
    except _PROVIDER_DISCOVERY_ERRORS:
        return None
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
            except _PROVIDER_DISCOVERY_ERRORS:
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
        return "Document"
    return label


def _sanitize_tab_icon(raw: object) -> str:
    """Return a safe Artifacts tab icon, or ``""`` for stored junk."""
    try:
        icon = validate_icon(raw, "ref.icon")
    except GateError:
        return ""
    if icon is None or cell_len(icon) > 2:
        return ""
    return icon


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
