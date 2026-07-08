"""User-facing ``%n(parent, suffix)`` family attach support."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from sase.agent import _family_attach_candidates as _candidates
from sase.agent import _family_attach_directives as _directives
from sase.agent import _family_attach_launch as _launch
from sase.agent import _family_attach_resolution as _resolution
from sase.agent import _family_attach_types as _types

if TYPE_CHECKING:
    from sase.agent.launch_executor_types import LaunchSpawnRequest

FAMILY_ATTACH_ENV = _types.FAMILY_ATTACH_ENV
FamilyAttachSibling = _types.FamilyAttachSibling
_FamilyAttachDirective = _types._FamilyAttachDirective
_FamilyAttachError = _types._FamilyAttachError
_FamilyAttachLaunchPlan = _types._FamilyAttachLaunchPlan
_ParsedNameDirective = _types._ParsedNameDirective

_agent_family_snapshot = _candidates._agent_family_snapshot
_artifacts_timestamp_from_launch_timestamp = (
    _candidates._artifacts_timestamp_from_launch_timestamp
)
_candidate_from_record = _candidates._candidate_from_record
_candidate_from_sibling = _candidates._candidate_from_sibling
_candidate_is_dismissed = _candidates._candidate_is_dismissed
_candidate_label = _candidates._candidate_label
_candidate_matches_parent = _candidates._candidate_matches_parent
_dismissed_identity_dicts = _candidates._dismissed_identity_dicts
_family_base = _candidates._family_base
_family_role = _resolution._family_role
_family_sase_plan = _candidates._family_sase_plan
_known_agent_names = _candidates._known_agent_names
_known_agent_names_from_siblings = _candidates._known_agent_names_from_siblings
_known_family_suffixes = _candidates._known_family_suffixes
_known_family_suffixes_from_siblings = _candidates._known_family_suffixes_from_siblings
_record_by_artifact_dir = _candidates._record_by_artifact_dir
_record_cl_name = _candidates._record_cl_name
_resolution_error_message = _candidates._resolution_error_message
_resolve_agent_family_parent_fallback = (
    _candidates._resolve_agent_family_parent_fallback
)
_resolve_binding = _candidates._resolve_binding
_resolve_role_suffix = _resolution._resolve_role_suffix
_sibling_by_artifact_dir = _candidates._sibling_by_artifact_dir
_str_or_none = _launch._str_or_none
_int_or_none = _launch._int_or_none
_ensure_family_name_available = _resolution._ensure_family_name_available
_extract_family_attach_directive = _directives._extract_family_attach_directive
_family_attach_parent_from_prompt = _directives._family_attach_parent_from_prompt
_normalize_family_suffix_arg = _directives._normalize_family_suffix_arg
_prompt_segment_at_offset = _directives._prompt_segment_at_offset
default_with_feedback_parent_from_family_attach = (
    _directives.default_with_feedback_parent_from_family_attach
)
parse_name_directive_args = _directives.parse_name_directive_args


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
        resolve_family_attach_plan=_resolve_family_attach_plan,
    )


def load_family_attach_plan_from_env(
    env: dict[str, str] | None = None,
) -> _FamilyAttachLaunchPlan | None:
    return _launch.load_family_attach_plan_from_env(env)


def _resolve_family_attach_plan(
    directive: _FamilyAttachDirective,
    *,
    project_name: str,
    pending_family_parents: list[FamilyAttachSibling] | None = None,
) -> _FamilyAttachLaunchPlan:
    return _resolution._resolve_family_attach_plan(
        directive,
        project_name=project_name,
        pending_family_parents=pending_family_parents,
        agent_family_snapshot=_agent_family_snapshot,
        dismissed_identity_dicts=_dismissed_identity_dicts,
    )


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
    "FamilyAttachSibling",
    "build_family_attach_sibling_from_spawn",
    "default_with_feedback_parent_from_family_attach",
    "load_family_attach_plan_from_env",
    "parse_name_directive_args",
    "prepare_family_attach_launch",
    "_FamilyAttachDirective",
    "_FamilyAttachError",
    "_FamilyAttachLaunchPlan",
    "_ParsedNameDirective",
    "_agent_family_snapshot",
    "_artifacts_timestamp_from_launch_timestamp",
    "_candidate_from_record",
    "_candidate_from_sibling",
    "_candidate_is_dismissed",
    "_candidate_label",
    "_candidate_matches_parent",
    "_dismissed_identity_dicts",
    "_ensure_family_name_available",
    "_extract_family_attach_directive",
    "_family_attach_parent_from_prompt",
    "_family_base",
    "_family_role",
    "_family_sase_plan",
    "_int_or_none",
    "_known_agent_names",
    "_known_agent_names_from_siblings",
    "_known_family_suffixes",
    "_known_family_suffixes_from_siblings",
    "_normalize_family_suffix_arg",
    "_prompt_segment_at_offset",
    "_record_by_artifact_dir",
    "_record_cl_name",
    "_resolution_error_message",
    "_resolve_agent_family_parent_fallback",
    "_resolve_binding",
    "_resolve_family_attach_plan",
    "_resolve_role_suffix",
    "_sibling_by_artifact_dir",
    "_str_or_none",
]
