"""Main invoke_agent() orchestrator for the LLM provider abstraction layer.

This is the provider-agnostic orchestration layer that delegates the actual
LLM call to a pluggable provider.
"""

import logging
import os
import subprocess
import time
from typing import Any, Literal, cast

from sase.core.time import generate_timestamp
from .messages import AIMessage
from sase.output import print_decision_counts, print_prompt_and_response
from sase.telemetry.metrics import (
    LLM_CACHE_READ_TOKENS,
    LLM_ERRORS,
    LLM_INPUT_TOKENS,
    LLM_INVOCATION_DURATION,
    LLM_INVOCATIONS,
    LLM_OUTPUT_TOKENS,
)

from .postprocessing import (
    postprocess_error,
    postprocess_success,
    save_prompt_to_file,
)
from .preprocessing import preprocess_prompt
from sase.xprompt.directives import PromptDirectives
from .commit_finalizer import run_commit_finalizer
from .config import resolve_effective_effort
from .registry import get_default_provider_name, get_provider, resolve_model_provider
from .types import (
    LLMInvocationError,
    LLMInvocationOptions,
    _MODEL_SIZE_TO_TIER,
    _MODEL_TIER_TO_LABEL,
    LoggingContext,
    ModelTier,
)

logger = logging.getLogger(__name__)


