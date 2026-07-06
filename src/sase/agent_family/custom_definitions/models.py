"""Data models for file-backed custom agent-family definitions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

STANDARD_EXTENDS_ID = "standard_plan_chain"

type RoleOnDone = Literal["re_review", "continue", "terminate"]
type RoleOnFailure = Literal["notify_and_continue", "notify_and_stop"]
type RoleAuto = Literal["run", "skip"]


@dataclass(frozen=True)
class AgentFamilyRoleDefinition:
    """A custom role loaded from an ``agent_family`` YAML file."""

    id: str
    suffix: str
    prompt_template: str
    placement_after: str
    on_done: RoleOnDone
    max_visits: int
    on_failure: RoleOnFailure
    auto: RoleAuto
    default_enabled: bool
    config_id: str
    config_version: int
    config_hash: str
    source_path: str
    label: str | None = None
    done_label: str | None = None
    reserved: Mapping[str, object] = field(default_factory=dict)

    def as_snapshot(self) -> dict[str, object]:
        return {
            "id": self.id,
            "suffix": self.suffix,
            "prompt_template": self.prompt_template,
            "placement_after": self.placement_after,
            "on_done": self.on_done,
            "max_visits": self.max_visits,
            "on_failure": self.on_failure,
            "auto": self.auto,
            "default": self.default_enabled,
            "config_id": self.config_id,
            "config_version": self.config_version,
            "config_hash": self.config_hash,
            "source_path": self.source_path,
            "label": self.label,
            "done_label": self.done_label,
            "reserved": dict(self.reserved),
        }


@dataclass(frozen=True)
class AgentFamilyDefinition:
    """A validated ``kind: agent_family`` definition."""

    id: str
    version: int
    extends: str
    roles: tuple[AgentFamilyRoleDefinition, ...]
    source_path: str
    config_hash: str
