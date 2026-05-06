"""Mobile helper bridge operations for app update jobs."""

from __future__ import annotations

from typing import Any

from sase.integrations.chat_install import (
    ChatInstallLaunchResult,
    ChatInstallStatusResult,
    read_chat_install_status,
    start_chat_install_worker,
)

from ._mobile_helper_common import (
    GATEWAY_WIRE_SCHEMA_VERSION,
    MobileHelperBridgeError,
    MobileUpdateAlreadyRunning,
    MobileUpdateJobNotFound,
    helper_result,
    optional_string,
    path_display,
    reject_unexpected_fields,
    required_string,
)


def update_start_response(request: dict[str, Any]) -> dict[str, Any]:
    reject_unexpected_fields(request, {"schema_version", "request_id", "device_id"})
    optional_string(request.get("request_id"), "request_id")
    optional_string(request.get("device_id"), "device_id")

    result = start_chat_install_worker()
    if result.status == "already_running":
        raise MobileUpdateAlreadyRunning(result.message)
    if result.status in {"config_missing_command", "workspace_resolution_failed"}:
        raise MobileHelperBridgeError(result.message)

    if result.status == "launch_failed":
        return {
            "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
            "result": helper_result("failed", result.message),
            "job": _launch_job_wire(result, "failed"),
        }

    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": helper_result("success", result.message),
        "job": _launch_job_wire(result, "running"),
    }


def update_status_response(request: dict[str, Any]) -> dict[str, Any]:
    reject_unexpected_fields(request, {"schema_version", "job_id", "device_id"})
    job_id = required_string(request.get("job_id"), "job_id")
    optional_string(request.get("device_id"), "device_id")

    result = read_chat_install_status(job_id)
    if result.status == "not_found":
        raise MobileUpdateJobNotFound(result.message)

    helper_status = "failed" if result.status == "failed" else "success"
    return {
        "schema_version": GATEWAY_WIRE_SCHEMA_VERSION,
        "result": helper_result(helper_status, result.message),
        "job": _status_job_wire(result),
    }


def _launch_job_wire(result: ChatInstallLaunchResult, status: str) -> dict[str, object]:
    return {
        "job_id": result.job_id or "",
        "status": status,
        "started_at": None,
        "finished_at": None,
        "message": result.message,
        "log_path_display": path_display(result.log_path),
        "completion_path_display": path_display(result.status_path),
    }


def _status_job_wire(result: ChatInstallStatusResult) -> dict[str, object]:
    return {
        "job_id": result.job_id,
        "status": result.status,
        "started_at": result.started_at,
        "finished_at": result.finished_at,
        "message": result.message,
        "log_path_display": path_display(result.log_path),
        "completion_path_display": path_display(result.completion_path),
    }
