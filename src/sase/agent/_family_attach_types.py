"""Shared family attach data types."""

from __future__ import annotations

from dataclasses import dataclass, field

FAMILY_ATTACH_ENV = "SASE_AGENT_FAMILY_ATTACH"


@dataclass(frozen=True)
class ParsedNameDirective:
    plain_name: str | None = None
    bead_id: str | None = None
    clan: str | None = None
    tribe: str | None = None
    force_reuse: bool = False
    family_parent: str | None = None
    family_suffix: str | None = None


@dataclass(frozen=True)
class FamilyAttachDirective:
    parent: str
    suffix: str


@dataclass(frozen=True)
class FamilyAttachLaunchPlan:
    parent_arg: str
    suffix_arg: str
    parent_name: str
    parent_base: str
    parent_timestamp: str
    parent_artifacts_dir: str
    role_suffix: str
    agent_name: str
    agent_family_role: str
    parent_family_member_name: str
    parent_family_role_suffix: str
    parent_needs_rename: bool
    parent_project_name: str
    parent_is_running: bool = False
    parent_cl_name: str | None = None
    parent_agent_clan: str | None = None
    parent_agent_clan_generation: str | None = None
    parent_workspace_dir: str | None = None
    parent_workspace_num: int | None = None
    sase_plan: str | None = None
    model_alias_overrides: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FamilyAttachSibling:
    """Launch-batch sibling known before its async artifact metadata is written."""

    name: str
    family_base: str
    timestamp: str
    artifact_dir: str
    project_name: str
    cl_name: str | None = None
    workspace_dir: str | None = None
    workspace_num: int | None = None
    can_attach_parent: bool = True
    family_root_role_suffix: str = "--0"
    agent_clan: str | None = None
    agent_clan_generation: str | None = None
    model_alias_overrides: dict[str, str] = field(default_factory=dict)


class FamilyAttachError(RuntimeError):
    """Raised when a ``%id(suffix, family=parent)`` launch cannot be prepared."""


__all__ = [
    "FAMILY_ATTACH_ENV",
    "FamilyAttachDirective",
    "FamilyAttachError",
    "FamilyAttachLaunchPlan",
    "FamilyAttachSibling",
    "ParsedNameDirective",
]
