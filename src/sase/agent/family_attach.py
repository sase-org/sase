"""User-facing ``%i(parent, suffix)`` family attach support."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from sase.agent import _family_attach_candidates as _candidates
from sase.agent import _family_attach_directives as _directives
from sase.agent import _family_attach_launch as _launch
from sase.agent import _family_promotion as _promotion
from sase.agent import _family_attach_resolution as _resolution
from sase.agent import _family_attach_types as _types

if TYPE_CHECKING:
    from sase.agent.launch_executor_types import LaunchSpawnRequest

FAMILY_ATTACH_ENV = _types.FAMILY_ATTACH_ENV
FamilyAttachDirective = _types.FamilyAttachDirective
FamilyAttachError = _types.FamilyAttachError
FamilyAttachLaunchPlan = _types.FamilyAttachLaunchPlan
FamilyAttachSibling = _types.FamilyAttachSibling
ParsedNameDirective = _types.ParsedNameDirective

agent_family_snapshot = _candidates.agent_family_snapshot
dismissed_identity_dicts = _candidates.dismissed_identity_dicts
extract_family_attach_directive = _directives.extract_family_attach_directive
normalize_family_suffix_arg = _directives.normalize_family_suffix_arg
default_with_feedback_parent_from_family_attach = (
    _directives.default_with_feedback_parent_from_family_attach
)
parse_name_directive_args = _directives.parse_name_directive_args
promote_agent_to_family = _promotion.promote_agent_to_family
promote_family_parent_for_attach = _promotion.promote_family_parent_for_attach


def prepare_family_attach_launch(
    prompt: str,
    context: Any,
    extra_env: dict[str, str] | None,
    *,
    pending_family_parents: list[FamilyAttachSibling] | None = None,
) -> tuple[Any, dict[str, str] | None]:
    """Resolve family attach metadata and return adjusted launch context/env."""
    return _launch.prepare_family_attach_launch(
        prompt,
        context,
        extra_env,
        pending_family_parents=pending_family_parents,
        resolve_family_attach_plan=resolve_family_attach_plan,
    )


def load_family_attach_plan_from_env(
    env: dict[str, str] | None = None,
) -> FamilyAttachLaunchPlan | None:
    return _launch.load_family_attach_plan_from_env(env)


def _resolve_family_attach_plan(
    directive: FamilyAttachDirective,
    *,
    project_name: str,
    pending_family_parents: list[FamilyAttachSibling] | None = None,
) -> FamilyAttachLaunchPlan:
    return _resolution.resolve_family_attach_plan(
        directive,
        project_name=project_name,
        pending_family_parents=pending_family_parents,
        agent_family_snapshot=agent_family_snapshot,
        dismissed_identity_dicts=dismissed_identity_dicts,
    )


resolve_family_attach_plan = _resolve_family_attach_plan


def build_family_attach_sibling_from_spawn(
    request: LaunchSpawnRequest,
    name: str,
    *,
    family_base: str | None = None,
    can_attach_parent: bool = True,
) -> FamilyAttachSibling | None:
    """Return the in-batch sibling descriptor for a successful spawn request."""
    return _launch.build_family_attach_sibling_from_spawn(
        request,
        name,
        family_base=family_base,
        can_attach_parent=can_attach_parent,
    )


__all__ = [
    "FAMILY_ATTACH_ENV",
    "FamilyAttachDirective",
    "FamilyAttachError",
    "FamilyAttachLaunchPlan",
    "FamilyAttachSibling",
    "ParsedNameDirective",
    "build_family_attach_sibling_from_spawn",
    "default_with_feedback_parent_from_family_attach",
    "extract_family_attach_directive",
    "load_family_attach_plan_from_env",
    "normalize_family_suffix_arg",
    "parse_name_directive_args",
    "prepare_family_attach_launch",
    "promote_agent_to_family",
    "promote_family_parent_for_attach",
    "resolve_family_attach_plan",
]
