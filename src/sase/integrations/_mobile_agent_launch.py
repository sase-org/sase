"""Mobile agent launch and image-upload handling."""

from __future__ import annotations

import base64
import binascii
import os
import re
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sase.artifacts import convert_timestamp_to_artifacts_format
from sase.xprompt._parsing import normalize_launch_xprompt_at_refs

from ._mobile_agent_common import (
    MOBILE_AGENT_SCHEMA_VERSION,
    _IMAGE_TYPES,
    _MAX_IMAGE_UPLOAD_BYTES,
    MobileAgentBridgeError,
    MobileAgentInvalidUploadError,
    MobileProjectContext,
    mobile_model_directive_value,
    optional_str,
    required_byte_length,
    required_str,
    safe_device_id,
    safe_error_message,
)
from ._mobile_agent_context import (
    mobile_launch_cwd,
    persist_last_mobile_project_context,
    project_context_from_request,
)
from ._mobile_agent_deps import AgentLaunchResult, launch_agents_from_cwd
from ._mobile_agent_paths import mobile_image_upload_dir
from ._mobile_agent_state import persist_mobile_launch_contexts


def launch_mobile_text_agents(request: dict[str, Any]) -> dict[str, Any]:
    """Launch text agents through the normal SASE launch path."""
    prompt = mobile_launch_prompt(request)
    return launch_mobile_prompt(
        prompt,
        request,
        launch_kind="text",
        project_context=project_context_from_request(request, prompt),
    )


def launch_mobile_image_agents(request: dict[str, Any]) -> dict[str, Any]:
    """Store an uploaded image and launch agents with a local image path prompt."""
    stored_path = store_mobile_image_upload(request)
    prompt = mobile_image_launch_prompt(request, stored_path)
    return launch_mobile_prompt(
        prompt,
        request,
        launch_kind="image",
        image_host_path=str(stored_path),
        project_context=project_context_from_request(request, prompt),
    )


def launch_mobile_prompt(
    prompt: str,
    request: dict[str, Any],
    *,
    launch_kind: str,
    image_host_path: str | None = None,
    source_agent_name: str | None = None,
    retry_of_agent: str | None = None,
    project_context: MobileProjectContext | None = None,
) -> dict[str, Any]:
    planned_name = planned_name_for_prompt(prompt)
    if request.get("dry_run") is True:
        return dry_run_launch_response(prompt)

    try:
        with mobile_launch_cwd(project_context):
            results = launch_agents_from_cwd(prompt)
    except Exception as exc:
        raise MobileAgentBridgeError(safe_error_message(exc)) from exc

    if not results:
        raise MobileAgentBridgeError("agent launch produced no results")
    response = mobile_launch_response(results, planned_name=planned_name)
    persist_mobile_launch_contexts(
        response,
        prompt,
        request,
        launch_kind=launch_kind,
        image_host_path=image_host_path,
        source_agent_name=source_agent_name,
        retry_of_agent=retry_of_agent,
        project_context=project_context,
    )
    persist_last_mobile_project_context(
        optional_str(request.get("device_id")), project_context
    )
    return response


def mobile_launch_prompt(payload: dict[str, Any]) -> str:
    raw_prompt = payload.get("prompt")
    if not isinstance(raw_prompt, str) or not raw_prompt.strip():
        raise MobileAgentBridgeError("prompt must be a non-empty string")

    prompt = normalize_launch_xprompt_at_refs(raw_prompt.strip())
    directives: list[str] = []
    name = optional_str(payload.get("name"))
    if name:
        if prompt_has_name_directive(prompt):
            raise MobileAgentBridgeError(
                "name cannot be provided when prompt already has a name directive"
            )
        from ._mobile_agent_common import directive_name

        directives.append(f"%name:{directive_name(name)}")

    model = optional_str(payload.get("model"))
    provider = optional_str(payload.get("provider"))
    runtime = optional_str(payload.get("runtime"))
    model_value = mobile_model_directive_value(model, provider, runtime)
    if model_value:
        directives.append(f"%model:{model_value}")

    if directives:
        prompt = "\n".join([*directives, prompt])
    return prompt