def invoke_agent(
    prompt: str,
    *,
    agent_type: str,
    model_tier: ModelTier = "large",
    model_size: Literal["little", "big"] | None = None,
    iteration: int | None = None,
    workflow_tag: str | None = None,
    artifacts_dir: str | None = None,
    workflow: str | None = None,
    suppress_output: bool = False,
    timestamp: str | None = None,
    is_home_mode: bool = False,
    branch_or_workspace: str | None = None,
    decision_counts: dict[str, Any] | None = None,
    provider_name: str | None = None,
    skip_preprocessing: bool = False,
    directives: PromptDirectives | None = None,
) -> AIMessage:
    """Invoke an LLM agent with standard preprocessing, logging, and postprocessing.

    This is the main entry point for sending prompts to any configured LLM
    backend. It handles the full lifecycle:

    1. Preprocess the prompt (xprompt, file refs, jinja2, prettier).
    2. Display decision counts and prompt (if not suppressed).
    3. Save prompt to artifacts directory.
    4. Get provider from registry and invoke.
    5. Postprocess response (logging, chat history, audio).
    6. Return AIMessage.

    Args:
        prompt: The raw prompt to send to the agent.
        agent_type: Type of agent (e.g., "editor", "planner", "research").
        model_tier: Model tier ("large" or "small").
        model_size: Deprecated. Use ``model_tier`` instead. Maps "big" to
            "large" and "little" to "small".
        iteration: Optional iteration number.
        workflow_tag: Optional workflow tag.
        artifacts_dir: Optional artifacts directory for logging.
        workflow: Optional workflow name for chat history.
        suppress_output: If True, suppress output display.
        timestamp: Optional timestamp for chat file naming (YYmmdd_HHMMSS).
        is_home_mode: If True, skip file copying for ``@`` file references.
        branch_or_workspace: Optional branch/workspace name for chat history
            filenames. When not provided, auto-detected from the current
            working directory.
        decision_counts: Optional planning agent decision counts for display.
        provider_name: Optional provider name override (default from config).
        skip_preprocessing: If True, skip the ``preprocess_prompt()`` call
            and use the prompt as-is (caller already preprocessed).
        directives: Pre-extracted prompt directives to use when
            ``skip_preprocessing=True``.

    Returns:
        The AIMessage response from the agent.
    """
    # Handle deprecated model_size parameter
    if model_size is not None:
        model_tier = _MODEL_SIZE_TO_TIER[model_size]

    # Check for global model tier override (env var)
    tier_override = os.environ.get("SASE_MODEL_TIER_OVERRIDE") or os.environ.get(
        "SASE_MODEL_SIZE_OVERRIDE"
    )
    if tier_override:
        # Accept both old ("big"/"little") and new ("large"/"small") values
        if tier_override in _MODEL_SIZE_TO_TIER:
            model_tier = _MODEL_SIZE_TO_TIER[tier_override]
        elif tier_override in ("large", "small"):
            model_tier = cast(ModelTier, tier_override)

    # Build logging context
    context = LoggingContext(
        agent_type=agent_type,
        iteration=iteration,
        workflow_tag=workflow_tag,
        artifacts_dir=artifacts_dir,
        suppress_output=suppress_output,
        workflow=workflow,
        timestamp=timestamp,
        is_home_mode=is_home_mode,
        branch_or_workspace=branch_or_workspace,
        decision_counts=decision_counts,
    )

    # 1. Preprocess prompt
    if skip_preprocessing:
        query = prompt
        result_directives = directives or PromptDirectives()
    else:
        result = preprocess_prompt(prompt, is_home_mode=is_home_mode)
        query = result.prompt
        result_directives = result.directives
    model_override = result_directives.model
    model_alias_overrides = dict(result_directives.model_alias_overrides)
    if model_alias_overrides and artifacts_dir:
        from .launch_alias_overrides import export_launch_alias_overrides

        export_launch_alias_overrides(model_alias_overrides)
        from sase.axe.run_agent_helpers import update_meta_field

        update_meta_field(
            artifacts_dir,
            "model_alias_overrides",
            model_alias_overrides,
        )

    # Resolve the effective reasoning effort (explicit %effort/@effort beats
    # the llm_provider.default_effort config) into per-invocation options that
    # each provider translates into its own CLI args.
    effective_effort, effort_explicit = resolve_effective_effort(result_directives)
    invocation_options = LLMInvocationOptions(
        reasoning_effort=effective_effort,
        explicit=effort_explicit,
    )

    # Resolve provider from model override (e.g. "o3" → codex, "codex/o3" → codex)
    if model_override and not provider_name:
        original_model_override = model_override
        if model_alias_overrides:
            resolved_provider, model_override = resolve_model_provider(
                model_override,
                model_alias_overrides,
            )
        else:
            resolved_provider, model_override = resolve_model_provider(model_override)
        if resolved_provider:
            provider_name = resolved_provider
        else:
            provider_name = get_default_provider_name()
            logger.warning(
                "Model override %r did not resolve to an LLM provider; "
                "falling back to default provider %r.",
                original_model_override,
                provider_name,
            )

    # Resolve the launch default only when neither an explicit %model directive
    # nor an explicit provider_name was supplied. Explicit caller intent always
    # wins over the default.
    if not model_override and not provider_name:
        from .config import default_model_alias_name, get_model_aliases
        from .temporary_override import (
            get_active_temporary_override,
            resolve_effective_default_provider_model,
        )

        active = get_active_temporary_override()
        if default_model_alias_name() in model_alias_overrides:
            provider_name, model_override = resolve_effective_default_provider_model(
                model_tier,
                model_alias_overrides,
            )
        elif active is not None:
            # An active primary temporary override wins the new-launch-default
            # slot (it is the user's recent explicit choice).
            provider_name = active.provider
            model_override = active.model
        elif default_model_alias_name() in get_model_aliases():
            # A configured @default alias routes the no-directive launch through
            # the alias resolver so a configured default model is never silently
            # bypassed. With no configured default, @default is just the provider
            # tier default, so the plain-tier resolution below is left untouched.
            provider_name, model_override = resolve_effective_default_provider_model(
                model_tier,
                model_alias_overrides or None,
            )

    # 2. Build display label
    if model_override:
        agent_type_with_tier = f"{agent_type} [{model_override}]"
    else:
        model_tier_label = _MODEL_TIER_TO_LABEL[model_tier]
        agent_type_with_tier = f"{agent_type} [{model_tier_label}]"

    # 3. Display decision counts (if not suppressed)
    if not suppress_output and decision_counts is not None:
        print_decision_counts(decision_counts)

    # 4. Print prompt BEFORE execution (if not suppressed)
    if not suppress_output:
        print_prompt_and_response(
            prompt=query,
            response="",
            agent_type=agent_type_with_tier,
            iteration=iteration,
            show_prompt=True,
            show_response=False,
        )

    # 5. Generate or use provided timestamp
    start_timestamp = timestamp or generate_timestamp()

    # 6. Save prompt to artifacts
    if artifacts_dir:
        save_prompt_to_file(
            prompt=query,
            artifacts_dir=artifacts_dir,
            agent_type=agent_type,
            iteration=iteration,
        )

    # 7. Get provider and invoke
    provider_label = provider_name or get_default_provider_name()
    context.metadata_llm_provider = provider_label
    context.metadata_model = model_override
    t0 = time.monotonic()
    try:
        provider = get_provider(provider_name)
        if context.metadata_model is None:
            resolved_model = provider.resolve_model_name(model_tier)
            if resolved_model and resolved_model != "unknown":
                context.metadata_model = resolved_model
        invoke_result = provider.invoke(
            query,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            options=invocation_options,
        )
        invoke_result = run_commit_finalizer(
            provider=provider,
            original_prompt=query,
            invoke_result=invoke_result,
            model_tier=model_tier,
            suppress_output=suppress_output,
            model_override=model_override,
            artifacts_dir=artifacts_dir,
            options=invocation_options,
        )
        response_content = invoke_result.content

        # Record success metrics
        elapsed = time.monotonic() - t0
        LLM_INVOCATIONS.labels(provider=provider_label, status="ok").inc()
        LLM_INVOCATION_DURATION.labels(provider=provider_label).observe(elapsed)
        if invoke_result.usage:
            LLM_INPUT_TOKENS.labels(provider=provider_label).inc(
                invoke_result.usage.get("input_tokens", 0)
            )
            LLM_OUTPUT_TOKENS.labels(provider=provider_label).inc(
                invoke_result.usage.get("output_tokens", 0)
            )
            LLM_CACHE_READ_TOKENS.labels(provider=provider_label).inc(
                invoke_result.usage.get("cache_read_input_tokens", 0)
            )

        # 8. Postprocess success
        postprocess_success(
            prompt=query,
            response=response_content,
            context=context,
            model_tier=model_tier,
            start_timestamp=start_timestamp,
        )

        return AIMessage(content=response_content)

    except subprocess.CalledProcessError as e:
        elapsed = time.monotonic() - t0
        LLM_INVOCATIONS.labels(provider=provider_label, status="error").inc()
        LLM_INVOCATION_DURATION.labels(provider=provider_label).observe(elapsed)
        LLM_ERRORS.labels(
            provider=provider_label, error_type="CalledProcessError"
        ).inc()

        parts = [f"Error running LLM provider command (exit code {e.returncode})"]
        if e.stderr:
            parts.append(f"stderr: {e.stderr.strip()}")
        if e.output:
            parts.append(f"output: {e.output.strip()}")
        error_content = "\n".join(parts)

        postprocess_error(
            prompt=query,
            error_content=error_content,
            context=context,
            model_tier=model_tier,
            start_timestamp=start_timestamp,
        )

        raise LLMInvocationError(error_content) from e

    except LLMInvocationError as e:
        elapsed = time.monotonic() - t0
        LLM_INVOCATIONS.labels(provider=provider_label, status="error").inc()
        LLM_INVOCATION_DURATION.labels(provider=provider_label).observe(elapsed)
        LLM_ERRORS.labels(
            provider=provider_label, error_type="LLMInvocationError"
        ).inc()

        error_content = str(e)
        postprocess_error(
            prompt=query,
            error_content=error_content,
            context=context,
            model_tier=model_tier,
            start_timestamp=start_timestamp,
        )

        raise

    except Exception as e:
        elapsed = time.monotonic() - t0
        LLM_INVOCATIONS.labels(provider=provider_label, status="error").inc()
        LLM_INVOCATION_DURATION.labels(provider=provider_label).observe(elapsed)
        LLM_ERRORS.labels(provider=provider_label, error_type=type(e).__name__).inc()

        error_content = f"Error: {str(e)}"

        postprocess_error(
            prompt=query,
            error_content=error_content,
            context=context,
            model_tier=model_tier,
            start_timestamp=start_timestamp,
        )

        raise LLMInvocationError(error_content) from e
