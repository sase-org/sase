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

from sase.sidecar_ref_config import SidecarRefPolicy


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
    PLAN_OPEN_BEAD = "plan_open_bead"
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
            "suppressions": dict(self.suppressions),
        }


@dataclass(frozen=True, slots=True)
class PaneQuerySchema:
    """Later-phase query schema placeholder. Empty this phase."""

    fields: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PaneRelationDecl:
    """Later-phase relation placeholder. Unused this phase."""

    name: str
    target: str


@dataclass(frozen=True, slots=True)
class PaneGroupingDecl:
    """Later-phase grouping placeholder. Empty this phase."""

    keys: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PaneStatusCounter:
    """Later-phase status-counter placeholder. Unused this phase."""

    name: str
    field: str


@dataclass(frozen=True, slots=True)
class PaneEmptyState:
    """Host-owned empty-state copy for one pane."""

    title: str = ""
    body: str = ""


@dataclass(frozen=True, slots=True)
class ArtifactsPaneContract:
    """Immutable, widget-free behavioral contract for one Artifacts pane."""

    id: str
    label: str
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
    query_schema: PaneQuerySchema
    relations: tuple[PaneRelationDecl, ...]
    grouping: PaneGroupingDecl
    detail_fields: tuple[str, ...]
    status_counters: tuple[PaneStatusCounter, ...]
    empty_state: PaneEmptyState
    copy_group: str
    copy_targets: tuple[str, ...]
    facts: PaneDeclaredFacts
    detail_scroll_id: str | None = None
    copy_keymap_group: str = ""
    adapter: str | None = None

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
            "query_schema": {"fields": list(self.query_schema.fields)},
            "relations": [
                {"name": item.name, "target": item.target} for item in self.relations
            ],
            "grouping": {"keys": list(self.grouping.keys)},
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
