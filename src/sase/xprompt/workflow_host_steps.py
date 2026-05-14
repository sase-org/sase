"""Host-routed bash/python workflow step helpers."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from typing import Any

from sase.xprompt.workflow_models import WorkflowExecutionError


@dataclass(frozen=True)
class _HostedWorkflowStepResult:
    returncode: int
    stdout: str
    stderr: str


def run_hosted_bash_step(
    command: str,
    *,
    cwd: str,
    env: dict[str, str],
) -> _HostedWorkflowStepResult | None:
    return _run_hosted_step(
        operation="workflow.step.bash",
        payload={"command": command, "cwd": cwd, "env": env},
    )


def run_hosted_python_step(
    code: str,
    *,
    cwd: str,
    env: dict[str, str],
) -> _HostedWorkflowStepResult | None:
    return _run_hosted_step(
        operation="workflow.step.python",
        payload={"code": code, "cwd": cwd, "env": env},
    )


def _run_hosted_step(
    *,
    operation: str,
    payload: dict[str, Any],
) -> _HostedWorkflowStepResult | None:
    if os.environ.get("SASE_DAEMON_SCHEDULER_HOST_BRIDGE") != "1":
        return None
    if os.environ.get("SASE_PROVIDER_HOST_DIRECT_CALL") == "1":
        return None

    from sase.host.client import call_provider_host, is_host_fallbackable
    from sase.host.wire import HOST_CAP_WORKFLOW_STEP

    try:
        response = call_provider_host(
            family="workflow.step",
            operation=operation,
            payload=payload,
            required_capability=HOST_CAP_WORKFLOW_STEP,
            timeout_ms=300_000,
        )
    except Exception as exc:
        if is_host_fallbackable(exc):
            return None
        raise

    _emit_host_logs(response.logs)
    if response.status == "ok":
        return _HostedWorkflowStepResult(
            returncode=int(response.result.get("returncode", 1)),
            stdout=str(response.result.get("stdout", "")),
            stderr=str(response.result.get("stderr", "")),
        )

    code = response.error.code if response.error is not None else "host_protocol_error"
    if code in {
        "host_unavailable",
        "resource_limit_exceeded",
        "operation_unsupported",
        "capability_denied",
        "host_protocol_error",
    }:
        return None
    message = response.error.message if response.error is not None else response.status
    raise WorkflowExecutionError(f"Hosted workflow step failed: {message}")


def _emit_host_logs(logs: Any) -> None:
    for log in logs or ():
        stream = getattr(log, "stream", None)
        message = getattr(log, "message", "")
        if stream == "stderr" and message:
            sys.stderr.write(str(message))
            if not str(message).endswith("\n"):
                sys.stderr.write("\n")
