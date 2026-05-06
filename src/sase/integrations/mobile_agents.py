"""Read-only mobile agent bridge projections."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from sase.agent.launcher import AgentLaunchResult, launch_agents_from_cwd
from sase.agent.names import allocate_retry_name
from sase.agent.retry_prompt import rewrite_retry_prompt_name
from sase.agent.running import (
    KillResult,
    RunningAgentInfo,
    kill_named_agent,
    list_all_agents,
    list_running_agents,
)
from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.xprompt._parsing import normalize_launch_xprompt_at_refs

MOBILE_AGENT_SCHEMA_VERSION = 1

_PROMPT_SNIPPET_LIMIT = 200
_SAFE_DIRECTIVE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_SAFE_DEVICE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_MAX_IMAGE_UPLOAD_BYTES = 10 * 1024 * 1024
_IMAGE_TYPES: dict[str, tuple[str, bytes | tuple[bytes, ...]]] = {
    ".png": ("image/png", b"\x89PNG\r\n\x1a\n"),
    ".jpg": ("image/jpeg", b"\xff\xd8\xff"),
    ".jpeg": ("image/jpeg", b"\xff\xd8\xff"),
    ".webp": ("image/webp", b"RIFF"),
    ".gif": ("image/gif", (b"GIF87a", b"GIF89a")),
}


class _MobileAgentBridgeError(RuntimeError):
    """Deterministic bridge error for JSON command failures."""


class _MobileAgentInvalidUploadError(_MobileAgentBridgeError):
    """Deterministic bridge error for rejected mobile image uploads."""


class _MobileAgentNotFoundError(_MobileAgentBridgeError):
    """Deterministic bridge error for missing mobile agent lifecycle targets."""


class _MobileAgentNotRunningError(_MobileAgentBridgeError):
    """Deterministic bridge error for non-running mobile lifecycle targets."""


class _MobileAgentPermissionDeniedError(_MobileAgentBridgeError):
    """Deterministic bridge error for denied host lifecycle mutations."""


@dataclass(frozen=True)
class _MobileAgentListRequest:
    include_recent: bool = False
    status: str | None = None
    project: str | None = None
    limit: int | None = None


def _list_mobile_agents(request: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return mobile-shaped agent summaries for running/recent agents."""
    parsed = _parse_list_request(request or {})
    agents = list_all_agents() if parsed.include_recent else list_running_agents()
    agents = _filter_agents(agents, parsed)
    total_count = len(agents)
    if parsed.limit is not None:
        agents = agents[: parsed.limit]
    return {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "agents": [_agent_summary(agent) for agent in agents],
        "total_count": total_count,
    }


def _mobile_agent_resume_options() -> dict[str, Any]:
    """Return copy/share/direct-launch resume and wait prompt options."""
    options: list[dict[str, Any]] = []
    seen: set[str] = set()
    for agent in list_all_agents():
        if not agent.name or agent.name in seen:
            continue
        seen.add(agent.name)
        quoted_name = _directive_name(agent.name)
        options.extend(
            [
                {
                    "id": f"{_option_id(agent.name)}:resume",
                    "agent_name": agent.name,
                    "kind": "resume",
                    "label": f"Resume {agent.name}",
                    "prompt_text": f"#resume:{quoted_name}\n",
                    "direct_launch_supported": True,
                },
                {
                    "id": f"{_option_id(agent.name)}:wait",
                    "agent_name": agent.name,
                    "kind": "wait",
                    "label": f"Wait for {agent.name}",
                    "prompt_text": f"%wait:{quoted_name}\n",
                    "direct_launch_supported": True,
                },
            ]
        )
    return {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "options": options,
    }


def _launch_mobile_text_agents(request: dict[str, Any]) -> dict[str, Any]:
    """Launch text agents through the normal SASE launch path."""
    prompt = _mobile_launch_prompt(request)
    return _launch_mobile_prompt(prompt, request, launch_kind="text")


def _launch_mobile_image_agents(request: dict[str, Any]) -> dict[str, Any]:
    """Store an uploaded image and launch agents with a local image path prompt."""
    stored_path = _store_mobile_image_upload(request)
    prompt = _mobile_image_launch_prompt(request, stored_path)
    return _launch_mobile_prompt(
        prompt, request, launch_kind="image", image_host_path=str(stored_path)
    )


