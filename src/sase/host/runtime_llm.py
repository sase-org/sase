"""LLM operation handlers for the provider host runtime."""

from __future__ import annotations

import contextlib
import io
import os
from collections.abc import Mapping
from typing import Any, Literal, cast

from sase.host.runtime_shared import (
    OperationContext,
    ProviderHostRuntimeError,
    append_captured_process_logs,
    optional_str,
    require_capability,
    required_str,
    string_mapping,
    temporary_cwd,
    temporary_environ,
)
from sase.host.wire import HOST_CAP_LLM_INVOKE, HOST_CAP_LLM_METADATA


def llm_metadata(context: OperationContext) -> Mapping[str, Any]:
    require_capability(context, HOST_CAP_LLM_METADATA)
    from sase.llm_provider.registry import direct_llm_metadata_payload

    context.logs.append("info", "LLM metadata collected", target="sase.host.llm")
    return direct_llm_metadata_payload()


def llm_invoke(context: OperationContext) -> Mapping[str, Any]:
    require_capability(context, HOST_CAP_LLM_INVOKE)
    payload = context.request.payload
    prompt = required_str(payload, "prompt")
    model_tier = optional_str(payload.get("model_tier")) or "large"
    if model_tier not in ("large", "small"):
        raise ProviderHostRuntimeError(
            "host_protocol_error",
            "payload.model_tier must be 'large' or 'small'",
            target="payload.model_tier",
        )
    model_tier_value = cast(Literal["large", "small"], model_tier)
    suppress_output = bool(payload.get("suppress_output", False))
    model_override = optional_str(payload.get("model_override"))
    provider_name = optional_str(payload.get("provider_name"))
    cwd = optional_str(payload.get("cwd"))
    provider_label = provider_name

    from sase.llm_provider.registry import (
        get_default_provider_name,
        get_provider,
    )

    if provider_label is None:
        provider_label = get_default_provider_name()

    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    try:
        with (
            temporary_environ(string_mapping(payload.get("env"))),
            temporary_cwd(cwd),
            contextlib.redirect_stdout(stdout_buffer),
            contextlib.redirect_stderr(stderr_buffer),
        ):
            os.environ["SASE_PROVIDER_HOST_DIRECT_CALL"] = "1"
            provider = get_provider(provider_name)
            invoke_result = provider.invoke(
                prompt,
                model_tier=model_tier_value,
                suppress_output=suppress_output,
                model_override=model_override,
            )
    except Exception as exc:
        append_captured_process_logs(context, stdout_buffer, stderr_buffer)
        raise ProviderHostRuntimeError(
            "provider_execution_failed",
            str(exc).strip() or type(exc).__name__,
            target="llm.invoke",
            details={"type": type(exc).__name__},
        ) from exc

    append_captured_process_logs(context, stdout_buffer, stderr_buffer)
    context.logs.append("info", "LLM invocation completed", target="sase.host.llm")
    return {
        "content": invoke_result.content,
        "usage": invoke_result.usage,
        "provider": provider_label,
    }
