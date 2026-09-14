"""Budget preflight for continuation-backed provider invocations."""

from __future__ import annotations

import os
import time
from collections.abc import Mapping

from sase.core.continuation_facade import plan_continuation_budget
from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.llm_provider.continuation_budget_decision import (
    normalized_decision,
    refusal_message,
    verify_projection,
)
from sase.llm_provider.continuation_budget_persistence import (
    CONTINUATION_BUDGET_DECISION_FILENAME,
    persist_decision,
    persist_projected_prompt,
    prompt_path,
    record_child_metadata,
    record_delivery_refusal,
    record_parent_refusal,
)
from sase.llm_provider.continuation_budget_projection import (
    project_prompt,
    prompt_projection,
    utf8_len,
)
from sase.llm_provider.continuation_budget_request import (
    CONTINUATION_BUDGET_ENFORCE_ENV,
    MONITOR_CONTINUATION_ENV,
    budget_request,
    budget_required,
)
from sase.llm_provider.types import LLMInvocationError, LLMInvocationOptions, ModelTier


def enforce_continuation_budget(
    prompt: str,
    *,
    artifacts_dir: str | None,
    provider_name: str,
    model_tier: ModelTier,
    model_override: str | None,
    model_name: str | None = None,
    options: LLMInvocationOptions,
    env: Mapping[str, str] | None = None,
) -> str:
    """Record and enforce the Rust-owned continuation budget decision."""

    runtime_env = env or os.environ
    if not budget_required(runtime_env):
        return prompt

    projection = prompt_projection(prompt)
    request = budget_request(
        prompt,
        runtime_env,
        provider_name=provider_name,
        model_tier=model_tier,
        model_name=model_name or model_override,
        options=options,
        projection=projection,
    )
    decision = normalized_decision(plan_continuation_budget(request))
    projected_prompt = project_prompt(prompt, decision, projection)
    decision = verify_projection(decision, projected_prompt)
    record = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "kind": "continuation_budget_preflight",
        "provider": provider_name,
        "model_tier": model_tier,
        "model": model_name or model_override,
        "reasoning_effort": options.reasoning_effort,
        "request": request,
        "decision": decision,
        "projected_prompt_bytes": utf8_len(projected_prompt),
        "recorded_at_epoch": time.time(),
    }
    projected_prompt_path = persist_projected_prompt(
        artifacts_dir,
        projected_prompt,
        original_prompt=prompt,
        decision=decision,
    )
    if projected_prompt_path:
        record["projected_prompt_path"] = projected_prompt_path
    decision_path = persist_decision(artifacts_dir, record)
    record_child_metadata(
        artifacts_dir,
        decision,
        decision_path=decision_path,
        projected_prompt_bytes=utf8_len(projected_prompt),
        projected_prompt_path=projected_prompt_path,
    )

    if str(decision.get("kind") or "") != "refuse":
        return projected_prompt

    message = refusal_message(decision)
    record_parent_refusal(
        runtime_env,
        message,
        decision_path=decision_path,
        prompt_path=prompt_path(artifacts_dir),
    )
    record_delivery_refusal(
        runtime_env,
        message,
        decision_path=decision_path,
    )
    raise LLMInvocationError(message)


__all__ = [
    "CONTINUATION_BUDGET_DECISION_FILENAME",
    "CONTINUATION_BUDGET_ENFORCE_ENV",
    "MONITOR_CONTINUATION_ENV",
    "enforce_continuation_budget",
]
