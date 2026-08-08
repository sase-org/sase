"""Versioned, I/O-free model for ``sase xprompt show``."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sase.xprompt.models import MemoryType

SHOW_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class ShowInput:
    name: str
    type: str
    required: bool
    default_display: str | None
    description: str | None
    repeatable: bool
    position: int


@dataclass(frozen=True, slots=True)
class ShowLocalXPrompt:
    name: str
    description: str | None
    input_signature: str | None
    line_count: int


@dataclass(frozen=True, slots=True)
class ShowStep:
    index: int
    name: str
    type: str
    label: str
    hidden: bool
    condition: str | None
    output_schema: dict[str, Any] | None
    body: str | None = None


@dataclass(frozen=True, slots=True)
class ShowReference:
    raw_ref: str
    name: str
    kind: str | None
    resolved: bool
    source_display: str | None


@dataclass(frozen=True, slots=True)
class ShowProvenance:
    source_id: str | None
    source_bucket: str
    source_display: str | None
    definition_path: str | None
    definition_line: int | None
    hosted_url: str | None
    editable: bool


@dataclass(frozen=True, slots=True)
class XPromptShowRecord:
    name: str
    reference: str
    prefix: str
    kind: str
    is_skill: bool
    skill_name: str | None
    """Provider-visible ``/`` name; :attr:`reference` stays the ``#`` form."""
    is_swarm: bool
    segment_count: int
    description: str | None
    project: str | None
    provenance: ShowProvenance
    tags: list[str]
    skill: bool | list[str] | None
    snippet: str | bool | None
    log_skill_use: bool | None
    input_signature: str | None
    inputs: list[ShowInput]
    local_xprompts: list[ShowLocalXPrompt]
    steps: list[ShowStep]
    body: str | None
    body_first_line: int | None
    raw: str | None
    warnings: list[str]
    references: list[ShowReference]
    memory_type: MemoryType | None = None

    @property
    def raw_available(self) -> bool:
        """Whether the exact source definition was available."""
        return self.raw is not None

    def to_json_dict(self) -> dict[str, Any]:
        """Return the complete, stable schema-versioned JSON projection."""
        return {
            "schema_version": SHOW_SCHEMA_VERSION,
            **asdict(self),
            "raw_available": self.raw_available,
        }


__all__ = [
    "SHOW_SCHEMA_VERSION",
    "ShowInput",
    "ShowLocalXPrompt",
    "ShowProvenance",
    "ShowReference",
    "ShowStep",
    "XPromptShowRecord",
]
