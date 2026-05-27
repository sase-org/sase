"""Filesystem paths used by mobile agent integration."""

from __future__ import annotations

from pathlib import Path

from sase.core.paths import sase_home as _core_sase_home

from ._mobile_agent_common import safe_device_id


def sase_home() -> Path:
    return _core_sase_home()


def mobile_gateway_state_dir() -> Path:
    return sase_home() / "mobile_gateway"


def mobile_launch_context_store_path() -> Path:
    return mobile_gateway_state_dir() / "agent_launch_contexts.jsonl"


def mobile_kill_context_dir() -> Path:
    return mobile_gateway_state_dir() / "agent_kill_contexts"


def mobile_image_upload_dir(device_id: str) -> Path:
    return mobile_gateway_state_dir() / "uploads" / "images" / device_id


def device_project_context_path(device_id: str) -> Path:
    return (
        mobile_gateway_state_dir()
        / "device_project_contexts"
        / f"{safe_device_id(device_id)}.json"
    )


def mobile_device_project_context_path(device_id: str) -> Path:
    """Return the durable project-context path for a paired mobile device."""
    return device_project_context_path(device_id)
