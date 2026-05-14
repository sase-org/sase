"""Workflow step operation handlers for the provider host runtime."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Mapping
from typing import Any

from sase.host.manifest import effective_timeout_ms
from sase.host.runtime_shared import (
    OperationContext,
    ProviderHostRuntimeError,
    optional_str,
    require_capability,
    required_str,
    string_mapping,
)
from sase.host.wire import HOST_CAP_WORKFLOW_STEP


def workflow_step_bash(context: OperationContext) -> Mapping[str, Any]:
    require_capability(context, HOST_CAP_WORKFLOW_STEP)
    return _run_workflow_step_process(
        context,
        command=required_str(context.request.payload, "command"),
        shell=True,
    )


def workflow_step_python(context: OperationContext) -> Mapping[str, Any]:
    require_capability(context, HOST_CAP_WORKFLOW_STEP)
    return _run_workflow_step_process(
        context,
        command=[
            sys.executable,
            "-c",
            required_str(context.request.payload, "code"),
        ],
        shell=False,
    )


def _run_workflow_step_process(
    context: OperationContext,
    *,
    command: str | list[str],
    shell: bool,
) -> Mapping[str, Any]:
    payload = context.request.payload
    cwd = optional_str(payload.get("cwd")) or os.getcwd()
    env = os.environ.copy()
    env.update(string_mapping(payload.get("env")))
    timeout_ms = effective_timeout_ms(
        context.request, default_timeout_ms=context.config.default_timeout_ms
    )
    try:
        result = subprocess.run(
            command,
            shell=shell,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
            timeout=timeout_ms / 1000,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProviderHostRuntimeError(
            "host_timeout",
            f"workflow step exceeded timeout of {timeout_ms}ms",
            retryable=True,
            target=context.request.request_id,
            details={"stdout": exc.stdout, "stderr": exc.stderr},
        ) from exc
    except Exception as exc:
        raise ProviderHostRuntimeError(
            "provider_execution_failed",
            str(exc).strip() or type(exc).__name__,
            target="workflow.step",
            details={"type": type(exc).__name__},
        ) from exc

    if result.stdout:
        context.logs.append(
            "info", result.stdout, target="sase.host.workflow", stream="stdout"
        )
    if result.stderr:
        context.logs.append(
            "warn", result.stderr, target="sase.host.workflow", stream="stderr"
        )
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "cwd": cwd,
    }
