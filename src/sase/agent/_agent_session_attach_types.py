"""Shared agent-session attach data types."""

from __future__ import annotations

from dataclasses import dataclass, field

# legacy agent-family spelling: the handoff variable keeps its name until
# ``SASE_AGENT_SESSION_ATTACH`` is introduced.
LEGACY_AGENT_FAMILY_ATTACH_ENV = "SASE_AGENT_FAMILY_ATTACH"


@dataclass(frozen=True)
class ParsedNameDirective:
    plain_name: str | None = None
    bead_id: str | None = None
    clan: str | None = None
    tribe: str | None = None
    force_reuse: bool = False
    agent_session_parent: str | None = None
    agent_session_suffix: str | None = None


@dataclass(frozen=True)
class AgentSessionAttachDirective:
    parent: str
    suffix: str
    force_reuse: bool = False


@dataclass(frozen=True)
class AgentSessionAttachLaunchPlan:
    parent_arg: str
    suffix_arg: str
    parent_name: str
    parent_base: str
    parent_timestamp: str
    parent_artifacts_dir: str
    role_suffix: str
    agent_name: str
    agent_session_role: str
    parent_agent_session_member_name: str
    parent_agent_session_role_suffix: str
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
class AgentSessionAttachSibling:
    """Launch-batch sibling known before its async artifact metadata is written."""

    name: str
    agent_session_base_name: str
    timestamp: str
    artifact_dir: str
    project_name: str
    cl_name: str | None = None
    workspace_dir: str | None = None
    workspace_num: int | None = None
    can_attach_parent: bool = True
    agent_session_root_role_suffix: str = "--0"
    agent_clan: str | None = None
    agent_clan_generation: str | None = None
    model_alias_overrides: dict[str, str] = field(default_factory=dict)


class AgentSessionAttachError(RuntimeError):
    """Raised when a ``%id(suffix, family=parent)`` launch cannot be prepared."""


__all__ = [
    "LEGACY_AGENT_FAMILY_ATTACH_ENV",
    "AgentSessionAttachDirective",
    "AgentSessionAttachError",
    "AgentSessionAttachLaunchPlan",
    "AgentSessionAttachSibling",
    "ParsedNameDirective",
]