def _kill_mobile_agent(request: dict[str, Any]) -> dict[str, Any]:
    """Kill a named agent and persist retry context for mobile follow-up."""
    name = _required_bridge_str(request.get("name"), "name")
    before = _find_mobile_agent_summary(name)
    result = kill_named_agent(name, exact_name=True)
    if not result.success:
        _raise_lifecycle_error(result)

    _persist_mobile_kill_context(name, request, before, result)
    return {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "name": name,
        "status": result.status or "killed",
        "pid": _optional_uint(result.pid),
        "changed": bool(result.changed),
        "message": result.message,
    }


def _retry_mobile_agent(request: dict[str, Any]) -> dict[str, Any]:
    """Retry an agent from artifacts or durable mobile launch context."""
    source_name = _required_bridge_str(request.get("name"), "name")
    context = _resolve_mobile_retry_context(source_name)
    prompt = _retry_prompt_from_context(context, request)

    if request.get("kill_source_first") is True:
        result = kill_named_agent(source_name, exact_name=True)
        if not result.success and result.reason == "permission_denied":
            _raise_lifecycle_error(result)

    retry_name = allocate_retry_name(context["agent_name"])
    retry_prompt = rewrite_retry_prompt_name(prompt, retry_name)
    launch = _launch_mobile_prompt(
        retry_prompt,
        {
            **request,
            "name": None,
        },
        launch_kind="retry",
        source_agent_name=context["agent_name"],
        retry_of_agent=context["agent_name"],
    )
    return {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "source_agent": context["agent_name"],
        "launch": launch,
    }


def _launch_mobile_prompt(
    prompt: str,
    request: dict[str, Any],
    *,
    launch_kind: str,
    image_host_path: str | None = None,
    source_agent_name: str | None = None,
    retry_of_agent: str | None = None,
) -> dict[str, Any]:
    planned_name = _planned_name_for_prompt(prompt)
    if request.get("dry_run") is True:
        return _dry_run_launch_response(prompt)

    try:
        results = launch_agents_from_cwd(prompt)
    except Exception as exc:
        raise _MobileAgentBridgeError(_safe_error_message(exc)) from exc

    if not results:
        raise _MobileAgentBridgeError("agent launch produced no results")
    response = _mobile_launch_response(results, planned_name=planned_name)
    _persist_mobile_launch_contexts(
        response,
        prompt,
        request,
        launch_kind=launch_kind,
        image_host_path=image_host_path,
        source_agent_name=source_agent_name,
        retry_of_agent=retry_of_agent,
    )
    return response


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


def _parse_list_request(payload: dict[str, Any]) -> _MobileAgentListRequest:
    raw_limit = payload.get("limit")
    limit: int | None = None
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError) as exc:
            raise _MobileAgentBridgeError("limit must be an integer") from exc
        if limit < 0:
            raise _MobileAgentBridgeError("limit must be non-negative")

    status = payload.get("status")
    if status is not None and not isinstance(status, str):
        raise _MobileAgentBridgeError("status must be a string")
    project = payload.get("project")
    if project is not None and not isinstance(project, str):
        raise _MobileAgentBridgeError("project must be a string")

    return _MobileAgentListRequest(
        include_recent=bool(payload.get("include_recent", False)),
        status=status.strip().upper() if status and status.strip() else None,
        project=project.strip() if project and project.strip() else None,
        limit=limit,
    )


def _mobile_launch_prompt(payload: dict[str, Any]) -> str:
    raw_prompt = payload.get("prompt")
    if not isinstance(raw_prompt, str) or not raw_prompt.strip():
        raise _MobileAgentBridgeError("prompt must be a non-empty string")

    prompt = normalize_launch_xprompt_at_refs(raw_prompt.strip())
    directives: list[str] = []
    name = _optional_str(payload.get("name"))
    if name:
        if _prompt_has_name_directive(prompt):
            raise _MobileAgentBridgeError(
                "name cannot be provided when prompt already has a name directive"
            )
        directives.append(f"%name:{_directive_name(name)}")

    model = _optional_str(payload.get("model"))
    provider = _optional_str(payload.get("provider"))
    runtime = _optional_str(payload.get("runtime"))
    model_value = _mobile_model_directive_value(model, provider, runtime)
    if model_value:
        directives.append(f"%model:{model_value}")

    if directives:
        prompt = "\n".join([*directives, prompt])
    return prompt


