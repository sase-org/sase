"""Mobile agent bridge facade."""

# ruff: noqa: F401

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, TextIO

from ._mobile_agent_common import (
    MOBILE_AGENT_SCHEMA_VERSION,
    _IMAGE_TYPES,
    _MAX_IMAGE_UPLOAD_BYTES,
    _PROMPT_SNIPPET_LIMIT,
    _SAFE_CONTEXT_COMPONENT_RE,
    _SAFE_DEVICE_ID_RE,
    _SAFE_DIRECTIVE_NAME_RE,
    _SAFE_PROJECT_NAME_RE,
    MobileAgentBridgeError as _MobileAgentBridgeError,
    MobileAgentInvalidUploadError as _MobileAgentInvalidUploadError,
    MobileAgentListRequest as _MobileAgentListRequest,
    MobileAgentNotFoundError as _MobileAgentNotFoundError,
    MobileAgentNotRunningError as _MobileAgentNotRunningError,
    MobileAgentPermissionDeniedError as _MobileAgentPermissionDeniedError,
    MobileProjectContext as _MobileProjectContext,
    directive_name as _directive_name,
    mobile_model_directive_value as _mobile_model_directive_value,
    optional_str as _optional_str,
    optional_uint as _optional_uint,
    option_id as _option_id,
    required_bridge_str as _required_bridge_str,
    required_byte_length as _required_byte_length,
    required_str as _required_str,
    safe_context_id as _safe_context_id,
    safe_device_id as _safe_device_id,
    safe_error_message as _safe_error_message,
)
from ._mobile_agent_context import (
    known_project_file as _known_project_file,
    launch_cwd_for_project_context as _launch_cwd_for_project_context,
    mobile_launch_cwd as _mobile_launch_cwd,
    mobile_prompt_vcs_ref as _mobile_prompt_vcs_ref,
    persist_last_mobile_project_context as _persist_last_mobile_project_context,
    project_context_from_agent as _project_context_from_agent,
    project_context_from_context as _project_context_from_context,
    project_context_from_project_value as _project_context_from_project_value,
    project_context_from_prompt as _project_context_from_prompt,
    project_context_from_request as _project_context_from_request,
    project_context_to_record as _project_context_to_record,
)
from ._mobile_agent_deps import (
    AgentLaunchResult,
    KillResult,
    RunningAgentInfo,
    allocate_retry_name,
    kill_named_agent,
    launch_agents_from_cwd,
    list_all_agents,
    list_running_agents,
    rewrite_retry_prompt_name,
)
from ._mobile_agent_launch import (
    artifact_dir_for_launch as _artifact_dir_for_launch,
    atomic_write_bytes as _atomic_write_bytes,
    dry_run_launch_response as _dry_run_launch_response,
    generated_image_filename as _generated_image_filename,
    launch_mobile_image_agents as _launch_mobile_image_agents,
    launch_mobile_prompt as _launch_mobile_prompt,
    launch_mobile_text_agents as _launch_mobile_text_agents,
    matches_magic as _matches_magic,
    mobile_image_launch_prompt as _mobile_image_launch_prompt,
    mobile_launch_prompt as _mobile_launch_prompt,
    mobile_launch_response as _mobile_launch_response,
    planned_name_for_prompt as _planned_name_for_prompt,
    prompt_has_name_directive as _prompt_has_name_directive,
    result_to_slot as _result_to_slot,
    store_mobile_image_upload as _store_mobile_image_upload,
)
from ._mobile_agent_lifecycle import (
    kill_mobile_agent as _kill_mobile_agent,
    raise_lifecycle_error as _raise_lifecycle_error,
    resolve_mobile_retry_context as _resolve_mobile_retry_context,
    retry_mobile_agent as _retry_mobile_agent,
    retry_prompt_from_context as _retry_prompt_from_context,
)
from ._mobile_agent_paths import (
    device_project_context_path as _device_project_context_path,
    mobile_gateway_state_dir as _mobile_gateway_state_dir,
    mobile_image_upload_dir as _mobile_image_upload_dir,
    mobile_kill_context_dir as _mobile_kill_context_dir,
    mobile_launch_context_store_path as _mobile_launch_context_store_path,
    mobile_device_project_context_path,
    sase_home as _sase_home,
)
from ._mobile_agent_state import (
    agent_name_from_artifact_meta as _agent_name_from_artifact_meta,
    artifact_timestamp as _artifact_timestamp,
    context_from_agent as _context_from_agent,
    iter_mobile_launch_contexts as _iter_mobile_launch_contexts,
    latest_mobile_launch_context as _latest_mobile_launch_context,
    mobile_kill_context as _mobile_kill_context,
    persist_mobile_kill_context as _persist_mobile_kill_context,
    persist_mobile_launch_contexts as _persist_mobile_launch_contexts,
    project_context_from_kill_or_launch_context as _project_context_from_kill_or_launch_context,
    project_from_artifact_dir as _project_from_artifact_dir,
    read_prompt_file as _read_prompt_file,
)
from ._mobile_agent_summary import (
    agent_summary as _agent_summary,
    filter_agents as _filter_agents,
    find_mobile_agent_summary as _find_mobile_agent_summary,
    list_mobile_agents as _list_mobile_agents,
    mobile_agent_resume_options as _mobile_agent_resume_options,
    parse_list_request as _parse_list_request,
    prompt_snippet as _prompt_snippet,
    retry_lineage as _retry_lineage,
    subtitle as _subtitle,
)

__all__ = [
    "MOBILE_AGENT_SCHEMA_VERSION",
    "handle_mobile_agent_bridge",
    "mobile_device_project_context_path",
]


def handle_mobile_agent_bridge(
    args: argparse.Namespace,
    *,
    stdin: TextIO = sys.stdin,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    """Run one fixed mobile agent bridge operation over JSON stdin/stdout."""
    try:
        request = _read_request(stdin)
        operation = getattr(args, "mobile_agent_bridge_subcommand", None)
        if operation == "list-agents":
            response = _list_mobile_agents(request)
        elif operation == "resume-options":
            response = _mobile_agent_resume_options()
        elif operation == "launch-text":
            response = _launch_mobile_text_agents(request)
        elif operation == "launch-image":
            response = _launch_mobile_image_agents(request)
        elif operation == "kill-agent":
            response = _kill_mobile_agent(request)
        elif operation == "retry-agent":
            response = _retry_mobile_agent(request)
        else:
            raise _MobileAgentBridgeError("unknown mobile agent bridge operation")
    except _MobileAgentInvalidUploadError as exc:
        print(f"mobile agent bridge error: {exc}", file=stderr)
        return 3
    except _MobileAgentNotFoundError as exc:
        print(f"mobile agent bridge error: {exc}", file=stderr)
        return 4
    except _MobileAgentNotRunningError as exc:
        print(f"mobile agent bridge error: {exc}", file=stderr)
        return 5
    except _MobileAgentPermissionDeniedError as exc:
        print(f"mobile agent bridge error: {exc}", file=stderr)
        return 6
    except (_MobileAgentBridgeError, ValueError, TypeError) as exc:
        print(f"mobile agent bridge error: {exc}", file=stderr)
        return 2

    json.dump(response, stdout, separators=(",", ":"))
    stdout.write("\n")
    return 0


def _read_request(stdin: TextIO) -> dict[str, Any]:
    raw = stdin.read()
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise _MobileAgentBridgeError(f"invalid JSON request: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise _MobileAgentBridgeError("request JSON must be an object")
    return payload
