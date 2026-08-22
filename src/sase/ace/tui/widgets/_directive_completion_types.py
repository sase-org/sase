"""Shared types for ACE prompt directive completion."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from sase.ace.tui.widgets.file_completion import CompletionCandidate

BeadsState = Literal["warm", "loading", "unavailable"]
FinalizersState = BeadsState
PathCandidateBuilder = Callable[[str], tuple[list[CompletionCandidate], str]]


@dataclass(frozen=True, slots=True)
class DirectiveCompletionMetadata:
    """Display metadata for a prompt directive completion candidate."""

    aliases: tuple[str, ...] = ()
    argument_hint: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class DirectiveArgCompletionMetadata:
    """Display metadata for a prompt directive argument completion candidate."""

    directive_name: str = ""
    description: str = ""


@dataclass(frozen=True, slots=True)
class ModelCompletionMetadata:
    """Display metadata for an enriched ``%model`` completion row."""

    value: str
    kind: str
    alias_kind: str = ""
    provider: str = ""
    provider_display: str = ""
    short_alias: str = ""
    target_provider: str = ""
    target_model: str = ""
    target_effort: str = ""
    provenance: str = ""
    reference: str = ""
    reference_effort: str = ""
    pool_available: int = 0
    pool_total: int = 0
    description: str = ""
    config_source: str = ""
    provider_model_count: int = 0


@dataclass(frozen=True, slots=True)
class BeadCompletionMetadata:
    """Display metadata for an open-bead directive value row."""

    bead_id: str
    title: str = ""
    status: str = ""
    type_label: str = ""
    task_type: str = ""
    project: str = ""
    created_at: str = ""
    documentation: str = ""


@dataclass(frozen=True, slots=True)
class FinalizerCompletionMetadata:
    """Display metadata for a ``%final`` selector completion row."""

    value: str
    kind: str
    status: str = ""
    provider: str = ""
    documentation: str = ""

    @property
    def state_label(self) -> str:
        """Accessible policy or operation label, independent of color."""
        if self.kind == "finalizer_remove":
            return "remove"
        if self.kind == "finalizer_clear":
            return "clear"
        if self.status in {"required", "default", "optional", "clear"}:
            return self.status
        return "optional"


@dataclass(frozen=True, slots=True)
class DirectiveCatalogPlaceholder:
    """Non-selectable loading or unavailable dynamic-catalog row."""

    kind: Literal["loading", "unavailable"]
    message: str
    catalog: Literal["beads", "finalizers"] = "beads"
