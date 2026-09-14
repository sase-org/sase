"""Building the Rust-bound continuation budget request and its config layers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sase.core.continuation_wire import CONTINUATION_WIRE_SCHEMA_VERSION
from sase.llm_provider.continuation_budget_projection import (
    PromptProjection,
    prompt_projection,
)
from sase.llm_provider.types import LLMInvocationOptions, ModelTier

MONITOR_CONTINUATION_ENV = "SASE_MONITOR_CONTINUATION"
CONTINUATION_BUDGET_ENFORCE_ENV = "SASE_CONTINUATION_BUDGET_ENFORCE"

_DEFAULT_CONTEXT_LIMIT_BYTES = 800_000
_AGY_PRINT_PROMPT_TRANSPORT_LIMIT_BYTES = 120 * 1024
_AGY_PRINT_PROMPT_OVERHEAD_BYTES = 512
_PROVIDER_TRANSPORT_LIMIT_BYTES = {
    "agy": _AGY_PRINT_PROMPT_TRANSPORT_LIMIT_BYTES,
}
_PROVIDER_INSTRUCTION_RESERVE_BYTES = {
    "agy": _AGY_PRINT_PROMPT_OVERHEAD_BYTES,
}
_ENV_TO_CONFIG_KEY = {
    "context_limit_bytes": "SASE_CONTINUATION_CONTEXT_LIMIT_BYTES",
    "transport_limit_bytes": "SASE_CONTINUATION_TRANSPORT_LIMIT_BYTES",
    "checkpoint_threshold_bytes": "SASE_CONTINUATION_CHECKPOINT_THRESHOLD_BYTES",
    "instruction_reserve_bytes": "SASE_CONTINUATION_INSTRUCTION_RESERVE_BYTES",
    "tool_reserve_bytes": "SASE_CONTINUATION_TOOL_RESERVE_BYTES",
    "output_reserve_bytes": "SASE_CONTINUATION_OUTPUT_RESERVE_BYTES",
    "reasoning_reserve_bytes": "SASE_CONTINUATION_REASONING_RESERVE_BYTES",
}


def budget_required(env: Mapping[str, str]) -> bool:
    return (
        env.get(MONITOR_CONTINUATION_ENV) == "1"
        or env.get(CONTINUATION_BUDGET_ENFORCE_ENV) == "1"
    )


def budget_request(
    prompt: str,
    env: Mapping[str, str],
    *,
    provider_name: str,
    model_tier: ModelTier,
    model_name: str | None,
    options: LLMInvocationOptions,
    projection: PromptProjection | None = None,
) -> dict[str, Any]:
    from sase.llm_provider.config import get_llm_provider_config

    raw_config = get_llm_provider_config()
    budget_config = raw_config.get("continuation_budget") if raw_config else None
    config = budget_config if isinstance(budget_config, Mapping) else {}
    layers = _config_layers(config, provider_name=provider_name, model_name=model_name)
    prompt_proj = projection or prompt_projection(prompt)
    provider_budget = _provider_budget(
        env,
        provider_name=provider_name,
        layers=layers,
    )
    request: dict[str, Any] = {
        "schema_version": CONTINUATION_WIRE_SCHEMA_VERSION,
        "rendered_prompt_bytes": prompt_proj.rendered_prompt_bytes,
        "essential_bytes": prompt_proj.essential_bytes,
        "selected_evidence_bytes": prompt_proj.selected_evidence_bytes,
        "provider_budget": provider_budget,
        "reduction_candidates": list(prompt_proj.candidates),
        "provider": provider_name,
        "model_tier": model_tier,
        "model": model_name,
        "reasoning_effort": options.reasoning_effort,
    }
    threshold = _int_setting("checkpoint_threshold_bytes", env, layers)
    if threshold is not None:
        request["checkpoint_threshold_bytes"] = threshold
    return request


def _provider_budget(
    env: Mapping[str, str],
    *,
    provider_name: str,
    layers: tuple[Mapping[str, object], ...],
) -> dict[str, Any]:
    instruction_reserve = (
        _int_setting("instruction_reserve_bytes", env, layers, default=0) or 0
    )
    instruction_reserve = max(
        instruction_reserve,
        _PROVIDER_INSTRUCTION_RESERVE_BYTES.get(provider_name, 0),
    )
    return {
        "context_limit_bytes": _int_setting(
            "context_limit_bytes",
            env,
            layers,
            default=_DEFAULT_CONTEXT_LIMIT_BYTES,
        ),
        "transport_limit_bytes": _int_setting(
            "transport_limit_bytes",
            env,
            layers,
            default=_PROVIDER_TRANSPORT_LIMIT_BYTES.get(provider_name),
        ),
        "instruction_reserve_bytes": instruction_reserve,
        "tool_reserve_bytes": _int_setting(
            "tool_reserve_bytes",
            env,
            layers,
            default=0,
        )
        or 0,
        "output_reserve_bytes": _int_setting(
            "output_reserve_bytes",
            env,
            layers,
            default=0,
        )
        or 0,
        "reasoning_reserve_bytes": _int_setting(
            "reasoning_reserve_bytes",
            env,
            layers,
            default=0,
        )
        or 0,
        "estimate_uncertain": _bool_setting(
            "estimate_uncertain",
            layers,
            default=True,
        ),
    }


def _int_setting(
    key: str,
    env: Mapping[str, str],
    config_layers: tuple[Mapping[str, object], ...],
    *,
    default: int | None = None,
) -> int | None:
    raw: object | None = env.get(_ENV_TO_CONFIG_KEY[key])
    if raw is None:
        for config in reversed(config_layers):
            if key in config:
                raw = config.get(key)
                break
    if raw is None or isinstance(raw, bool):
        return default
    if not isinstance(raw, (int, str)):
        return default
    if isinstance(raw, int):
        return raw if raw > 0 else default
    try:
        parsed = int(raw)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _bool_setting(
    key: str,
    config_layers: tuple[Mapping[str, object], ...],
    *,
    default: bool,
) -> bool:
    for config in reversed(config_layers):
        if key not in config:
            continue
        value = config.get(key)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            lowered = value.strip().casefold()
            if lowered in {"1", "true", "yes", "on"}:
                return True
            if lowered in {"0", "false", "no", "off"}:
                return False
    return default


def _config_layers(
    config: Mapping[str, object],
    *,
    provider_name: str,
    model_name: str | None,
) -> tuple[Mapping[str, object], ...]:
    layers: list[Mapping[str, object]] = [config]
    providers = config.get("providers")
    provider_config: Mapping[str, object] | None = None
    if isinstance(providers, Mapping):
        raw_provider = providers.get(provider_name)
        if isinstance(raw_provider, Mapping):
            provider_config = raw_provider
            layers.append(provider_config)
    if model_name and provider_config is not None:
        models = provider_config.get("models")
        if isinstance(models, Mapping):
            raw_model = models.get(model_name)
            if isinstance(raw_model, Mapping):
                layers.append(raw_model)
    return tuple(layers)