def _mobile_image_launch_prompt(payload: dict[str, Any], image_path: Path) -> str:
    prompt = _mobile_launch_prompt(payload)
    return f"The image has been saved to: {image_path}\n\n{prompt}"


def _store_mobile_image_upload(payload: dict[str, Any]) -> Path:
    filename = _required_str(payload.get("original_filename"), "original_filename")
    content_type = _required_str(payload.get("content_type"), "content_type").lower()
    byte_length = _required_byte_length(payload.get("byte_length"))
    raw_base64 = _required_str(payload.get("base64_image"), "base64_image")

    extension = Path(filename).suffix.lower()
    if not extension or extension not in _IMAGE_TYPES:
        raise _MobileAgentInvalidUploadError("unsupported image extension")
    expected_content_type, magic = _IMAGE_TYPES[extension]
    if content_type != expected_content_type:
        raise _MobileAgentInvalidUploadError(
            "image extension does not match content type"
        )
    if byte_length > _MAX_IMAGE_UPLOAD_BYTES:
        raise _MobileAgentInvalidUploadError("image upload exceeds maximum size")

    try:
        image_bytes = base64.b64decode(raw_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _MobileAgentInvalidUploadError("invalid base64 image data") from exc
    if len(image_bytes) != byte_length:
        raise _MobileAgentInvalidUploadError(
            "byte_length does not match decoded image size"
        )
    if len(image_bytes) > _MAX_IMAGE_UPLOAD_BYTES:
        raise _MobileAgentInvalidUploadError("image upload exceeds maximum size")
    if not _matches_magic(image_bytes, magic, extension):
        raise _MobileAgentInvalidUploadError("image bytes do not match content type")

    device_id = _safe_device_id(_optional_str(payload.get("device_id")))
    upload_dir = _mobile_image_upload_dir(device_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    final_path = upload_dir / _generated_image_filename(extension)
    return _atomic_write_bytes(upload_dir, final_path, image_bytes)


def _matches_magic(
    image_bytes: bytes, magic: bytes | tuple[bytes, ...], extension: str
) -> bool:
    if extension == ".webp":
        return (
            len(image_bytes) >= 12
            and image_bytes.startswith(b"RIFF")
            and image_bytes[8:12] == b"WEBP"
        )
    if isinstance(magic, tuple):
        return any(image_bytes.startswith(prefix) for prefix in magic)
    return image_bytes.startswith(magic)


def _mobile_image_upload_dir(device_id: str) -> Path:
    sase_home = Path(os.environ.get("SASE_HOME") or Path.home() / ".sase")
    return sase_home / "mobile_gateway" / "uploads" / "images" / device_id


def _generated_image_filename(extension: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}_{uuid.uuid4().hex}{extension}"


def _atomic_write_bytes(upload_dir: Path, final_path: Path, image_bytes: bytes) -> Path:
    tmp_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb", dir=upload_dir, prefix=".upload-", suffix=".tmp", delete=False
        ) as tmp:
            tmp.write(image_bytes)
            tmp.flush()
            os.fsync(tmp.fileno())
            tmp_name = tmp.name
        os.replace(tmp_name, final_path)
        return final_path
    except OSError as exc:
        if tmp_name is not None:
            Path(tmp_name).unlink(missing_ok=True)
        raise _MobileAgentInvalidUploadError("failed to store image upload") from exc


def _required_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _MobileAgentInvalidUploadError(f"{field} must be a non-empty string")
    return value.strip()


def _required_bridge_str(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _MobileAgentBridgeError(f"{field} must be a non-empty string")
    return value.strip()


def _required_byte_length(value: Any) -> int:
    try:
        byte_length = int(value)
    except (TypeError, ValueError) as exc:
        raise _MobileAgentInvalidUploadError("byte_length must be an integer") from exc
    if byte_length < 0:
        raise _MobileAgentInvalidUploadError("byte_length must be non-negative")
    return byte_length


def _safe_device_id(device_id: str | None) -> str:
    if not device_id:
        return "unknown_device"
    safe = _SAFE_DEVICE_ID_RE.sub("-", device_id).strip(".-")
    return safe or "unknown_device"


def _mobile_model_directive_value(
    model: str | None,
    provider: str | None,
    runtime: str | None,
) -> str | None:
    if model is None:
        return None
    prefix = provider or runtime
    if prefix and "/" not in model:
        return f"{prefix}/{model}"
    return model


def _prompt_has_name_directive(prompt: str) -> bool:
    if "%" not in prompt:
        return False
    from sase.agent.multi_prompt_references import extract_static_name_directive

    return extract_static_name_directive(prompt) is not None or bool(
        re.search(r"(?:^|\s)%(?:name|n)(?:[:+(]|\s|$)", prompt, re.MULTILINE)
    )


def _dry_run_launch_response(prompt: str) -> dict[str, Any]:
    slot = {
        "slot_id": "0",
        "name": _planned_name_for_prompt(prompt),
        "status": "dry_run",
        "artifact_dir": None,
        "message": "launch request validated",
    }
    return {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "primary": slot,
        "slots": [slot],
    }


def _mobile_launch_response(
    results: list[AgentLaunchResult],
    *,
    planned_name: str | None = None,
) -> dict[str, Any]:
    slots = [
        _result_to_slot(
            str(index),
            result,
            planned_name=planned_name if index == 0 else None,
        )
        for index, result in enumerate(results)
    ]
    return {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "primary": slots[0] if slots else None,
        "slots": slots,
    }


def _result_to_slot(
    slot_id: str,
    result: AgentLaunchResult,
    *,
    planned_name: str | None,
) -> dict[str, Any]:
    return {
        "slot_id": slot_id,
        "name": planned_name,
        "status": "launched",
        "artifact_dir": _artifact_dir_for_launch(result),
        "message": f"started pid {result.pid}",
    }


def _artifact_dir_for_launch(result: AgentLaunchResult) -> str | None:
    if not result.timestamp or not result.project_name:
        return None
    artifacts_timestamp = convert_timestamp_to_artifacts_format(result.timestamp)
    return str(
        Path.home()
        / ".sase"
        / "projects"
        / result.project_name
        / "artifacts"
        / "ace-run"
        / artifacts_timestamp
    )


def _planned_name_for_prompt(prompt: str) -> str | None:
    from sase.agent.multi_prompt_references import extract_static_name_directive

    return extract_static_name_directive(prompt)


def _safe_error_message(exc: BaseException) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


def _filter_agents(
    agents: list[RunningAgentInfo],
    request: _MobileAgentListRequest,
) -> list[RunningAgentInfo]:
    filtered = agents
    if request.project:
        filtered = [agent for agent in filtered if agent.project == request.project]
    if request.status:
        filtered = [
            agent for agent in filtered if agent.status.upper() == request.status
        ]
    return filtered


def _agent_summary(agent: RunningAgentInfo) -> dict[str, Any]:
    name = agent.name or "(unnamed)"
    has_name = bool(agent.name)
    has_artifact_dir = bool(agent.artifacts_dir and Path(agent.artifacts_dir).is_dir())
    context = _latest_mobile_launch_context(name) if has_name else None
    retry_lineage = _retry_lineage(agent.artifacts_dir, context)
    prompt = _prompt_snippet(agent.prompt)

    return {
        "name": name,
        "project": agent.project or None,
        "status": agent.status.lower(),
        "pid": _optional_uint(agent.pid),
        "model": agent.model,
        "provider": agent.provider,
        "workspace_number": _optional_uint(agent.workspace_num),
        "started_at": agent.started_at.isoformat() if agent.started_at else None,
        "duration_seconds": _optional_uint(agent.duration_seconds),
        "prompt_snippet": prompt,
        "has_artifact_dir": has_artifact_dir,
        "retry_lineage": retry_lineage,
        "actions": {
            "can_resume": has_name,
            "can_wait": has_name,
            "can_kill": has_name and agent.status.upper() == "RUNNING",
            "can_retry": has_name and (has_artifact_dir or context is not None),
        },
        "display": {
            "title": name,
            "subtitle": _subtitle(agent),
            "status_label": agent.status.replace("_", " ").title(),
        },
    }


def _retry_lineage(
    artifacts_dir: str | None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    empty = {
        "retry_of_timestamp": None,
        "retried_as_timestamp": None,
        "retry_chain_root_timestamp": None,
        "retry_attempt": None,
        "parent_agent_name": _optional_str(context.get("source_agent_name"))
        if context is not None
        else None,
    }
    if not artifacts_dir:
        return empty
    meta_path = Path(artifacts_dir) / "agent_meta.json"
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty
    if not isinstance(data, dict):
        return empty
    return {
        "retry_of_timestamp": _optional_str(data.get("retry_of_timestamp")),
        "retried_as_timestamp": _optional_str(data.get("retried_as_timestamp")),
        "retry_chain_root_timestamp": _optional_str(
            data.get("retry_chain_root_timestamp")
        ),
        "retry_attempt": _optional_uint(data.get("retry_attempt")),
        "parent_agent_name": _optional_str(data.get("parent_agent_name")),
    }


def _prompt_snippet(prompt: str | None) -> str | None:
    if prompt is None:
        return None
    prompt = prompt.replace("\n", " ").strip()
    if len(prompt) <= _PROMPT_SNIPPET_LIMIT:
        return prompt
    return prompt[:_PROMPT_SNIPPET_LIMIT]


def _subtitle(agent: RunningAgentInfo) -> str | None:
    parts = [part for part in (agent.project, agent.provider, agent.model) if part]
    return " - ".join(parts) if parts else None


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_uint(value: Any) -> int | None:
    if value is None:
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _find_mobile_agent_summary(name: str) -> RunningAgentInfo | None:
    for agent in list_all_agents():
        if agent.name == name:
            return agent
    return None


def _raise_lifecycle_error(result: KillResult) -> None:
    if result.reason == "not_found":
        raise _MobileAgentNotFoundError(result.message)
    if result.reason in {"already_completed", "missing_pid"}:
        raise _MobileAgentNotRunningError(result.message)
    if result.reason == "permission_denied":
        raise _MobileAgentPermissionDeniedError(result.message)
    raise _MobileAgentBridgeError(result.message)


def _persist_mobile_kill_context(
    name: str,
    request: dict[str, Any],
    before: RunningAgentInfo | None,
    result: KillResult,
) -> None:
    context_dir = _mobile_kill_context_dir()
    context_dir.mkdir(parents=True, exist_ok=True)
    context = {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "agent_name": name,
        "artifact_dir": result.artifacts_dir
        or (before.artifacts_dir if before is not None else None),
        "artifacts_timestamp": result.timestamp
        or _artifact_timestamp(before.artifacts_dir if before else None),
        "project": result.project or (before.project if before is not None else None),
        "raw_prompt": before.prompt if before is not None else None,
        "killed_pid": _optional_uint(result.pid),
        "device_id": _optional_str(request.get("device_id")),
        "reason": _optional_str(request.get("reason")),
        "status": result.status or "killed",
        "killed_at": datetime.now(UTC).isoformat(),
    }
    final_path = context_dir / f"{_option_id(name)}.json"
    tmp_path = final_path.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(context, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp_path, final_path)


def _persist_mobile_launch_contexts(
    response: dict[str, Any],
    prompt: str,
    request: dict[str, Any],
    *,
    launch_kind: str,
    image_host_path: str | None,
    source_agent_name: str | None,
    retry_of_agent: str | None,
) -> None:
    slots = response.get("slots")
    if not isinstance(slots, list):
        return

    store_path = _mobile_launch_context_store_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)
    launched_at = datetime.now(UTC).isoformat()
    request_id = _optional_str(request.get("request_id"))
    device_id = _optional_str(request.get("device_id"))
    rows: list[dict[str, Any]] = []

    for slot in slots:
        if not isinstance(slot, dict) or slot.get("status") != "launched":
            continue
        agent_name = _optional_str(slot.get("name"))
        artifact_dir = _optional_str(slot.get("artifact_dir"))
        if not agent_name and artifact_dir:
            agent_name = _agent_name_from_artifact_meta(artifact_dir)
        if not agent_name:
            continue
        row = {
            "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
            "launch_kind": launch_kind,
            "agent_name": agent_name,
            "source_agent_name": source_agent_name,
            "retry_of_agent": retry_of_agent,
            "artifact_dir": artifact_dir,
            "artifacts_timestamp": _artifact_timestamp(artifact_dir),
            "project": _optional_str(request.get("project"))
            or _project_from_artifact_dir(artifact_dir),
            "raw_prompt_path": str(Path(artifact_dir) / "raw_xprompt.md")
            if artifact_dir
            else None,
            "prompt_snapshot": prompt,
            "image_host_path": image_host_path,
            "request_id": request_id,
            "device_id": device_id,
            "launched_at": launched_at,
        }
        rows.append(row)

    if not rows:
        return
    with store_path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def _resolve_mobile_retry_context(name: str) -> dict[str, Any]:
    live_agent = _find_mobile_agent_summary(name)
    if live_agent is not None:
        context = _context_from_agent(live_agent)
        stored = _latest_mobile_launch_context(name)
        if stored is not None:
            context = {**stored, **{k: v for k, v in context.items() if v is not None}}
        return context

    stored = _latest_mobile_launch_context(name)
    if stored is not None:
        return stored

    killed = _mobile_kill_context(name)
    if killed is not None:
        return killed

    raise _MobileAgentNotFoundError(f"No retry context found for agent '{name}'")


def _retry_prompt_from_context(context: dict[str, Any], request: dict[str, Any]) -> str:
    override = _optional_str(request.get("prompt_override"))
    if override and override.strip():
        return override.strip()

    raw_prompt_path = _optional_str(context.get("raw_prompt_path"))
    artifact_dir = _optional_str(context.get("artifact_dir"))
    prompt = _read_prompt_file(raw_prompt_path)
    if prompt is None and artifact_dir:
        prompt = _read_prompt_file(str(Path(artifact_dir) / "raw_xprompt.md"))
    if prompt is None:
        prompt = _optional_str(context.get("prompt_snapshot")) or _optional_str(
            context.get("raw_prompt")
        )
    if prompt is None or not prompt.strip():
        raise _MobileAgentNotFoundError(
            f"No prompt context found for agent '{context['agent_name']}'"
        )
    return prompt.strip()


def _context_from_agent(agent: RunningAgentInfo) -> dict[str, Any]:
    return {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "agent_name": agent.name or "(unnamed)",
        "artifact_dir": agent.artifacts_dir,
        "artifacts_timestamp": _artifact_timestamp(agent.artifacts_dir),
        "project": agent.project,
        "raw_prompt_path": str(Path(agent.artifacts_dir) / "raw_xprompt.md")
        if agent.artifacts_dir
        else None,
        "prompt_snapshot": agent.prompt,
        "source_agent_name": None,
    }


def _latest_mobile_launch_context(name: str) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    for row in _iter_mobile_launch_contexts():
        agent_name = _optional_str(row.get("agent_name"))
        artifact_dir = _optional_str(row.get("artifact_dir"))
        artifacts_timestamp = _optional_str(row.get("artifacts_timestamp"))
        if (
            agent_name == name
            or artifacts_timestamp == name
            or (artifact_dir and Path(artifact_dir).name == name)
        ):
            latest = row
    return latest


def _iter_mobile_launch_contexts() -> list[dict[str, Any]]:
    path = _mobile_launch_context_store_path()
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            rows.append(data)
    return rows


def _mobile_kill_context(name: str) -> dict[str, Any] | None:
    path = _mobile_kill_context_dir() / f"{_option_id(name)}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("agent_name", name)
    data.setdefault("prompt_snapshot", data.get("raw_prompt"))
    return data


def _mobile_launch_context_store_path() -> Path:
    return _mobile_gateway_state_dir() / "agent_launch_contexts.jsonl"


def _mobile_kill_context_dir() -> Path:
    return _mobile_gateway_state_dir() / "agent_kill_contexts"


def _mobile_gateway_state_dir() -> Path:
    sase_home = Path(os.environ.get("SASE_HOME") or Path.home() / ".sase")
    return sase_home / "mobile_gateway"


def _artifact_timestamp(artifacts_dir: str | None) -> str | None:
    if not artifacts_dir:
        return None
    return Path(artifacts_dir).name


def _read_prompt_file(path: str | None) -> str | None:
    if not path:
        return None
    try:
        prompt = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    prompt = prompt.strip()
    return prompt or None


def _agent_name_from_artifact_meta(artifact_dir: str) -> str | None:
    try:
        data = json.loads((Path(artifact_dir) / "agent_meta.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return _optional_str(data.get("name"))


def _project_from_artifact_dir(artifact_dir: str | None) -> str | None:
    if not artifact_dir:
        return None
    parts = Path(artifact_dir).parts
    try:
        index = parts.index("projects")
    except ValueError:
        return None
    if index + 1 >= len(parts):
        return None
    return parts[index + 1]


def _directive_name(name: str) -> str:
    if _SAFE_DIRECTIVE_NAME_RE.fullmatch(name):
        return name
    return f"`{name.replace('`', '')}`"


def _option_id(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-") or "agent"
