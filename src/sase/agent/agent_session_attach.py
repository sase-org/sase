"""User-facing ``%id(suffix, session=parent)`` agent-session attach support."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from sase.agent import _agent_session_attach_candidates as _candidates
from sase.agent import _agent_session_attach_directives as _directives
from sase.agent import _agent_session_attach_launch as _launch
from sase.agent import _agent_session_promotion as _promotion
from sase.agent import _agent_session_attach_resolution as _resolution
from sase.agent import _agent_session_attach_types as _types

if TYPE_CHECKING:
    from sase.agent.launch_executor_types import LaunchSpawnRequest

AGENT_SESSION_ATTACH_ENV = _types.AGENT_SESSION_ATTACH_ENV
LEGACY_AGENT_FAMILY_ATTACH_ENV = _types.LEGACY_AGENT_FAMILY_ATTACH_ENV
AgentSessionAttachDirective = _types.AgentSessionAttachDirective
AgentSessionAttachError = _types.AgentSessionAttachError
AgentSessionAttachLaunchPlan = _types.AgentSessionAttachLaunchPlan
AgentSessionAttachSibling = _types.AgentSessionAttachSibling
ParsedNameDirective = _types.ParsedNameDirective

agent_session_snapshot = _candidates.agent_session_snapshot
dismissed_identity_dicts = _candidates.dismissed_identity_dicts
extract_agent_session_attach_directive = (
    _directives.extract_agent_session_attach_directive
)
normalize_agent_session_suffix_arg = _directives.normalize_agent_session_suffix_arg
default_with_feedback_parent_from_agent_session_attach = (
    _directives.default_with_feedback_parent_from_agent_session_attach
)
parse_name_directive_args = _directives.parse_name_directive_args
promote_agent_to_agent_session = _promotion.promote_agent_to_agent_session
promote_agent_session_parent_for_attach = (
    _promotion.promote_agent_session_parent_for_attach
)


def prepare_agent_session_attach_launch(
    prompt: str,
    context: Any,
    extra_env: dict[str, str] | None,
    *,
    pending_agent_session_parents: list[AgentSessionAttachSibling] | None = None,
) -> tuple[Any, dict[str, str] | None]:
    """Resolve agent-session attach metadata and return adjusted launch context/env."""
    return _launch.prepare_agent_session_attach_launch(
        prompt,
        context,
        extra_env,
        pending_agent_session_parents=pending_agent_session_parents,
        resolve_agent_session_attach_plan=resolve_agent_session_attach_plan,
    )


def load_agent_session_attach_plan_from_env(
    env: dict[str, str] | None = None,
) -> AgentSessionAttachLaunchPlan | None:
    return _launch.load_agent_session_attach_plan_from_env(env)


def _resolve_agent_session_attach_plan(
    directive: AgentSessionAttachDirective,
    *,
    project_name: str,
    pending_agent_session_parents: list[AgentSessionAttachSibling] | None = None,
) -> AgentSessionAttachLaunchPlan:
    return _resolution.resolve_agent_session_attach_plan(
        directive,
        project_name=project_name,
        pending_agent_session_parents=pending_agent_session_parents,
        agent_session_snapshot=agent_session_snapshot,
        dismissed_identity_dicts=dismissed_identity_dicts,
    )


resolve_agent_session_attach_plan = _resolve_agent_session_attach_plan


def build_agent_session_attach_sibling_from_spawn(
    request: LaunchSpawnRequest,
    name: str,
    *,
    agent_session_base_name: str | None = None,
    can_attach_parent: bool = True,
) -> AgentSessionAttachSibling | None:
    """Return the in-batch sibling descriptor for a successful spawn request."""
    return _launch.build_agent_session_attach_sibling_from_spawn(
        request,
        name,
        agent_session_base_name=agent_session_base_name,
        can_attach_parent=can_attach_parent,
    )


__all__ = [
    "AGENT_SESSION_ATTACH_ENV",
    "LEGACY_AGENT_FAMILY_ATTACH_ENV",
    "AgentSessionAttachDirective",
    "AgentSessionAttachError",
    "AgentSessionAttachLaunchPlan",
    "AgentSessionAttachSibling",
    "ParsedNameDirective",
    "build_agent_session_attach_sibling_from_spawn",
    "default_with_feedback_parent_from_agent_session_attach",
    "extract_agent_session_attach_directive",
    "load_agent_session_attach_plan_from_env",
    "normalize_agent_session_suffix_arg",
    "parse_name_directive_args",
    "prepare_agent_session_attach_launch",
    "promote_agent_to_agent_session",
    "promote_agent_session_parent_for_attach",
    "resolve_agent_session_attach_plan",
]
