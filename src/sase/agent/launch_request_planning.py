"""Validation and preview planning for launch approval requests."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from sase.agent.launch_request_types import (
    LAUNCH_REQUEST_SCHEMA_VERSION,
    LaunchRequestError,
)


def normalize_request_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    schema_version = payload.get("schema_version")
    if schema_version != LAUNCH_REQUEST_SCHEMA_VERSION:
        raise LaunchRequestError(
            "invalid_schema",
            "schema_version",
            f"schema_version must be {LAUNCH_REQUEST_SCHEMA_VERSION}",
        )

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise LaunchRequestError("invalid_request", "prompt", "prompt is required")

    reason = payload.get("reason")
    if reason is None:
        reason = "Detached launch requested."
    if not isinstance(reason, str) or not reason.strip():
        raise LaunchRequestError("invalid_request", "reason", "reason is required")

    approval = payload.get("approval", "required")
    if approval != "required":
        raise LaunchRequestError(
            "unsupported_approval",
            "approval",
            "only approval='required' is supported",
        )

    raw_max_slots = payload.get("max_slots", 1)
    try:
        max_slots = int(raw_max_slots)
    except (TypeError, ValueError) as exc:
        raise LaunchRequestError(
            "invalid_request", "max_slots", "max_slots must be an integer"
        ) from exc
    if max_slots < 1:
        raise LaunchRequestError(
            "invalid_request", "max_slots", "max_slots must be at least 1"
        )

    normalized: dict[str, Any] = {
        "schema_version": LAUNCH_REQUEST_SCHEMA_VERSION,
        "prompt": prompt,
        "reason": reason,
        "approval": approval,
        "max_slots": max_slots,
    }
    family_type = payload.get("family_type")
    if family_type is not None:
        if not isinstance(family_type, str) or not family_type.strip():
            raise LaunchRequestError(
                "invalid_request", "family_type", "family_type must be a string"
            )
        normalized["family_type"] = family_type
    return normalized


def build_preview_plan(prompt: str) -> tuple[str, Any]:
    from sase.agent.multi_prompt import parse_multi_prompt
    from sase.agent.xprompt_swarm import expand_xprompt_swarms_with_metadata
    from sase.project_aliases import canonicalize_project_aliases_in_prompt
    from sase.xprompt._parsing import (
        normalize_default_vcs_workflow,
        normalize_default_vcs_workflow_segment,
    )

    submitted = canonicalize_project_aliases_in_prompt(prompt)
    multi = parse_multi_prompt(submitted)
    expanded_records = expand_xprompt_swarms_with_metadata(
        multi.segments, multi.local_xprompts
    )
    expanded_segments = [record.prompt for record in expanded_records]
    if len(expanded_segments) > 1:
        from sase.core.agent_launch_facade import plan_fake_fanout

        normalized_segments = [
            normalize_default_vcs_workflow_segment(segment)
            for segment in expanded_segments
        ]
        return "\n---\n".join(normalized_segments), plan_fake_fanout(
            "multi_prompt", normalized_segments
        )

    query = normalize_default_vcs_workflow(expanded_segments[0])

    from sase.core.agent_launch_facade import plan_agent_launch_fanout, plan_fake_fanout

    repeat_plan = plan_agent_launch_fanout(query, launch_kind="repeat")
    if repeat_plan.slots:
        return query, repeat_plan

    from sase.xprompt.directives import plan_prompt_fanout_variants

    fanout_plan = plan_prompt_fanout_variants(query)
    if fanout_plan is None and "#" in query:
        from sase.xprompt.processor import (
            process_xprompt_references,
            prompt_may_reference_xprompt,
        )

        if prompt_may_reference_xprompt(query):
            expanded = process_xprompt_references(query)
            fanout_plan = plan_prompt_fanout_variants(expanded)
    if fanout_plan is not None:
        return query, fanout_plan
    return query, plan_fake_fanout("single", [query])


def preview_context() -> Any:
    from sase.agent.launch_executor import LaunchExecutionContext
    from sase.core.paths import sase_projects_dir
    from sase.main.utils import ensure_project_file_and_get_workspace_num

    project_file, workspace_num, project_name = (
        ensure_project_file_and_get_workspace_num(create_missing=False)
    )
    is_home_mode = project_file is None
    if is_home_mode:
        from sase.ace.changespec.project_spec_path import preferred_project_spec_path

        project_name = "home"
        home_dir = str(sase_projects_dir() / "home")
        project_file = preferred_project_spec_path(home_dir, "home")
        workspace_num = 0

    assert project_file is not None
    assert project_name is not None
    return LaunchExecutionContext(
        cl_name=project_name,
        project_file=project_file,
        project_name=project_name,
        is_home_mode=is_home_mode,
        workspace_num=workspace_num,
        workspace_dir=str(Path.cwd()) if is_home_mode else None,
    )


def requester_context() -> dict[str, str]:
    keys = (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_ARTIFACTS_DIR",
        "SASE_AGENT_WORKFLOW_NAME",
    )
    return {key: value for key in keys if (value := os.environ.get(key))}
