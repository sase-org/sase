"""Identifiers, constants, and immutable records for Artifacts tabs.

Split out of :mod:`sase.ace.tui.artifact_tabs` so descriptor construction and
provider discovery can share one vocabulary without importing each other.  Like
that module this one has no Textual widget dependencies.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from sase.ace.query_profile import CompiledQueryProfile
from sase.sidecar_ref_config import SidecarRefPolicy


ArtifactsSubTab = str
FilesSubTab = str
ArtifactsPaneKey = str

DEFAULT_ARTIFACTS_SUBTAB: ArtifactsSubTab = "stitches"
DEFAULT_ARTIFACTS_RELATIONS_COLLAPSED: bool = True
FIXED_ARTIFACTS_SUBTAB_ORDER: tuple[ArtifactsSubTab, ...] = (
    "agents",
    "stitches",
    "patches",
    "beads",
    "files",
)
FIXED_ARTIFACTS_PANE_IDS: dict[ArtifactsSubTab, str] = {
    "patches": "artifacts-patches-pane",
    "stitches": "artifacts-stitches-pane",
    "beads": "artifacts-beads-pane",
    "agents": "artifacts-agents-pane",
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
    "agents": "#0062FF",
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
    "agents": "⬡",
    "files": "▤",
}

CapabilityState = Literal["ON", "OFF"]


class PaneCapability(StrEnum):
    """Closed vocabulary of host-owned Artifacts pane verbs.

    A capability enables registered host behavior. It never contains
    callbacks, commands, widgets, colors, or provider code.
    """

    ENTRY_NAVIGATION = "entry_navigation"
    ENTRY_OPEN = "entry_open"
    FILTER_SESSION = "filter_session"
    REFRESH = "refresh"
    PROJECT_SCOPE = "project_scope"
    STABLE_MARKS = "stable_marks"
    DETAIL_SCROLL = "detail_scroll"
    STABLE_REFERENCE_COPY = "stable_reference_copy"
    QUERY_HISTORY = "query_history"
    SAVED_QUERIES = "saved_queries"
    VERSIONS = "versions"
    MUTATION = "mutation"
    PLAN_APPROVE = "plan_approve"
    PLAN_REJECT = "plan_reject"
    RELATIONS = "relations"
    GROUPING = "grouping"
    STATUS_COUNTERS = "status_counters"
    SHELL = "shell"


@dataclass(frozen=True, slots=True)
class CapabilityVerdict:
    """Auditable ON/OFF decision for one closed host capability."""

    capability: PaneCapability
    enabled: bool
    rule: str
    fact: str
    reason: str
    suppression: str | None = None

    @property
    def state(self) -> CapabilityState:
        return "ON" if self.enabled else "OFF"

    def to_payload(self) -> dict[str, Any]:
        """Return the stable CLI/JSON explanation for this verdict."""

        return {
            "capability": self.capability.value,
            "state": self.state,
            "rule": self.rule,
            "fact": self.fact,
            "reason": self.reason,
            "suppression": self.suppression,
        }


class RelationKind(StrEnum):
    """Closed relation primitives understood by the Artifacts host."""

    HIERARCHY = "hierarchy"
    FAMILY = "family"
    LINK = "link"


@dataclass(frozen=True, slots=True)
class PaneRelationDecl:
    """One declared relation edge family for an Artifacts pane."""

    name: str
    kind: RelationKind
    label: str
    source: str
    target_pane: str | None
    inverse: str | None
    directed: bool
    transitive: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "label": self.label,
            "source": self.source,
            "target_pane": self.target_pane,
            "inverse": self.inverse,
            "directed": self.directed,
            "transitive": self.transitive,
        }


@dataclass(frozen=True, slots=True)
class PaneGroupingModeDecl:
    """One declared grouping mode for an Artifacts pane."""

    id: str
    label: str
    keys: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "keys": list(self.keys),
        }


@dataclass(frozen=True, slots=True)
class PaneGroupingDecl:
    """Declared grouping modes for an Artifacts pane."""

    modes: tuple[PaneGroupingModeDecl, ...] = ()
    default_mode: str | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "default_mode": self.default_mode,
            "modes": [mode.to_payload() for mode in self.modes],
        }


@dataclass(frozen=True, slots=True)
class PaneDeclaredFacts:
    """Immutable declared facts the compiler uses to derive capabilities."""

    source: Literal["builtin", "provider"]
    adapter: str | None
    is_degraded: bool
    has_inventory: bool
    has_fields: bool
    has_stable_identity: bool
    has_revisions: bool
    can_mutate: bool
    is_plan_adapter: bool
    project_scoped: bool
    has_detail: bool
    relations: tuple[PaneRelationDecl, ...] = ()
    grouping: PaneGroupingDecl = field(default_factory=PaneGroupingDecl)
    status_counters: tuple[PaneStatusCounter, ...] = field(default_factory=tuple)
    suppressions: Mapping[str, str] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "adapter": self.adapter,
            "is_degraded": self.is_degraded,
            "has_inventory": self.has_inventory,
            "has_fields": self.has_fields,
            "has_stable_identity": self.has_stable_identity,
            "has_revisions": self.has_revisions,
            "can_mutate": self.can_mutate,
            "is_plan_adapter": self.is_plan_adapter,
            "project_scoped": self.project_scoped,
            "has_detail": self.has_detail,
            "relations": [item.to_payload() for item in self.relations],
            "grouping": self.grouping.to_payload(),
            "status_counters": [item.to_payload() for item in self.status_counters],
            "suppressions": dict(self.suppressions),
        }


@dataclass(frozen=True, slots=True)
class PaneStatusCounter:
    """One declared status vocabulary used by relation rows and count lanes."""

    name: str
    field: str

    def to_payload(self) -> dict[str, Any]:
        return {"name": self.name, "field": self.field}


@dataclass(frozen=True, slots=True)
class PaneEmptyState:
    """Host-owned empty-state copy for one pane."""

    title: str = ""
    body: str = ""


@dataclass(frozen=True, slots=True)
class PaneRowPresentation:
    """Provider-safe fields used to render one generic document row."""

    title: str = "title"
    badges: tuple[str, ...] = ()
    secondary: tuple[str, ...] = ()
    list_fields: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "badges": list(self.badges),
            "secondary": list(self.secondary),
            "list_fields": list(self.list_fields),
        }


@dataclass(frozen=True, slots=True)
class PaneSortField:
    """One safe provider-declared default sort key."""

    field: str
    direction: Literal["asc", "desc"] = "asc"

    def to_payload(self) -> dict[str, Any]:
        return {"field": self.field, "direction": self.direction}


@dataclass(frozen=True, slots=True)
class PaneDescription:
    """Resolved summary/body copy for one Artifacts pane."""

    summary: str = ""
    body: str = ""
    summary_source: str = "fallback"
    body_source: str = "fallback"

    def to_payload(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "body": self.body,
            "summary_source": self.summary_source,
            "body_source": self.body_source,
        }


@dataclass(frozen=True, slots=True)
class PanePresentation:
    """Normalized Python-owned presentation data for provider panes."""

    description: str = ""
    description_body: str = ""
    row: PaneRowPresentation = field(default_factory=PaneRowPresentation)
    default_sort: tuple[PaneSortField, ...] = ()
    facets: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "description": self.description,
            "description_body": self.description_body,
            "row": self.row.to_payload(),
            "default_sort": [item.to_payload() for item in self.default_sort],
            "facets": list(self.facets),
        }


@dataclass(frozen=True, slots=True)
class ArtifactsPaneContract:
    """Immutable, widget-free behavioral contract for one Artifacts pane."""

    id: str
    label: str
    description: str
    icon: str
    accent: str
    order: int
    digit: str | None
    ref_kind: str | None
    target_prefix: str
    project_scoping: bool
    presentation_digest: str
    capabilities: frozenset[PaneCapability]
    verdicts: tuple[CapabilityVerdict, ...]
    query_profile: CompiledQueryProfile
    relations: tuple[PaneRelationDecl, ...]
    grouping: PaneGroupingDecl
    presentation: PanePresentation
    detail_fields: tuple[str, ...]
    status_counters: tuple[PaneStatusCounter, ...]
    empty_state: PaneEmptyState
    copy_group: str
    copy_targets: tuple[str, ...]
    facts: PaneDeclaredFacts
    detail_scroll_id: str | None = None
    copy_keymap_group: str = ""
    adapter: str | None = None
    description_body: str = ""
    description_source: str = "builtin"
    description_body_source: str = "builtin"

    def has(self, capability: PaneCapability) -> bool:
        return capability in self.capabilities

    def is_document_provider(self) -> bool:
        return self.ref_kind is not None

    def is_plan_adapter(self) -> bool:
        return self.facts.is_plan_adapter

    def verdict_for(self, capability: PaneCapability) -> CapabilityVerdict | None:
        return next(
            (verdict for verdict in self.verdicts if verdict.capability == capability),
            None,
        )

    def explanation_payload(self) -> dict[str, Any]:
        """Return the deterministic CLI/JSON explanation payload."""

        return {
            "id": self.id,
            "label": self.label,
            "description": self.description,
            "description_detail": PaneDescription(
                summary=self.description,
                body=self.description_body,
                summary_source=self.description_source,
                body_source=self.description_body_source,
            ).to_payload(),
            "icon": self.icon,
            "accent": self.accent,
            "order": self.order,
            "digit": self.digit,
            "ref_kind": self.ref_kind,
            "target_prefix": self.target_prefix,
            "project_scoping": self.project_scoping,
            "presentation_digest": self.presentation_digest,
            "adapter": self.adapter,
            "copy_group": self.copy_group,
            "copy_targets": list(self.copy_targets),
            "detail_fields": list(self.detail_fields),
            "detail_scroll_id": self.detail_scroll_id,
            "empty_state": {
                "title": self.empty_state.title,
                "body": self.empty_state.body,
            },
            "query_profile": self.query_profile.to_wire(),
            "relations": [item.to_payload() for item in self.relations],
            "grouping": self.grouping.to_payload(),
            "presentation": self.presentation.to_payload(),
            "status_counters": [
                {"name": item.name, "field": item.field}
                for item in self.status_counters
            ],
            "facts": self.facts.to_payload(),
            "capabilities": [verdict.to_payload() for verdict in self.verdicts],
        }


@dataclass(frozen=True, slots=True)
class ArtifactsTabDescriptor:
    """Immutable runtime descriptor for one top-level Artifacts pane."""

    id: ArtifactsSubTab
    label: str
    accent: str
    pane_id: str
    description: str = ""
    description_body: str = ""
    icon: str = ""
    provider_kind: str | None = None
    provider_spec_digest: str | None = None
    provider_spec: Mapping[str, Any] | None = None
    digit_shortcut: str | None = None
    error: str | None = None
    error_code: str | None = None
    error_source: str | None = None
    contract: ArtifactsPaneContract | None = None

    @property
    def is_provider(self) -> bool:
        return self.provider_kind is not None

    @property
    def is_degraded(self) -> bool:
        return self.error is not None

    @property
    def resolved_contract(self) -> ArtifactsPaneContract:
        if self.contract is None:
            raise ValueError(f"Artifacts pane {self.id!r} has no compiled contract")
        return self.contract


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
class ProjectProviderRecord:
    """One discovered document-provider root, before it becomes a tab."""

    project: str
    display_name: str
    workspace_dir: str | None
    role: str
    root: Path
    policy: SidecarRefPolicy


@dataclass(frozen=True, slots=True)
class ProviderDiscoveryIssue:
    """A provider-discovery failure that must stay visible on a tab."""

    message: str
    code: str
    kind: str | None = None
    role: str | None = None
    source: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderLoadResult:
    """Everything one discovery pass learned: healthy roots plus failures."""

    records: tuple[ProjectProviderRecord, ...]
    issues: tuple[ProviderDiscoveryIssue, ...]
