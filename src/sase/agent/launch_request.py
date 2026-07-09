"""Host-side LaunchApproval request creation and approved dispatch."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.agent.launch_preview import (
    LAUNCH_REQUEST_FILE,
    build_launch_preview_request,
    write_launch_preview_files,
)
from sase.agent.launch_types import AgentLaunchResult

LAUNCH_REQUEST_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class LaunchRequestCreationResult:
    request_id: str
    notification_id: str
    response_dir: Path
    request_path: Path
    preview_path: Path
    response_path: Path
    request: dict[str, Any]


@dataclass(frozen=True)
class _ApprovedLaunchDispatchResult:
    request_id: str
    results: list[AgentLaunchResult]

    @property
    def launched_count(self) -> int:
        return len(self.results)


class LaunchRequestError(RuntimeError):
    """Deterministic launch-request validation or dispatch failure."""

    def __init__(self, code: str, target: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.target = target


def create_launch_approval_request_from_prompt(
    prompt: str,
    *,
    reason: str,
    approval: str = "required",
    max_slots: int = 1,
    source_surface: str | None = None,
) -> LaunchRequestCreationResult:
    """Create a pending LaunchApproval request from a prompt string."""
    return create_launch_approval_request(
        {
            "schema_version": LAUNCH_REQUEST_SCHEMA_VERSION,
            "prompt": prompt,
            "reason": reason,
            "approval": approval,
            "max_slots": max_slots,
        },
        source_surface=source_surface,
    )


def create_launch_approval_request(
    payload: Mapping[str, Any],
    *,
    source_surface: str | None = None,
) -> LaunchRequestCreationResult:
    """Build preview files, register a LaunchApproval, and return its id."""
    normalized = _normalize_request_payload(payload)
    source = source_surface or _default_source_surface()
    prompt = str(normalized["prompt"])
    max_slots = int(normalized["max_slots"])
    _preview_prompt, plan = _build_preview_plan(prompt)
    slot_count = len(plan.slots)
    if slot_count > max_slots:
        raise LaunchRequestError(
            "max_slots_exceeded",
            "max_slots",
            f"launch request plans {slot_count} slot(s), max_slots is {max_slots}",
        )

    context = _preview_context()
    request = build_launch_preview_request(
        plan=plan,
        context=context,
        source_surface=source,
        submitted_prompt=prompt,
    )
    request["launch_request"] = normalized
    request["requester"] = _requester_context()
    request["dispatch"] = {
        "cwd": str(Path.cwd()),
        "prompt": prompt,
    }

    paths = write_launch_preview_files(request)
    from sase.notifications.senders import notify_launch_approval

    notification_id = notify_launch_approval(
        request_id=str(request["request_id"]),
        response_dir=str(paths["response_dir"]),
        source_surface=source,
        slot_count=slot_count,
        preview_file=str(paths["preview"]),
        request_file=str(paths["request"]),
    )
    return LaunchRequestCreationResult(
        request_id=str(request["request_id"]),
        notification_id=notification_id,
        response_dir=paths["response_dir"],
        request_path=paths["request"],
        preview_path=paths["preview"],
        response_path=paths["response"],
        request=request,
    )


def dispatch_approved_launch_request(
    response_dir: Path,
) -> _ApprovedLaunchDispatchResult:
    """Dispatch the launch described by an approved request directory."""
    request_path = response_dir / LAUNCH_REQUEST_FILE
    try:
        data = json.loads(request_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise LaunchRequestError(
            "invalid_request", str(request_path), "launch request is missing"
        ) from exc
    except json.JSONDecodeError as exc:
        raise LaunchRequestError(
            "invalid_request", str(request_path), "launch request is not valid JSON"
        ) from exc
    if not isinstance(data, dict):
        raise LaunchRequestError(
            "invalid_request", str(request_path), "launch request must be an object"
        )

    dispatch = data.get("dispatch")
    if not isinstance(dispatch, dict):
        raise LaunchRequestError(
            "invalid_request", "dispatch", "launch request has no dispatch payload"
        )
    prompt = dispatch.get("prompt")
    cwd = dispatch.get("cwd")
    if not isinstance(prompt, str) or not prompt.strip():
        raise LaunchRequestError(
            "invalid_request", "dispatch.prompt", "dispatch prompt is missing"
        )
    if not isinstance(cwd, str) or not cwd:
        raise LaunchRequestError(
            "invalid_request", "dispatch.cwd", "dispatch cwd is missing"
        )

    cwd_path = Path(cwd).expanduser()
    if not cwd_path.is_dir():
        raise LaunchRequestError(
            "invalid_request", "dispatch.cwd", f"dispatch cwd does not exist: {cwd}"
        )

    original_cwd = Path.cwd()
    try:
        os.chdir(cwd_path)
        from sase.agent import launcher as launcher_mod

        results = launcher_mod.launch_agents_from_cwd(prompt)
    finally:
        os.chdir(original_cwd)

    return _ApprovedLaunchDispatchResult(
        request_id=str(data.get("request_id") or ""),
        results=results,
    )


def running_agent_context_requires_launch_approval() -> bool:
    """Return whether this process is running inside an agent context."""
    return bool(os.environ.get("SASE_AGENT"))


def _normalize_request_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
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


def _build_preview_plan(prompt: str) -> tuple[str, Any]:
    from sase.agent.xprompt_swarm import expand_xprompt_swarms_with_metadata
    from sase.agent.multi_prompt import parse_multi_prompt
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


def _preview_context() -> Any:
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


def _requester_context() -> dict[str, str]:
    keys = (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_ARTIFACTS_DIR",
        "SASE_AGENT_WORKFLOW_NAME",
    )
    return {key: value for key in keys if (value := os.environ.get(key))}


def _default_source_surface() -> str:
    return "agent_skill" if running_agent_context_requires_launch_approval() else "cli"


__all__ = [
    "LAUNCH_REQUEST_SCHEMA_VERSION",
    "LaunchRequestCreationResult",
    "LaunchRequestError",
    "create_launch_approval_request",
    "create_launch_approval_request_from_prompt",
    "dispatch_approved_launch_request",
    "running_agent_context_requires_launch_approval",
]
