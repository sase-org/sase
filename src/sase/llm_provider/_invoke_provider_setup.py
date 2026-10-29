"""Resolve provider execution state immediately before invoking the provider."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from typing import Any

from sase.env_contracts import (
    SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV,
    SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV,
)

from .continuation_budget import enforce_continuation_budget
from .types import LLMInvocationOptions, LoggingContext, ModelTier

logger = logging.getLogger(__name__)


def provider_sync_ceiling_seconds(provider: object) -> int | None:
    """Return a provider's validated synchronous kill ceiling, if any."""
    accessor = getattr(provider, "sync_ceiling_seconds", None)
    if accessor is None:
        return None
    try:
        value = accessor()
    except Exception:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        return None
    return value


def _mark_usage_hot_for_launch(provider_name: str | None) -> None:
    """Best-effort usage hint for the provider this launch is about to use."""
    try:
        if not provider_name:
            return
        from sase.llm_provider.usage.refresh import mark_provider_usage_hot_hint

        mark_provider_usage_hot_hint(provider_name)
    except Exception:
        logger.debug("usage hot hint failed for %r", provider_name, exc_info=True)


def prepare_provider_invocation(
    *,
    provider_lookup_name: str | None,
    execution_provider_label: str,
    requested_provider_label: str,
    routing_context: Any,
    query: str,
    model_tier: ModelTier,
    model_override: str | None,
    artifacts_dir: str | None,
    options: LLMInvocationOptions,
    context: LoggingContext,
    get_provider_fn: Callable[..., Any],
    provider_sync_ceiling_fn: Callable[[object], int | None],
) -> tuple[Any, str]:
    """Set provider-scoped state and return the provider and budgeted prompt."""
    provider = get_provider_fn(
        provider_lookup_name,
        routing_context=routing_context,
    )
    sync_ceiling = provider_sync_ceiling_fn(provider)
    if sync_ceiling is None:
        os.environ.pop(SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV, None)
    else:
        os.environ[SASE_PROVIDER_SYNC_CEILING_SECONDS_ENV] = str(sync_ceiling)

    try:
        from sase.config.tools import get_tool_runs_soft_ceiling_seconds

        soft_ceiling = get_tool_runs_soft_ceiling_seconds(execution_provider_label)
    except Exception:  # noqa: BLE001 - soft-ceiling export fails open.
        soft_ceiling = None
    if soft_ceiling is None:
        os.environ.pop(SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV, None)
    else:
        os.environ[SASE_PROVIDER_SYNC_SOFT_CEILING_SECONDS_ENV] = str(soft_ceiling)
    if artifacts_dir:
        from sase.axe.run_agent_helpers import update_meta_field

        update_meta_field(
            artifacts_dir,
            "exec_llm_provider",
            execution_provider_label,
        )
    _mark_usage_hot_for_launch(execution_provider_label)
    from sase.monitor.continuation_delivery import (
        adopt_ordinary_continuation_delivery,
    )

    adopt_ordinary_continuation_delivery()
    budget_model_name = model_override
    if budget_model_name is None:
        try:
            budget_model_name = provider.resolve_model_name(model_tier)
        except Exception:
            budget_model_name = None
    if not isinstance(budget_model_name, str):
        budget_model_name = None
    query = enforce_continuation_budget(
        query,
        artifacts_dir=artifacts_dir,
        provider_name=execution_provider_label,
        model_tier=model_tier,
        model_override=model_override,
        model_name=budget_model_name,
        options=options,
    )
    if context.metadata_model is None:
        metadata_model = budget_model_name
        if execution_provider_label != requested_provider_label:
            metadata_provider = get_provider_fn(
                requested_provider_label,
                routing_context=routing_context,
            )
            try:
                metadata_model = metadata_provider.resolve_model_name(model_tier)
            except Exception:
                metadata_model = None
        elif metadata_model is None:
            try:
                metadata_model = provider.resolve_model_name(model_tier)
            except Exception:
                metadata_model = None
        if (
            isinstance(metadata_model, str)
            and metadata_model
            and metadata_model != "unknown"
        ):
            context.metadata_model = metadata_model
    if artifacts_dir:
        from sase.axe.runner_lifecycle_phase import mark_lifecycle_phase

        mark_lifecycle_phase(artifacts_dir, "provider_running")
    return provider, query
