"""Request-payload helpers for typed launch admission."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.agent.launch_request_types import LaunchRequestError
from sase.core.agent_launch_wire import LaunchPlanWire, launch_plan_from_dict


def typed_plan_from_request(data: Mapping[str, Any]) -> LaunchPlanWire:
    raw = data.get("typed_plan")
    if not isinstance(raw, dict):
        raise LaunchRequestError(
            "invalid_request",
            "typed_plan",
            "typed launch plan is missing",
        )
    plan = launch_plan_from_dict(raw)
    # An approval authorizes exactly the plan the user was shown, identified by
    # its content digest. Admitting a plan whose digest no longer matches would
    # dispatch unapproved units.
    digest = data.get("plan_digest")
    if digest not in (None, "") and str(digest) != plan.content_digest:
        raise LaunchRequestError(
            "plan_digest_mismatch",
            "plan_digest",
            "approved launch plan digest does not match typed_plan.content_digest",
        )
    return plan


def request_source_cwd(data: Mapping[str, Any]) -> str | None:
    dispatch = data.get("dispatch")
    if not isinstance(dispatch, Mapping):
        return None
    cwd = dispatch.get("cwd")
    return None if cwd is None else str(cwd)


def request_project_file(data: Mapping[str, Any]) -> str | None:
    raw = data.get("project_file")
    return str(raw) if raw else None


def request_safe_inputs(data: Mapping[str, Any]) -> dict[str, Any]:
    raw = data.get("safe_inputs")
    if isinstance(raw, Mapping):
        return {str(key): value for key, value in raw.items()}
    request = data.get("launch_request")
    if isinstance(request, Mapping) and isinstance(request.get("inputs"), Mapping):
        return {str(key): value for key, value in request["inputs"].items()}
    return {}


__all__ = [
    "request_project_file",
    "request_safe_inputs",
    "request_source_cwd",
    "typed_plan_from_request",
]