def mobile_image_launch_prompt(payload: dict[str, Any], image_path: Path) -> str:
    prompt = mobile_launch_prompt(payload)
    return f"The image has been saved to: {image_path}\n\n{prompt}"


def store_mobile_image_upload(payload: dict[str, Any]) -> Path:
    filename = required_str(payload.get("original_filename"), "original_filename")
    content_type = required_str(payload.get("content_type"), "content_type").lower()
    byte_length = required_byte_length(payload.get("byte_length"))
    raw_base64 = required_str(payload.get("base64_image"), "base64_image")

    extension = Path(filename).suffix.lower()
    if not extension or extension not in _IMAGE_TYPES:
        raise MobileAgentInvalidUploadError("unsupported image extension")
    expected_content_type, magic = _IMAGE_TYPES[extension]
    if content_type != expected_content_type:
        raise MobileAgentInvalidUploadError(
            "image extension does not match content type"
        )
    if byte_length > _MAX_IMAGE_UPLOAD_BYTES:
        raise MobileAgentInvalidUploadError("image upload exceeds maximum size")

    try:
        image_bytes = base64.b64decode(raw_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise MobileAgentInvalidUploadError("invalid base64 image data") from exc
    if len(image_bytes) != byte_length:
        raise MobileAgentInvalidUploadError(
            "byte_length does not match decoded image size"
        )
    if len(image_bytes) > _MAX_IMAGE_UPLOAD_BYTES:
        raise MobileAgentInvalidUploadError("image upload exceeds maximum size")
    if not matches_magic(image_bytes, magic, extension):
        raise MobileAgentInvalidUploadError("image bytes do not match content type")

    device_id = safe_device_id(optional_str(payload.get("device_id")))
    upload_dir = mobile_image_upload_dir(device_id)
    upload_dir.mkdir(parents=True, exist_ok=True)
    final_path = upload_dir / generated_image_filename(extension)
    return atomic_write_bytes(upload_dir, final_path, image_bytes)


def matches_magic(
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


def generated_image_filename(extension: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"{timestamp}_{uuid.uuid4().hex}{extension}"


def atomic_write_bytes(upload_dir: Path, final_path: Path, image_bytes: bytes) -> Path:
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
        raise MobileAgentInvalidUploadError("failed to store image upload") from exc


def prompt_has_name_directive(prompt: str) -> bool:
    if "%" not in prompt:
        return False
    from sase.agent.multi_prompt_references import extract_static_name_directive

    return extract_static_name_directive(prompt) is not None or bool(
        re.search(r"(?:^|\s)%(?:name|n)(?:[:+(]|\s|$)", prompt, re.MULTILINE)
    )


def dry_run_launch_response(prompt: str) -> dict[str, Any]:
    slot = {
        "slot_id": "0",
        "name": planned_name_for_prompt(prompt),
        "status": "dry_run",
        "artifact_dir": None,
        "message": "launch request validated",
    }
    return {
        "schema_version": MOBILE_AGENT_SCHEMA_VERSION,
        "primary": slot,
        "slots": [slot],
    }


def mobile_launch_response(
    results: list[AgentLaunchResult],
    *,
    planned_name: str | None = None,
) -> dict[str, Any]:
    slots = [
        result_to_slot(
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


def result_to_slot(
    slot_id: str,
    result: AgentLaunchResult,
    *,
    planned_name: str | None,
) -> dict[str, Any]:
    return {
        "slot_id": slot_id,
        "name": planned_name,
        "status": "launched",
        "artifact_dir": artifact_dir_for_launch(result),
        "message": f"started pid {result.pid}",
    }


def artifact_dir_for_launch(result: AgentLaunchResult) -> str | None:
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


def planned_name_for_prompt(prompt: str) -> str | None:
    from sase.agent.multi_prompt_references import extract_static_name_directive

    return extract_static_name_directive(prompt)
