"""Launch-time family attach context and environment handling."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, replace
import json
import os
from typing import Any, TYPE_CHECKING

from sase.agent import _family_attach_candidates as _candidates
from sase.agent import _family_attach_directives as _directives
from sase.agent import _family_attach_resolution as _resolution
from sase.agent import _family_attach_types as _types

if TYPE_CHECKING:
    from sase.agent.launch_executor_types import LaunchSpawnRequest

_FamilyAttachPlanResolver = Callable[..., _types.FamilyAttachLaunchPlan]


def prepare_family_attach_launch(
    prompt: str,
    context: Any,
    extra_env: dict[str, str] | None,
    *,
    pending_family_parents: list[_types.FamilyAttachSibling] | None = None,
    resolve_family_attach_plan: _FamilyAttachPlanResolver | None = None,
) -> tuple[Any, dict[str, str] | None]:
    """Resolve family attach metadata and return adjusted launch context/env."""

    directive = _directives.extract_family_attach_directive(prompt)
    if directive is None:
        return context, extra_env

    resolver = resolve_family_attach_plan or _resolution.resolve_family_attach_plan
    plan = resolver(
        directive,
        project_name=context.project_name,
        pending_family_parents=pending_family_parents,
    )
    env = dict(extra_env or {})

    from sase.agent.launch_validation import INTERNAL_AGENT_NAME_BYPASS_ENV

    env[INTERNAL_AGENT_NAME_BYPASS_ENV] = "1"
    env[_types.FAMILY_ATTACH_ENV] = json.dumps(asdict(plan), sort_keys=True)
    if plan.sase_plan:
        env["SASE_PLAN"] = plan.sase_plan
    if plan.model_alias_overrides:
        from sase.llm_provider.launch_alias_overrides import (
            SASE_MODEL_ALIAS_OVERRIDES_ENV,
            encode_launch_alias_overrides,
        )

        env[SASE_MODEL_ALIAS_OVERRIDES_ENV] = encode_launch_alias_overrides(
            plan.model_alias_overrides
        )

    context_updates: dict[str, Any] = {}
    if plan.parent_cl_name:
        context_updates["cl_name"] = plan.parent_cl_name
        context_updates["history_sort_key"] = plan.parent_cl_name
    if plan.parent_is_running and not context.is_home_mode:
        context_updates["deferred_workspace"] = True
        context_updates["use_preallocated_workspace"] = False
        if plan.parent_workspace_dir:
            context_updates["workspace_dir"] = plan.parent_workspace_dir
            env["SASE_AGENT_DEFERRED_TARGET_WORKSPACE_DIR"] = plan.parent_workspace_dir
        if plan.parent_workspace_num is not None and plan.parent_workspace_num > 0:
            context_updates["workspace_num"] = plan.parent_workspace_num
            env["SASE_AGENT_DEFERRED_TARGET_WORKSPACE_NUM"] = str(
                plan.parent_workspace_num
            )
    elif (
        plan.parent_workspace_dir
        and plan.parent_workspace_num is not None
        and plan.parent_workspace_num > 0
        and not context.is_home_mode
    ):
        context_updates.update(
            workspace_dir=plan.parent_workspace_dir,
            workspace_num=plan.parent_workspace_num,
            use_preallocated_workspace=True,
            deferred_workspace=False,
        )
    if context_updates:
        context = replace(context, **context_updates)
    return context, env


def load_family_attach_plan_from_env(
    env: dict[str, str] | None = None,
) -> _types.FamilyAttachLaunchPlan | None:
    raw = (env or os.environ).get(_types.FAMILY_ATTACH_ENV)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _types.FamilyAttachError(
            "Invalid SASE_AGENT_FAMILY_ATTACH payload"
        ) from exc
    if not isinstance(data, dict):
        raise _types.FamilyAttachError("Invalid SASE_AGENT_FAMILY_ATTACH payload")
    return _types.FamilyAttachLaunchPlan(
        parent_arg=str(data["parent_arg"]),
        suffix_arg=str(data["suffix_arg"]),
        parent_name=str(data["parent_name"]),
        parent_base=str(data["parent_base"]),
        parent_timestamp=str(data["parent_timestamp"]),
        parent_artifacts_dir=str(data["parent_artifacts_dir"]),
        role_suffix=str(data["role_suffix"]),
        agent_name=str(data["agent_name"]),
        agent_family_role=str(data["agent_family_role"]),
        parent_project_name=str(data.get("parent_project_name") or ""),
        parent_is_running=bool(data.get("parent_is_running", False)),
        parent_cl_name=_str_or_none(data.get("parent_cl_name")),
        parent_workspace_dir=_str_or_none(data.get("parent_workspace_dir")),
        parent_workspace_num=_int_or_none(data.get("parent_workspace_num")),
        sase_plan=_str_or_none(data.get("sase_plan")),
        model_alias_overrides=_string_mapping(data.get("model_alias_overrides")),
    )


def build_family_attach_sibling_from_spawn(
    request: LaunchSpawnRequest,
    name: str,
    *,
    family_base: str | None = None,
    can_attach_parent: bool = True,
) -> _types.FamilyAttachSibling | None:
    """Return the in-batch sibling descriptor for a successful spawn request."""

    if not name or not request.project_name or not request.workspace_dir:
        return None

    from sase.core.agent_artifact_paths import canonical_agent_artifact_path
    from sase.plan_chain import agent_family_base

    artifact_timestamp = _candidates.artifacts_timestamp_from_launch_timestamp(
        request.timestamp
    )
    base = family_base or agent_family_base(name) or name
    from sase.llm_provider.launch_alias_overrides import SASE_MODEL_ALIAS_OVERRIDES_ENV

    raw_overrides = (request.extra_env or {}).get(SASE_MODEL_ALIAS_OVERRIDES_ENV, "")
    return _types.FamilyAttachSibling(
        name=name,
        family_base=base,
        timestamp=artifact_timestamp,
        artifact_dir=str(
            canonical_agent_artifact_path(
                request.project_name,
                "ace-run",
                artifact_timestamp,
            )
        ),
        project_name=request.project_name,
        cl_name=request.cl_name or None,
        workspace_dir=request.workspace_dir,
        workspace_num=request.workspace_num,
        can_attach_parent=can_attach_parent,
        model_alias_overrides=(
            _decode_model_alias_overrides(raw_overrides)
            if raw_overrides
            else _prompt_model_alias_overrides(request.prompt)
        ),
    )


def _decode_model_alias_overrides(raw: str) -> dict[str, str]:
    try:
        return _string_mapping(json.loads(raw))
    except json.JSONDecodeError:
        return {}


def _prompt_model_alias_overrides(prompt: str) -> dict[str, str]:
    try:
        from sase.xprompt.directives import extract_prompt_directives

        _, directives = extract_prompt_directives(prompt)
    except Exception:
        return {}
    return dict(directives.model_alias_overrides)


def _string_mapping(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        key: item
        for key, item in value.items()
        if isinstance(key, str) and isinstance(item, str) and key and item
    }


def _str_or_none(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _int_or_none(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value:
        try:
            return int(value)
        except ValueError:
            return None
    return None


__all__ = [
    "build_family_attach_sibling_from_spawn",
    "load_family_attach_plan_from_env",
    "prepare_family_attach_launch",
    "_int_or_none",
    "_str_or_none",
]
